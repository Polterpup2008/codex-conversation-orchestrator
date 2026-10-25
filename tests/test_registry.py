import concurrent.futures
import pathlib
import sys
import tempfile
import unittest
import uuid
import threading
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]/'plugin'))
from orchestrator.errors import BridgeError
from orchestrator.storage import Registry
from orchestrator.tools import validate, invoke
from orchestrator.service import Service
from orchestrator.transport import AppServer


class RegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = pathlib.Path(self.temp.name)/'state.sqlite3'
        self.db = Registry(self.path)
        self.a, self.b = str(uuid.uuid4()), str(uuid.uuid4())
        with self.db.transaction() as db:
            db.execute("INSERT INTO projects(id,root,mode,created) VALUES('test',?,'experiment',0)", (self.temp.name,))
            for tid in [self.a,self.b]:
                db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities) VALUES(?,'test','developer','test','[]')", (tid,))

    def test_duplicate_and_conflicting_content(self):
        self.assertTrue(self.db.reserve_message('k',self.a,'hello',None)[1])
        self.assertFalse(self.db.reserve_message('k',self.a,'hello',None)[1])
        with self.assertRaisesRegex(BridgeError,'different content'):
            self.db.reserve_message('k',self.a,'changed',None)

    def test_parallel_exclusive_send(self):
        def attempt(i):
            try:
                Registry(self.path).reserve_message(str(i),self.a,'hello',None); return True
            except BridgeError:
                return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(attempt,range(8))),1)

    def test_restart_preserves_unknown_and_prevents_resend(self):
        self.db.reserve_message('k',self.a,'hello',None)
        self.db.set_message('k','unknown')
        restarted = Registry(self.path)
        self.assertEqual(restarted.one('messages','key','k')['state'],'unknown')
        with self.assertRaises(BridgeError):
            restarted.reserve_message('new',self.a,'hello',None)

    def test_dispatch_boundary_is_durable_and_not_inferred_from_missing_history(self):
        self.db.reserve_message('prepared',self.a,'hello',None)
        self.assertEqual(Registry(self.path).one('messages','key','prepared')['stage'],'prepared')
        self.db.mark_dispatching('prepared')
        self.assertEqual(Registry(self.path).one('messages','key','prepared')['stage'],'dispatching')

    def test_terminal_event_cannot_be_downgraded(self):
        self.db.reserve_message('k',self.a,'hello',None)
        tid = str(uuid.uuid4()); self.db.set_message('k','sent',tid)
        self.db.completed(self.a,dict(id=tid,status='completed',items=[]))
        self.db.set_message('k','sent',tid)
        self.assertEqual(self.db.one('messages','key','k')['state'],'completed')
        self.assertEqual(self.db.one('conversations','thread_id',self.a)['latest_completed_turn'],tid)

    def test_completion_not_task_acceptance(self):
        with self.db.connect() as db:
            db.execute("INSERT INTO tasks(id,project_id,owner,requirements,dependencies) VALUES('t','test',?,'requirements','[]')", (self.a,))
        self.db.reserve_message('k',self.a,'hello','t')
        tid = str(uuid.uuid4()); self.db.set_message('k','sent',tid)
        self.db.completed(self.a,dict(id=tid,status='completed',items=[]))
        self.assertEqual(self.db.one('tasks','id','t')['state'],'needs_audit')
        revision=self.db.one('tasks','id','t')['revision']
        self.db.completed(self.a,dict(id=tid,status='completed',items=[]))
        self.assertEqual(self.db.one('tasks','id','t')['revision'],revision)

    def test_independent_threads_can_run_concurrently(self):
        self.db.reserve_message('a',self.a,'a',None)
        self.db.reserve_message('b',self.b,'b',None)
        self.assertEqual(len(self.db.rows('SELECT * FROM messages')),2)

    def test_invalid_ownership_and_dependency(self):
        with self.db.connect() as db:
            db.execute("INSERT INTO tasks(id,project_id,owner,requirements,dependencies) VALUES('t','test',?,'r','[\"dep\"]')", (self.a,))
        with self.assertRaisesRegex(BridgeError,'not assigned'):
            self.db.reserve_message('x',self.b,'x','t')
        with self.assertRaisesRegex(BridgeError,'not passed'):
            self.db.reserve_message('y',self.a,'y','t')


class BoundaryTests(unittest.TestCase):
    def test_validation(self):
        for value in ['', ' ', None, 2]:
            with self.assertRaises(BridgeError):
                validate(value,{'type':'string','minLength':1})
        for value in [True, -1, 51, float('nan')]:
            with self.assertRaises(BridgeError):
                validate(value, {'type':'number','minimum':0,'maximum':50})
        with self.assertRaises(BridgeError):
            invoke(None,'thread_delete',{})

    def test_invalid_ids_and_nonempty_workspace(self):
        with tempfile.TemporaryDirectory() as directory:
            s = Service(pathlib.Path(directory)/'state')
            with self.assertRaisesRegex(BridgeError,'UUID'):
                s.conversation_read('fake')
            path = pathlib.Path(directory)/'unrelated'; path.mkdir(); (path/'keep').write_text('untouched')
            with self.assertRaisesRegex(BridgeError,'empty'):
                s.project_create('test',str(path))
            self.assertEqual((path/'keep').read_text(),'untouched')
            s.close()

    def test_failed_process_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(BridgeError,'cannot find|No such|WinError'):
                AppServer(directory, executable=str(pathlib.Path(directory)/'does-not-exist.exe'))


class CoordinationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base=pathlib.Path(self.temp.name)
        self.service=Service(self.base/'state')
        self.addCleanup(self.service.close)
        self.service.project_create('project',str(self.base/'workspace'))
        self.worker=str(uuid.uuid4());self.auditor=str(uuid.uuid4())
        with self.service.registry.connect() as db:
            for worker,role in [(self.worker,'Developer'),(self.auditor,'Auditor')]:
                db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities) VALUES(?,'project',?,'test','[]')",(worker,role))
        self.task=self.service.task_assign('project','task',self.worker,'Implement a function.')

    def test_live_ack_beats_interrupted_persisted_history(self):
        turn_id=str(uuid.uuid4());calls=[]
        def call(method,params):
            calls.append(method)
            if method=='thread/read': return {'thread':{'status':{'type':'idle'}}}
            return {'data':[{'id':turn_id,'status':'interrupted','items':[]}]}
        self.service._transport=SimpleNamespace(closed=False,active={(self.worker,turn_id)},completed={},guard=threading.RLock(),call=call,close=lambda:None)
        self.service.loaded.add(self.worker)
        self.service.registry.reserve_message('live',self.worker,'instruction',None,self.service.instance)
        self.service.registry.set_message('live','sent',turn_id)
        result=self.service.message_status('live')
        self.assertEqual(result['delivery_state'],'sent')
        self.assertNotIn('thread/turns/list',calls)

    def test_cross_bridge_observer_does_not_resume_owner(self):
        self.service.registry.reserve_message('owned',self.worker,'instruction',None,self.service.instance)
        observer=Service(self.base/'state')
        try:
            result=observer.message_status('owned')
            self.assertTrue(result['owner_bridge_active'])
            self.assertIsNone(observer._transport)
            with self.assertRaisesRegex(BridgeError,'different live bridge'):
                observer.conversation_resume(self.worker)
        finally: observer.close()

    def test_restart_can_resolve_a_proven_never_dispatched_preparation(self):
        self.service.registry.reserve_message('prepared',self.worker,'instruction','task',self.service.instance)
        self.service.close()
        observer=Service(self.base/'state')
        try:
            result=observer.message_status('prepared')
            self.assertEqual(result['delivery_state'],'failed')
            self.assertIsNone(result['turn_id'])
            self.assertEqual(observer.registry.one('tasks','id','task')['state'],'blocked')
        finally: observer.close()

    def test_task_review_requires_independent_actual_verdict_and_revision(self):
        registry=self.service.registry
        def completed(key,worker,text,task=None):
            turn_id=str(uuid.uuid4());registry.reserve_message(key,worker,'prompt',task)
            registry.set_message(key,'sent',turn_id)
            registry.completed(worker,{'id':turn_id,'status':'completed','items':[{'type':'agentMessage','text':text}]})
        completed('dev',self.worker,'Done','task')
        completed('audit',self.auditor,'REJECT: incorrect boundary.')
        revision=registry.one('tasks','id','task')['revision']
        with self.assertRaisesRegex(BridgeError,'absent'):
            self.service.task_review('task',revision,'audit','accept','Claim contradicted by audit.')
        with self.assertRaisesRegex(BridgeError,'Task changed'):
            self.service.task_review('task',revision+1,'audit','reject','Stale caller.')
        result=self.service.task_review('task',revision,'audit','reject','Reproduced incorrect boundary.')
        self.assertEqual(result['state'],'rejected')
        with self.assertRaises(BridgeError):
            self.service.task_review('task',result['revision'],'dev','accept','Self audit.')

    def test_interrupted_task_requires_explicit_recovery(self):
        registry=self.service.registry
        registry.reserve_message('dev',self.worker,'prompt','task')
        tid=str(uuid.uuid4());registry.set_message('dev','sent',tid)
        registry.completed(self.worker,{'id':tid,'status':'interrupted','items':[]})
        task=registry.one('tasks','id','task')
        self.assertEqual(task['state'],'blocked')
        with self.assertRaisesRegex(BridgeError,'Cannot dispatch'):
            registry.reserve_message('retry',self.worker,'retry','task')
        recovered=self.service.task_recover('task',task['revision'],'Transport interruption observed; previous send is terminal.')
        self.assertEqual(recovered['state'],'ready')
        self.assertEqual(recovered['owner'],self.worker)
        self.assertTrue(registry.reserve_message('retry',self.worker,'retry','task')[1])

    def test_status_reports_acceptance_only_after_independent_review(self):
        r=self.service.registry
        for key,worker,task,text in [('dev',self.worker,'task','Implemented.'),('audit',self.auditor,None,'ACCEPT: verified boundary and tests.')]:
            tid=str(uuid.uuid4());r.reserve_message(key,worker,'instruction',task)
            r.set_message(key,'sent',tid);r.completed(worker,{'id':tid,'status':'completed','itemsView':'full','items':[{'type':'agentMessage','text':text}]})
        self.assertFalse(self.service.message_status('dev',reconcile=False)['task_verified'])
        task=r.one('tasks','id','task')
        self.service.task_review('task',task['revision'],'audit','accept','Controller independently ran tests.')
        self.assertTrue(self.service.message_status('dev',reconcile=False)['task_verified'])


if __name__ == '__main__':
    unittest.main()
