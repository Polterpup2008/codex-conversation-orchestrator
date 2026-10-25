"""Authoritative local-project discovery; canonical paths and verified worktrees."""
import os
import pathlib
import subprocess
import json
from .errors import BridgeError


def canonical(path):
    value=os.fspath(path)
    if os.name=='nt':
        if value.startswith('\\\\?\\UNC\\'): value='\\\\'+value[8:]
        elif value.startswith('\\\\?\\'): value=value[4:]
    p=pathlib.Path(value)
    if not p.is_absolute():
        raise BridgeError('INVALID_WORKSPACE','Workspace paths must be absolute; the plugin directory is never a fallback.')
    return str(p.resolve())


def path_key(path):
    return os.path.normcase(canonical(path))


def contained(path,root):
    try: return os.path.commonpath([path_key(path),path_key(root)])==path_key(root)
    except ValueError:return False


def common_git_dir(path):
    result=subprocess.run(['git','-C',canonical(path),'rev-parse','--path-format=absolute','--git-common-dir'],
        capture_output=True,text=True)
    if result.returncode:
        return None
    return path_key(result.stdout.strip())


def allowed_workspace(root,workspace):
    root=canonical(root);workspace=canonical(workspace)
    if not pathlib.Path(workspace).is_dir():
        raise BridgeError('INVALID_WORKSPACE','Worker workspace does not exist.')
    if contained(workspace,root):return workspace
    main_git=common_git_dir(root)
    if main_git and main_git==common_git_dir(workspace):return workspace
    raise BridgeError('UNRELATED_WORKSPACE','Worker workspace is outside the project and is not a verified worktree of it.')


