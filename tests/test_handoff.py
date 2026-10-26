import datetime
import json
import os
import pathlib
import tempfile
import time
import threading
import sqlite3
import unittest
import uuid
from unittest.mock import patch

from test_artifacts import ArtifactTransport
from orchestrator.authorization import grant_project
from orchestrator.errors import BridgeError
from orchestrator.handoff import project_bridge_register,project_bridge_prepare,recent_release_proof,preflight_project_bridge,RELEASE_COMMAND
from orchestrator.service import Service


class ProjectBridgeHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=pathlib.Path(self.temp.name);self.home=self.base/'profile';(self.home/'sessions').mkdir(parents=True)
        self.roots={name:self.base/name for name in ('alpha','beta')};self.ids={name:str(uuid.uuid4()) for name in self.roots};self.meta={}
        for name,root in self.roots.items():
            root.mkdir();path=self.home/'sessions'/(name+'.jsonl')
            self.meta[self.ids[name]]={'id':self.ids[name],'cwd':str(root),'path':str(path),'status':{'type':'idle'}}
        self.factory=lambda *args,**kw:ArtifactTransport(self.meta)
        self.old=Service(self.base/'state',transport_factory=self.factory);self.addCleanup(self.old.close)
        self.other=Service(self.base/'state',transport_factory=self.factory);self.addCleanup(self.other.close)
        self.new=Service(self.base/'state',transport_factory=self.factory);self.addCleanup(self.new.close)
        for name,root in self.roots.items():grant_project(self.old.registry,name,root,self.ids[name],headless=True)
        self.old.coordinator_register('alpha',self.ids['alpha']);self.other.coordinator_register('beta',self.ids['beta'])
        self.env=patch.dict(os.environ,{'CODEX_THREAD_ID':self.ids['alpha'],'CODEX_HOME':str(self.home)})
        self.env.start();self.addCleanup(self.env.stop)
        project_bridge_prepare(self.new,'alpha')
        self.write_release()

    def write_release(self,age=0,mutation=False,fork=False,command=RELEASE_COMMAND,owner=None,output=None):
        stamp=datetime.datetime.fromtimestamp(time.time()-age,datetime.timezone.utc).isoformat()
        result=(owner or self.old).bridge_release()
        end=datetime.datetime.fromtimestamp(time.time()-age,datetime.timezone.utc).isoformat()
        thread=self.meta[self.ids['alpha']]
        rows=[{'type':'session_meta','payload':{'id':self.ids['alpha'],'cwd':str(self.roots['alpha']),'timestamp':stamp}},
            {'type':'response_item','timestamp':stamp,'payload':{'type':'custom_tool_call','name':'exec','call_id':'release-call','input':command}},
            {'type':'response_item','timestamp':end,'payload':{'type':'custom_tool_call_output','call_id':'release-call','output':output if output is not None else json.dumps(result)}}]
        if mutation:rows.append({'type':'response_item','timestamp':stamp,'payload':{'type':'function_call','name':'exec','call_id':'send','arguments':'tools.mcp__conversation_orchestrator__message_send({})'}})
        if fork:rows.append({'type':'session_meta','payload':{'id':str(uuid.uuid4()),'cwd':str(self.roots['alpha']),'timestamp':stamp}})
        pathlib.Path(thread['path']).write_text(''.join(json.dumps(x)+'\n' for x in rows),encoding='utf-8')

    def test_same_chat_handoff_fences_old_scope_and_preserves_other_project(self):
        before=self.old.registry.rows('SELECT * FROM authorizations ORDER BY project_id')
        result=project_bridge_register(self.new,'alpha',handoff=True)
        self.assertEqual(result['coordinator_thread_id'],self.ids['alpha'])
        self.assertEqual(self.new.project_scope,'alpha')
        self.assertEqual(self.new.project_status('alpha')['projects'][0]['root'],str(self.roots['alpha']))
        with self.assertRaisesRegex(BridgeError,'registration'):self.old.project_status('alpha')
        after=self.new.registry.rows('SELECT * FROM authorizations ORDER BY project_id')
        self.assertEqual(before[1],after[1])
        self.assertEqual({k:v for k,v in before[0].items() if k!='created'},{k:v for k,v in after[0].items() if k!='created'})
        self.assertNotEqual(before[0]['created'],after[0]['created'])
        self.assertEqual(self.other.project_status('beta')['projects'][0]['root'],str(self.roots['beta']))
        replay=Service(self.base/'state',transport_factory=self.factory);self.addCleanup(replay.close)
        with self.assertRaisesRegex(BridgeError,'prepare-handoff'):project_bridge_register(replay,'alpha',handoff=True)

    def test_pending_send_blocks_handoff_without_fencing(self):
        with self.old.registry.connect() as db:
            db.execute("INSERT INTO messages(key,thread_id,fingerprint,text,state,created,updated) VALUES('pending',?,'fixture','pending','sent',?,?)",(self.ids['alpha'],time.time(),time.time()))
        before=self.old.registry.rows('SELECT * FROM authorizations WHERE project_id=?',('alpha',))
        with self.assertRaisesRegex(BridgeError,'terminal'):project_bridge_register(self.new,'alpha',handoff=True)
        self.assertEqual(self.old.registry.rows('SELECT * FROM authorizations WHERE project_id=?',('alpha',)),before)
        self.assertEqual(self.old.project_status('alpha')['unresolved_messages'][0]['key'],'pending')

    def test_wrong_shell_cannot_take_over_another_coordinator(self):
        transport=self.new._transport
        os.environ['CODEX_THREAD_ID']=self.ids['beta']
        with self.assertRaisesRegex(BridgeError,'original'):project_bridge_register(self.new,'alpha',handoff=True)
        self.assertIs(self.new._transport,transport)

    def test_release_proof_rejects_stale_fork_and_following_mutation(self):
        thread=self.meta[self.ids['alpha']]
        for kwargs in ({'age':600},{'fork':True},{'mutation':True}):
            self.write_release(**kwargs)
            with self.subTest(kwargs=kwargs):
                release=self.old.registry.rows('SELECT * FROM bridge_control_activity WHERE token=?',(self.old.instance,))[0]
                with self.assertRaises(BridgeError):recent_release_proof(thread,0,release)

    def test_non_handoff_registration_cannot_steal_a_live_lease(self):
        with self.assertRaisesRegex(BridgeError,'different live'):project_bridge_register(self.new,'alpha',handoff=False)

    def test_wrong_caller_preflight_does_not_migrate_existing_schema(self):
        with self.old.registry.connect() as db:db.execute('PRAGMA user_version=10')
        os.environ['CODEX_THREAD_ID']=self.ids['beta']
        with self.assertRaisesRegex(BridgeError,'shell'):preflight_project_bridge(self.base/'state','alpha',True)
        with self.old.registry.connect() as db:self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],10)

    def test_worker_identity_is_rejected_before_epoch_change(self):
        before=self.old.registry.rows('SELECT * FROM authorizations WHERE project_id=?',('alpha',))
        with self.old.registry.connect() as db:db.execute("UPDATE conversations SET role='Developer' WHERE thread_id=?",(self.ids['alpha'],))
        with self.assertRaisesRegex(BridgeError,'worker'):project_bridge_register(self.new,'alpha',True)
        self.assertEqual(self.old.registry.rows('SELECT * FROM authorizations WHERE project_id=?',('alpha',)),before)

    def test_reports_other_namespace_and_failed_envelopes_are_not_release_proof(self):
        for kwargs in (
            {'command':'text(await tools.exec_command({cmd:"read saved-bridge_release-report.json"}));'},
            {'command':'text(await tools.mcp__other_instance__bridge_release({}));'},
            {'output':json.dumps({'isError':True,'content':[{'type':'text','text':json.dumps({'released':True,'histories_preserved':True})}]})}):
            with self.subTest(kwargs=kwargs):
                self.write_release(**kwargs)
                with self.assertRaisesRegex(BridgeError,'execute exactly'):project_bridge_register(self.new,'alpha',True)

    def test_actual_native_exec_output_envelope_is_decoded(self):
        envelope={'content':[{'type':'text','text':json.dumps({'released':True,'histories_preserved':True}).replace('"','\\"')}],'isError':False}
        self.write_release(output=[{'type':'input_text','text':'Script completed\nOutput:\n'},{'type':'input_text','text':json.dumps(envelope)}])
        self.assertEqual(project_bridge_register(self.new,'alpha',True)['connection_scope'],'alpha')

    def test_unprepared_or_preparation_after_release_requires_new_owner_release(self):
        project_bridge_prepare(self.new,'alpha')
        with self.assertRaisesRegex(BridgeError,'after prepare-handoff'):project_bridge_register(self.new,'alpha',True)
        self.write_release();self.assertEqual(project_bridge_register(self.new,'alpha',True)['connection_scope'],'alpha')

    def add_worker(self):
        worker=str(uuid.uuid4());self.meta[worker]={'id':worker,'cwd':str(self.roots['alpha']),'status':{'type':'idle'}}
        with self.old.registry.connect() as db:
            db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities,workspace,desktop_sync_state) VALUES(?,'alpha','Developer','fixture','[]',?,'headless')",(worker,str(self.roots['alpha'])))
        return worker

    def test_completed_resume_after_proof_does_not_allow_handoff(self):
        worker=self.add_worker();before=self.old.registry.rows('SELECT * FROM authorizations')
        from orchestrator import handoff
        original=handoff.recent_release_proof;checked=threading.Event();proceed=threading.Event();result={}
        def pause(*args,**kwargs):
            proof=original(*args,**kwargs);checked.set()
            if not proceed.wait(5):raise RuntimeError('test interleaving did not proceed')
            return proof
        def transfer():
            try:result['value']=project_bridge_register(self.new,'alpha',True)
            except BridgeError as exc:result['error']=exc.code
        with patch.object(handoff,'recent_release_proof',pause):
            thread=threading.Thread(target=transfer);thread.start();self.assertTrue(checked.wait(5),result)
            try:self.old.conversation_resume(worker)
            finally:proceed.set();thread.join(5)
        self.assertFalse(thread.is_alive());self.assertEqual(result.get('error'),'BRIDGE_RELEASE_REQUIRED')
        self.assertEqual(self.old.registry.rows('SELECT * FROM authorizations'),before)
        self.assertIn(worker,self.old.loaded)
        self.write_release();self.assertEqual(project_bridge_register(self.new,'alpha',True)['connection_scope'],'alpha')
        self.assertIsNone(self.old._transport)

    def test_retired_owner_cannot_enter_control_after_handoff(self):
        project_bridge_register(self.new,'alpha',True)
        with self.old.registry.connect() as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError,'retired'):
                db.execute("INSERT INTO control_lock VALUES(1,?,'conversation_resume')",(self.old.instance,))
        self.assertEqual(self.other.project_status('beta')['projects'][0]['id'],'beta')

    def test_native_timestamp_rounding_is_allowed_but_future_or_preparation_gaps_are_not(self):
        thread=self.meta[self.ids['alpha']]
        release=self.old.registry.rows('SELECT * FROM bridge_control_activity WHERE token=?',(self.old.instance,))[0]
        proof=recent_release_proof(thread,0,release);stamp=proof['timestamp']
        self.assertEqual(recent_release_proof(thread,stamp+0.000001,release,now=stamp-0.000001)['control_revision'],release['revision'])
        for after,now in ((stamp+1,stamp+2),(stamp-1,stamp-1)):
            with self.assertRaises(BridgeError):recent_release_proof(thread,after,release,now=now)

    def test_completed_fallback_question_reply_invalidates_owner_release(self):
        worker=self.add_worker();turn=str(uuid.uuid4());r=self.old.registry
        r.reserve_message('alpha::question-source',worker,'Original technical question',None,self.old.instance)
        r.mark_dispatching('alpha::question-source',self.old.instance)
        r.set_message('alpha::question-source','sent',turn)
        r.completed(worker,{'id':turn,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer',
            'text':'ORCHESTRATOR_QUESTION_JSON\n'+json.dumps({'question':'Which API?','category':'technical','sources':[]})}]})
        question=self.old.question_list()['questions'][0]
        self.write_release()
        reply=self.old.question_reply(question['key'],'alpha::answer','Use the approved API','technical','Existing contract')
        sent=r.one('messages','key','alpha::answer-continuation')
        r.completed(worker,{'id':sent['turn_id'],'status':'completed','items':[]})
        self.old.rpc.active.discard((worker,sent['turn_id']))
        self.assertEqual(r.one('messages','key',sent['key'])['state'],'completed')
        with self.assertRaisesRegex(BridgeError,'no subsequent control'):project_bridge_register(self.new,'alpha',True)


if __name__=='__main__':unittest.main()
