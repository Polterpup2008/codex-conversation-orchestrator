"""Tool contracts and strict validation, separate from transport and coordination."""
from .errors import BridgeError


def string(description, **options):
    return {'type':'string','minLength':1,'maxLength':100000,'description':description,**options}


def tool(name, description, properties, required=(), read_only=False):
    return {'name': name, 'description': description,
        'inputSchema': {'type': 'object', 'properties': properties, 'required': list(required), 'additionalProperties': False},
        'annotations': {'readOnlyHint': read_only, 'destructiveHint': name == 'conversation_archive',
                        'openWorldHint': name in ('conversation_create','conversation_resume','message_send')}}


ID = string('Real persistent Codex thread UUID.')
KEY = dict(type='string', minLength=1, maxLength=512, pattern=r'^[A-Za-z0-9_.:-]+$')
PAGE = {'cursor': string('Opaque nextCursor from a previous response.'), 'limit': {'type': 'integer', 'minimum': 1, 'maximum': 100}}
ROUTING={'model':string('Exact account-advertised model ID. Explicit unsupported choices are rejected.'),
    'effort':{'type':'string','enum':['none','minimal','low','medium','high','xhigh','max','ultra']},
    'difficulty':{'type':'string','enum':['routine','standard','complex','demanding','extreme']},
    'justification':string('Technical reason for escalation; required for extreme or Ultra.')}