class ProjectOperations:
    def _workspace_exclusive(self,project_id,cwd):
        associations=self.registry.rows('SELECT id AS project_id,root AS workspace FROM projects WHERE id<>? UNION ALL SELECT project_id,workspace FROM conversations WHERE project_id<>? AND workspace IS NOT NULL UNION ALL SELECT project_id,workspace FROM creations WHERE project_id<>? AND workspace IS NOT NULL AND state=\'preparing\'',(project_id,project_id,project_id))
        for other in associations:
            if contained(cwd,other['workspace']) or contained(other['workspace'],cwd):
                raise BridgeError('PROJECT_OVERLAP','The workspace overlaps another project root or registered worker workspace.')

    def desktop_project_list(self):
        data=[];cursor=None
        while True:
            result=self.rpc.call('project/list',{'limit':100,'cursor':cursor})
            data.extend(result['data']);cursor=result.get('nextCursor')
            if not cursor:
                if self.project_scope:
                    root=self._project(self.project_scope)['root']
                    data=[p for p in data if any(path_key(r['path'])==path_key(root) for r in p['roots'])]
                return {'projects':data,'kind':'local_codex','experimental_api':True,
                'desktop_registration_note':'App Server projects and desktop saved-folder IDs may differ. Confirm UI membership separately.'}

    def project_discover(self,coordinator_thread_id=None):
        from .service import identifier
        tid=coordinator_thread_id or os.environ.get('CODEX_THREAD_ID')
        if not tid:raise BridgeError('COORDINATOR_REQUIRED','Provide the genuine coordinator thread ID; no cwd/plugin-root guessing is allowed.')
        identifier(tid)
        thread=self.rpc.call('thread/read',{'threadId':tid,'includeTurns':False})['thread']
        cwd=canonical(thread['cwd'])
        if self.project_scope:
            local=self._project(self.project_scope)
            if tid!=local['coordinator_thread_id'] or path_key(cwd)!=path_key(local['root']):
                raise BridgeError('PROJECT_CONFLICT','Coordinator identity or cwd differs from the local grant.')
            return {'coordinator_thread_id':tid,'desktop_project_id':local['desktop_project_id'],
                'desktop_ui_project_id':local['desktop_ui_project_id'],'primary_root':local['root'],'coordinator_cwd':cwd,
                'basis':'explicit local operator grant and actual coordinator metadata','kind':'local_codex'}
        registered=self.registry.rows('SELECT * FROM projects WHERE coordinator_thread_id=? AND desktop_project_id IS NOT NULL',(tid,))
        if thread.get('projectId'):
            project=self.rpc.call('project/read',{'projectId':thread['projectId']})['project'];basis='thread.projectId'
        elif len(registered)==1:
            project=self.rpc.call('project/read',{'projectId':registered[0]['desktop_project_id']})['project']
            basis='durable_coordinator_binding; desktop and App Server identities are separate'
        else:
            matches=[p for p in self.desktop_project_list()['projects'] if any(contained(cwd,r['path']) for r in p['roots'])]
            if len(matches)!=1:
                raise BridgeError('PROJECT_AMBIGUOUS','Coordinator has no explicit project and its roots do not identify one unique local project.',
                    {'coordinator_id':tid,'cwd':cwd,'candidate_project_ids':[p['id'] for p in matches]})
            project=matches[0];basis='unique_registered_root'
        matches=[canonical(r['path']) for r in project['roots'] if contained(cwd,r['path'])]
        if len(matches)==1:root=matches[0]
        elif len(project['roots'])==1 and common_git_dir(cwd)==common_git_dir(project['roots'][0]['path']) and common_git_dir(cwd):
            root=canonical(project['roots'][0]['path'])
        else:raise BridgeError('PRIMARY_ROOT_AMBIGUOUS','Cannot identify the coordinator primary project root reliably.')
        return {'coordinator_thread_id':tid,'desktop_project_id':project['id'],'project':project,
            'primary_root':root,'coordinator_cwd':cwd,'basis':basis,'kind':'local_codex'}

    def conversation_desktop_prepare(self,thread_id):
        worker,project=self._worker(thread_id)
        if self.registry.rows("SELECT key FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(thread_id,)):
            raise BridgeError('CONVERSATION_BUSY','Finish the active turn before synchronizing desktop membership.')
        ui_id=project.get('desktop_ui_project_id')
        if not ui_id:raise BridgeError('DESKTOP_PROJECT_REQUIRED','Bind the actual desktop saved-project ID first.')
        # The current desktop cannot safely move a thread whose canonical server
        # project ID is unknown to its legacy sidebar registry. Clear only this
        # registered experimental thread's canonical assignment, preserving its
        # durable parent association in our registry and its complete history.
        with self._exclusive_operation(thread_id,'desktop_prepare'):
            self._operation_dispatch(thread_id)
            self.rpc.call('thread/metadata/update',{'threadId':thread_id,'projectId':''})
            with self.registry.connect() as db:
                db.execute("UPDATE conversations SET desktop_sync_state='pending',desktop_evidence=NULL WHERE thread_id=?",(thread_id,))
        return {'thread_id':thread_id,'desktop_project_id':ui_id,'status':'host_action_required',
            'required_operations':[
                {'tool':'move_thread_to_project','arguments':{'threadId':thread_id,'projectId':ui_id,'hostId':'local'}},
                {'tool':'list_threads','arguments':{}}],
            'metadata_hydration_if_missing':[
                {'tool':'move_thread_to_sidebar_section','arguments':{'threadId':thread_id,'sectionId':'pinned','source':'codex','hostId':'local'}},
                {'tool':'move_thread_to_project','arguments':{'threadId':thread_id,'projectId':ui_id,'hostId':'local'}},
                {'tool':'move_thread_to_sidebar_section','arguments':{'threadId':thread_id,'sectionId':None,'source':'codex','hostId':'local'}}],
            'note':'Release the owning bridge first. If the native move cannot locate a new worker, record its prior pin state, temporarily pin to hydrate metadata, move to the expected project, then restore that prior pin state. The unpin step shown assumes a newly created unpinned worker. Verify actual UI grouping. Avoid opening the worker: a desktop writer can block the independent bridge. Do not replace IDs or automatically archive/unarchive. Host tools are required; this server cannot call them itself.'}

    def conversation_desktop_confirm(self,thread_id,observed_project_id,evidence):
        worker,project=self._worker(thread_id)
        if not project.get('desktop_ui_project_id') or observed_project_id!=project['desktop_ui_project_id']:
            raise BridgeError('PROJECT_CONFLICT','Observed desktop membership differs from the parent project.')
        if worker.get('desktop_sync_state')!='pending':
            raise BridgeError('DESKTOP_SYNC_STATE','Prepare the native desktop association before confirming it.')
        with self.registry.connect() as db:
            db.execute("UPDATE conversations SET desktop_sync_state='confirmed',desktop_evidence=? WHERE thread_id=?",
                (json.dumps({'observed_project_id':observed_project_id,'coordinator_evidence':evidence}),thread_id))
        return {'worker':self.registry.one('conversations','thread_id',thread_id),
            'verification_source':'coordinator-recorded native desktop observation, not an independent App Server UI assertion'}

    def project_link(self,project_id,desktop_project_id=None,coordinator_thread_id=None,desktop_ui_project_id=None):
        local=self._project(project_id)
        if local['mode']=='production':
            if coordinator_thread_id not in (None,local['coordinator_thread_id']) or desktop_ui_project_id not in (None,local['desktop_ui_project_id']):
                raise BridgeError('PROJECT_ACCESS_DENIED','Changing granted coordinator/native identities requires the local operator.')
        if coordinator_thread_id:
            discovery=self.project_discover(coordinator_thread_id)
            if desktop_project_id and discovery.get('desktop_project_id') and desktop_project_id!=discovery['desktop_project_id']:
                raise BridgeError('PROJECT_CONFLICT','Explicit project disagrees with the coordinator project.')
            desktop_project_id=desktop_project_id or discovery['desktop_project_id']
        if not desktop_project_id:
            raise BridgeError('PROJECT_REQUIRED','Supply a verified local App Server project ID or coordinator ID.')
        project=self.rpc.call('project/read',{'projectId':desktop_project_id})['project']
        if not any(path_key(r['path'])==path_key(local['root']) for r in project['roots']):
            raise BridgeError('PROJECT_CONFLICT','The local Codex project primary root does not match the isolated registry workspace.')
        if local.get('desktop_project_id') and local['desktop_project_id']!=desktop_project_id:
            raise BridgeError('PROJECT_CONFLICT','An experiment cannot silently switch its bound parent project.')
        with self.registry.transaction() as db:
            changed_ui=desktop_ui_project_id and desktop_ui_project_id!=local.get('desktop_ui_project_id')
            if changed_ui:
                if db.execute("SELECT 1 FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE c.project_id=? AND m.state IN ('preparing','sent','unknown')",(project_id,)).fetchone():
                    raise BridgeError('PROJECT_BUSY','Resolve messages before changing native project identity.')
                db.execute("UPDATE conversations SET desktop_sync_state='pending',desktop_evidence=NULL WHERE project_id=? AND desktop_sync_state='confirmed'",(project_id,))
            db.execute('UPDATE projects SET desktop_project_id=?,coordinator_thread_id=coalesce(?,coordinator_thread_id),desktop_ui_project_id=coalesce(?,desktop_ui_project_id) WHERE id=?',
                (desktop_project_id,coordinator_thread_id,desktop_ui_project_id,project_id))
        return {'registry_project':self.registry.one('projects','id',project_id),'local_codex_project':project,
            'ui_verified':False,'note':'Association recorded. UI membership requires a separate observed desktop check.'}

    def _creation_context(self,project,coordinator_thread_id=None,workspace=None):
        coordinator_thread_id=coordinator_thread_id or project.get('coordinator_thread_id')
        desktop_id=project.get('desktop_project_id')
        default_cwd=project['root']
        if coordinator_thread_id:
            if project['mode']=='production':
                thread=self.rpc.call('thread/read',{'threadId':coordinator_thread_id,'includeTurns':False})['thread']
                if path_key(thread['cwd'])!=path_key(project['root']):
                    raise BridgeError('PROJECT_CONFLICT','Coordinator moved outside its granted primary root.')
                default_cwd=thread['cwd']
            else:
                found=self.project_discover(coordinator_thread_id)
                if not desktop_id or desktop_id!=found['desktop_project_id'] or path_key(project['root'])!=path_key(found['primary_root']):
                    raise BridgeError('PROJECT_CONFLICT','Bind this experiment to its coordinator project before creating workers.')
                default_cwd=found['coordinator_cwd']
        cwd=allowed_workspace(project['root'],workspace or default_cwd)
        self._workspace_exclusive(project['id'],cwd)
        return cwd,desktop_id,coordinator_thread_id
