"""Scoped coordination operations on real persistent threads."""
import json
import os
import pathlib
import threading
import time
import uuid
import re
import subprocess
import sys
import contextlib
import functools
import inspect
from .errors import BridgeError
from .storage import Registry, fingerprint
from .transport import AppServer,integration_policy
from .projects import ProjectOperations,canonical,path_key,allowed_workspace,contained
from .routing import ModelOperations
from .authorization import AuthorizationOperations
from .auditing import AuditOperations
from .questions import QuestionOperations,QUESTION_TOOL
from .coordination import CoordinationOperations
from .runtime import RuntimeOperations

TERMINAL = ('completed', 'failed', 'interrupted')
SOURCES = ['cli', 'vscode', 'exec', 'appServer', 'unknown']


def identifier(value):
    try:
        uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as e:
        raise BridgeError('INVALID_THREAD_ID', 'Conversation ID must be a genuine Codex UUID.') from e
    return value


class Service(ProjectOperations,ModelOperations,AuthorizationOperations,AuditOperations,QuestionOperations,CoordinationOperations,RuntimeOperations):
    def bridge_status(self):
        from . import __version__
        root=pathlib.Path(__file__).resolve().parents[1]
        assets_available=(root/'skills').is_dir()
        try:
            skills={p.name:str(p/'SKILL.md') for p in ((root/'skills').iterdir() if assets_available else ()) if p.is_dir() and (p/'SKILL.md').is_file()}
        except OSError:
            assets_available=False;skills={}
        with self.registry.connect() as db:schema=db.execute('PRAGMA user_version').fetchone()[0]
        return {'version':__version__,'registry_schema':schema,'plugin_root':str(root),'coordination_skill':str(root/'skills/conversation-coordinate/SKILL.md'),
                'specialized_skills':skills,
                'loaded_package_resources_available':assets_available,'host_refresh_required':not assets_available,
                'codex_home':str(pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))),'data_dir':str(self.data_dir),
                'project_scope':self.project_scope,'per_project_plugin_copy_required':False,'production_requires_local_grant_and_registration':False,
                'activation_methods':['coordinator_activate: verified direct human appointment, no second confirmation','coordinator_register: existing local grant'],
                'caller_probe':{'challenge':self.caller_challenge,
                    'command':[sys.executable,'-I','-B','-S',str(root/'caller.py'),'--challenge',self.caller_challenge],
                    'instruction':'When MCP lacks CODEX_THREAD_ID, execute this read-only command inside THIS chat shell, then call coordinator_activate on this same connection. It prints a nonce-bound identity into this chat native tool history; no registry write or human grant.'},
                'routine_runtime_preflight':'runtime_check probes both role policies and can repair standard per-user Windows Python read/execute access.',
                'note':'This is the version actually serving this MCP connection. Old chats can retain older tool processes. Installation and merely reading a template do not appoint a coordinator.'}

    def __init__(self, data_dir=None, transport_factory=AppServer):
        self.data_dir = pathlib.Path(data_dir or os.environ.get('ORCHESTRATOR_DATA_DIR') or
            pathlib.Path(os.environ.get('CODEX_HOME', pathlib.Path.home()/'.codex'))/'conversation-orchestrator')
        self.registry = Registry(self.data_dir/'registry.sqlite3')
        self.transport_factory, self._transport = transport_factory, None
        self.start_guard = threading.Lock()
        self.binding_guard = threading.Lock()
        self.control_guard = threading.RLock()
        self.control_context = threading.local()
        self.project_scope = None
        self.project_policy = None
        self._closed = False
        self.resume_guard = threading.Lock()
        self.loaded = set()
        self.instance = str(uuid.uuid4())
        self.caller_challenge = uuid.uuid4().hex
        self.stop_heartbeat = threading.Event()
        with self.registry.connect() as db:
            db.execute('INSERT INTO bridges VALUES(?,?,1,?)', (self.instance, os.getpid(), time.time()))
        def heartbeat():
            while not self.stop_heartbeat.wait(10):
                with self.registry.connect() as db:
                    db.execute('UPDATE bridges SET last_seen=? WHERE token=?', (time.time(),self.instance))
        threading.Thread(target=heartbeat,daemon=True).start()

    @property
    def rpc(self):
        with self.start_guard:
            if self._closed:raise BridgeError('CONNECTION_CLOSED','This bridge has shut down; use a fresh connection.')
            if self._transport is None or self._transport.closed:
                if self._transport:
                    self._transport.close()
                options={}
                if self.project_scope and self.transport_factory is AppServer:
                    options={'workspace':self._project(self.project_scope)['root'],
                             'allow_integrations':json.loads(self.project_policy['integrations'])}
                generation=str(uuid.uuid4()) if self.transport_factory is AppServer else None
                if self.transport_factory is AppServer:options.update(on_question=self._capture_question,generation=generation)
                self._transport = self.transport_factory(self.data_dir/'logs',lambda method,params:self._event(method,params,generation),**options)
                self.loaded.clear()
            return self._transport

    def _event(self,method,params,generation=None):
        self.registry.event(method,params);self._question_event(method,params,generation)

    def close(self):
        if self._closed:return
        self._closed=True
        self.stop_heartbeat.set()
        if self._transport:
            self._transport.close()
        with self.registry.connect() as db:
            db.execute('UPDATE bridges SET active=0,last_seen=? WHERE token=?', (time.time(),self.instance))

    def bridge_release(self):
        pending=self.registry.rows("SELECT key FROM messages WHERE owner_token=? AND state IN ('preparing','sent','unknown')",(self.instance,))
        if pending:raise BridgeError('BRIDGE_BUSY','Resolve this bridge active or uncertain messages before releasing its App Server.',{'messages':pending})
        with self.start_guard:
            if self._transport:
                with self._transport.guard:
                    if self._transport.pending or self._transport.active:raise BridgeError('BRIDGE_BUSY','Another App Server request or turn is still pending.')
                    self._transport.closed=True
                self._transport.close();self._transport=None
            self.loaded.clear()
        return {'released':True,'histories_preserved':True,'note':'The next remote operation reconnects lazily. Desktop attachment can proceed without this bridge holding idle writer locks.'}

    def _other_owner(self, row):
        if not row.get('owner_token') or row['owner_token'] == self.instance:
            return False
        owners = self.registry.rows('SELECT * FROM bridges WHERE token=?', (row['owner_token'],))
        if not owners or not owners[0]['active']:
            return False
        pid = owners[0]['pid']
        if os.name == 'nt':
            import ctypes
            kernel = ctypes.WinDLL('kernel32',use_last_error=True)
            kernel.OpenProcess.restype = ctypes.c_void_p
            kernel.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
            handle = kernel.OpenProcess(0x1000,False,pid)
            if not handle:
                # ERROR_INVALID_PARAMETER means no such PID; access denied is conservatively live.
                return ctypes.get_last_error() != 87
            code = ctypes.c_ulong()
            try:
                if not kernel.GetExitCodeProcess(handle,ctypes.byref(code)):
                    return True
                return code.value == 259
            finally:
                kernel.CloseHandle(handle)
        try:
            os.kill(pid,0); return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    def _worker(self, thread_id, allow_archived=False):
        identifier(thread_id)
        worker = self.registry.one('conversations', 'thread_id', thread_id)
        if worker['archived'] and not allow_archived:
            raise BridgeError('ARCHIVED', 'Archived experiment conversations cannot receive mutations.')
        project = self._project(worker['project_id'])
        if os.path.normcase(os.path.abspath(project['root']))!=os.path.normcase(canonical(project['root'])):
            raise BridgeError('SCOPE_LOST','The authorized root now resolves elsewhere; local operator review is required.')
        if worker.get('workspace'):
            allowed_workspace(project['root'],worker['workspace'])
            self._workspace_exclusive(project['id'],worker['workspace'])
        if project['mode']=='experiment' and not (pathlib.Path(project['root'])/'.conversation-orchestrator-experiment').is_file():
            raise BridgeError('SCOPE_LOST', 'Experiment marker is missing; mutations are blocked.')
        return worker, project

    @contextlib.contextmanager
    def _control_operation(self,name):
        # Serialize control-plane transitions, including local grant changes.
        # Running worker turns remain concurrent; waits do not hold this gate.
        with self.control_guard:
            if getattr(self.control_context,'active',False):
                yield;return
            with self.registry.transaction() as db:
                lock=db.execute('SELECT * FROM control_lock WHERE id=1').fetchone()
                if lock:
                    if self._other_owner(dict(lock)) or lock['owner_token']==self.instance:
                        raise BridgeError('PROJECT_BUSY','Another control operation is in progress; retry with the same stable key.')
                    db.execute('DELETE FROM control_lock WHERE id=1')
                if self.project_scope:self._project(self.project_scope)
                db.execute('INSERT INTO control_lock VALUES(1,?,?)',(self.instance,name))
            self.control_context.active=True
            try:yield
            finally:
                self.control_context.active=False
                with self.registry.connect() as db:db.execute('DELETE FROM control_lock WHERE id=1 AND owner_token=?',(self.instance,))

    def _clear_orphaned_operation(self,thread_id):
        rows=self.registry.rows('SELECT * FROM operations WHERE thread_id=?',(thread_id,))
        if not rows:return
        old=rows[0]
        if self._other_owner(old):raise BridgeError('CONVERSATION_BUSY','Another live bridge owns this lifecycle operation.')
        if old['stage']=='dispatching':
            raise BridgeError('LIFECYCLE_UNKNOWN','Release the old bridge, then call conversation_lifecycle_reconcile before conflicting operations.')
        with self.registry.transaction() as db:
            db.execute('DELETE FROM operations WHERE thread_id=? AND owner_token=?',(thread_id,old['owner_token']))

    def conversation_lifecycle_reconcile(self,thread_id):
        self._worker(thread_id,allow_archived=True)
        rows=self.registry.rows('SELECT * FROM operations WHERE thread_id=?',(thread_id,))
        if not rows:return {'thread_id':thread_id,'pending_operation':False}
        old=rows[0]
        if self._other_owner(old):raise BridgeError('CONVERSATION_BUSY','The lifecycle owner is still live; release/close it first.')
        if old['owner_token']==self.instance and self._transport is not None:
            raise BridgeError('BRIDGE_BUSY','Call bridge_release before reconciling an uncertain lifecycle RPC.')
        if old['stage']=='dispatching':
            if old['name'] in ('archive','unarchive'):
                archived=self._native_archive_state(thread_id)
                with self.registry.connect() as db:db.execute('UPDATE conversations SET archived=? WHERE thread_id=?',(int(archived),thread_id))
            elif old['name']=='desktop_prepare':
                remote=self.rpc.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
                if 'projectId' not in remote:raise BridgeError('LIFECYCLE_UNKNOWN','Current native project metadata is unavailable; keep the fence.')
                # A closed former transport cannot apply a delayed update now.
                # Either observed outcome requires fresh host attachment proof.
                with self.registry.connect() as db:db.execute("UPDATE conversations SET desktop_sync_state='pending',desktop_evidence=NULL WHERE thread_id=?",(thread_id,))
            else:raise BridgeError('LIFECYCLE_UNKNOWN','Unsupported recovery operation; keep the fence.')
        with self.registry.connect() as db:db.execute('DELETE FROM operations WHERE thread_id=? AND owner_token=?',(thread_id,old['owner_token']))
        return {'thread_id':thread_id,'reconciled':True,'worker':self.registry.one('conversations','thread_id',thread_id)}

    def _native_archive_state(self,thread_id):
        found=[]
        for archived in (False,True):
            cursor=None
            while True:
                page=self.rpc.call('thread/list',{'archived':archived,'limit':100,'cursor':cursor,'sourceKinds':SOURCES,'useStateDbOnly':True})
                found.extend(archived for t in page['data'] if t['id']==thread_id)
                cursor=page.get('nextCursor')
                if not cursor:break
        if not found:
            # Empty sessions are omitted by native thread/list in the tested
            # runtime. Use only the official thread/read path, and only its
            # recognized placement inside this local Codex profile.
            thread=self.rpc.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
            path=thread.get('path')
            home=pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))
            if path and contained(path,home/'archived_sessions'):return True
            if path and contained(path,home/'sessions'):return False
        if len(found)!=1:raise BridgeError('LIFECYCLE_UNKNOWN','Native persisted archive state is not uniquely observable; keep the fence.')
        return found[0]

    def _operation_dispatch(self,thread_id):
        with self.registry.connect() as db:
            if db.execute("UPDATE operations SET stage='dispatching' WHERE thread_id=? AND owner_token=?",(thread_id,self.instance)).rowcount!=1:
                raise BridgeError('DISPATCH_FENCED','Lifecycle ownership changed before dispatch.')

    @contextlib.contextmanager
    def _exclusive_operation(self,thread_id,name):
        self._clear_orphaned_operation(thread_id)
        with self.registry.transaction() as db:
            if db.execute('SELECT 1 FROM operations WHERE thread_id=?',(thread_id,)).fetchone() or db.execute("SELECT 1 FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(thread_id,)).fetchone():
                raise BridgeError('CONVERSATION_BUSY','Resolve active sends/lifecycle operations first.')
            db.execute("INSERT INTO operations(thread_id,owner_token,name,stage) VALUES(?,?,?,'preparing')",(thread_id,self.instance,name))
        try:
            yield
        except BaseException:
            with self.registry.connect() as db:db.execute("DELETE FROM operations WHERE thread_id=? AND owner_token=? AND stage='preparing'",(thread_id,self.instance))
            raise
        else:
            with self.registry.connect() as db:db.execute('DELETE FROM operations WHERE thread_id=? AND owner_token=?',(thread_id,self.instance))

    def project_create(self, project_id, workspace, desktop=False, name=None, desktop_project_id=None):
        if ':' in project_id:raise BridgeError('INVALID_PROJECT_ID','Project IDs cannot contain the reserved colon separator.')
        path = pathlib.Path(canonical(workspace))
        if not path.is_absolute():
            raise BridgeError('INVALID_WORKSPACE', 'Use an absolute path for a new isolated experiment directory.')
        path = path.resolve()
        old = self.registry.rows('SELECT * FROM projects WHERE id=?', (project_id,))
        if old:
            self._project(project_id)
            if path_key(old[0]['root']) != path_key(path):
                raise BridgeError('PROJECT_CONFLICT', 'Project ID is already associated with a different workspace.')
            if desktop_project_id:return self.project_link(project_id,desktop_project_id)['registry_project']
            if desktop and not old[0].get('desktop_project_id'):
                created=self.rpc.call('project/create',{'idempotencyKey':'conversation-orchestrator:'+project_id,
                    'name':name or project_id,'roots':[{'path':str(path)}],
                    'metadata':{'purpose':'isolated-conversation-orchestrator-experiment'}})['project']['id']
                return self.project_link(project_id,created)['registry_project']
            return old[0]
        if any((p/'.git').exists() for p in (path, *path.parents)):
            raise BridgeError('EXISTING_REPOSITORY', 'This proof of concept cannot coordinate an existing repository.')
        if path.exists() and any(path.iterdir()):
            raise BridgeError('WORKSPACE_NOT_EMPTY', 'Create a new empty temporary workspace.')
        path.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            # Sandbox worker accounts create files with a different owner. Preserve
            # access for the controlling user explicitly, rather than relying on OWNER RIGHTS.
            account = subprocess.run(['whoami'],capture_output=True,text=True,check=True).stdout.strip()
            acl = subprocess.run(['icacls',str(path),'/grant',f'{account}:(OI)(CI)M'],capture_output=True,text=True)
            if acl.returncode:
                raise BridgeError('WORKSPACE_ACL_FAILED', 'Cannot preserve controller access in the new test directory.', {'stderr':acl.stderr})
        (path/'.conversation-orchestrator-experiment').write_text(project_id+'\n', encoding='utf-8')
        try:
            with self.registry.transaction() as db:
                db.execute("INSERT INTO projects(id,root,mode,created) VALUES(?,?,'experiment',?)", (project_id, str(path), time.time()))
        except Exception:
            # Preserve evidence rather than removing a path on a partially failed operation.
            raise
        if desktop and not desktop_project_id:
            desktop_project_id=self.rpc.call('project/create',{'idempotencyKey':'conversation-orchestrator:'+project_id,
                'name':name or project_id,'roots':[{'path':str(path)}],
                'metadata':{'purpose':'isolated-conversation-orchestrator-experiment'}})['project']['id']
        if desktop_project_id:return self.project_link(project_id,desktop_project_id)['registry_project']
        return self.registry.one('projects', 'id', project_id)

    def conversation_list(self, project_id=None, cursor=None, limit=25, archived=False):
        project_id=project_id or self.project_scope
        if project_id:
            self._project(project_id)
            return {'registered': self.registry.rows('SELECT * FROM conversations WHERE project_id=? AND archived=?', (project_id, int(archived)))}
        result = self.rpc.call('thread/list', dict(limit=limit, cursor=cursor,
            sourceKinds=SOURCES, archived=archived, useStateDbOnly=True))
        hidden={r['thread_id'] for r in self.registry.rows("SELECT c.thread_id FROM conversations c JOIN projects p ON p.id=c.project_id WHERE p.mode='production'")}
        result['data']=[r for r in result['data'] if r['id'] not in hidden]
        result['registry'] = self.registry.rows("SELECT c.* FROM conversations c JOIN projects p ON p.id=c.project_id WHERE c.archived=? AND p.mode='experiment'", (int(archived),))
        result['discovery'] = 'Database-only: does not repair unindexed legacy rollout files.'
        return result


    def _role_instructions(self,role,root,cwd,inherited=''):
        conversation_rule=('Coordinate regular persistent workers through the orchestrator tools. You are the technical director, not a developer or auditor; delegate implementation and independent auditing. Do not create unrelated conversations. '
            if role.lower()=='coordinator' else 'Do not create other conversations. ')
        return (inherited+f'\nAssigned role: {role}. Work only on the explicitly authorized project. '
            f'Authorized project root: {root}. Worker workspace: {cwd}. Modify only the worker workspace. '
            'Auditors may inspect artifacts in other registered workspaces of this same project. Do not access unrelated projects, spawn subagents, or contact people. '
            +conversation_rule+'Resolve routine technical choices within your assigned task; do not ask the human for repeated work/validation/Python permission. Refer ordinary uncertainty and environment failures to your coordinator. '
            f'The host Python interpreter is {sys.executable}; it may be inaccessible in a worker sandbox. '
            'Use the project runtime with -B. For stdlib-only diagnostics an accessible installed or bundled runtime may help; never silently substitute it for the project dependency/GPU runtime. Report the exact executable and failure so the coordinator can run runtime_check and repair supported access without a redundant human confirmation. '
            'State observed evidence and limitations. Auditor roles must not modify the implementation. '
            'For an ordinary blocking question use orchestrator_question if available. Otherwise end your turn with exactly ORCHESTRATOR_QUESTION_JSON followed by a newline and a JSON object with question (string), category (technical, requirement, creative or strategic), and sources (array of paths). Do not invent missing requirements. Never use this mechanism for security approvals, permissions, secrets or irreversible confirmations.')

    def conversation_create(self, project_id, name, role, create_key, capabilities=None,coordinator_thread_id=None,
                            workspace=None,model=None,effort=None,difficulty=None,justification=None):
        project = self._project(project_id)
        if project['mode']=='experiment' and not (pathlib.Path(project['root'])/'.conversation-orchestrator-experiment').is_file():
            raise BridgeError('SCOPE_LOST', 'Experiment marker is missing.')
        if project['mode']=='production' and role.lower() in ('coordinator','orchestrator'):
            raise BridgeError('ROLE_CONFLICT','Register the designated coordinator; workers cannot appoint another coordinator.')
        rpc = self.rpc  # Fail connection/auth checks before reserving a remote mutation.
        inputs={k:v for k,v in dict(coordinator_thread_id=coordinator_thread_id,workspace=workspace,model=model,effort=effort,
            difficulty=difficulty,justification=justification).items() if v is not None}
        digest = fingerprint([project_id, name, role, capabilities or []]+([inputs] if inputs else []))
        # Resolve and validate before reserving any remote mutation.
        cwd,desktop_id,coordinator=self._creation_context(project,coordinator_thread_id,workspace)
        route=self.model_route(difficulty or ('complex' if 'audit' in role.lower() else 'standard'),role,model,effort,justification)
        effective=self.rpc.call('config/read',{'cwd':cwd,'includeLayers':False})['config']
        inherited_instructions=effective.get('developer_instructions') or ''
        worker_config=integration_policy(effective,json.loads(self.project_policy['integrations']) if self.project_policy else ())
        worker_config.update({'model_reasoning_effort':route['effort'],'sandbox_workspace_write':{'network_access':False,'writable_roots':[cwd]}})
        params={
            'cwd': cwd, 'ephemeral': False, 'approvalPolicy': 'never',
            'sandbox': 'read-only' if any(r in role.lower() for r in ('audit','architect','review')) else 'workspace-write', 'modelProvider': 'openai',
            'model':route['model'],'config':worker_config,'allowProviderModelFallback':False,
            'serviceName': 'conversation_orchestrator',
            'developerInstructions':self._role_instructions(role,project['root'],cwd,inherited_instructions)}
        params['dynamicTools']=[QUESTION_TOOL]
        if desktop_id and not project.get('desktop_ui_project_id'):
            params['projectId']=desktop_id
        params['runtimeWorkspaceRoots']=[cwd]
        with self.registry.transaction() as db:
            old = db.execute('SELECT * FROM creations WHERE key=?', (create_key,)).fetchone()
            if old:
                if old['fingerprint'] != digest:
                    raise BridgeError('IDEMPOTENCY_CONFLICT', 'Creation key was used with different parameters.')
                if old['thread_id']:
                    return {'worker':dict(db.execute('SELECT * FROM conversations WHERE thread_id=?', (old['thread_id'],)).fetchone()),
                            'duplicate_prevented':True}
                raise BridgeError('CREATION_UNKNOWN', 'Prior thread creation outcome is uncertain; inspect conversation_list. It will not be repeated.')
            db.execute("INSERT INTO creations(key,fingerprint,state,thread_id,project_id,workspace) VALUES(?,?,'preparing',NULL,?,?)", (create_key, digest,project_id,cwd))
        result = rpc.call('thread/start', params)
        thread_id = result['thread']['id']; self.loaded.add(thread_id)
        with self.registry.transaction() as db:
            db.execute('INSERT INTO conversations(thread_id,project_id,role,name,capabilities,workspace,desktop_project_id,model,effort,routing_justification,desktop_sync_state) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (thread_id, project_id, role, name, json.dumps(capabilities or []),cwd,desktop_id,route['model'],route['effort'],json.dumps(route),
                 'pending' if project.get('desktop_ui_project_id') else 'headless' if project['mode']=='production' else 'legacy'))
            db.execute("UPDATE creations SET state='created',thread_id=? WHERE key=?", (thread_id, create_key))
            if role.lower()=='coordinator' and desktop_id:
                db.execute('UPDATE projects SET coordinator_thread_id=coalesce(coordinator_thread_id,?) WHERE id=?',(thread_id,project_id))
        # Persist identity before naming, so naming failure never loses ownership.
        self.rpc.call('thread/name/set', {'threadId': thread_id, 'name': name})
        if result['model']!=route['model'] or result.get('reasoningEffort')!=route['effort']:
            raise BridgeError('ROUTING_MISMATCH','Thread created, but App Server configuration differs from the explicit request.',
                {'thread_id':thread_id,'requested':route,'observed_model':result['model'],'observed_effort':result.get('reasoningEffort')})
        return {'worker': self.registry.one('conversations', 'thread_id', thread_id), 'thread': result['thread'],
            'routing':route,'observed_model':result['model'],'observed_effort':result.get('reasoningEffort'),
            'desktop_membership':{'status':'host_action_required' if project.get('desktop_ui_project_id') else 'not_ui_verified',
                'desktop_project_id':project.get('desktop_ui_project_id'),
                'next_step':'conversation_desktop_prepare, release the owning bridge, then supported native desktop operations and confirmation'},
            'instruction_sources':result.get('instructionSources',[]),'inherited_project_instructions':bool(inherited_instructions)}

    def conversation_read(self, thread_id, cursor=None, limit=25):
        identifier(thread_id)
        self.authorize_call('conversation_read',{'thread_id':thread_id})
        metadata = self.rpc.call('thread/read', {'threadId': thread_id, 'includeTurns': False})
        turns = self.rpc.call('thread/turns/list', {'threadId': thread_id, 'limit': limit,
            'cursor': cursor, 'itemsView': 'full', 'sortDirection': 'asc'})
        return {'thread': metadata['thread'], 'turns': turns}

    def conversation_items(self, thread_id, turn_id=None, cursor=None, limit=50):
        identifier(thread_id)
        self.authorize_call('conversation_items',{'thread_id':thread_id})
        params = {'threadId': thread_id, 'limit': limit, 'sortDirection': 'asc'}
        for key, value in [('turnId', turn_id), ('cursor', cursor)]:
            if value is not None:
                params[key] = value
        return self.rpc.call('thread/items/list', params)

    def conversation_resume(self, thread_id):
        worker, project = self._worker(thread_id)
        unresolved = self.registry.rows("SELECT * FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')", (thread_id,))
        if any(self._other_owner(row) for row in unresolved):
            raise BridgeError('CONVERSATION_OWNED', 'A different live bridge owns this turn. Read status or wait; do not resume it in another App Server.')
        # Resume is serialized locally so concurrent callers cannot double-load a thread.
        with self.resume_guard:
            rpc = self.rpc
            if thread_id not in self.loaded:
                cwd=worker.get('workspace') or project['root']
                effective=rpc.call('config/read',{'cwd':cwd,'includeLayers':False})['config']
                inherited=effective.get('developer_instructions') or ''
                worker_config=integration_policy(effective,json.loads(self.project_policy['integrations']) if self.project_policy else ())
                result = rpc.call('thread/resume', {'threadId': thread_id, 'excludeTurns': True,
                    'cwd':cwd, 'approvalPolicy': 'never',
                    'developerInstructions':self._role_instructions(worker['role'],project['root'],cwd,inherited),
                    'sandbox': 'read-only' if any(r in worker['role'].lower() for r in ('audit','architect','review')) else 'workspace-write', 'modelProvider': 'openai','config':worker_config})
                self.loaded.add(thread_id)
            else:
                result = rpc.call('thread/read', {'threadId': thread_id, 'includeTurns': False})
        return result

    def conversation_name(self, thread_id, name):
        self._worker(thread_id)
        self.rpc.call('thread/name/set', {'threadId': thread_id, 'name': name})
        with self.registry.connect() as db:
            db.execute('UPDATE conversations SET name=? WHERE thread_id=?', (name, thread_id))
        return self.registry.one('conversations', 'thread_id', thread_id)

    def conversation_role(self, thread_id, role, capabilities=None):
        worker,project=self._worker(thread_id)
        if project['mode']=='production' and (worker['role'].lower()=='coordinator' or role.lower() in ('coordinator','orchestrator')):
            raise BridgeError('ROLE_CONFLICT','Coordinator ownership requires an explicit local operator handoff.')
        if self.registry.rows("SELECT key FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')", (thread_id,)):
            raise BridgeError('CONVERSATION_BUSY', 'Cannot change role during an unresolved turn.')
        with self.registry.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(thread_id,)).fetchone():
                db.rollback();raise BridgeError('CONVERSATION_BUSY','A send began before the role change.')
            db.execute('UPDATE conversations SET role=?,capabilities=? WHERE thread_id=?', (role, json.dumps(capabilities or []), thread_id));db.commit()
        self.loaded.discard(thread_id)
        return {'worker': self.registry.one('conversations', 'thread_id', thread_id),
                'effect': 'Role saved. Sandbox and role instructions refresh before the next managed turn.'}

    def message_send(self, thread_id, message, message_key, task_id=None,model=None,effort=None,difficulty=None,justification=None,audit_task_id=None,audit_artifacts=None,handoff_key=None):
        worker, _ = self._worker(thread_id)
        if self.project_scope and worker['role'].lower()=='coordinator':
            raise BridgeError('COORDINATOR_PROTECTED','The coordinator directs workers; it is not a managed worker dispatch target.')
        if worker.get('desktop_sync_state')=='pending':
            raise BridgeError('DESKTOP_SYNC_REQUIRED','Finish and verify the native desktop project attachment before dispatching work to this new worker.')
        intent={k:v for k,v in dict(model=model,effort=effort,difficulty=difficulty,justification=justification).items() if v is not None}
        if audit_task_id:intent['audit_task_id']=audit_task_id
        if audit_artifacts:intent['audit_artifacts']=audit_artifacts
        existing=self.registry.rows('SELECT key FROM messages WHERE key=?',(message_key,))
        profiles=self.registry.rows('SELECT payload FROM worker_profiles WHERE thread_id=?',(thread_id,))
        if profiles and json.loads(profiles[0]['payload'])['status']=='retired':raise BridgeError('WORKER_RETIRED','Explicitly reactivate this worker context before sending new work.')
        if handoff_key:
            intent['handoff_key']=handoff_key
            message+=self._handoff_text(handoff_key,thread_id,verify=not existing)
        paths=[] if existing else self._planned_paths(task_id)
        audit_link=None if existing else self._audit_request(worker,audit_task_id,audit_artifacts)
        route=None if existing else self._message_route(worker,task_id,model,effort,difficulty,justification)
        self._clear_orphaned_operation(thread_id)
        row, fresh = self.registry.reserve_message(message_key, thread_id, message, task_id, self.instance,intent,audit_link,paths)
        if not fresh:
            return {'duplicate_prevented': True, **self.message_status(message_key)}
        self.registry.routing(message_key,{'selection':route,'intent':intent})
        dispatched = False
        try:
            state = self.conversation_resume(thread_id)['thread'].get('status', {})
            if state.get('type') == 'active':
                raise BridgeError('CONVERSATION_BUSY', 'Codex reports an already active turn; refusing to steer it.')
            marker = f'[orchestrator-message:{message_key}]'
            self.registry.mark_dispatching(message_key,self.instance)
            dispatched = True
            turn = self.rpc.call('turn/start', {'threadId': thread_id,
                'model':route['model'],'effort':route['effort'],
                'sandboxPolicy':({'type':'readOnly','networkAccess':False} if any(r in worker['role'].lower() for r in ('audit','architect','review')) else
                    {'type':'workspaceWrite','writableRoots':[worker.get('workspace') or self._project(worker['project_id'])['root']],
                     'networkAccess':False,'excludeTmpdirEnvVar':True,'excludeSlashTmp':True}),
                'clientUserMessageId': str(uuid.uuid5(uuid.NAMESPACE_URL, message_key)),
                'input': [{'type': 'text', 'text': f'{marker}\nAssigned registry role: {worker["role"]}\n{message}'}]})['turn']
            # Acknowledgment can precede turn/started, and persisted history can
            # temporarily label the not-yet-started turn interrupted. Own it immediately.
            with self.rpc.guard:
                if (thread_id, turn['id']) not in self.rpc.completed:
                    self.rpc.active.add((thread_id, turn['id']))
            self.registry.set_message(message_key, 'sent', turn['id'])
            metadata=self.rpc.call('thread/read',{'threadId':thread_id,'includeTurns':False})['thread']
            self.registry.routing(message_key,{'observed_thread_configuration':{'model':metadata.get('model'),
                'effort':metadata.get('reasoningEffort'),'cwd':metadata.get('cwd')},'configuration_observed_at':'after turn/start'})
            completed = self.rpc.completed.get((thread_id, turn['id']))
            if completed:
                self.registry.completed(thread_id, completed)
            return self.message_status(message_key, reconcile=False)
        except BridgeError as e:
            # Definitive local refusal can be retried only with a new key. Network/remote
            # errors remain ambiguous until history reconciliation proves the outcome.
            self.registry.set_message(message_key, 'unknown' if dispatched else 'failed', result={'error': e.as_dict(), 'turn_start_dispatched': dispatched})
            raise

    def _turn(self, thread_id, turn_id=None, marker=None):
        cursor = None
        matches=[]
        while True:
            page = self.rpc.call('thread/turns/list', {'threadId': thread_id, 'limit': 100,
                'cursor': cursor, 'itemsView': 'full', 'sortDirection': 'desc'})
            for turn in page['data']:
                if turn_id and turn['id'] == turn_id:
                    return turn
                if not turn_id and marker and any(item.get('type')=='userMessage' and any(part.get('type')=='text' and part.get('text','').startswith(marker+'\n') for part in item.get('content',[])) for item in turn['items']):
                    matches.append(turn)
            cursor = page.get('nextCursor')
            if not cursor:
                if len(matches)>1:raise BridgeError('HISTORY_AMBIGUOUS','Several persisted turns share this marker; no completion was inferred.')
                return matches[0] if matches else None

    def message_status(self, message_key, reconcile=True):
        row = self.registry.one('messages', 'key', message_key)
        worker=self.registry.one('conversations','thread_id',row['thread_id'])
        self._project(worker['project_id'])
        external_owner = row['state'] not in TERMINAL and self._other_owner(row)
        if external_owner:
            reconcile = False
        if reconcile and row['state'] in ('preparing','unknown') and row['stage']=='prepared' and row['owner_token'] != self.instance:
            self.registry.set_message(message_key,'failed',result={'error':{'code':'PREPARATION_INTERRUPTED',
                'message':'Previous bridge stopped before the durable dispatch boundary. No turn/start was sent.'}})
            row = self.registry.one('messages','key',message_key)
        if reconcile and row['state'] not in TERMINAL:
            self.conversation_resume(row['thread_id'])
            live = (row['thread_id'], row['turn_id']) in self.rpc.active
            turn = None if live else self._turn(row['thread_id'], row['turn_id'], f'[orchestrator-message:{message_key}]')
            if turn:
                self.registry.set_message(message_key, 'sent', turn['id'])
                if turn['status'] in TERMINAL:
                    self.registry.completed(row['thread_id'], turn)
            # Missing history after a crash is never proof that a send did not occur.
            row = self.registry.one('messages', 'key', message_key)
        result = json.loads(row['result']) if row['result'] else None
        if reconcile and row['state'] in TERMINAL and (not result or not result.get('items') or result.get('itemsView') != 'full'):
            hydrated = self._turn(row['thread_id'], row['turn_id']) if row['turn_id'] else None
            if hydrated and hydrated['status'] in TERMINAL:
                self.registry.set_message(message_key, row['state'], result=hydrated)
                result = hydrated
        if row['state']=='completed':self.registry.reconcile_questions(message_key)
        outputs = [item['text'] for item in (result or {}).get('items', []) if item.get('type') == 'agentMessage']
        task_state = None; task_verified = False
        if row['task_id']:
            task_state = self.registry.one('tasks','id',row['task_id'])['state']
            latest = self.registry.rows("SELECT key FROM messages WHERE task_id=? AND state='completed' ORDER BY created DESC LIMIT 1",(row['task_id'],))
            task_verified = task_state == 'accepted' and bool(latest) and latest[0]['key'] == message_key
        return {'message_key': message_key, 'thread_id': row['thread_id'], 'turn_id': row['turn_id'],
            'routing':json.loads(row['routing']) if row.get('routing') else None,
            'delivery_state': row['state'], 'turn': result, 'outputs': outputs,
            'owner_bridge_active': external_owner,
            'questions':self.registry.rows("SELECT key,mode,state,payload,task_id FROM questions WHERE message_key=? AND state IN ('pending','escalated','answering')",(message_key,)),
            'task_state': task_state, 'task_verified': task_verified, 'note': 'Turn completion does not imply task acceptance.'}

    def message_wait(self, message_key, timeout_seconds=30):
        row = self.registry.one('messages', 'key', message_key)
        result = self.message_status(message_key)
        if result['delivery_state'] in TERMINAL:
            return result
        if result.get('owner_bridge_active'):
            # Cross-process observers do not steal the subscription or repeatedly poll.
            self.stop_heartbeat.wait(timeout_seconds)
            result = self.message_status(message_key)
            return {**result, 'timed_out': result['delivery_state'] not in TERMINAL}
        if not result['turn_id']:
            return {**result, 'timed_out': False, 'requires_reconciliation': True}
        turn = self.rpc.wait(row['thread_id'], result['turn_id'], timeout_seconds)
        if turn:
            self.registry.completed(row['thread_id'], turn)
        # One reconciliation at the deadline catches missed notifications. No polling loop.
        return {**self.message_status(message_key), 'timed_out': turn is None}

    def turn_interrupt(self, message_key):
        row = self.registry.one('messages', 'key', message_key)
        self._worker(row['thread_id'])
        if row['state'] in TERMINAL:
            return self.message_status(message_key, reconcile=False)
        if not row['turn_id']:
            raise BridgeError('OUTCOME_UNKNOWN', 'Reconcile the message before interrupting a specific turn.')
        self.conversation_resume(row['thread_id'])
        self.rpc.call('turn/interrupt', {'threadId': row['thread_id'], 'turnId': row['turn_id']})
        return self.message_wait(message_key, 10)

    def conversation_archive(self, thread_id, reason=None):
        worker,project=self._worker(thread_id,allow_archived=True)
        if worker['role'].lower()=='coordinator':
            raise BridgeError('COORDINATOR_PROTECTED','The active project coordinator cannot archive itself.')
        if project['mode']=='production' and not reason:
            raise BridgeError('ARCHIVE_REASON_REQUIRED','Record the handoff/cleanup reason before archiving.')
        with self._exclusive_operation(thread_id,'archive'):
            if self.registry.rows("SELECT key FROM questions WHERE thread_id=? AND state IN ('pending','escalated','answering')",(thread_id,)):
                raise BridgeError('UNRESOLVED_QUESTIONS','Answer or explicitly resolve outstanding worker questions before archival.')
            if self._native_archive_state(thread_id):
                with self.registry.connect() as db:db.execute('UPDATE conversations SET archived=1 WHERE thread_id=?',(thread_id,))
                return {'thread_id':thread_id,'archived':True,'permanently_deleted':False,'duplicate_prevented':True}
            if self.registry.rows("SELECT id FROM tasks WHERE owner=? AND state NOT IN ('accepted','cancelled')",(thread_id,)):
                raise BridgeError('UNFINISHED_TASKS','Complete, hand off or explicitly cancel unfinished tasks first.')
            state=self.conversation_resume(thread_id)['thread'].get('status',{})
            if state.get('type')=='active':raise BridgeError('CONVERSATION_BUSY','An actual Codex turn is active.')
            self._operation_dispatch(thread_id)
            self.rpc.call('thread/archive',{'threadId':thread_id})
            with self.registry.transaction() as db:
                db.execute('UPDATE conversations SET archived=1 WHERE thread_id=?',(thread_id,))
                db.execute('INSERT INTO events(method,payload,created) VALUES(?,?,?)',('bridge/archive',json.dumps({'thread_id':thread_id,'project_id':project['id'],'reason':reason or 'Idle experimental cleanup'}),time.time()))
            self.loaded.discard(thread_id)
        return {'thread_id':thread_id,'archived':True,'permanently_deleted':False}

    def conversation_unarchive(self,thread_id):
        worker,_=self._worker(thread_id,allow_archived=True)
        with self._exclusive_operation(thread_id,'unarchive'):
            if not self._native_archive_state(thread_id):
                with self.registry.connect() as db:db.execute('UPDATE conversations SET archived=0 WHERE thread_id=?',(thread_id,))
                return {'thread_id':thread_id,'archived':False,'duplicate_prevented':True}
            self._operation_dispatch(thread_id)
            self.rpc.call('thread/unarchive',{'threadId':thread_id})
            with self.registry.connect() as db:db.execute('UPDATE conversations SET archived=0 WHERE thread_id=?',(thread_id,))
        return {'thread_id':thread_id,'archived':False,'history_preserved':True}

    def task_cancel(self,task_id,expected_revision,reason):
        task=self.registry.one('tasks','id',task_id);self._project(task['project_id'])
        with self.registry.transaction() as db:
            current=db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            if current['revision']!=expected_revision:raise BridgeError('REVISION_CONFLICT','Task revision changed.')
            if current['state'] in ('accepted','cancelled'):raise BridgeError('TASK_STATE','A terminal task cannot be cancelled again.')
            if db.execute("SELECT 1 FROM messages m LEFT JOIN audit_links a ON a.message_key=m.key WHERE (m.task_id=? OR a.task_id=?) AND m.state IN ('preparing','sent','unknown')",(task_id,task_id)).fetchone():
                raise BridgeError('OUTCOME_UNKNOWN','Resolve the pending delivery before cancelling.')
            db.execute("UPDATE tasks SET state='cancelled',evidence=?,revision=revision+1 WHERE id=?",(json.dumps({'cancellation_reason':reason,'previous_evidence':current['evidence']}),task_id))
            db.execute("UPDATE questions SET state='unavailable' WHERE (task_id=? OR message_key IN (SELECT message_key FROM audit_links WHERE task_id=?)) AND state IN ('pending','escalated','answering')",(task_id,task_id))
        return self.registry.one('tasks','id',task_id)

    def task_assign(self, project_id, task_id, owner, requirements, dependencies=None,model=None,effort=None,difficulty=None,justification=None,plan_key=None):
        worker, _ = self._worker(owner)
        if self.project_scope and worker['role'].lower()=='coordinator':
            raise BridgeError('COORDINATOR_PROTECTED','Assign delivery work to a developer, architect or other worker.')
        if worker['project_id'] != project_id:
            raise BridgeError('PROJECT_CONFLICT', 'Task owner belongs to a different experiment.')
        dependencies = dependencies or []
        if plan_key:
            planned=self._planned_task(plan_key,task_id)
            if (planned['owner'],planned['requirements'],planned['dependencies'])!=(owner,requirements,dependencies):raise BridgeError('PLAN_CONFLICT','Use the owner, exact requirements and dependencies returned by the current plan.')
        if any(v is not None for v in [model,effort,difficulty]):
            self.model_route(difficulty or 'standard',worker['role'],model or (None if difficulty else worker.get('model')),effort,justification)
        with self.registry.transaction() as db:
            old = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if old:
                if (old['project_id'],old['owner'],old['requirements'],old['dependencies']) != (project_id,owner,requirements,json.dumps(dependencies)):
                    raise BridgeError('OWNERSHIP_CONFLICT', 'Task ID already has an assignment. It cannot be silently reassigned.')
                if (old['model'],old['effort'],old['difficulty'],old['routing_justification'])!=(model,effort,difficulty,justification):
                    raise BridgeError('IDEMPOTENCY_CONFLICT','Existing task has different model-routing overrides.')
                if old['plan_key']!=plan_key:raise BridgeError('PLAN_CONFLICT','Existing task has another plan binding.')
                return dict(old)
            for dep in dependencies:
                row = db.execute('SELECT project_id FROM tasks WHERE id=?', (dep,)).fetchone()
                if not row or row['project_id'] != project_id:
                    raise BridgeError('INVALID_DEPENDENCY', 'Dependencies must already exist in the same project, preventing cycles.')
            db.execute('INSERT INTO tasks(id,project_id,owner,requirements,dependencies,model,effort,difficulty,routing_justification,plan_key) VALUES(?,?,?,?,?,?,?,?,?,?)',
                (task_id, project_id, owner, requirements, json.dumps(dependencies),model,effort,difficulty,justification,plan_key))
        return self.registry.one('tasks', 'id', task_id)

    def task_review(self, task_id, expected_revision, audit_message_key, verdict, evidence):
        self._planned_paths(task_id)
        self._project(self.registry.one('tasks','id',task_id)['project_id'])
        audit = self.registry.one('messages', 'key', audit_message_key)
        auditor = self.registry.one('conversations', 'thread_id', audit['thread_id'])
        if audit['state'] != 'completed':
            raise BridgeError('AUDIT_INCOMPLETE', 'Audit must have an actually completed turn.')
        with self.registry.transaction() as db:
            task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not task:
                raise BridgeError('NOT_FOUND', 'Task is not registered.')
            if task['revision'] != expected_revision:
                raise BridgeError('REVISION_CONFLICT', 'Task changed since it was read.')
            if task['state'] != 'needs_audit':
                raise BridgeError('TASK_STATE', 'Only completed work awaiting audit can be reviewed.')
            if auditor['project_id'] != task['project_id'] or auditor['thread_id'] == task['owner'] or 'audit' not in auditor['role'].lower():
                raise BridgeError('INDEPENDENT_AUDIT_REQUIRED', 'Use a different auditor conversation in the same project.')
            audit_turn = json.loads(audit['result'])
            replies=[i for i in audit_turn.get('items',[]) if i.get('type')=='agentMessage']
            finals=[i for i in replies if i.get('phase')=='final_answer']
            audit_text=(finals or replies)[-1].get('text','') if replies else ''
            actual_verdict = re.search(r'^\s*(?:\*\*)?(ACCEPT|REJECT)\b', audit_text.upper())
            if not actual_verdict or actual_verdict.group(1) != verdict.upper():
                raise BridgeError('VERDICT_EVIDENCE_MISMATCH', 'Requested verdict is absent from the actual auditor response.')
            self._validate_audit_link(dict(task),audit)
            state = 'accepted' if verdict == 'accept' else 'rejected'
            db.execute('UPDATE tasks SET state=?,audit_verdict=?,evidence=?,revision=revision+1 WHERE id=?',
                (state, verdict, json.dumps({'audit_message_key': audit_message_key, 'controller_evidence': evidence}), task_id))
            db.execute("UPDATE questions SET state='unavailable' WHERE message_key IN (SELECT message_key FROM audit_links WHERE task_id=?) AND state IN ('pending','escalated','answering')",(task_id,))
        return self.registry.one('tasks', 'id', task_id)

    def task_recover(self, task_id, expected_revision, reason):
        self._project(self.registry.one('tasks','id',task_id)['project_id'])
        with self.registry.transaction() as db:
            task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
            if not task:
                raise BridgeError('NOT_FOUND', 'Task is not registered.')
            if task['revision'] != expected_revision:
                raise BridgeError('REVISION_CONFLICT', 'Task revision changed.')
            if task['state'] != 'blocked':
                raise BridgeError('TASK_STATE', 'Only blocked tasks can be explicitly recovered.')
            active = db.execute("SELECT key FROM messages WHERE task_id=? AND state IN ('preparing','sent','unknown')", (task_id,)).fetchone()
            if active:
                raise BridgeError('OUTCOME_UNKNOWN', 'Reconcile pending messages before recovering task ownership.')
            db.execute("UPDATE tasks SET state='ready',evidence=?,revision=revision+1 WHERE id=?", (json.dumps({'recovery_reason':reason}),task_id))
        return self.registry.one('tasks', 'id', task_id)

    def project_note(self, project_id, kind, text):
        self._project(project_id)
        with self.registry.connect() as db:
            cursor = db.execute('INSERT INTO notes(project_id,kind,text,created) VALUES(?,?,?,?)', (project_id, kind, text, time.time()))
        return {'note_id': cursor.lastrowid}

    def project_status(self, project_id=None):
        project_id=project_id or self.project_scope
        if project_id:
            self._project(project_id)
        params = (project_id,) if project_id else ()
        where = ' WHERE project_id=?' if project_id else ''
        result={'activation': 'authorized_project' if self.project_scope else 'experiment_only', 'permanent_deletion': 'disabled',
            'projects': self.registry.rows('SELECT * FROM projects'+(' WHERE id=?' if project_id else ''), params),
            'workers': self.registry.rows('SELECT * FROM conversations'+where, params),
            'tasks': self.registry.rows('SELECT * FROM tasks'+where, params),
            'notes': self.registry.rows('SELECT * FROM notes'+where, params),
            'unresolved_messages': self.registry.rows("SELECT m.key,m.thread_id,m.state,m.turn_id FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE m.state IN ('preparing','sent','unknown')"+(' AND c.project_id=?' if project_id else ''), params)}
        if not project_id:
            visible={p['id'] for p in result['projects'] if p['mode']=='experiment'}
            result['projects']=[p for p in result['projects'] if p['id'] in visible]
            for key in ['workers','tasks','notes']:
                result[key]=[r for r in result[key] if r['project_id'] in visible]
            workers={w['thread_id'] for w in result['workers']}
            result['unresolved_messages']=[r for r in result['unresolved_messages'] if r['thread_id'] in workers]
        visible={p['id'] for p in result['projects']}
        result['coordination_records']=[r for r in self.registry.rows('SELECT key,project_id,kind,revision FROM coordination_records') if r['project_id'] in visible]
        return result


