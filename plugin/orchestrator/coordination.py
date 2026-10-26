"""Scoped expertise, bounded context packets, plans, contracts and audit judgments."""
import json
import time
from .errors import BridgeError
from .projects import canonical,contained
from .storage import fingerprint


class CoordinationOperations:
    def coordination_read(self,record_key):
        row=self.registry.one('coordination_records','key',record_key);self._project(row['project_id'])
        row['payload']=json.loads(row['payload']);return row

    def _record(self,key,kind):
        row=self.registry.one('coordination_records','key',key);self._project(row['project_id'])
        if row['kind']!=kind:raise BridgeError('RECORD_KIND','This key belongs to another coordination record type.')
        row['payload']=json.loads(row['payload']);return row

    def _immutable_record(self,key,project_id,kind,payload):
        with self.registry.transaction() as db:
            old=db.execute('SELECT * FROM coordination_records WHERE key=?',(key,)).fetchone()
            if old:
                if old['project_id']!=project_id or old['kind']!=kind or json.loads(old['payload'])!=payload:raise BridgeError('IDEMPOTENCY_CONFLICT','Coordination key already has different content.')
            else:db.execute('INSERT INTO coordination_records VALUES(?,?,?,0,?,?)',(key,project_id,kind,json.dumps(payload),time.time()))
        return self._record(key,kind)

    def worker_context(self,thread_id,expected_revision,specialization,expertise,summary,sources=None,status='active'):
        worker,project=self._worker(thread_id,allow_archived=True)
        if worker['role'].lower()=='coordinator':raise BridgeError('ROLE_CONFLICT','Expertise profiles describe workers, not coordinator authority.')
        artifacts=self._audit_artifacts(project,sources or [])
        if status=='retired' and (self.registry.rows("SELECT id FROM tasks WHERE owner=? AND state NOT IN ('accepted','cancelled')",(thread_id,)) or self.registry.rows("SELECT key FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(thread_id,)) or self.registry.rows("SELECT key FROM questions WHERE thread_id=? AND state IN ('pending','escalated','answering')",(thread_id,))):
            raise BridgeError('UNFINISHED_TASKS','Resolve or explicitly hand off work before retiring this worker.')
        payload={'specialization':specialization,'expertise':expertise,'summary':summary,'sources':artifacts,'status':status,'observed_at':time.time()}
        with self.registry.transaction() as db:
            old=db.execute('SELECT revision FROM worker_profiles WHERE thread_id=?',(thread_id,)).fetchone()
            current=old['revision'] if old else 0
            if expected_revision!=current:raise BridgeError('REVISION_CONFLICT','Worker expertise/context changed.')
            db.execute('INSERT INTO worker_profiles VALUES(?,?,?) ON CONFLICT(thread_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(thread_id,current+1,json.dumps(payload)))
        return {'thread_id':thread_id,'revision':current+1,**payload}

    def worker_discover(self,project_id=None,role=None,expertise=None,include_retired=False):
        project_id=project_id or self.project_scope
        if not project_id:raise BridgeError('PROJECT_REQUIRED','Select an authorized project.')
        self._project(project_id);result=[]
        for worker in self.registry.rows("SELECT * FROM conversations WHERE project_id=? AND lower(role)<>'coordinator'",(project_id,)):
            if role and role.lower() not in worker['role'].lower():continue
            rows=self.registry.rows('SELECT * FROM worker_profiles WHERE thread_id=?',(worker['thread_id'],))
            profile=json.loads(rows[0]['payload']) if rows else {'expertise':[],'sources':[],'status':'active'}
            if not include_retired and (worker['archived'] or profile['status']=='retired'):continue
            fresh=True
            try:self._audit_artifacts(self._project(project_id),profile['sources'])
            except (OSError,BridgeError):fresh=False
            overlap=len(set(v.lower() for v in (expertise or [])) & set(v.lower() for v in profile['expertise']))
            result.append({'worker':worker,'profile':profile,'profile_revision':rows[0]['revision'] if rows else 0,'recorded_sources_unchanged':fresh,'expertise_overlap':overlap,'tasks':self.registry.rows('SELECT id,state,revision FROM tasks WHERE owner=?',(worker['thread_id'],))})
        result.sort(key=lambda r:(-r['expertise_overlap'],-bool(r['worker']['latest_completed_turn']),r['worker']['thread_id']))
        return {'candidates':result,'note':'Ranking uses explicit expertise tags and prior delivery, not inferred competence. Inspect relevant history and current files; unchanged hashes do not prove complete context.'}

    def context_handoff(self,project_id,handoff_key,thread_id,summary,sources,note_ids=None):
        worker,project=self._worker(thread_id)
        if project_id!=worker['project_id']:raise BridgeError('PROJECT_ACCESS_DENIED','Handoff target belongs to another project.')
        notes=[]
        for note_id in note_ids or []:
            note=self.registry.one('notes','id',note_id)
            if note['project_id']!=project_id:raise BridgeError('PROJECT_ACCESS_DENIED','Use decisions from this project only.')
            notes.append(note)
        return self._immutable_record(handoff_key,project_id,'handoff',{'thread_id':thread_id,'summary':summary,'sources':self._audit_artifacts(project,sources),'notes':notes})

    def _handoff_text(self,key,thread_id,verify=True):
        record=self._record(key,'handoff');payload=record['payload']
        if payload['thread_id']!=thread_id:raise BridgeError('OWNERSHIP_CONFLICT','This context packet belongs to another worker.')
        if verify:self._audit_artifacts(self._project(record['project_id']),payload['sources'])
        return '\nBound context handoff '+key+':\n'+json.dumps(payload,ensure_ascii=False)

    def architecture_contract(self,project_id,contract_key,expected_revision,content,sources):
        project=self._project(project_id);artifacts=self._audit_artifacts(project,sources)
        old=self.registry.rows('SELECT * FROM coordination_records WHERE key=?',(contract_key,))
        if old:
            record=self._record(contract_key,'contract')
            if record['project_id']!=project_id:raise BridgeError('PROJECT_ACCESS_DENIED','Contract belongs to another project.')
            for task in self.registry.rows("SELECT * FROM tasks WHERE project_id=? AND plan_key IS NOT NULL AND state NOT IN ('accepted','cancelled')",(project_id,)):
                plan=self._record(task['plan_key'],'plan')['payload']
                if any(r['key']==contract_key for r in plan['contracts']):raise BridgeError('CONTRACT_IN_USE','Resolve/cancel dependent work before changing its architecture contract.')
        current=old[0]['revision'] if old else 0
        if current!=expected_revision:raise BridgeError('REVISION_CONFLICT','Architecture contract changed.')
        payload={'content':content,'sources':artifacts}
        with self.registry.connect() as db:
            db.execute('INSERT INTO coordination_records VALUES(?,?,?, ?,?,?) ON CONFLICT(key) DO UPDATE SET revision=excluded.revision,payload=excluded.payload',(contract_key,project_id,'contract',current+1,json.dumps(payload),time.time()))
        return self._record(contract_key,'contract')

    def _check_contracts(self,project_id,refs):
        for ref in refs:
            contract=self._record(ref['key'],'contract')
            if contract['project_id']!=project_id:raise BridgeError('PROJECT_ACCESS_DENIED','Plan contract belongs to another project.')
            if contract['revision']!=ref['revision']:raise BridgeError('STALE_CONTRACT','Architecture contract revision changed. Replan explicitly.')
            self._audit_artifacts(self._project(project_id),contract['payload']['sources'])

    def plan_record(self,project_id,plan_key,objective,approval_evidence,tasks,contracts=None):
        tasks=json.loads(json.dumps(tasks))
        self._project(project_id);contracts=contracts or [];self._check_contracts(project_id,contracts)
        ids=[t['id'] for t in tasks]
        if len(set(ids))!=len(ids):raise BridgeError('PLAN_INVALID','Plan task IDs must be unique.')
        known=set(ids);done=set();order=[]
        for task in tasks:
            worker,project=self._worker(task['owner'])
            if worker['project_id']!=project_id or worker['role'].lower()=='coordinator':raise BridgeError('OWNERSHIP_CONFLICT','Assign planned work to a worker of this project.')
            task['write_paths']=[canonical(p) for p in task['write_paths']]
            for path in task['write_paths']:
                if not any(contained(path,root) for root in self._worker_write_roots(worker,project)):raise BridgeError('ARTIFACT_SCOPE','Declared writes must stay in the worker workspace or its authorized artifact directories.')
            if task['write_paths'] and any(r in worker['role'].lower() for r in ('audit','review','architect')):raise BridgeError('ROLE_CONFLICT','Read-only workers cannot own planned writes.')
            task['requirements']=task['requirements']+'\nInputs: '+json.dumps(task['inputs'])+'\nOutputs: '+json.dumps(task['outputs'])+'\nAcceptance: '+json.dumps(task['acceptance'])+'\nArchitecture contracts: '+json.dumps(contracts)
            for dependency in task['dependencies']:
                if dependency not in known:
                    prior=self.registry.one('tasks','id',dependency)
                    if prior['project_id']!=project_id:raise BridgeError('PROJECT_ACCESS_DENIED','Dependencies must belong to this project.')
        while len(done)<len(ids):
            ready=[t for t in tasks if t['id'] not in done and all(d not in known or d in done for d in t['dependencies'])]
            if not ready:raise BridgeError('DEPENDENCY_CYCLE','Plan contains a dependency cycle.')
            for task in ready:done.add(task['id']);order.append(task['id'])
        return self._immutable_record(plan_key,project_id,'plan',{'objective':objective,'approval_evidence':approval_evidence,'tasks':tasks,'contracts':contracts,'order':order})

    def _planned_task(self,plan_key,task_id):
        plan=self._record(plan_key,'plan');self._check_contracts(plan['project_id'],plan['payload']['contracts'])
        task=next((t for t in plan['payload']['tasks'] if t['id']==task_id),None)
        if not task:raise BridgeError('PLAN_INVALID','Task is not part of the referenced plan.')
        return task

    def _planned_paths(self,task_id):
        if not task_id:return []
        task=self.registry.one('tasks','id',task_id)
        if not task.get('plan_key'):return []
        planned=self._planned_task(task['plan_key'],task_id)
        for path in planned['write_paths']:
            worker,project=self._worker(task['owner'])
            if not any(contained(path,root) for root in self._worker_write_roots(worker,project)):raise BridgeError('ARTIFACT_SCOPE','A declared write now resolves outside its authorized directories.')
        return planned['write_paths']

    def audit_assess(self,assessment_key,task_id,audit_message_key,decision,evidence):
        task=self.registry.one('tasks','id',task_id);self._project(task['project_id'])
        existing=self.registry.rows('SELECT key FROM coordination_records WHERE key=?',(assessment_key,))
        if existing:
            previous=self._record(assessment_key,'assessment');payload=previous['payload']
            if (payload['task_id'],payload['audit_message_key'],payload['decision'],payload['evidence'])!=(task_id,audit_message_key,decision,evidence):raise BridgeError('IDEMPOTENCY_CONFLICT','This assessment key records a different judgment.')
            return {'assessment':previous,'task_state':task['state'],'acceptance_changed':False,'duplicate_prevented':True,'note':'Historical assessment retained at its recorded revision; this is not a new acceptance or current-artifact verification.'}
        audit=self.registry.one('messages','key',audit_message_key);auditor,_=self._worker(audit['thread_id'],allow_archived=True)
        if audit['state']!='completed' or auditor['project_id']!=task['project_id'] or auditor['thread_id']==task['owner'] or 'audit' not in auditor['role'].lower():raise BridgeError('INDEPENDENT_AUDIT_REQUIRED','Assess a completed independent audit in this project.')
        self._validate_audit_link(task,audit)
        record=self._immutable_record(assessment_key,task['project_id'],'assessment',{'task_id':task_id,'task_revision':task['revision'],'audit_message_key':audit_message_key,'decision':decision,'evidence':evidence})
        return {'assessment':record,'task_state':task['state'],'acceptance_changed':False,'next_step':'Use task_review only when an actual current independent verdict and integration evidence support acceptance/rejection. Disputes and insufficient evidence require further verification; they do not override a verdict.'}
