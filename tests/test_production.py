import json
import os
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'plugin'))
from orchestrator.authorization import grant_project
from orchestrator.auditing import artifact_hash
from orchestrator.errors import BridgeError
from orchestrator.routing import select_route
from orchestrator.service import Service
from orchestrator.tools import invoke
from test_upgrade import CATALOG


class RecordedTransport:
    def __init__(self,metadata):
        self.closed=False;self.metadata=metadata;self.calls=[]
        self.active=set();self.completed={};self.guard=threading.RLock();self.pending={}
        self.generation=str(uuid.uuid4())
    def close(self):self.closed=True
    def call(self,method,params):
        self.calls.append((method,params))
        if method=='thread/read':return {'thread':self.metadata[params['threadId']]}
        if method=='thread/resume':
            self.metadata.setdefault(params['threadId'],{'id':params['threadId'],'cwd':params.get('cwd'),'status':{'type':'idle'}})
            return {'thread':self.metadata[params['threadId']]}
        if method=='config/read':return {'config':{}}
        if method=='model/list':return {'data':CATALOG,'nextCursor':None}
        if method=='thread/turns/list':return {'data':self.turns,'nextCursor':None}
        return {}


class ProductionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=pathlib.Path(self.temp.name).resolve();self.state=self.base/'state'
        self.roots={p:self.base/p for p in ('alpha','beta')}
        self.coordinators={p:str(uuid.uuid4()) for p in self.roots}
        self.meta={}
        for p,root in self.roots.items():
            root.mkdir();self.meta[self.coordinators[p]]={'id':self.coordinators[p],'cwd':str(root),'name':p,'status':{'type':'idle'}}
        def factory(*args,**kwargs):return RecordedTransport(self.meta)
        self.a=Service(self.state,transport_factory=factory);self.addCleanup(self.a.close)
        for p,root in self.roots.items():grant_project(self.a.registry,p,root,self.coordinators[p],headless=True)
        self.b=Service(self.state,transport_factory=factory);self.addCleanup(self.b.close)
        for service,p in [(self.a,'alpha'),(self.b,'beta')]:
            invoke(service,'coordinator_register',{'project_id':p,'coordinator_thread_id':self.coordinators[p]})
        self.workers={}
        with self.a.registry.connect() as db:
            for project in self.roots:
                for role in ('Developer','Auditor'):
                    tid=str(uuid.uuid4());self.workers[(project,role)]=tid
                    self.meta[tid]={'id':tid,'cwd':str(self.roots[project]),'status':{'type':'idle'}}
                    db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities,workspace,desktop_sync_state) VALUES(?,?,?,?,'[]',?,'headless')",(tid,project,role,role,str(self.roots[project])))

    def test_two_coordinators_have_scoped_status_and_namespaces(self):
        for service,project in [(self.a,'alpha'),(self.b,'beta')]:
            result=invoke(service,'task_assign',{'project_id':project,'task_id':'same-task','owner':self.workers[(project,'Developer')],'requirements':'Independent contract'})
            self.assertEqual(result['id'],project+'::same-task')
            invoke(service,'project_note',{'project_id':project,'kind':'decision','text':project})
            status=invoke(service,'project_status',{})
            self.assertEqual([p['id'] for p in status['projects']],[project])
            self.assertTrue(all(w['project_id']==project for w in status['workers']))
            self.assertEqual([n['text'] for n in status['notes']],[project])

    def test_grant_change_cannot_overlap_control_preparation(self):
        with self.a._control_operation('creation-preflight'):
            with self.assertRaisesRegex(BridgeError,'control operation'):
                grant_project(self.a.registry,'alpha',self.roots['alpha'],self.coordinators['alpha'],desktop_ui_id='native')
            with self.assertRaisesRegex(BridgeError,'control operation'):
                self.b.project_note('beta','decision','Concurrent mutation')
        self.b.project_note('beta','decision','Independent mutation after short gate')

    def test_repeated_registration_preserves_live_transport(self):
        transport=self.a.rpc
        result=self.a.coordinator_register('alpha',self.coordinators['alpha'])
        self.assertTrue(result['duplicate_prevented']);self.assertIs(self.a.rpc,transport)
        self.assertFalse(transport.closed)

    def test_role_and_archive_assignment_interleavings_are_fenced(self):
        worker=self.workers[('alpha','Developer')]
        entered=threading.Event();release=threading.Event();done=threading.Event();errors=[]
        def preparing():
            with self.a._control_operation('send-preparation'):
                entered.set();release.wait(5)
        def change():
            try:self.a.conversation_role(worker,'Auditor')
            except Exception as exc:errors.append(exc)
            finally:done.set()
        first=threading.Thread(target=preparing);second=threading.Thread(target=change)
        first.start();self.assertTrue(entered.wait(3));second.start()
        self.assertFalse(done.wait(.1));release.set();first.join(3);second.join(3)
        self.assertFalse(errors);self.assertTrue(done.is_set())
        rpc=self.a.rpc;old=rpc.call
        def call(method,params):
            if method=='thread/list':return {'data':[{'id':worker}] if not params['archived'] else [],'nextCursor':None}
            if method=='thread/resume':return {'thread':{'status':{'type':'idle'}}}
            if method=='thread/archive':return {}
            return old(method,params)
        rpc.call=call;self.a.conversation_archive(worker,'Complete')
        with self.assertRaisesRegex(BridgeError,'Archived'):
            self.a.task_assign('alpha','after-archive',worker,'No stranded task')

    def test_concurrent_registration_cannot_hold_two_project_leases(self):
        self.a.close();self.b.close()
        service=Service(self.state,transport_factory=lambda *a,**k:RecordedTransport(self.meta));self.addCleanup(service.close)
        start=threading.Barrier(2);results=[]
        def register(project):
            start.wait()
            try:service.coordinator_register(project,self.coordinators[project]);results.append('ok')
            except BridgeError:results.append('denied')
        threads=[threading.Thread(target=register,args=(p,)) for p in self.roots]
        for thread in threads:thread.start()
        for thread in threads:thread.join(5)
        self.assertEqual(sorted(results),['denied','ok'])
        self.assertEqual(len(service.registry.rows('SELECT * FROM coordinator_leases WHERE owner_token=?',(service.instance,))),1)

    def test_reserved_project_separator_and_external_worker_overlap(self):
        for project in ['p::nested','p:',':p']:
            with self.assertRaisesRegex(BridgeError,'separator'):
                grant_project(self.a.registry,project,self.base/'alpha',str(uuid.uuid4()),headless=True)
        external=self.base/'external-worktree';external.mkdir()
        with self.a.registry.connect() as db:
            db.execute('UPDATE conversations SET workspace=? WHERE thread_id=?',(str(external),self.workers[('alpha','Developer')]))
        with self.assertRaisesRegex(BridgeError,'worker workspace'):
            grant_project(self.a.registry,'external',external,str(uuid.uuid4()),headless=True)

    def test_uncertain_archive_keeps_fence_until_native_reconciliation(self):
        worker=self.workers[('alpha','Developer')];rpc=self.a.rpc;old=rpc.call
        def call(method,params):
            if method=='thread/list':return {'data':[{'id':worker}] if not params['archived'] else [],'nextCursor':None}
            if method=='thread/resume':return {'thread':{'status':{'type':'idle'}}}
            if method=='thread/archive':raise BridgeError('RPC_TIMEOUT','Uncertain archive')
            return old(method,params)
        rpc.call=call
        with self.assertRaisesRegex(BridgeError,'Uncertain archive'):self.a.conversation_archive(worker,'Finished')
        self.assertEqual(self.a.registry.rows('SELECT stage FROM operations')[0]['stage'],'dispatching')
        for action in [lambda:self.a.message_send(worker,'work','after-archive'),lambda:self.a.task_assign('alpha','late',worker,'late assignment'),lambda:self.a.conversation_role(worker,'Auditor')]:
            with self.assertRaisesRegex(BridgeError,'lifecycle'):action()
        self.a.bridge_release();rpc=self.a.rpc;old=rpc.call
        def reconcile(method,params):
            if method=='thread/list':return {'data':[{'id':worker}] if params['archived'] else [],'nextCursor':None}
            return old(method,params)
        rpc.call=reconcile
        # The old lifecycle owner has released its transport; reconciliation
        # itself must start with no cached transport from that owner.
        self.a._transport=None
        self.a.transport_factory=lambda *a,**k:rpc
        result=self.a.conversation_lifecycle_reconcile(worker)
        self.assertTrue(result['worker']['archived']);self.assertFalse(self.a.registry.rows('SELECT * FROM operations'))

    def test_worker_effective_integrations_are_disabled_on_resume(self):
        worker=self.workers[('alpha','Developer')];rpc=self.a.rpc;old=rpc.call
        def call(method,params):
            if method=='config/read':return {'config':{'mcp_servers':{'worker.only':{'command':'private-command','env':{'TOKEN':'private'}}},'plugins':{'worker-plugin':{'enabled':True}}}}
            if method=='thread/resume':
                self.assertEqual(params['config']['mcp_servers'],{'worker.only':{'enabled':False}})
                self.assertEqual(params['config']['plugins'],{'worker-plugin':{'enabled':False}})
                self.assertNotIn('private',json.dumps(params));return {'thread':{'status':{'type':'idle'}}}
            return old(method,params)
        rpc.call=call;self.a.conversation_resume(worker)

    def test_unarchive_checks_native_state_instead_of_stale_registry_flag(self):
        worker=self.workers[('alpha','Developer')];rpc=self.a.rpc;old=rpc.call;native={'archived':True,'calls':0}
        def call(method,params):
            if method=='thread/list':return {'data':[{'id':worker}] if params['archived']==native['archived'] else [],'nextCursor':None}
            if method=='thread/unarchive':native['archived']=False;native['calls']+=1;return {}
            return old(method,params)
        rpc.call=call
        self.a.conversation_unarchive(worker)
        self.assertFalse(self.a.registry.one('conversations','thread_id',worker)['archived'])
        self.assertTrue(self.a.conversation_unarchive(worker)['duplicate_prevented'])
        self.assertEqual(native['calls'],1)

    def test_uncertain_lifecycle_is_project_local_and_failed_prepare_is_recoverable(self):
        worker=self.workers[('alpha','Developer')]
        self.a.meta=None
        with self.a.registry.connect() as db:
            db.execute("INSERT INTO operations(thread_id,owner_token,name,stage) VALUES(?,?,'desktop_prepare','dispatching')",(worker,self.a.instance))
        # Unrelated local policy changes remain available while alpha is fenced.
        grant_project(self.a.registry,'beta',self.roots['beta'],self.coordinators['beta'],headless=True,integrations=['mcp_servers.local'])
        with self.assertRaisesRegex(BridgeError,'uncertain'):
            grant_project(self.a.registry,'alpha',self.roots['alpha'],self.coordinators['alpha'],headless=True)
        self.a.bridge_release()
        self.meta[worker]={'id':worker,'cwd':str(self.roots['alpha']),'projectId':'unchanged-canonical-project'}
        result=self.a.conversation_lifecycle_reconcile(worker)
        self.assertTrue(result['reconciled'])
        self.assertEqual(result['worker']['desktop_sync_state'],'pending')
        self.assertFalse(self.a.registry.rows('SELECT * FROM operations'))

    def test_legacy_lifecycle_migration_is_conservative(self):
        from orchestrator.storage import Registry
        worker=self.workers[('alpha','Developer')]
        with self.a.registry.connect() as db:
            db.execute('DROP TABLE operations')
            db.execute('CREATE TABLE operations(thread_id TEXT PRIMARY KEY,owner_token TEXT NOT NULL,name TEXT NOT NULL)')
            db.execute("INSERT INTO operations VALUES(?,?,'archive')",(worker,'old-owner'))
            db.execute('PRAGMA user_version=6')
        migrated=Registry(self.a.registry.path)
        self.assertEqual(migrated.rows('SELECT stage FROM operations')[0]['stage'],'dispatching')
        with self.assertRaisesRegex(BridgeError,'lifecycle'):
            self.a.message_send(worker,'Must be blocked','legacy-fence')

    def test_redirected_grant_root_blocks_creation_preflight(self):
        from unittest.mock import patch
        with patch('orchestrator.authorization.canonical',return_value=str(self.roots['beta'])):
            with self.assertRaisesRegex(BridgeError,'resolves elsewhere'):
                self.a.conversation_create('alpha','No redirect','Developer','root-redirect')
        self.assertFalse(self.a.registry.rows("SELECT * FROM creations WHERE key='root-redirect'"))

    def test_cross_project_reads_mutations_and_rebinding_are_denied(self):
        for tool,args in [('conversation_role',{'thread_id':self.workers[('beta','Developer')],'role':'Auditor'}),
                          ('conversation_read',{'thread_id':self.workers[('beta','Developer')]}),
                          ('conversation_archive',{'thread_id':self.workers[('beta','Auditor')],'reason':'wrong project'}),
                          ('project_status',{'project_id':'beta'}),
                          ('project_note',{'project_id':'beta','kind':'decision','text':'wrong'}),
                          ('coordinator_register',{'project_id':'beta','coordinator_thread_id':self.coordinators['beta']})]:
            with self.subTest(tool=tool),self.assertRaises(BridgeError):invoke(self.a,tool,args)
        with self.assertRaises(BridgeError):invoke(self.a,'conversation_read',{'thread_id':str(uuid.uuid4())})
        self.assertIsNone(self.a._transport)

    def test_optional_canonical_identity_can_be_verified_after_native_grant(self):
        rpc=self.a.rpc;old=rpc.call
        def call(method,params):
            if method=='project/read':return {'project':{'id':'canonical-alpha','roots':[{'path':str(self.roots['alpha'])}]}}
            return old(method,params)
        rpc.call=call
        result=self.a.project_link('alpha','canonical-alpha',self.coordinators['alpha'])
        self.assertEqual(result['registry_project']['desktop_project_id'],'canonical-alpha')

    def test_coordinator_cannot_receive_implementation_tasks_or_worker_messages(self):
        with self.assertRaisesRegex(BridgeError,'Assign delivery'):
            invoke(self.a,'task_assign',{'project_id':'alpha','task_id':'self','owner':self.coordinators['alpha'],'requirements':'Implement code'})
        with self.assertRaisesRegex(BridgeError,'directs workers'):
            invoke(self.a,'message_send',{'thread_id':self.coordinators['alpha'],'message':'Implement','message_key':'self'})

    def test_unbound_service_cannot_read_production_data(self):
        outsider=Service(self.state);self.addCleanup(outsider.close)
        self.assertFalse(invoke(outsider,'project_status',{})['projects'])
        with self.assertRaises(BridgeError):invoke(outsider,'conversation_read',{'thread_id':self.workers[('alpha','Developer')]})

    def test_one_live_coordinator_connection_and_revoked_grants(self):
        other=Service(self.state,transport_factory=lambda *a,**k:RecordedTransport(self.meta));self.addCleanup(other.close)
        with self.assertRaisesRegex(BridgeError,'live MCP connection'):
            invoke(other,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['alpha']})
        with self.a.registry.connect() as db:db.execute("UPDATE authorizations SET enabled=0 WHERE project_id='alpha'")
        with self.assertRaises(BridgeError):invoke(self.a,'project_status',{})
        self.assertEqual(invoke(self.b,'project_status',{})['projects'][0]['id'],'beta')

    def test_changed_grant_invalidates_old_connection_and_native_confirmation(self):
        grant_project(self.a.registry,'alpha',self.roots['alpha'],self.coordinators['alpha'],desktop_ui_id='new-native-id')
        with self.assertRaises(BridgeError):invoke(self.a,'project_status',{})
        rows=self.a.registry.rows("SELECT desktop_sync_state FROM conversations WHERE project_id='alpha' AND role='Developer'")
        self.assertEqual(rows[0]['desktop_sync_state'],'pending')
        self.assertEqual(invoke(self.b,'project_status',{})['projects'][0]['id'],'beta')

    def test_same_coordinator_refreshes_changed_policy_without_restart(self):
        old=self.a.rpc;other=self.b.rpc;before=self.b.project_policy.copy()
        grant_project(self.a.registry,'alpha',self.roots['alpha'],self.coordinators['alpha'],headless=True,integrations=['mcp_servers.example'])
        with self.assertRaises(BridgeError):invoke(self.a,'project_status',{})
        result=invoke(self.a,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['alpha']})
        self.assertTrue(result['policy_refreshed']);self.assertFalse(result['restart_required'])
        self.assertTrue(old.closed);self.assertIsNone(self.a._transport)
        self.assertEqual(json.loads(self.a.project_policy['integrations']),['mcp_servers.example'])
        self.assertEqual(invoke(self.a,'project_status',{})['projects'][0]['root'],str(self.roots['alpha']))
        self.assertIs(self.b.rpc,other);self.assertFalse(other.closed);self.assertEqual(before,self.b.project_policy)

    def test_policy_refresh_refuses_pending_work_and_preserves_transport(self):
        old=self.a.rpc;prior=self.a.project_policy.copy()
        grant_project(self.a.registry,'alpha',self.roots['alpha'],self.coordinators['alpha'],headless=True,integrations=['mcp_servers.example'])
        with self.a.registry.connect() as db:
            db.execute("INSERT INTO messages(key,thread_id,fingerprint,text,state,created,updated) VALUES('pending-refresh',?,'fixture','fixture','unknown',0,0)",(self.workers[('alpha','Developer')],))
        with self.assertRaisesRegex(BridgeError,'Reconcile'):
            invoke(self.a,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['alpha']})
        self.assertEqual(prior,self.a.project_policy);self.assertIs(self.a._transport,old);self.assertFalse(old.closed)

    def test_revocation_cannot_be_refreshed_but_idle_transport_can_be_released(self):
        old=self.a.rpc
        with self.a.registry.connect() as db:db.execute("UPDATE authorizations SET enabled=0 WHERE project_id='alpha'")
        with self.assertRaises(BridgeError):invoke(self.a,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['alpha']})
        self.assertTrue(invoke(self.a,'bridge_release',{})['released']);self.assertTrue(old.closed)
        self.assertEqual(self.a.registry.one('authorizations','project_id','alpha')['enabled'],0)

    def test_policy_refresh_rejects_foreign_identity_and_moved_native_root(self):
        old=self.a.rpc
        grant_project(self.a.registry,'alpha',self.roots['alpha'],self.coordinators['alpha'],headless=True,integrations=['mcp_servers.example'])
        with self.assertRaisesRegex(BridgeError,'identity cannot change'):
            invoke(self.a,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['beta']})
        self.meta[self.coordinators['alpha']]['cwd']=str(self.roots['beta'])
        with self.assertRaisesRegex(BridgeError,'moved away'):
            invoke(self.a,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['alpha']})
        self.assertIs(self.a._transport,old);self.assertFalse(old.closed)

    def test_overlapping_projects_and_unrelated_workspaces_are_rejected(self):
        nested=self.roots['alpha']/'nested';nested.mkdir()
        with self.assertRaisesRegex(BridgeError,'non-overlapping'):
            grant_project(self.a.registry,'nested',nested,str(uuid.uuid4()),headless=True)
        with self.assertRaises(BridgeError):
            self.a._creation_context(self.a._project('alpha'),workspace=str(self.roots['beta']))

    def test_lifecycle_reservation_excludes_dispatch_and_coordinator_is_protected(self):
        worker=self.workers[('alpha','Developer')]
        with self.a._exclusive_operation(worker,'archive'):
            with self.assertRaisesRegex(BridgeError,'lifecycle'):
                self.a.registry.reserve_message('a',worker,'work',None)
        with self.assertRaisesRegex(BridgeError,'coordinator'):
            self.a.conversation_archive(self.coordinators['alpha'],'self archive')

    def test_dispatch_fence_prevents_start_after_preparation_was_failed(self):
        r=self.a.registry;worker=self.workers[('alpha','Developer')]
        r.reserve_message('fenced',worker,'work',None,self.a.instance)
        r.set_message('fenced','failed')
        with self.assertRaisesRegex(BridgeError,'no longer owns'):r.mark_dispatching('fenced',self.a.instance)

    def test_closed_bridge_cannot_reconnect_and_restart_takes_lease(self):
        self.a.close()
        with self.assertRaisesRegex(BridgeError,'shut down'):self.a.rpc
        other=Service(self.state,transport_factory=lambda *a,**k:RecordedTransport(self.meta));self.addCleanup(other.close)
        invoke(other,'coordinator_register',{'project_id':'alpha','coordinator_thread_id':self.coordinators['alpha']})
        self.assertEqual(invoke(other,'project_status',{})['activation'],'authorized_project')

    def test_difficulty_only_configuration_escalates_and_role_refreshes_sandbox(self):
        worker=self.workers[('alpha','Developer')]
        result=invoke(self.a,'conversation_configure',{'thread_id':worker,'model':'gpt-6-luna','effort':'low'})
        result=invoke(self.a,'conversation_configure',{'thread_id':worker,'difficulty':'complex'})
        self.assertEqual((result['routing']['model'],result['routing']['effort']),('gpt-6-astra','high'))
        self.a.loaded.add(worker)
        invoke(self.a,'conversation_role',{'thread_id':worker,'role':'Auditor'})
        self.assertIn(worker,self.a.loaded);self.assertIsNone(self.a.loaded_artifacts[worker])
        rpc=self.a.rpc;old=rpc.call
        def call(method,params):
            if method=='thread/resume':
                self.assertEqual(params['sandbox'],'read-only')
                self.assertIn('Assigned role: Auditor',params['developerInstructions'])
                return {'thread':{'status':{'type':'idle'}}}
            return old(method,params)
        rpc.call=call
        self.a.conversation_resume(worker)

    def test_exact_turn_identity_wins_over_quoted_marker_and_ambiguity_fails(self):
        rpc=self.a.rpc
        def turn(tid,text):return {'id':tid,'status':'completed','items':[{'type':'userMessage','content':[{'type':'text','text':text}]}]}
        rpc.turns=[turn('quoted','[marker]\nquoted'),turn('original','[marker]\noriginal')]
        self.assertEqual(self.a._turn('any','original','[marker]')['id'],'original')
        with self.assertRaisesRegex(BridgeError,'Several persisted'):self.a._turn('any',marker='[marker]')

    def test_new_audits_are_bound_to_current_artifacts_and_delivery(self):
        r=self.a.registry;developer=self.workers[('alpha','Developer')];auditor=self.workers[('alpha','Auditor')]
        task=invoke(self.a,'task_assign',{'project_id':'alpha','task_id':'work','owner':developer,'requirements':'contract'})
        r.reserve_message('delivery',developer,'work',task['id']);r.set_message('delivery','sent','turn-1')
        r.completed(developer,{'id':'turn-1','status':'completed','itemsView':'full','items':[]})
        path=self.roots['alpha']/'artifact.txt';path.write_text('v1')
        link=self.a._audit_request(r.one('conversations','thread_id',auditor),task['id'],[{'path':str(path),'sha256':artifact_hash(path)}])
        r.reserve_message('audit',auditor,'audit',None,audit_link=link);r.set_message('audit','sent','audit-turn')
        r.completed(auditor,{'id':'audit-turn','status':'completed','itemsView':'full','items':[{'type':'agentMessage','text':'**ACCEPT** — verified.'}]})
        revision=r.one('tasks','id',task['id'])['revision']
        path.write_text('v2')
        with self.assertRaisesRegex(BridgeError,'differs'):self.a.task_review(task['id'],revision,'audit','accept','Evidence')
        path.write_text('v1')
        with r.connect() as db:db.execute('UPDATE tasks SET revision=revision+1 WHERE id=?',(task['id'],))
        with self.assertRaisesRegex(BridgeError,'current task delivery'):self.a.task_review(task['id'],revision+1,'audit','accept','Evidence')

    def test_final_audit_verdict_is_separate_from_commentary(self):
        r=self.a.registry;developer=self.workers[('alpha','Developer')];auditor=self.workers[('alpha','Auditor')]
        task=invoke(self.a,'task_assign',{'project_id':'alpha','task_id':'work','owner':developer,'requirements':'contract'})
        r.reserve_message('delivery',developer,'work',task['id']);r.set_message('delivery','sent','work-turn')
        r.completed(developer,{'id':'work-turn','status':'completed','items':[]})
        path=self.roots['alpha']/'artifact.txt';path.write_text('current')
        link=self.a._audit_request(r.one('conversations','thread_id',auditor),task['id'],[{'path':str(path),'sha256':artifact_hash(path)}])
        r.reserve_message('audit',auditor,'audit',None,audit_link=link);r.set_message('audit','sent','audit-turn')
        r.completed(auditor,{'id':'audit-turn','status':'completed','items':[{'type':'agentMessage','text':'I will inspect the code.','phase':'commentary'},{'type':'agentMessage','text':'ACCEPT: verified current artifact.','phase':'final_answer'}]})
        result=self.a.task_review(task['id'],r.one('tasks','id',task['id'])['revision'],'audit','accept','Controller evidence')
        self.assertEqual(result['state'],'accepted')

    def test_pre_task_audit_cannot_accept_production_work(self):
        r=self.a.registry;developer=self.workers[('alpha','Developer')];auditor=self.workers[('alpha','Auditor')]
        task=invoke(self.a,'task_assign',{'project_id':'alpha','task_id':'work','owner':developer,'requirements':'contract'})
        for key,worker,task_id in [('old-audit',auditor,None),('work',developer,task['id'])]:
            r.reserve_message(key,worker,'prompt',task_id);r.set_message(key,'sent',key)
            r.completed(worker,{'id':key,'status':'completed','items':[{'type':'agentMessage','text':'ACCEPT: unrelated.'}]})
        with self.assertRaisesRegex(BridgeError,'task-bound audit'):
            self.a.task_review(task['id'],r.one('tasks','id',task['id'])['revision'],'old-audit','accept','Invalid old audit')