TOOLS = [
    tool('project_create', 'Register an isolated, empty experiment workspace. Existing projects use coordinator_activate after direct human designation, or coordinator_register for an existing grant.',
         {'project_id': KEY, 'workspace': string('Absolute path to a new empty test workspace.'),
          'desktop':{'type':'boolean'},'name':string('Local project name.'),
          'desktop_project_id':KEY}, ['project_id', 'workspace']),
    tool('conversation_list', 'Discover actual Codex conversations or registered workers and capabilities. Includes App Server sources; paginated, database-only discovery.',
         {'project_id': KEY, **PAGE, 'archived': {'type': 'boolean'}}, read_only=True),
    tool('conversation_create', 'Create a genuine independent persistent Codex thread in an experiment; idempotent creation key. Uses existing ChatGPT authentication.',
         {'project_id': KEY, 'name': string('Human-readable conversation name.'), 'role': string('Explicit worker role.'), 'create_key': KEY,
          'capabilities': {'type': 'array', 'items': string('Worker capability.'), 'maxItems': 50}}, ['project_id', 'name', 'role', 'create_key']),
    tool('conversation_read', 'Read real thread metadata and a page of full turn history without creating a turn.',
         {'thread_id': ID, **PAGE}, ['thread_id'], True),
    tool('conversation_items', 'Read a page of persisted items, optionally restricted to a turn.',
         {'thread_id': ID, 'turn_id': ID, **PAGE}, ['thread_id'], True),
    tool('conversation_resume', 'Load an existing registered project thread using its original ID; preserves history.', {'thread_id': ID}, ['thread_id']),
    tool('conversation_name', 'Set a registered project conversation name in Codex and the registry.', {'thread_id': ID, 'name': string('New display name.')}, ['thread_id', 'name']),
    tool('conversation_role', 'Update registry role/capabilities; role is included in subsequent messages. Does not rewrite history.',
         {'thread_id': ID, 'role': string('Assigned role.'), 'capabilities': {'type': 'array', 'items': string('Capability.'), 'maxItems': 50}}, ['thread_id', 'role']),
    tool('message_send', 'Send one message to a registered conversation. Requires stable idempotency key; refuses concurrent or uncertain sends. Turn completion is separate from task acceptance.',
         {'thread_id': ID, 'message': string('Precise worker instruction.'), 'message_key': KEY, 'task_id': KEY,'audit_task_id':KEY,'audit_artifacts':{'type':'array','maxItems':100,'items':{'type':'object','properties':{'path':string('Absolute artifact path in this project.'),'sha256':{'type':'string','pattern':'^[a-f0-9]{64}$'}},'required':['path','sha256'],'additionalProperties':False}},**ROUTING}, ['thread_id', 'message', 'message_key']),
    tool('message_status', 'Reconcile delivery and actual turn status against persisted Codex history and retrieve complete assistant outputs.', {'message_key': KEY}, ['message_key']),
    tool('message_wait', 'Wait for a real completion event, up to 50 seconds. Timeout leaves the turn running; call again with the same key.',
         {'message_key': KEY, 'timeout_seconds': {'type': 'number', 'minimum': 0, 'maximum': 50}}, ['message_key']),
    tool('turn_interrupt', 'Interrupt only the specific active turn belonging to a registered projectal message.', {'message_key': KEY}, ['message_key']),
    tool('conversation_archive', 'Archive an idle registered worker, preserving it. Permanent deletion is not available.', {'thread_id': ID,'reason':string('Cleanup reason and durable handoff evidence.')}, ['thread_id']),
    tool('conversation_unarchive','Restore an archived worker in this authorized project using its original ID/history.',{'thread_id':ID},['thread_id']),
    tool('task_cancel','Cancel resolved but unfinished work with a reason and current revision; preserves ownership/history.',{'task_id':KEY,'expected_revision':{'type':'integer','minimum':0},'reason':string('Cancellation and handoff reason.')},['task_id','expected_revision','reason']),
    tool('task_assign', 'Create a durable task with exclusive conversation ownership and already-existing dependencies. Task IDs are idempotent and cannot be silently reassigned.',
         {'project_id': KEY, 'task_id': KEY, 'owner': ID, 'requirements': string('Written requirements and observable acceptance conditions.'),
          'dependencies': {'type': 'array', 'items': KEY, 'maxItems': 100},**ROUTING}, ['project_id', 'task_id', 'owner', 'requirements']),
    tool('task_review', 'Record controller acceptance/rejection after a completed independent auditor turn. Requires current revision and actual audit evidence; this operation records a judgment, not automatic proof.',
         {'task_id': KEY, 'expected_revision': {'type': 'integer', 'minimum': 0}, 'audit_message_key': KEY,
          'verdict': {'type': 'string', 'enum': ['accept', 'reject']}, 'evidence': string('Controller validation evidence and interpretation of audit findings.')},
         ['task_id', 'expected_revision', 'audit_message_key', 'verdict', 'evidence']),
    tool('project_note', 'Persist a technical decision, outstanding problem, or resolution for the experiment.',
         {'project_id': KEY, 'kind': {'type': 'string', 'enum': ['decision', 'problem', 'resolution']}, 'text': string('Inspectable note.')}, ['project_id', 'kind', 'text']),
    tool('task_recover', 'Explicitly recover a blocked task only after all sends have resolved; retains ownership and records the reason.',
         {'task_id': KEY, 'expected_revision': {'type':'integer','minimum':0}, 'reason': string('Observed recovery evidence.')}, ['task_id','expected_revision','reason']),
    tool('project_status', 'Retrieve durable scoped project/worker/task/decision state. Unregistered connections show experiment_only until coordinator_activate or existing grant/registration; this does not imply missing production support.', {'project_id': KEY}, read_only=True),
    tool('desktop_project_list','Read account-local App Server projects. These are local Codex projects, separate from ChatGPT cloud Projects. UI registration must be verified separately.',{},read_only=True),
    tool('project_discover','Resolve the genuine coordinator primary local project from thread metadata or one unambiguous registered root. Never guesses the plugin cwd.',
        {'coordinator_thread_id':ID},read_only=True),
    tool('project_link','Bind an isolated registry project to the authoritative local Codex project/coordinator. Does not move unrelated threads or activate permanent coordination.',
        {'project_id':KEY,'desktop_project_id':KEY,'coordinator_thread_id':ID,'desktop_ui_project_id':KEY},['project_id']),
    tool('coordinator_register','Resume an existing scoped authorization and original coordinator. A new human designation uses coordinator_activate without a second local grant.',
        {'project_id':KEY,'coordinator_thread_id':ID},['project_id','coordinator_thread_id']),
    tool('model_list','Discover current account-visible models, supported efforts and defaults with official model/list. Catalog availability is distinct from successful execution.',
        {'refresh':{'type':'boolean'}},read_only=True),
    tool('model_route','Preview an explicit or automatic selection using the current catalog. Explicit unsupported combinations fail; Ultra is never automatic.',
        {'role':string('Worker role.'),**ROUTING},read_only=True),
    tool('conversation_configure','Persist validated worker model/effort preferences for subsequent turns. Preserves thread identity and history, and refuses active workers.',
        {'thread_id':ID,'expected_revision':{'type':'integer','minimum':0},**ROUTING},['thread_id']),
    tool('conversation_desktop_prepare','Prepare a registered idle experiment worker for the supported native desktop attachment workflow. Returns required host-tool operations; this server cannot itself invoke the hosting desktop tools.',
        {'thread_id':ID},['thread_id']),
    tool('conversation_desktop_confirm','Record the coordinator observation after native list_threads/UI verifies membership. Does not independently assert or synthesize desktop evidence.',
        {'thread_id':ID,'observed_project_id':KEY,'evidence':string('Actual native desktop membership observation and UI evidence.')},['thread_id','observed_project_id','evidence']),
    tool('bridge_release','Release idle App Server writer locks while keeping the MCP/registry available. Refuses active or uncertain owned sends; reconnects lazily on later operations.',{}),
    tool('conversation_lifecycle_reconcile','After releasing/closing the old bridge, reconcile a fenced uncertain archive/unarchive/desktop preparation against native persisted metadata. Never blindly retries the mutation.',{'thread_id':ID},['thread_id']),
]

