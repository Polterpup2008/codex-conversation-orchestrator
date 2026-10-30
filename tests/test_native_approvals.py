import json
import pathlib
import subprocess
import sys
import unittest
import uuid
import contextlib
import threading
from unittest.mock import Mock,patch

import test_artifacts as artifacts
from orchestrator.authorization import grant_project
from orchestrator.errors import BridgeError
from orchestrator.transport import AppServer


class NativeApprovalTests(unittest.TestCase):
    def setUp(self):
        self.fixture=artifacts.ArtifactRootTests('test_exact_writer_roots_readonly_auditor_and_project_isolation')
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.a=self.fixture.a;self.worker=self.fixture.workers[('alpha','Developer')]

    def prepare(self):
        grant_project(self.a.registry,'alpha',self.fixture.roots['alpha'],self.fixture.coordinators['alpha'],headless=True,integrations=['mcp_servers.node_repl','plugins.computer-use@openai-bundled'])
        self.a.coordinator_register('alpha',self.fixture.coordinators['alpha'])
        self.a.native_approval_handler=Mock(return_value={'action':'decline'})
        rpc=self.a.rpc;rpc.elicitations={};self.turn=str(uuid.uuid4());rpc.active.add((self.worker,self.turn))
        self.a.registry.reserve_message('alpha::native-app',self.worker,'Native app fixture',None,self.a.instance)
        self.a.registry.mark_dispatching('alpha::native-app',self.a.instance);self.a.registry.set_message('alpha::native-app','sent',self.turn)
        self.params={'threadId':self.worker,'turnId':self.turn,'serverName':'node_repl','mode':'form','message':'Allow Codex to use fixture?','requestedSchema':{'type':'object','properties':{}},'_meta':{'connector_id':'computer-use','connector_name':'Computer Use','codex_approval_kind':'mcp_tool_call','tool_params':{'app':'fixture.exe'},'tool_params_display':[{'name':'app','display_name':'App','value':'fixture'}],'persist':['session','always'],'riskLevel':'low'}}
        rpc.elicitations[1]=self.params
        return rpc

    def test_only_granted_computer_integration_and_capable_client_allow_elicitation(self):
        self.assertEqual(self.a._application_approval_policy(),'never')
        self.a.native_approval_handler=Mock();self.assertEqual(self.a._application_approval_policy(),'never')
        self.prepare();policy=self.a._application_approval_policy()['granular']
        self.assertTrue(policy['mcp_elicitations'])
        self.assertTrue(all(not v for k,v in policy.items() if k!='mcp_elicitations'))

    def test_exact_native_form_and_client_response_are_forwarded_without_question_or_grant(self):
        rpc=self.prepare();before=self.a.registry.rows('SELECT * FROM authorizations ORDER BY project_id')
        expected={'action':'accept','content':{'fixture_only':True},'_meta':{'fixture_response':True}}
        def host(request,valid):
            self.assertTrue(valid());self.assertEqual(request,{k:self.params[k] for k in ('mode','message','requestedSchema','_meta')});return expected
        self.a.native_approval_handler=host
        self.assertEqual(self.a._relay_application_approval(self.params,rpc.generation),expected)
        self.assertEqual(self.a.registry.rows('SELECT * FROM questions'),[])
        self.assertEqual(self.a.registry.rows('SELECT * FROM authorizations ORDER BY project_id'),before)

    def test_other_approvals_foreign_workers_audio_and_wrong_turn_are_refused(self):
        rpc=self.prepare()
        cases=[{'serverName':'foreign'},{'mode':'url'},{'requestedSchema':{'type':'object','properties':{'password':{'type':'string'}}}},{'message':'Enter a secret'},{'threadId':self.fixture.workers[('beta','Developer')]},{'turnId':str(uuid.uuid4())}, {'_meta':{'connector_id':'other'}},{'_meta':{'connector_id':'computer-use','connector_name':'Computer Use','codex_approval_kind':'mcp_tool_call','tool_params':{'app':'computer-audio'}}}]
        for changes in cases:
            with self.subTest(changes=changes),self.assertRaises(BridgeError):self.a._relay_application_approval({**self.params,**changes},rpc.generation)
        self.a.native_approval_handler.assert_not_called()

    def test_expired_request_revoked_grant_and_invalid_host_response_never_accept(self):
        rpc=self.prepare()
        def ended(request,valid):
            rpc.active.clear();self.assertFalse(valid());return {'action':'accept'}
        self.a.native_approval_handler=ended
        with self.assertRaises(BridgeError):self.a._relay_application_approval(self.params,rpc.generation)
        rpc.active.add((self.worker,self.turn));self.a.native_approval_handler=lambda *_: {'action':'invented'}
        with self.assertRaises(BridgeError):self.a._relay_application_approval(self.params,rpc.generation)
        def revoked(request,valid):
            with self.a.registry.connect() as db:db.execute("UPDATE authorizations SET enabled=0 WHERE project_id='alpha'")
            self.assertFalse(valid());return {'action':'accept'}
        self.a.native_approval_handler=revoked
        with self.assertRaises(BridgeError):self.a._relay_application_approval(self.params,rpc.generation)

    def test_status_distinguishes_native_consent_from_ordinary_questions(self):
        rpc=self.prepare();result=self.a.message_status('alpha::native-app',reconcile=False)
        self.assertEqual(result['native_application_approvals'],[{'app':'fixture.exe','state':'awaiting_native_client','ordinary_question':False}])
        self.assertEqual(result['questions'],[]);self.assertTrue(result['turn_observed_live'])

    def test_resolved_native_request_cannot_reuse_acceptance_during_same_turn(self):
        rpc=self.prepare()
        def resolved(request,valid):
            rpc.elicitations.clear();self.assertFalse(valid());return {'action':'accept'}
        self.a.native_approval_handler=resolved
        with self.assertRaises(BridgeError):self.a._relay_application_approval(self.params,rpc.generation)

    def test_native_decision_event_is_retained_without_ordinary_question(self):
        self.a.registry.event('bridge/nativeAppApproval',{'thread_id':self.worker,'action':'decline','decision_source':'native_client'})
        rows=self.a.registry.rows("SELECT payload FROM events WHERE method='bridge/nativeAppApproval'")
        self.assertEqual(json.loads(rows[0]['payload'])['action'],'decline')
        self.assertEqual(self.a.registry.rows('SELECT * FROM questions'),[])

    def relay_fixture(self,rpc):
        rpc.on_elicitation=self.a._relay_application_approval;rpc.on_event=Mock();rpc._write=Mock()
        return lambda:AppServer._relay_elicitation(rpc,1,self.params)

    def test_completion_and_revocation_before_final_fence_never_forward_accept(self):
        rpc=self.prepare();relay=self.relay_fixture(rpc)
        self.a.native_approval_handler=lambda *_:{'action':'accept'}
        transaction=self.a.registry.transaction;injected=[]
        @contextlib.contextmanager
        def before_final_fence():
            with transaction() as db:
                db.execute("UPDATE messages SET state='completed' WHERE key='alpha::native-app'")
                db.execute("UPDATE authorizations SET enabled=0 WHERE project_id='alpha'")
            injected.append(True)
            with transaction() as db:yield db
        with patch.object(self.a.registry,'transaction',before_final_fence):relay()
        self.assertEqual(injected,[True])
        self.assertEqual(rpc._write.call_args.args[0]['result']['action'],'decline')
        self.assertEqual(rpc._write.call_count,1)

    def test_final_write_is_serialized_with_concurrent_delivery_completion_and_revocation(self):
        rpc=self.prepare();relay=self.relay_fixture(rpc)
        self.a.native_approval_handler=lambda *_:{'action':'accept'}
        entering=threading.Event();started=threading.Event();finished=threading.Event();errors=[];wire=[]
        def revoke():
            try:
                self.assertTrue(entering.wait(5));started.set()
                with self.a.registry.transaction() as db:
                    db.execute("UPDATE messages SET state='completed' WHERE key='alpha::native-app'")
                    db.execute("UPDATE authorizations SET enabled=0 WHERE project_id='alpha'")
                finished.set()
            except BaseException as error:errors.append(error)
        def write(packet):
            entering.set();self.assertTrue(started.wait(5))
            self.assertFalse(finished.wait(.15),'Concurrent revocation committed before consent was forwarded')
            wire.append(packet)
        rpc._write=write;t=threading.Thread(target=revoke);t.start()
        try:relay()
        finally:t.join(timeout=10)
        self.assertFalse(t.is_alive());self.assertEqual(errors,[]);self.assertTrue(finished.is_set())
        self.assertEqual(wire[0]['result']['action'],'accept')
        self.assertFalse(self.a.registry.rows("SELECT * FROM authorizations WHERE project_id='alpha' AND enabled=1"))

    def test_uncertain_wire_write_is_never_replayed(self):
        rpc=self.prepare();relay=self.relay_fixture(rpc)
        self.a.native_approval_handler=lambda *_:{'action':'accept'}
        rpc._write.side_effect=BrokenPipeError('protocol fixture only');relay()
        self.assertEqual(rpc._write.call_count,1);self.assertNotIn(1,rpc.elicitations)
        event=rpc.on_event.call_args.args[1]
        self.assertEqual(event['action'],'unknown');self.assertEqual(event['decision_source'],'native_response_write_uncertain')


