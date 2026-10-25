"""Catalog-validated selection. Explicit unsupported choices never fall back."""
import json
import time
from .errors import BridgeError

EFFORTS=['none','minimal','low','medium','high','xhigh','max','ultra']
TIERS={
    'routine':('gpt-6-luna','low'),
    'standard':('gpt-6.1-sol','medium'),
    'complex':('gpt-6-astra','high'),
    'demanding':('gpt-6-astra','xhigh'),
    'extreme':('gpt-6-astra','max'),
}


def select_route(catalog,model=None,effort=None,difficulty=None,role='',justification=None):
    explicit_effort=effort
    models={m['model']:m for m in catalog}
    if not models:raise BridgeError('MODEL_CATALOG_EMPTY','No account-visible models were advertised.')
    reason='explicit model preference' if model else 'automatic selection'
    level=difficulty or ('complex' if 'audit' in role.lower() else 'standard')
    if level not in TIERS:raise BridgeError('INVALID_DIFFICULTY','Unknown routing difficulty.')
    if level=='extreme' and not justification:
        raise BridgeError('ROUTING_JUSTIFICATION_REQUIRED','Extreme routing requires a technical justification.')
    preferred,suggested=TIERS[level]
    if model and model not in models:
        raise BridgeError('MODEL_UNAVAILABLE','Requested model is not advertised for this authenticated account.',{'model':model,'available':list(models)})
    if not model:
        model=next((name for name in [preferred,'gpt-6.1-sol'] if name in models),None)
        if not model:model=next((m['model'] for m in catalog if m.get('isDefault')),next(iter(models)))
        reason=f'automatic {level}: preferred {preferred}; selected available {model}'
    entry=models[model];supported=[e['reasoningEffort'] for e in entry['supportedReasoningEfforts']]
    if effort is not None and effort not in supported:
        raise BridgeError('EFFORT_UNSUPPORTED','Requested reasoning effort is not advertised for this model.',{'model':model,'effort':effort,'supported':supported})
    if effort is None:
        if reason=='explicit model preference':effort=entry.get('defaultReasoningEffort')
        else:effort=suggested if suggested in supported else entry.get('defaultReasoningEffort')
        if effort=='ultra':
            effort=next((v for v in ['high','medium','low','xhigh','max','minimal','none'] if v in supported),None)
            if effort is None:raise BridgeError('ULTRA_EXPLICIT_REQUIRED','This catalog requires explicit Ultra selection; automatic routing is unavailable.')
    if effort not in supported:raise BridgeError('MODEL_CATALOG_INVALID','Model catalog does not provide a supported default effort.')
    if effort=='ultra' and (explicit_effort!='ultra' or not justification):
        raise BridgeError('ROUTING_JUSTIFICATION_REQUIRED','Ultra may invoke proactive subagents and requires an explicit technical justification. It is never automatically selected.')
    return {'model':model,'effort':effort,'difficulty':level,'reason':reason,'justification':justification,
        'ultra_may_delegate':effort=='ultra','speed_tier':'inherited; not changed by model/effort routing'}


class ModelOperations:
    def model_list(self,refresh=False):
        now=time.monotonic();cached=getattr(self,'_model_cache',None)
        if not refresh and cached and now-cached[0]<60:return cached[1]
        entries=[];cursor=None
        while True:
            result=self.rpc.call('model/list',{'includeHidden':False,'limit':100,'cursor':cursor})
            entries.extend(result['data']);cursor=result.get('nextCursor')
            if not cursor:break
        result={'models':entries,'authentication':'existing_chatgpt_subscription',
            'access_note':'Catalog-advertised availability; actual execution errors remain explicit. No account restriction is bypassed.',
            'ultra_note':'Ultra can imply proactive subagent execution. It is never automatic routing or a speed tier.'}
        self._model_cache=(now,result);return result

    def model_route(self,difficulty=None,role='',model=None,effort=None,justification=None):
        return select_route(self.model_list()['models'],model,effort,difficulty,role,justification)

    def conversation_configure(self,thread_id,model=None,effort=None,difficulty=None,justification=None,expected_revision=None):
        worker,_=self._worker(thread_id)
        if self.registry.rows("SELECT key FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(thread_id,)):
            raise BridgeError('CONVERSATION_BUSY','Wait for the unresolved turn before changing worker preferences.')
        chosen_model=model or (None if difficulty else worker.get('model'))
        chosen_effort=effort if effort is not None else (None if model or difficulty else worker.get('effort'))
        route=self.model_route(difficulty,worker['role'],chosen_model,chosen_effort,justification)
        with self.registry.transaction() as db:
            if db.execute("SELECT 1 FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(thread_id,)).fetchone():
                raise BridgeError('CONVERSATION_BUSY','A send began before routing preferences could be committed.')
            row=db.execute('SELECT routing_revision FROM conversations WHERE thread_id=?',(thread_id,)).fetchone()
            if expected_revision is not None and row['routing_revision']!=expected_revision:
                raise BridgeError('REVISION_CONFLICT','Worker routing preferences changed.')
            db.execute('UPDATE conversations SET model=?,effort=?,routing_justification=?,routing_revision=routing_revision+1 WHERE thread_id=?',
                (route['model'],route['effort'],json.dumps(route),thread_id))
        return {'worker':self.registry.one('conversations','thread_id',thread_id),'routing':route,'applies_to':'subsequent turns; no turn was started'}

    def _message_route(self,worker,task_id,model,effort,difficulty,justification):
        task=self.registry.one('tasks','id',task_id) if task_id else {}
        if model:
            chosen_model=model;chosen_effort=effort
            source='message_override'
        elif difficulty:
            chosen_model=None;chosen_effort=effort;source='message_auto_routing'
        elif task.get('model') or task.get('difficulty'):
            chosen_model=task.get('model');chosen_effort=effort or task.get('effort');source='task_override'
        else:
            chosen_model=worker.get('model');chosen_effort=effort or task.get('effort') or worker.get('effort');source='worker_preference'
        stored_reason=worker.get('routing_justification')
        if stored_reason:
            try:stored_reason=json.loads(stored_reason).get('justification')
            except (ValueError,AttributeError):pass
        route=self.model_route(difficulty or task.get('difficulty'),worker['role'],chosen_model,chosen_effort,
            justification or task.get('routing_justification') or stored_reason)
        route['source']=source
        return route