next(t for t in TOOLS if t['name']=='conversation_create')['inputSchema']['properties'].update({
    'coordinator_thread_id':ID,'workspace':string('Primary workspace or a verified isolated worktree of the bound parent project.'),**ROUTING})

TEXTS={'type':'array','items':string('Concise value.',maxLength=2000),'maxItems':50}
ARTIFACTS=next(t for t in TOOLS if t['name']=='message_send')['inputSchema']['properties']['audit_artifacts']
next(t for t in TOOLS if t['name']=='message_send')['inputSchema']['properties']['handoff_key']=KEY
next(t for t in TOOLS if t['name']=='task_assign')['inputSchema']['properties']['plan_key']=KEY
PLAN_TASK={'type':'object','properties':{'id':KEY,'owner':ID,'requirements':string('Task scope and constraints.'),'inputs':TEXTS,'outputs':TEXTS,'acceptance':TEXTS,'dependencies':{'type':'array','items':KEY,'maxItems':50},'write_paths':TEXTS},'required':['id','owner','requirements','inputs','outputs','acceptance','dependencies','write_paths'],'additionalProperties':False}
CONTRACT_REF={'type':'object','properties':{'key':KEY,'revision':{'type':'integer','minimum':1}},'required':['key','revision'],'additionalProperties':False}
TOOLS.extend([
    tool('coordinator_activate','Activate THIS human-designated chat from an exact direct appointment already in its native history. No second grant/confirmation. Refuses managed workers, fabricated evidence, revoked grants, another owner or another project.',{'project_id':KEY,'coordinator_thread_id':ID,'appointment_quote':string('Exact short direct human designation from this conversation, without quotes/code fences.',maxLength=2000),'desktop_ui_project_id':KEY,'desktop_project_id':KEY,'headless':{'type':'boolean'}},['project_id','coordinator_thread_id','appointment_quote']),
    tool('runtime_check','Registered coordinator preflight: version-only probes under developer/auditor policies. Can add only RX to a standard per-user Windows base Python after an observed access failure, preserving runtime files and sandbox policies. No second human confirmation for routine authorized maintenance.',{'python_executable':string('Absolute existing project Python/venv executable.'),'repair_read_execute':{'type':'boolean'}},['python_executable']),
    tool('bridge_status','Read the actual serving plugin version, profile/runtime locations, available skills and registration requirements without starting a model or reading credentials.',{},read_only=True),
    tool('question_list','Inspect scoped ordinary worker questions, originating task/turn and active/turn-based reply availability. Does not expose or approve security requests.',{'project_id':KEY,'thread_id':ID,'include_resolved':{'type':'boolean'}},read_only=True),
    tool('question_reply','Answer an ordinary worker question once. Dedicated active requests resume the same turn; completed-turn questions continue the same worker/task. Security approvals are unsupported.',{'question_key':KEY,'answer_key':KEY,'answer':string('Precise answer; no permissions or secrets.'),'authority':{'type':'string','enum':['technical','documented_requirement','human_decision']},'evidence':string('Authoritative documentation/decision or actual human answer.')},['question_key','answer_key','answer','authority','evidence']),
    tool('question_escalate','Record an unresolved human decision and recommendation; transmits no answer/approval. The coordinator presents it to the human.',{'question_key':KEY,'reason':string('Why current authority/docs cannot resolve it.'),'recommendation':string('Options, consequences and recommendation.')},['question_key','reason','recommendation']),
    tool('worker_discover','Prefer existing scoped workers using explicit role/expertise, prior delivery and source freshness. Does not infer competence or appoint coordinators.',{'project_id':KEY,'role':string('Role filter.'),'expertise':TEXTS,'include_retired':{'type':'boolean'}},read_only=True),
    tool('worker_context','Persist scoped worker specialization, expertise and source-hash context with optimistic revision. Retirement refuses unresolved work.',{'thread_id':ID,'expected_revision':{'type':'integer','minimum':0},'specialization':string('Worker responsibility.'),'expertise':TEXTS,'summary':string('Relevant known context and limitations.',maxLength=6000),'sources':ARTIFACTS,'status':{'type':'string','enum':['active','retired']}},['thread_id','expected_revision','specialization','expertise','summary']),
    tool('context_handoff','Create an immutable bounded context packet for an existing worker: summary, current authoritative hashes and selected scoped notes. message_send can bind it by handoff_key.',{'project_id':KEY,'handoff_key':KEY,'thread_id':ID,'summary':string('Only necessary new context.',maxLength=12000),'sources':ARTIFACTS,'note_ids':{'type':'array','items':{'type':'integer','minimum':1},'maxItems':30}},['project_id','handoff_key','thread_id','summary','sources']),
    tool('plan_record','Record an approved objective, scoped owners, inputs/outputs/acceptance, acyclic dependencies, declared writes and architecture contract revisions. Returns normalized task requirements/order for task_assign.',{'project_id':KEY,'plan_key':KEY,'objective':string('Approved outcome.'),'approval_evidence':string('Existing user-approved objective/source; this tool grants no new authority.'),'tasks':{'type':'array','items':PLAN_TASK,'minItems':1,'maxItems':50},'contracts':{'type':'array','items':CONTRACT_REF,'maxItems':30}},['project_id','plan_key','objective','approval_evidence','tasks']),
    tool('architecture_contract','Create/update a scoped shared interface/integration contract with revision and authoritative hashes. Refuses changes while dependent work is unfinished.',{'project_id':KEY,'contract_key':KEY,'expected_revision':{'type':'integer','minimum':0},'content':string('Interfaces, ownership, dependencies, integration and regression criteria.'),'sources':ARTIFACTS},['project_id','contract_key','expected_revision','content','sources']),
    tool('audit_assess','Persist evidence-based acceptance/rejection/insufficient-evidence/disputed assessment of a current bound independent audit. Does not change acceptance or bypass task_review.',{'assessment_key':KEY,'task_id':KEY,'audit_message_key':KEY,'decision':{'type':'string','enum':['accept','reject','insufficient_evidence','audit_disputed']},'evidence':string('Verified claims, reproductions, revision, coverage and remaining gaps.')},['assessment_key','task_id','audit_message_key','decision','evidence']),
    tool('coordination_read','Read one scoped durable plan, handoff, architecture contract or audit assessment by its original key.',{'record_key':KEY},['record_key'],True),
])