class NativeMCPRelayTests(unittest.TestCase):

    def test_client_disconnect_cancels_pending_form_before_request_drain(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        script='''import sys
sys.path.insert(0,sys.argv[1]);import server
class Fake:
 def close(self):pass
s=Fake()
def invoke(service,name,args):return service.native_approval_handler({'mode':'form','message':'Synthetic fixture only','requestedSchema':{'type':'object','properties':{}}},lambda:True)
server.invoke=invoke;server.main(s)
'''
        p=subprocess.Popen([sys.executable,'-B','-c',script,str(root/'plugin')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            for packet in [
                {'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{'elicitation':{'form':{}}}}},
                {'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'fixture','arguments':{}}}
            ]:
                p.stdin.write(json.dumps(packet)+'\n');p.stdin.flush()
                response=json.loads(p.stdout.readline())
            self.assertEqual(response['method'],'elicitation/create')
            p.stdin.close();self.assertEqual(p.wait(timeout=10),0)
            remaining=[json.loads(line) for line in p.stdout]
            self.assertTrue(any(row.get('method')=='notifications/cancelled' for row in remaining))
            result=next(row for row in remaining if row.get('id')==2)
            self.assertTrue(result['result']['isError'])
        finally:
            if p.poll() is None:p.terminate();p.wait(timeout=10)
            p.stdout.close();p.stderr.close()

    def test_server_correlates_outbound_elicitation_and_keeps_shell_requests_closed(self):
        root=pathlib.Path(__file__).resolve().parents[1]
        script='''import sys,threading
sys.path.insert(0,sys.argv[1]);import server
class Fake:
 def close(self):pass
s=Fake()
def invoke(service,name,args):
 if name=='fixture':return service.native_approval_handler({'mode':'form','message':'Synthetic fixture only','requestedSchema':{'type':'object','properties':{}},'_meta':{'fixture':True}},lambda:True)
 return {'native':callable(getattr(service,'native_approval_handler',None))}
server.invoke=invoke;server.main(s)
'''
        p=subprocess.Popen([sys.executable,'-B','-c',script,str(root/'plugin')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            def write(packet):p.stdin.write(json.dumps(packet)+'\n');p.stdin.flush()
            write({'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-11-25','capabilities':{'elicitation':{'form':{}}}}})
            self.assertEqual(json.loads(p.stdout.readline())['id'],1)
            write({'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'fixture','arguments':{}}})
            request=json.loads(p.stdout.readline());self.assertEqual(request['method'],'elicitation/create')
            self.assertTrue(request['id'].startswith('native-app-'));self.assertEqual(request['params']['_meta'],{'fixture':True})
            write({'jsonrpc':'2.0','id':'unrelated','result':{'action':'accept'}})
            write({'jsonrpc':'2.0','id':request['id'],'result':{'action':'decline'}})
            result=json.loads(p.stdout.readline());self.assertEqual(result['id'],2)
            self.assertEqual(json.loads(result['result']['content'][0]['text']),{'action':'decline'})
            p.stdin.close();self.assertEqual(p.wait(timeout=10),0)
        finally:
            if p.poll() is None:p.terminate();p.wait(timeout=10)
            p.stdout.close();p.stderr.close()


if __name__=='__main__':unittest.main()
