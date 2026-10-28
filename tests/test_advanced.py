import io
import json
import pathlib
import threading
import unittest
import uuid
from unittest.mock import patch,Mock
from types import SimpleNamespace
import test_production
from orchestrator.auditing import artifact_hash,leading_verdict
from orchestrator.errors import BridgeError
from orchestrator.questions import fallback_question
from orchestrator.storage import fingerprint
from orchestrator.tools import invoke
from orchestrator.transport import AppServer,integration_policy,installed_plugin_inventory


class AdvancedTests(unittest.TestCase):
    setUp=test_production.ProductionTests.setUp

    def test_default_enabled_embedded_plugin_servers_are_explicitly_denied(self):
        home=self.base/'profile';root=home/'plugins/cache/catalog/extra/1.0';root.mkdir(parents=True)
        (root/'.mcp.json').write_text(json.dumps({'mcpServers':{'embedded':{'command':'private-command','env':{'SECRET':'private-value'}}}}))
        result={'marketplaces':[{'plugins':[{'installed':True,'id':'extra@catalog','localVersion':'1.0'}]}]}
        metadata=SimpleNamespace(call=Mock(return_value=result),close=Mock())
        with patch('orchestrator.transport.AppServer',return_value=metadata) as factory,patch('orchestrator.transport.subprocess.run',side_effect=AssertionError('CLI marketplace listing must not run')):
            inventory=installed_plugin_inventory('codex',home)
        self.assertEqual(inventory,{'extra@catalog':{'mcp_servers':{'embedded':{}}}})
        self.assertTrue(factory.call_args.kwargs['inventory_only']);metadata.close.assert_called_once()
        metadata.call.assert_called_once_with('plugin/installed',{'cwds':[]},timeout=15)
        config={'plugins':inventory}
        denied=integration_policy(config,[]);allowed=integration_policy(config,['plugins.extra@catalog'])
        self.assertEqual(denied,{'plugins':{'extra@catalog':{'enabled':False,'mcp_servers':{'embedded':{'enabled':False}}}}})
        self.assertEqual(allowed['plugins']['extra@catalog']['mcp_servers']['embedded'],{'enabled':True})
        self.assertNotIn('private',json.dumps([inventory,denied,allowed]))

    def test_unknown_or_missing_plugin_inventory_fails_closed(self):
        for result in ({},{'marketplaces':[],'marketplaceLoadErrors':[{'name':'unavailable'}]},{'marketplaces':[{'plugins':[{'installed':True,'id':'extra@catalog','localVersion':'1.0'}]}]},{'marketplaces':[{'plugins':[{'installed':True,'id':'../bad@catalog','version':'1.0'}]}]}):
            with self.subTest(result=result),patch('orchestrator.transport.AppServer',return_value=SimpleNamespace(call=lambda *a,**k:result,close=lambda:None)):
                with self.assertRaises(BridgeError) as caught:installed_plugin_inventory('codex',self.base/'missing')
                self.assertEqual(caught.exception.code,'INTEGRATION_INVENTORY_UNAVAILABLE')

    def test_inventory_metadata_connection_cannot_start_execution_or_tools(self):
        server=AppServer.__new__(AppServer);server.inventory_only=True
        for method in ('turn/start','thread/start','thread/resume','command/exec','mcpServer/tool/call','plugin/list'):
            with self.subTest(method=method),self.assertRaises(BridgeError) as caught:server.call(method,{})
            self.assertEqual(caught.exception.code,'INVENTORY_ONLY')

    def test_current_explicit_verdict_labels_are_distinct_from_quoted_or_historical_text(self):
        for text,expected in [('**Verdict consolidé : REJECT maintenu** pour le candidat actuel.','REJECT'),('Verdict final : ACCEPT — vérifié.','ACCEPT'),('**ACCEPT** — verified.','ACCEPT'),('REJECT: current defect.','REJECT')]:
            with self.subTest(text=text):self.assertEqual(leading_verdict(text),expected)
        for text in ('> Verdict consolidé : ACCEPT','"Verdict consolidé : ACCEPT"','Earlier verdict: ACCEPT','Verdict précédent : ACCEPT','Verdict consolidé : pas ACCEPT','Verdict consolidé : ACCEPT ou REJECT ?','```text\nACCEPT\n```','I will inspect.\nACCEPT'):
            with self.subTest(text=text):self.assertIsNone(leading_verdict(text))

    def test_consolidated_french_reject_can_review_bound_current_delivery(self):
        self.delivery('Delivered implementation');auditor=self.workers[('alpha','Auditor')];r=self.a.registry
        link=self.a._audit_request(r.one('conversations','thread_id',auditor),'alpha::task',[self.source()])
        r.reserve_message('alpha::consolidated-audit',auditor,'Audit',None,self.a.instance,audit_link=link)
        r.mark_dispatching('alpha::consolidated-audit',self.a.instance);turn=str(uuid.uuid4());r.set_message('alpha::consolidated-audit','sent',turn)
        r.completed(auditor,{'id':turn,'status':'completed','items':[{'type':'agentMessage','phase':'commentary','text':'ACCEPT is not established.'},{'type':'agentMessage','phase':'final_answer','text':'**Verdict consolidé : REJECT maintenu** pour le candidat actuel.'}]})
        task=r.one('tasks','id','alpha::task')
        with self.assertRaises(BridgeError):self.a.task_review(task['id'],task['revision'],'alpha::consolidated-audit','accept','Cannot reverse the actual reject')
        self.assertEqual(r.one('tasks','id',task['id'])['state'],'needs_audit')
        result=self.a.task_review(task['id'],task['revision'],'alpha::consolidated-audit','reject','Confirmed current evidence')
        self.assertEqual(result['state'],'rejected')

    def test_installed_metadata_failure_is_closed_and_has_actionable_cause(self):
        metadata=SimpleNamespace(call=Mock(side_effect=BridgeError('RPC_TIMEOUT','Recorded metadata timeout')),close=Mock())
        with patch('orchestrator.transport.AppServer',return_value=metadata):
            with self.assertRaises(BridgeError) as caught:installed_plugin_inventory('codex',self.base)
        metadata.close.assert_called_once();self.assertEqual(caught.exception.code,'INTEGRATION_INVENTORY_UNAVAILABLE')
        self.assertEqual(caught.exception.details['cause'],'RPC_TIMEOUT');self.assertFalse(caught.exception.details['worker_turn_started'])

    def test_malformed_inventory_is_distinct_from_a_genuine_empty_installed_list(self):
        malformed=[{'marketplaces':{}},{'marketplaces':''},{'marketplaces':[{'plugins':{}}]},{'marketplaces':[{'plugins':''}]},{'marketplaces':[None]},{'marketplaces':[{'plugins':[None]}]},{'marketplaces':[],'marketplaceLoadErrors':None}]
        for response in malformed:
            metadata=SimpleNamespace(call=Mock(return_value=response),close=Mock())
            with self.subTest(response=response),patch('orchestrator.transport.AppServer',return_value=metadata):
                with self.assertRaises(BridgeError) as caught:installed_plugin_inventory('codex',self.base)
                self.assertEqual(caught.exception.code,'INTEGRATION_INVENTORY_UNAVAILABLE')
            metadata.close.assert_called_once()
        with patch('orchestrator.transport.AppServer',return_value=SimpleNamespace(call=Mock(return_value={'marketplaces':[]}),close=Mock())):
            self.assertEqual(installed_plugin_inventory('codex',self.base),{})

    def test_native_writer_conflict_is_actionable_without_dispatch_or_forced_unlock(self):
        server=AppServer.__new__(AppServer);server.guard=threading.RLock();server.closed=False;server.counter=0;server.pending={}
        def reply(packet):server.pending[packet['id']].put({'error':{'code':-32600,'message':'This thread already has an active writer'}})
        server._write=reply
        with self.assertRaises(BridgeError) as caught:server.call('thread/resume',{'threadId':str(uuid.uuid4())})
        self.assertEqual(caught.exception.code,'WRITER_CONFLICT')
        self.assertFalse(caught.exception.details['turn_start_dispatched']);self.assertTrue(caught.exception.details['history_preserved'])
        self.assertIn('another appropriate worker',caught.exception.details['recovery'])
        self.assertEqual(server.pending,{})

    def test_serving_version_diagnostics_do_not_start_remote_transport(self):
        self.assertIsNone(self.a._transport)
        status=invoke(self.a,'bridge_status',{})
        self.assertFalse(status['per_project_plugin_copy_required']);self.assertEqual(status['registry_schema'],11)
        self.assertIsNone(self.a._transport)

    def test_terminal_active_turn_expires_uncertain_answer_attempt(self):
        worker=self.workers[('alpha','Developer')];r=self.a.registry
        r.reserve_message('active',worker,'Question',None,self.a.instance);r.mark_dispatching('active',self.a.instance)
        turn=str(uuid.uuid4());key=self.a._capture_question(7,{'threadId':worker,'turnId':turn,'callId':'one','arguments':{'question':'Which API?','category':'technical','sources':[]}},self.a.rpc.generation)
        with r.connect() as db:db.execute("UPDATE questions SET state='answering',answer_key='reserved' WHERE key=?",(key,))
        r.completed(worker,{'id':turn,'status':'interrupted','items':[]})
        self.assertEqual(r.one('questions','key',key)['state'],'unavailable')

    def source(self):
        path=self.roots['alpha']/'requirements.txt';path.write_text('Approved API: calculate(x)\n')
        return {'path':str(path),'sha256':artifact_hash(path)}

    def delivery(self,text,task=True,category='technical'):
        worker=self.workers[('alpha','Developer')];self.meta[worker]={'id':worker,'cwd':str(self.roots['alpha']),'status':{'type':'idle'}}
        if task:self.a.task_assign('alpha','alpha::task',worker,'Keep the original contract')
        r=self.a.registry;r.reserve_message('alpha::source',worker,'Original task','alpha::task' if task else None,self.a.instance)
        r.mark_dispatching('alpha::source',self.a.instance);turn=str(uuid.uuid4());r.set_message('alpha::source','sent',turn)
        r.completed(worker,{'id':turn,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':text}]})
        return worker,turn

    def question(self,category='technical'):
        self.delivery('ORCHESTRATOR_QUESTION_JSON\n'+json.dumps({'question':'Which API is approved?','category':category,'sources':['requirements.txt']}))
        return self.a.question_list()['questions'][0]

    def test_fallback_is_exact_final_output_and_preserves_task(self):
        row=self.question();self.assertEqual(row['mode'],'turn_based');self.assertEqual(row['task_id'],'alpha::task')
        self.assertEqual(self.a.registry.one('tasks','id','alpha::task')['state'],'waiting_input')
        self.assertIsNone(fallback_question({'items':[{'type':'agentMessage','phase':'commentary','text':'ORCHESTRATOR_QUESTION_JSON\n{}'},{'type':'agentMessage','phase':'final_answer','text':'Delivered, no question'}]}))
        self.assertIsNone(fallback_question({'items':[{'type':'agentMessage','text':'Ordinary prose?'}]}))

    def test_fallback_answer_continues_same_worker_task_once(self):
        row=self.question();worker=row['thread_id'];rpc=self.a.rpc;old=rpc.call;self.a.loaded.add(worker);turn=str(uuid.uuid4());calls=[]
        def call(method,params):
            if method=='turn/start':calls.append(params);return {'turn':{'id':turn,'status':'inProgress'}}
            return old(method,params)
        rpc.call=call
        args=dict(question_key=row['key'],answer_key='alpha::answer',answer='Reuse calculate(x).',authority='technical',evidence='requirements.txt approved interface')
        result=self.a.question_reply(**args)
        self.assertEqual(result['continuation']['thread_id'],worker)
        self.assertEqual(self.a.registry.one('messages','key','alpha::answer-continuation')['task_id'],'alpha::task')
        self.assertTrue(self.a.question_reply(**args)['duplicate_prevented']);self.assertEqual(len(calls),1)
        with self.assertRaises(BridgeError):self.a.question_reply(**dict(args,answer='Changed'))

    def test_fallback_retry_recovers_proven_pre_dispatch_failure(self):
        row=self.question();worker=row['thread_id'];rpc=self.a.rpc;old=rpc.call;self.a.loaded.add(worker);fail=[True];sent=[]
        def call(method,params):
            if method=='model/list' and fail[0]:fail[0]=False;raise BridgeError('RPC_TIMEOUT','Catalog unavailable before reservation')
            if method=='turn/start':sent.append(params);return {'turn':{'id':str(uuid.uuid4()),'status':'inProgress'}}
            return old(method,params)
        rpc.call=call;args=dict(question_key=row['key'],answer_key='alpha::retry',answer='Use the approved API',authority='technical',evidence='requirements.txt')
        with self.assertRaisesRegex(BridgeError,'Catalog'):self.a.question_reply(**args)
        self.assertFalse(self.a.registry.rows("SELECT key FROM messages WHERE key='alpha::retry-continuation'"))
        self.assertEqual(self.a._question(row['key'])['state'],'answering')
        result=self.a.question_reply(**args);self.assertTrue(result['recovered_before_dispatch']);self.assertEqual(len(sent),1)
        self.assertTrue(self.a.question_reply(**args)['duplicate_prevented']);self.assertEqual(len(sent),1)

    def test_continuation_collision_never_reserves_or_returns_foreign_output(self):
        question=self.question();r=self.a.registry;other=self.workers[('alpha','Auditor')]
        r.reserve_message('alpha::answer-continuation',other,'Unrelated work',None,self.a.instance)
        r.mark_dispatching('alpha::answer-continuation',self.a.instance);turn=str(uuid.uuid4());r.set_message('alpha::answer-continuation','sent',turn)
        r.completed(other,{'id':turn,'status':'completed','items':[{'type':'agentMessage','text':'UNRELATED OUTPUT'}]})
        args=dict(question_key=question['key'],answer_key='alpha::answer',answer='Use the API',authority='technical',evidence='Approved docs')
        revision=r.one('tasks','id','alpha::task')['revision']
        for _ in range(2):
            with self.assertRaisesRegex(BridgeError,'continuation key'):self.a.question_reply(**args)
            self.assertIsNone(self.a._question(question['key'])['answer_key'])
        self.assertEqual(r.one('tasks','id','alpha::task')['revision'],revision)
        # Old candidate state may already have reserved a colliding answer.
        with r.connect() as db:db.execute("UPDATE questions SET state='answering',answer_key=?,answer_fingerprint=?,answer=?,reply_message_key=? WHERE key=?",('alpha::answer',fingerprint([question['key'],args['answer'],args['authority'],args['evidence']]),json.dumps({k:args[k] for k in ('answer','authority','evidence')}),'alpha::answer-continuation',question['key']))
        with self.assertRaisesRegex(BridgeError,'different work'):self.a.question_reply(**args)

    def test_verified_continuation_settles_lost_question_commit_without_resend(self):
        question=self.question();r=self.a.registry;worker=question['thread_id'];rpc=self.a.rpc;old=rpc.call;self.a.loaded.add(worker);turn=str(uuid.uuid4());sends=[]
        def call(method,params):
            if method=='turn/start':sends.append(params);return {'turn':{'id':turn,'status':'inProgress'}}
            return old(method,params)
        rpc.call=call;args=dict(question_key=question['key'],answer_key='alpha::answer',answer='Use the API',authority='technical',evidence='Approved docs')
        self.a.question_reply(**args)
        with r.connect() as db:db.execute("UPDATE questions SET state='answering' WHERE key=?",(question['key'],))
        self.assertEqual(self.a.question_reply(**args)['question']['state'],'answered')
        with r.connect() as db:
            db.execute("UPDATE questions SET state='answering' WHERE key=?",(question['key'],))
            db.execute("UPDATE messages SET state='unknown' WHERE key='alpha::answer-continuation'")
        r.reconcile_question_answer(question['key']);self.assertEqual(self.a._question(question['key'])['state'],'answering')
        r.completed(worker,{'id':turn,'status':'completed','items':[{'type':'agentMessage','text':'Delivered'}]})
        self.assertEqual(self.a._question(question['key'])['state'],'answered');self.assertFalse(self.a.question_list()['questions'])
        self.assertEqual(len(sends),1)
        task=r.one('tasks','id','alpha::task');self.a.task_cancel(task['id'],task['revision'],'Retire disposable fixture')
        self.a._native_archive_state=lambda tid:False;self.a.conversation_resume=lambda tid:{'thread':{'status':{'type':'idle'}}}
        self.assertTrue(self.a.conversation_archive(worker,'Completed recovery fixture')['archived'])

    def auditor_question(self,text=None):
        self.delivery('Delivered implementation');r=self.a.registry;auditor=self.workers[('alpha','Auditor')]
        link=self.a._audit_request(r.one('conversations','thread_id',auditor),'alpha::task',[self.source()])
        r.reserve_message('alpha::audit',auditor,'Audit',None,self.a.instance,audit_link=link)
        r.mark_dispatching('alpha::audit',self.a.instance);turn=str(uuid.uuid4());r.set_message('alpha::audit','sent',turn)
        content=text if text is not None else 'ORCHESTRATOR_QUESTION_JSON '+json.dumps({'question':'Which revision?','category':'requirement','sources':[]})
        r.completed(auditor,{'id':turn,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':content}]})
        return auditor,turn

    def test_cancelled_task_resolves_its_auditor_question_and_allows_archive(self):
        auditor,_=self.auditor_question();r=self.a.registry;question=self.a.question_list()['questions'][0]
        task=r.one('tasks','id','alpha::task');self.a.task_cancel(task['id'],task['revision'],'Cancelled review scope')
        self.assertEqual(self.a._question(question['key'])['state'],'unavailable');self.assertFalse(self.a.question_list()['questions'])
        with self.assertRaisesRegex(BridgeError,'no longer answerable'):self.a.question_reply(question['key'],'alpha::answer','Old revision','documented_requirement','Old docs')
        self.a._native_archive_state=lambda tid:False;self.a.conversation_resume=lambda tid:{'thread':{'status':{'type':'idle'}}}
        self.assertTrue(self.a.conversation_archive(auditor,'Cancelled review scope')['archived'])

    def test_late_auditor_history_cannot_reopen_cancelled_scope(self):
        _,turn=self.auditor_question('');r=self.a.registry;task=r.one('tasks','id','alpha::task')
        self.a.task_cancel(task['id'],task['revision'],'Cancel before history hydration')
        full={'id':turn,'status':'completed','items':[{'type':'agentMessage','text':'ORCHESTRATOR_QUESTION_JSON '+json.dumps({'question':'Which revision?','category':'requirement','sources':[]})}]}
        r.set_message('alpha::audit','completed',result=full);r.reconcile_questions('alpha::audit')
        self.assertFalse(self.a.question_list()['questions']);self.assertEqual(self.a.question_list(include_resolved=True)['questions'][0]['state'],'unavailable')

    def test_hydrated_fallback_changes_waiting_state_only_once(self):
        worker,turn=self.delivery('')
        full={'id':turn,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'ORCHESTRATOR_QUESTION_JSON\n'+json.dumps({'question':'Which API?','category':'technical','sources':[]})}]}
        self.a.registry.set_message('alpha::source','completed',result=full)
        task=self.a.registry.one('tasks','id','alpha::task');self.assertEqual(task['state'],'waiting_input')
        self.a.registry.set_message('alpha::source','completed',result=full)
        self.assertEqual(self.a.registry.one('tasks','id','alpha::task')['revision'],task['revision'])
        self.assertEqual(len(self.a.question_list()['questions']),1)

    def test_marker_whitespace_and_already_full_history_are_reconciled(self):
        payload={'question':'Which approved contract?','category':'requirement','sources':['contract.md']}
        self.assertEqual(fallback_question({'items':[{'type':'agentMessage','text':'ORCHESTRATOR_QUESTION_JSON '+json.dumps(payload)}]}),payload)
        self.assertIsNone(fallback_question({'items':[{'type':'agentMessage','text':'ORCHESTRATOR_QUESTION_JSONISH '+json.dumps(payload)}]}))
        worker,turn=self.delivery('')
        full={'id':turn,'status':'completed','itemsView':'full','items':[{'type':'agentMessage','text':'ORCHESTRATOR_QUESTION_JSON '+json.dumps(payload)}]}
        with self.a.registry.connect() as db:db.execute('UPDATE messages SET result=? WHERE key=?',(json.dumps(full),'alpha::source'))
        self.a.registry.reconcile_questions('alpha::source');task=self.a.registry.one('tasks','id','alpha::task')
        self.assertEqual(task['state'],'waiting_input');self.a.registry.reconcile_questions('alpha::source')
        self.assertEqual(self.a.registry.one('tasks','id','alpha::task')['revision'],task['revision'])

    def test_transport_reconnect_cannot_send_old_answer_to_reused_request_id(self):
        r=self.a.registry;first=self.workers[('alpha','Developer')];second=self.workers[('alpha','Auditor')]
        def capture(worker,key,turn,call):
            r.reserve_message(key,worker,'Ordinary question',None,self.a.instance);r.mark_dispatching(key,self.a.instance)
            return self.a._capture_question(17,{'threadId':worker,'turnId':turn,'callId':call,'arguments':{'question':'Which module?','category':'technical','sources':[]}},self.a.rpc.generation)
        old=capture(first,'first',str(uuid.uuid4()),'old-call');self.a.rpc.close();new_rpc=self.a.rpc
        new=capture(second,'second',str(uuid.uuid4()),'new-call');responses=[]
        new_rpc.has_question=lambda rid,**identity:True;new_rpc.reply_question=lambda *a,**k:responses.append((a,k))
        with self.assertRaisesRegex(BridgeError,'original active bridge'):
            self.a.question_reply(old,'alpha::old','Wrong target','technical','Docs')
        self.assertFalse(responses)
        self.a.question_reply(new,'alpha::new','Correct target','technical','Docs');self.assertEqual(len(responses),1)

    def test_auditor_fallback_continuation_keeps_current_audit_binding(self):
        self.delivery('Delivered implementation');source=self.source();auditor=self.workers[('alpha','Auditor')];r=self.a.registry
        worker=self.a.registry.one('conversations','thread_id',auditor)
        link=self.a._audit_request(worker,'alpha::task',[source]);r.reserve_message('alpha::audit',auditor,'Audit',None,self.a.instance,audit_link=link)
        r.mark_dispatching('alpha::audit',self.a.instance);turn=str(uuid.uuid4());r.set_message('alpha::audit','sent',turn)
        r.completed(auditor,{'id':turn,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'ORCHESTRATOR_QUESTION_JSON\n'+json.dumps({'question':'Which specification revision?','category':'requirement','sources':['requirements.txt']})}]})
        self.meta[auditor]={'id':auditor,'cwd':str(self.roots['alpha']),'status':{'type':'idle'}};rpc=self.a.rpc;old=rpc.call;self.a.loaded.add(auditor);new_turn=str(uuid.uuid4())
        rpc.call=lambda method,params:{'turn':{'id':new_turn,'status':'inProgress'}} if method=='turn/start' else old(method,params)
        question=self.a.question_list()['questions'][0];self.assertEqual(question['audit_task_id'],'alpha::task')
        result=self.a.question_reply(question['key'],'alpha::audit-answer','Use the approved revision','documented_requirement','requirements.txt')
        reply=result['continuation']['message_key'];self.assertIsNone(r.one('messages','key',reply)['task_id'])
        self.assertEqual(r.rows('SELECT task_id FROM audit_links WHERE message_key=?',(reply,))[0]['task_id'],'alpha::task')
        r.completed(auditor,{'id':new_turn,'status':'completed','items':[{'type':'agentMessage','phase':'final_answer','text':'ACCEPT: current contract and tests verified'}]})
        task=r.one('tasks','id','alpha::task')
        assessment=self.a.audit_assess('alpha::assessment',task['id'],reply,'accept','Current contract and integration checks verified')
        self.assertEqual(self.a.task_review(task['id'],task['revision'],reply,'accept','Current integration checks passed')['state'],'accepted')
        repeated=self.a.audit_assess('alpha::assessment',task['id'],reply,'accept','Current contract and integration checks verified')
        self.assertEqual(repeated['assessment'],assessment['assessment']);self.assertFalse(repeated['acceptance_changed'])

    def test_pending_taskless_question_blocks_retirement_and_archive(self):
        worker,_=self.delivery('ORCHESTRATOR_QUESTION_JSON '+json.dumps({'question':'Which API?','category':'technical','sources':[]}),task=False)
        with self.assertRaises(BridgeError):self.a.worker_context(worker,0,'Idle expert',[],'Retire',status='retired')
        with self.assertRaises(BridgeError):self.a.conversation_archive(worker,reason='Retire')

    def test_disputed_reject_does_not_allow_acceptance(self):
        self.delivery('Delivered implementation');auditor=self.workers[('alpha','Auditor')];r=self.a.registry
        link=self.a._audit_request(r.one('conversations','thread_id',auditor),'alpha::task',[self.source()])
        r.reserve_message('alpha::negative-audit',auditor,'Audit',None,self.a.instance,audit_link=link)
        r.mark_dispatching('alpha::negative-audit',self.a.instance);turn=str(uuid.uuid4());r.set_message('alpha::negative-audit','sent',turn)
        r.completed(auditor,{'id':turn,'status':'completed','items':[{'type':'agentMessage','text':'REJECT: specific unresolved defect'}]})
        task=r.one('tasks','id','alpha::task')
        invoke(self.a,'audit_assess',{'assessment_key':'alpha::dispute','task_id':task['id'],'audit_message_key':'alpha::negative-audit','decision':'audit_disputed','evidence':'Request verification of the disputed claim'})
        with self.assertRaises(BridgeError):self.a.task_review(task['id'],task['revision'],'alpha::negative-audit','accept','Disputed')
        self.assertEqual(r.one('tasks','id',task['id'])['state'],'needs_audit')

    def test_creative_question_is_escalated_without_answer(self):
        row=self.question('creative')
        with self.assertRaisesRegex(BridgeError,'creative'):
            self.a.question_reply(row['key'],'alpha::answer','Invent a color','technical','No approved decision')
        result=self.a.question_escalate(row['key'],'Vision not documented','Ask the owner; continue unrelated technical work')
        self.assertTrue(result['human_action_required']);self.assertIsNone(result['question']['answer'])

    def test_foreign_questions_and_records_are_not_exposed(self):
        row=self.question()
        with self.assertRaises(BridgeError):self.b.question_escalate(row['key'],'wrong','wrong')
        self.assertFalse(self.b.question_list()['questions'])
        contract=self.a.architecture_contract('alpha','alpha::contract',0,'Interface',[])
        with self.assertRaises(BridgeError):self.b.coordination_read(contract['key'])

    def test_active_question_routes_exact_rpc_and_never_new_turn(self):
        worker=self.workers[('alpha','Developer')];r=self.a.registry
        r.reserve_message('active',worker,'Wait for ordinary input',None,self.a.instance);r.mark_dispatching('active',self.a.instance)
        turn=str(uuid.uuid4());key=self.a._capture_question(17,{'threadId':worker,'turnId':turn,'callId':'call-one','arguments':{'question':'Which module?','category':'technical','sources':[]}},self.a.rpc.generation)
        rpc=self.a.rpc;responses=[];rpc.has_question=lambda rid,**kw:rid==17;rpc.reply_question=lambda rid,result,**kw:responses.append((rid,result))
        result=self.a.question_reply(key,'alpha::active-answer','Use existing module','technical','Current approved architecture')
        self.assertEqual(result['continuation']['same_turn_id'],turn);self.assertEqual(len(responses),1)
        self.assertFalse(any(method=='turn/start' for method,_ in rpc.calls))

    def test_active_request_cannot_be_replayed_on_another_bridge(self):
        worker=self.workers[('alpha','Developer')];r=self.a.registry
        r.reserve_message('active',worker,'Question',None,self.a.instance);r.mark_dispatching('active',self.a.instance)
        key=self.a._capture_question('rpc-id',{'threadId':worker,'turnId':str(uuid.uuid4()),'callId':'one','arguments':{'question':'Which API?','category':'technical','sources':[]}},self.a.rpc.generation)
        self.a.bridge_release=lambda:None
        self.a._transport=None
        with self.assertRaisesRegex(BridgeError,'original active bridge'):
            self.a.question_reply(key,'alpha::reply','Answer','technical','Docs')
        self.assertFalse(self.a.question_list()['questions'][0]['reply_available'])

    def test_cancel_invalidates_completed_question(self):
        row=self.question();task=self.a.registry.one('tasks','id','alpha::task')
        self.a.task_cancel(task['id'],task['revision'],'Discard disposable question fixture')
        self.assertFalse(self.a.question_list()['questions'])

    def test_expertise_reuse_freshness_and_retirement(self):
        worker=self.workers[('alpha','Developer')];source=self.source()
        self.a.worker_context(worker,0,'API specialist',['python','interfaces'],'Existing knowledge',[source])
        result=self.a.worker_discover(expertise=['interfaces'])['candidates'][0]
        self.assertEqual(result['worker']['thread_id'],worker);self.assertTrue(result['recorded_sources_unchanged'])
        pathlib.Path(source['path']).write_text('Changed requirement')
        self.assertFalse(self.a.worker_discover(expertise=['interfaces'])['candidates'][0]['recorded_sources_unchanged'])
        with self.assertRaisesRegex(BridgeError,'changed'):self.a.worker_context(worker,0,'changed',[],'stale')
        self.a.worker_context(worker,1,'API specialist',[],'Retired',status='retired')
        with self.assertRaisesRegex(BridgeError,'reactivate'):self.a.message_send(worker,'work','retired')

    def test_handoff_preserves_scoped_notes_and_rejects_changed_sources(self):
        worker=self.workers[('alpha','Developer')];source=self.source();note=self.a.project_note('alpha','decision','Reuse existing API')['note_id']
        packet=self.a.context_handoff('alpha','alpha::handoff',worker,'Only new context',[source],[note])
        self.assertEqual(packet['payload']['notes'][0]['id'],note)
        pathlib.Path(source['path']).write_text('Changed')
        with self.assertRaisesRegex(BridgeError,'differs'):self.a._handoff_text('alpha::handoff',worker)
        with self.assertRaises(BridgeError):self.b.context_handoff('beta','beta::handoff',self.workers[('beta','Developer')],'No foreign notes',[],[note])

    def plan_task(self,key='build',deps=None):
        return {'id':key,'owner':self.workers[('alpha','Developer')],'requirements':'Implement the documented API','inputs':['requirements.txt'],'outputs':['api.py'],'acceptance':['Run integration tests'],'dependencies':deps or [],'write_paths':[str(self.roots['alpha']/'api.py')]}

    def test_plans_namespace_order_and_bind_exact_requirements(self):
        plan=invoke(self.a,'plan_record',{'project_id':'alpha','plan_key':'plan','objective':'Approved API','approval_evidence':'User request','tasks':[self.plan_task('use',['build']),self.plan_task('build')]})
        self.assertEqual(plan['payload']['order'],['alpha::build','alpha::use'])
        task=plan['payload']['tasks'][1]
        with self.assertRaisesRegex(BridgeError,'exact requirements'):
            self.a.task_assign('alpha',task['id'],task['owner'],'Vague request',plan_key=plan['key'])
        result=self.a.task_assign('alpha',task['id'],task['owner'],task['requirements'],plan_key=plan['key'])
        self.assertEqual(result['plan_key'],'alpha::plan')

    def test_cycle_wrong_owner_and_contract_change_are_blocked(self):
        with self.assertRaisesRegex(BridgeError,'cycle'):
            self.a.plan_record('alpha','cycle','Approved','User request',[self.plan_task('a',['b']),self.plan_task('b',['a'])])
        foreign=self.plan_task();foreign['owner']=self.workers[('beta','Developer')]
        with self.assertRaises(BridgeError):self.a.plan_record('alpha','foreign','Approved','User request',[foreign])
        contract=self.a.architecture_contract('alpha','alpha::contract',0,'Shared interface',[self.source()])
        plan=self.a.plan_record('alpha','alpha::plan','Approved','User request',[self.plan_task('alpha::build')],[{'key':contract['key'],'revision':1}])
        task=plan['payload']['tasks'][0];self.a.task_assign('alpha',task['id'],task['owner'],task['requirements'],plan_key=plan['key'])
        with self.assertRaisesRegex(BridgeError,'dependent work'):self.a.architecture_contract('alpha','alpha::contract',1,'Incompatible interface',[])

    def test_declared_write_conflict_retains_uncertain_claim(self):
        r=self.a.registry;a=self.workers[('alpha','Developer')];b=self.workers[('alpha','Auditor')];path=str(self.roots['alpha']/'shared.py')
        r.reserve_message('write-a',a,'write',None,self.a.instance,write_paths=[path]);r.set_message('write-a','unknown')
        with self.assertRaisesRegex(BridgeError,'overlap'):r.reserve_message('write-b',b,'write',None,self.a.instance,write_paths=[path])
        r.set_message('write-a','interrupted')
        self.assertTrue(r.reserve_message('write-b',b,'write',None,self.a.instance,write_paths=[path])[1])

    def test_native_approvals_are_never_routed_to_question_handler(self):
        packets=[{'id':1,'method':'item/tool/requestUserInput','params':{'questions':[{'question':'Accept connector action?'}]}},{'id':2,'method':'item/permissions/requestApproval','params':{}},{'id':3,'method':'item/tool/call','params':{'tool':'unrecognized','arguments':{}}}]
        server=AppServer.__new__(AppServer);server.guard=threading.RLock();server.changed=threading.Condition(server.guard);server.pending={};server.completed={};server.active=set();server.input_requests={};server.closed=False
        server.process=type('Process',(),{'stdout':io.StringIO('\n'.join(json.dumps(p) for p in packets))})();writes=[];delegations=[]
        server._write=writes.append;server.on_event=lambda *a:None;server.on_question=lambda *a:delegations.append(a)
        server._read()
        self.assertEqual(len(writes),3);self.assertFalse(delegations);self.assertTrue(all('error' in packet for packet in writes))


if __name__=='__main__':unittest.main()