class AdditionalRegressionTests(unittest.TestCase):
    def test_integration_credentials_are_not_copied_into_process_arguments(self):
        from unittest.mock import patch
        from orchestrator.transport import AppServer
        with tempfile.TemporaryDirectory() as temp:
            home=pathlib.Path(temp)
            (home/'config.toml').write_text('[mcp_servers."service.with.dots"]\ncommand="python"\n[mcp_servers."service.with.dots".env]\nTOKEN="synthetic-private-value"\n',encoding='utf-8')
            captured=[]
            def popen(command,**kwargs):
                captured.append(command)
                self.assertNotIn('synthetic-private-value',' '.join(command))
                self.assertIn('mcp_servers={"service.with.dots"={"enabled"=false}}',command)
                raise OSError('Synthetic process stop after checking arguments')
            with patch.dict(os.environ,{'CODEX_HOME':temp}),patch('orchestrator.transport.subprocess.Popen',side_effect=popen):
                with self.assertRaises(BridgeError):AppServer(home/'logs',executable=sys.executable)
            self.assertEqual(len(captured),1)

    def test_toml_table_overrides_preserve_literal_dotted_integration_names(self):
        import tomllib
        from orchestrator.transport import toml_value
        value={'service.with.dots':{'command':'python','args':['file with spaces.py'],'enabled':False}}
        self.assertEqual(tomllib.loads('mcp_servers='+toml_value(value))['mcp_servers'],value)

    def test_creation_config_failure_does_not_poison_idempotency_key(self):
        with tempfile.TemporaryDirectory() as temp:
            meta={};rpc=RecordedTransport(meta);calls=[]
            old=rpc.call;fail=[True]
            def call(method,params):
                calls.append(method)
                if method=='config/read' and fail[0]:
                    fail[0]=False;raise BridgeError('RPC_TIMEOUT','Read preparation failed')
                if method=='thread/start':return {'thread':{'id':str(uuid.uuid4())},'model':params['model'],'reasoningEffort':params['config']['model_reasoning_effort']}
                return old(method,params)
            rpc.call=call;s=Service(pathlib.Path(temp)/'state',transport_factory=lambda *a,**k:rpc)
            try:
                s.project_create('test',str(pathlib.Path(temp)/'root'))
                args=dict(project_id='test',name='worker',role='Developer',create_key='stable')
                with self.assertRaises(BridgeError):s.conversation_create(**args)
                self.assertFalse(s.registry.rows('SELECT * FROM creations'))
                s.conversation_create(**args)
                self.assertEqual(calls.count('thread/start'),1)
            finally:s.close()

    def test_shutdown_drains_running_handlers_before_closing_service(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        script="""import sys,time
sys.path.insert(0,sys.argv[1]);import server
class Fake:
    def __init__(self):self.closed=False
    def close(self):self.closed=True
def invoke(service,*args):
    time.sleep(.2)
    return {'alive':not service.closed}
server.Service=Fake;server.invoke=invoke;server.main()
"""
        packets=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},
                 {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'slow','arguments':{}}}]
        run=subprocess.run([sys.executable,'-c',script,str(root/'plugin')],input='\n'.join(json.dumps(p) for p in packets)+'\n',text=True,capture_output=True,timeout=10)
        self.assertEqual(run.returncode,0,run.stderr)
        response=next(json.loads(line) for line in run.stdout.splitlines() if json.loads(line)['id']==2)
        self.assertTrue(json.loads(response['result']['content'][0]['text'])['alive'])

    def test_automatic_routing_never_selects_ultra_even_as_catalog_default(self):
        catalog=[{'model':'other','supportedReasoningEfforts':[{'reasoningEffort':'ultra'},{'reasoningEffort':'high'}],'defaultReasoningEffort':'ultra','isDefault':True}]
        self.assertEqual(select_route(catalog,justification='Unrelated escalation')['effort'],'high')
        with self.assertRaises(BridgeError):select_route([dict(catalog[0],supportedReasoningEfforts=[{'reasoningEffort':'ultra'}])],justification='Escalation')

    def test_mcp_rejects_invalid_envelopes_without_executing_tools(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp:
            env=os.environ.copy();env['ORCHESTRATOR_DATA_DIR']=temp
            packets=[{'jsonrpc':'1.0','id':{'bad':1},'method':'tools/list'}, {'jsonrpc':'2.0','id':1,'method':'tools/list','params':None},[{'method':'ping'}]]
            run=subprocess.run([sys.executable,str(root/'plugin/server.py')],input='\n'.join(json.dumps(p) for p in packets)+'\n',text=True,capture_output=True,env=env,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            results=[json.loads(line) for line in run.stdout.splitlines()]
            self.assertEqual(len(results),3)
            self.assertTrue(all(r['error']['code']==-32600 for r in results))


if __name__=='__main__':unittest.main()
