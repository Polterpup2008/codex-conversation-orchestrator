"""Ordinary worker questions, distinct from security approval requests."""
import json
import time
from .errors import BridgeError
from .storage import fingerprint

QUESTION_SCHEMA={'type':'object','properties':{'question':{'type':'string','minLength':1,'maxLength':12000},'category':{'type':'string','enum':['technical','requirement','creative','strategic']},'sources':{'type':'array','items':{'type':'string'},'maxItems':30}},'required':['question','category','sources'],'additionalProperties':False}
QUESTION_TOOL={'type':'function','name':'orchestrator_question','description':'Ask your designated project coordinator an ordinary technical/requirements/product question and wait for its answer. Never use for permissions, secrets, purchases, security approvals or irreversible actions. If unavailable, return a final ORCHESTRATOR_QUESTION_JSON followed by the same JSON object.','inputSchema':QUESTION_SCHEMA}


def checked_question(value):
    from .tools import validate
    validate(value,QUESTION_SCHEMA)
    return value


def fallback_question(turn):
    replies=[i for i in turn.get('items',[]) if i.get('type')=='agentMessage']
    finals=[i for i in replies if i.get('phase')=='final_answer']
    text=(finals or replies)[-1].get('text','').strip() if replies else ''
    marker='ORCHESTRATOR_QUESTION_JSON'
    if not text.startswith(marker) or len(text)==len(marker) or not text[len(marker)].isspace():return None
    try:return checked_question(json.loads(text[len(marker):].strip()))
    except (ValueError,BridgeError):return None