def validate(value, schema, path='arguments'):
    import re
    kind = schema.get('type')
    valid = {'object': lambda: isinstance(value, dict), 'array': lambda: isinstance(value, list),
        'string': lambda: isinstance(value, str), 'boolean': lambda: isinstance(value, bool),
        'integer': lambda: isinstance(value, int) and not isinstance(value, bool),
        'number': lambda: isinstance(value, (int, float)) and not isinstance(value, bool)}
    if kind in valid and not valid[kind]():
        raise BridgeError('INVALID_ARGUMENT', f'{path} must be {kind}.')
    if 'enum' in schema and value not in schema['enum']:
        raise BridgeError('INVALID_ARGUMENT', f'{path} must be one of {schema["enum"]}.')
    if kind == 'object':
        properties = schema.get('properties', {})
        if any(k not in value for k in schema.get('required', [])):
            raise BridgeError('INVALID_ARGUMENT', f'{path} is missing required fields.')
        if schema.get('additionalProperties') is False and any(k not in properties for k in value):
            raise BridgeError('INVALID_ARGUMENT', f'{path} contains unknown fields.')
        for key, val in value.items():
            if key in properties:
                validate(val, properties[key], path+'.'+key)
    elif kind == 'array':
        if len(value)<schema.get('minItems',0):raise BridgeError('INVALID_ARGUMENT',f'{path} has too few entries.')
        if len(value) > schema.get('maxItems', 1000):
            raise BridgeError('INVALID_ARGUMENT', f'{path} has too many entries.')
        for entry in value:
            validate(entry, schema['items'], path+'[]')
    elif kind == 'string':
        if not value.strip() or len(value) < schema.get('minLength', 0) or len(value) > schema.get('maxLength', 100000):
            raise BridgeError('INVALID_ARGUMENT', f'{path} has an invalid length.')
        if schema.get('pattern') and not re.fullmatch(schema['pattern'], value):
            raise BridgeError('INVALID_ARGUMENT', f'{path} has invalid characters.')
    elif kind in ('number', 'integer'):
        import math
        if not math.isfinite(value) or not schema.get('minimum', -float('inf')) <= value <= schema.get('maximum', float('inf')):
            raise BridgeError('INVALID_ARGUMENT', f'{path} is outside its allowed range.')