def _serialized_control(method):
    @functools.wraps(method)
    def guarded(self,*args,**kwargs):
        nested=getattr(self.control_context,'active',False)
        with self._control_operation(method.__name__):
            if not nested and method.__name__ not in ('conversation_lifecycle_reconcile','conversation_archive','conversation_unarchive','conversation_desktop_prepare'):
                arguments=inspect.signature(method).bind(self,*args,**kwargs).arguments
                thread_id=arguments.get('thread_id') or arguments.get('owner')
                if thread_id:self._clear_orphaned_operation(thread_id)
            return method(self,*args,**kwargs)
    return guarded


# The same transition fence applies to direct callers and the MCP boundary.
# Polling/completion handlers intentionally remain outside the control gate.
for _method in ('coordinator_register','bridge_release','project_create','project_link',
                'conversation_create','conversation_resume','conversation_name','conversation_role',
                'conversation_configure','conversation_desktop_prepare','conversation_desktop_confirm',
                'conversation_archive','conversation_unarchive','conversation_lifecycle_reconcile',
                'message_send','turn_interrupt','task_assign','task_review','task_recover','task_cancel','project_note','question_reply','question_escalate',
                'worker_context','context_handoff','plan_record','architecture_contract','audit_assess'):
    setattr(Service,_method,_serialized_control(getattr(Service,_method)))