class QuestionOperations:
    def _question(self,key):
        row=self.registry.one('questions','key',key);self._project(row['project_id']);return row

    def _capture_question(self,request_id,params,transport_token):
        """Called only for our named dynamic tool, never for native input/approval."""
        payload=checked_question(params['arguments'])
        worker,project=self._worker(params['threadId'])
        with self.registry.transaction() as db:
            message=db.execute("SELECT * FROM messages WHERE thread_id=? AND owner_token=? AND state IN ('preparing','sent','unknown')",(worker['thread_id'],self.instance)).fetchone()
            if not message or message['stage']!='dispatching' or message['turn_id'] not in (None,params['turnId']):
                raise BridgeError('QUESTION_NOT_OWNED','No matching managed active delivery owns this question.')
            db.execute("UPDATE messages SET turn_id=coalesce(turn_id,?),state='sent' WHERE key=?",(params['turnId'],message['key']))
            key=project['id']+'::question-'+fingerprint([self.instance,transport_token,request_id,params['callId']])[:24]
            db.execute("INSERT OR IGNORE INTO questions(key,project_id,thread_id,message_key,task_id,turn_id,mode,request_id,owner_token,payload,created,transport_token,call_id) VALUES(?,?,?,?,?,?,'active',?,?,?,?,?,?)",(key,project['id'],worker['thread_id'],message['key'],message['task_id'],params['turnId'],json.dumps(request_id),self.instance,json.dumps(payload),time.time(),transport_token,params['callId']))
        return key

    def _question_event(self,method,params,generation=None):
        if method=='serverRequest/resolved':
            with self.registry.connect() as db:
                db.execute("UPDATE questions SET state='unavailable' WHERE thread_id=? AND request_id=? AND owner_token=? AND transport_token=? AND state IN ('pending','escalated')",(params['threadId'],json.dumps(params['requestId']),self.instance,generation))

    def question_list(self,project_id=None,thread_id=None,include_resolved=False):
        project_id=project_id or self.project_scope
        if not project_id:raise BridgeError('PROJECT_REQUIRED','Select an authorized project.')
        self._project(project_id)
        if thread_id:self._worker(thread_id,allow_archived=True)
        sql='SELECT * FROM questions WHERE project_id=?';values=[project_id]
        if thread_id:sql+=' AND thread_id=?';values.append(thread_id)
        if not include_resolved:sql+=" AND state IN ('pending','escalated','answering')"
        rows=self.registry.rows(sql+' ORDER BY created',values)
        for row in rows:
            row['payload']=json.loads(row['payload'])
            audit=self.registry.rows('SELECT task_id FROM audit_links WHERE message_key=?',(row['message_key'],))
            row['audit_task_id']=audit[0]['task_id'] if audit else None
            if row['mode']=='active' and row['state'] in ('pending','escalated') and (row['owner_token']!=self.instance or self._transport is None or self._transport.closed or row['transport_token']!=self._transport.generation):
                row['reply_available']=False
                row['recovery']='The suspended request belongs to its original live bridge. If it closed, reconcile the original message; do not replay a response ID on a new process. Use a new turn after a proven terminal outcome.'
            else:row['reply_available']=row['state'] in ('pending','escalated')
        return {'questions':rows}

    def question_escalate(self,question_key,reason,recommendation):
        row=self._question(question_key)
        if row['state'] not in ('pending','escalated'):raise BridgeError('QUESTION_STATE','Only an unresolved question can be escalated.')
        with self.registry.connect() as db:
            db.execute('INSERT INTO events(method,payload,created) VALUES(?,?,?)',('bridge/questionEscalated',json.dumps({'project_id':row['project_id'],'question_key':question_key,'reason':reason,'recommendation':recommendation}),time.time()))
            db.execute("UPDATE questions SET state='escalated',escalation=? WHERE key=?",(json.dumps({'reason':reason,'recommendation':recommendation}),question_key))
        return {'question':self._question(question_key),'human_action_required':True,'note':'Recorded for the coordinator to present to the human. No answer or approval was transmitted.'}

    def question_reply(self,question_key,answer_key,answer,authority,evidence):
        row=self._question(question_key);payload=json.loads(row['payload'])
        digest=fingerprint([question_key,answer,authority,evidence])
        if row['answer_key']:
            if row['answer_key']!=answer_key or row['answer_fingerprint']!=digest:raise BridgeError('IDEMPOTENCY_CONFLICT','This question already has a different reserved answer.')
            existing=self.registry.rows('SELECT key FROM messages WHERE key=?',(row['reply_message_key'],)) if row['reply_message_key'] else []
            if row['mode']=='turn_based' and row['state']=='answering' and not existing:
                # No durable message reservation proves no turn/start occurred.
                # Retry the same continuation identity, never an uncertain send.
                return self._continue_question(row,answer,authority,evidence,recovered=True)
            return {'question':row,'duplicate_prevented':True,'continuation':self.message_status(row['reply_message_key']) if existing else None,'note':'A reserved active response is not replayed. Reconcile its original turn if forwarding was uncertain.'}
        if row['state'] not in ('pending','escalated'):raise BridgeError('QUESTION_STATE','The originating question is no longer answerable.')
        if payload['category'] in ('creative','strategic') and authority not in ('documented_requirement','human_decision'):
            raise BridgeError('HUMAN_AUTHORITY_REQUIRED','Unresolved creative/strategic choices require documented authority or the human decision.')
        self._worker(row['thread_id'])
        if row['mode']=='active':
            if row['owner_token']!=self.instance or self._transport is None or self._transport.closed or row['transport_token']!=self._transport.generation:
                raise BridgeError('QUESTION_CONNECTION_LOST','Reply through the original active bridge. Reconcile a closed bridge before a turn-based continuation.')
            request_id=json.loads(row['request_id'])
            if not self._transport.has_question(request_id,**self._question_identity(row)):raise BridgeError('QUESTION_EXPIRED','The original active request is no longer pending.')
        else:
            source=self.registry.one('messages','key',row['message_key'])
            if source['state']!='completed':raise BridgeError('QUESTION_STATE','Turn-based continuation requires completed original delivery.')
            newer=self.registry.rows('SELECT key FROM messages WHERE thread_id=? AND created>?',(row['thread_id'],source['created']))
            if newer:raise BridgeError('STALE_QUESTION','Newer work exists. Reconcile it before answering the old question.')
        reply_key=answer_key+'-continuation' if row['mode']=='turn_based' else None
        with self.registry.transaction() as db:
            if db.execute("UPDATE questions SET state='answering',answer_key=?,answer_fingerprint=?,answer=?,reply_message_key=? WHERE key=? AND state IN ('pending','escalated') AND answer_key IS NULL",(answer_key,digest,json.dumps({'answer':answer,'authority':authority,'evidence':evidence}),reply_key,question_key)).rowcount!=1:
                raise BridgeError('QUESTION_EXPIRED','Question state changed before answer reservation; no response was sent.')
            if row['mode']=='turn_based' and row['task_id']:
                if db.execute("UPDATE tasks SET state='ready',revision=revision+1 WHERE id=? AND state='waiting_input'",(row['task_id'],)).rowcount!=1:
                    raise BridgeError('TASK_STATE','The originating task changed while waiting for input.')
        if row['mode']=='active':
            self._transport.reply_question(request_id,{'contentItems':[{'type':'inputText','text':json.dumps({'answer':answer,'authority':authority,'evidence':evidence})}],'success':True},**self._question_identity(row))
            continuation={'same_turn_id':row['turn_id'],'response_forwarded':True}
        else:
            return self._continue_question(self._question(question_key),answer,authority,evidence)
        with self.registry.connect() as db:db.execute("UPDATE questions SET state='answered' WHERE key=?",(question_key,))
        return {'question':self._question(question_key),'continuation':continuation,'note':'Forwarding an answer does not prove completion or acceptance. Observe the actual original/continuation turn.'}

    def _question_identity(self,row):
        return {'generation':row['transport_token'],'thread_id':row['thread_id'],'turn_id':row['turn_id'],'call_id':row['call_id']}

    def _continue_question(self,row,answer,authority,evidence,recovered=False):
        self._worker(row['thread_id'])
        source=self.registry.one('messages','key',row['message_key'])
        if source['state']!='completed':raise BridgeError('QUESTION_STATE','Original fallback turn is not completed.')
        if self.registry.rows('SELECT key FROM messages WHERE thread_id=? AND created>? AND key<>?',(row['thread_id'],source['created'],row['reply_message_key'])):
            raise BridgeError('STALE_QUESTION','Newer work exists; do not replay an obsolete answer.')
        audit_args={}
        links=self.registry.rows('SELECT * FROM audit_links WHERE message_key=?',(source['key'],))
        if links:
            link=links[0];task=self.registry.one('tasks','id',link['task_id'])
            self._validate_audit_link(task,source)
            audit_args={'audit_task_id':link['task_id'],'audit_artifacts':json.loads(link['artifacts'])}
        payload=json.loads(row['payload'])
        continuation=self.message_send(row['thread_id'],f'Answer to your question: {payload["question"]}\n{answer}\nAuthority: {authority}. Evidence: {evidence}\nContinue the original assigned task or independent audit; preserve its requirements and your worker role.',row['reply_message_key'],task_id=row['task_id'],**audit_args)
        with self.registry.connect() as db:db.execute("UPDATE questions SET state='answered' WHERE key=?",(row['key'],))
        return {'question':self._question(row['key']),'continuation':continuation,'recovered_before_dispatch':recovered,'note':'Same continuation identity; original task/audit binding retained. Completion and acceptance require actual evidence.'}