def invoke(service, name, arguments):
    import sqlite3
    spec = next((s for s in TOOLS if s['name'] == name), None)
    if not spec:
        raise BridgeError('UNKNOWN_TOOL', f'Unknown tool {name}. Permanent deletion is disabled.')
    validate(arguments, spec['inputSchema'])
    try:
        arguments=dict(arguments)
        if service.project_scope and name!='coordinator_register':
            prefix=service.project_scope+'::'
            for key in ('task_id','audit_task_id','message_key','audit_message_key','create_key','question_key','answer_key','plan_key','contract_key','handoff_key','assessment_key','record_key'):
                if arguments.get(key) and not arguments[key].startswith(prefix):arguments[key]=prefix+arguments[key]
            if 'dependencies' in arguments:arguments['dependencies']=[v if v.startswith(prefix) else prefix+v for v in arguments['dependencies']]
            if name=='plan_record':
                import copy
                arguments=copy.deepcopy(arguments)
                for task in arguments['tasks']:
                    task['id']=task['id'] if task['id'].startswith(prefix) else prefix+task['id']
                    task['dependencies']=[v if v.startswith(prefix) else prefix+v for v in task['dependencies']]
                for ref in arguments.get('contracts',[]):ref['key']=ref['key'] if ref['key'].startswith(prefix) else prefix+ref['key']
        service.authorize_call(name, arguments)
        return getattr(service, name)(**arguments)
    except sqlite3.Error as e:
        raise BridgeError('REGISTRY_ERROR', f'{type(e).__name__}: {e}') from e
    except OSError as e:
        raise BridgeError('FILESYSTEM_ERROR', str(e)) from e
