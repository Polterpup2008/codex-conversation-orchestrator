"""Project authority comes from the human, via native appointment or local grant.

Scopes prevent accidental cross-project API use. This is a same-OS-user tool,
not a security boundary against a person who can edit its database or run shell.
"""
import json
import os
import pathlib
import time
from .errors import BridgeError
from .projects import canonical, contained, path_key


def grant_project(registry, project_id, root, coordinator, desktop_ui_id=None,
                  desktop_project_id=None, headless=False, integrations=(), appointment=None,expected_state=None):
    from .service import identifier
    identifier(coordinator)
    if ':' in project_id:raise BridgeError('INVALID_PROJECT_ID','Project IDs cannot contain the reserved colon separator.')
    root = canonical(root)
    path = pathlib.Path(root)
    if not path.is_dir() or path == path.parent or path_key(path) == path_key(pathlib.Path.home()):
        raise BridgeError('INVALID_WORKSPACE', 'Authorize a specific existing project directory.')
    if not headless and not desktop_ui_id:
        raise BridgeError('DESKTOP_PROJECT_REQUIRED', 'Supply the native desktop project ID, or explicitly select headless mode.')
    with registry.transaction() as db:
        if expected_state is not None:
            authorization=db.execute('SELECT * FROM authorizations WHERE project_id=?',(project_id,)).fetchone()
            project=db.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
            current={'authorization':dict(authorization) if authorization else None,'project':dict(project) if project else None}
            if current!=expected_state:
                raise BridgeError('GRANT_CHANGED','The grant or project changed while options were being preserved. Reread the current settings before retrying this operator update.')
        from .artifacts import reserved_artifact_overlap
        if reserved_artifact_overlap(db,root):raise BridgeError('PROJECT_OVERLAP','A source root cannot overlap a reserved artifact directory.')
        if db.execute('SELECT 1 FROM control_lock').fetchone():
            raise BridgeError('PROJECT_BUSY','A control operation is in progress. Close a crashed bridge and reconcile it before changing grants.')
        if db.execute("SELECT 1 FROM creations WHERE state='preparing' AND (project_id=? OR project_id IS NULL)",(project_id,)).fetchone() or db.execute('SELECT 1 FROM operations o JOIN conversations c ON c.thread_id=o.thread_id WHERE c.project_id=?',(project_id,)).fetchone():
            raise BridgeError('OUTCOME_UNKNOWN','Resolve uncertain creations/lifecycle operations before changing grants.')
        rows = [dict(r) for r in db.execute('SELECT * FROM projects')]
        for row in rows:
            if row['id'] == project_id:
                if path_key(row['root']) != path_key(root):
                    raise BridgeError('PROJECT_CONFLICT', 'The project ID already has another root.')
                continue
            if contained(root, row['root']) or contained(row['root'], root):
                raise BridgeError('PROJECT_OVERLAP', 'Registered projects must have non-overlapping roots.')
        for worker in db.execute('SELECT project_id,workspace FROM conversations WHERE project_id<>? AND workspace IS NOT NULL',(project_id,)):
            if contained(root,worker['workspace']) or contained(worker['workspace'],root):
                raise BridgeError('PROJECT_OVERLAP','The root overlaps another project worker workspace.')
        for creation in db.execute("SELECT workspace FROM creations WHERE state='preparing' AND project_id<>? AND workspace IS NOT NULL",(project_id,)):
            if contained(root,creation['workspace']) or contained(creation['workspace'],root):
                raise BridgeError('PROJECT_OVERLAP','The root overlaps another project pending worker workspace.')
        prior = db.execute('SELECT * FROM authorizations WHERE project_id=?', (project_id,)).fetchone()
        if appointment and prior:
            # Recheck inside the same write transaction: operator provisioning or
            # revocation may have happened while native evidence was being read.
            if not prior['enabled']:
                raise BridgeError('AUTHORIZATION_REVOKED', 'A historical appointment cannot undo a revoked grant.')
            if prior['coordinator_thread_id'] != coordinator:
                raise BridgeError('COORDINATOR_CONFLICT', 'An appointment cannot replace another owner.')
            return next(row for row in rows if row['id'] == project_id)
        if prior and prior['enabled'] and prior['coordinator_thread_id'] != coordinator:
            raise BridgeError('COORDINATOR_CONFLICT', 'Revoke the old grant before an explicit coordinator handoff.')
        other = db.execute('SELECT project_id FROM authorizations WHERE coordinator_thread_id=? AND project_id<>? AND enabled=1',
                           (coordinator, project_id)).fetchone()
        if other:
            raise BridgeError('COORDINATOR_CONFLICT', 'One coordinator cannot own two authorized projects.')
        existing=next((r for r in rows if r['id']==project_id),None)
        if existing and desktop_project_id is None:desktop_project_id=existing['desktop_project_id']
        same=prior and prior['enabled'] and prior['coordinator_thread_id']==coordinator and bool(prior['headless'])==bool(headless) and sorted(json.loads(prior['integrations']))==sorted(set(integrations)) and existing['desktop_project_id']==desktop_project_id and existing['desktop_ui_project_id']==desktop_ui_id
        if same:return existing
        if db.execute("SELECT 1 FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE c.project_id=? AND m.state IN ('preparing','sent','unknown')",(project_id,)).fetchone():
            raise BridgeError('PROJECT_BUSY','Resolve pending deliveries before changing the project grant.')
        if prior and prior['coordinator_thread_id']!=coordinator:
            db.execute("UPDATE conversations SET role='Former Coordinator' WHERE thread_id=? AND project_id=?",(prior['coordinator_thread_id'],project_id))
        db.execute("INSERT INTO projects(id,root,mode,created,desktop_project_id,coordinator_thread_id,desktop_ui_project_id) VALUES(?,?,'production',?,?,?,?) ON CONFLICT(id) DO UPDATE SET mode='production',desktop_project_id=excluded.desktop_project_id,coordinator_thread_id=excluded.coordinator_thread_id,desktop_ui_project_id=excluded.desktop_ui_project_id",
                   (project_id, root, time.time(), desktop_project_id, coordinator, desktop_ui_id))
        db.execute('INSERT INTO authorizations(project_id,coordinator_thread_id,enabled,headless,integrations,created) VALUES(?,?,1,?,?,?) ON CONFLICT(project_id) DO UPDATE SET coordinator_thread_id=excluded.coordinator_thread_id,enabled=1,headless=excluded.headless,integrations=excluded.integrations,created=excluded.created',
                   (project_id, coordinator, int(headless), json.dumps(sorted(set(integrations))), time.time()))
        if appointment:
            db.execute("INSERT INTO notes(project_id,kind,text,created) VALUES(?,'decision',?,?)",
                       (project_id, json.dumps({'coordinator_appointment': appointment}), time.time()))
        if existing and (existing['desktop_ui_project_id']!=desktop_ui_id or prior and bool(prior['headless'])!=bool(headless)):
            db.execute("UPDATE conversations SET desktop_sync_state=?,desktop_evidence=NULL WHERE project_id=? AND lower(role)<>'coordinator'",('headless' if headless else 'pending',project_id))
    return registry.one('projects', 'id', project_id)


class AuthorizationOperations:
    def coordinator_activate(self, project_id, coordinator_thread_id, appointment_quote,
                             desktop_ui_project_id=None, desktop_project_id=None, headless=False):
        """Materialize an existing human appointment, without another user grant."""
        from .service import identifier
        from .appointment import appointment_proof, caller_proof
        identifier(coordinator_thread_id)
        if self.project_scope not in (None, project_id):
            raise BridgeError('PROJECT_ACCESS_DENIED', 'A connection cannot switch projects.')
        caller = os.environ.get('CODEX_THREAD_ID')
        if caller and caller != coordinator_thread_id:
            raise BridgeError('COORDINATOR_CONFLICT', 'Activate only the conversation calling this tool.')
        workers = self.registry.rows('SELECT role FROM conversations WHERE thread_id=?', (coordinator_thread_id,))
        if workers and workers[0]['role'].lower() != 'coordinator':
            raise BridgeError('ROLE_CONFLICT', 'A managed worker cannot appoint itself coordinator.')
        prior = self.registry.rows('SELECT * FROM authorizations WHERE project_id=?', (project_id,))
        if prior and not prior[0]['enabled']:
            raise BridgeError('AUTHORIZATION_REVOKED', 'This project was explicitly revoked. A historical appointment cannot undo revocation; use the deliberate operator handoff.')
        thread = self.rpc.call('thread/read', {'threadId': coordinator_thread_id, 'includeTurns': False})['thread']
        identity = {'source': 'host_environment'} if caller else caller_proof(thread, self.caller_challenge)
        proof = appointment_proof(thread, appointment_quote)
        if desktop_project_id:
            native = self.rpc.call('project/read', {'projectId': desktop_project_id})['project']
            if not any(path_key(r['path']) == path_key(thread['cwd']) for r in native['roots']):
                raise BridgeError('PROJECT_CONFLICT', 'The App Server project does not contain this primary root.')
        if prior:
            existing = self.registry.one('projects', 'id', project_id)
            if prior[0]['coordinator_thread_id'] != coordinator_thread_id or path_key(existing['root']) != path_key(thread['cwd']):
                raise BridgeError('COORDINATOR_CONFLICT', 'An appointment cannot replace another project owner.')
            # Resume existing permissions; an activation retry must not reset integrations/UI.
        else:
            grant_project(self.registry, project_id, thread['cwd'], coordinator_thread_id,
                          desktop_ui_project_id, desktop_project_id, headless, appointment=proof)
        result = self.coordinator_register(project_id, coordinator_thread_id)
        return {**result, 'authorization': 'verified_human_appointment', 'appointment': proof,
                'caller_identity': identity,
                'additional_human_confirmation_required': False}

    def _project(self, project_id):
        project = self.registry.one('projects', 'id', project_id)
        if os.path.normcase(os.path.abspath(project['root']))!=os.path.normcase(canonical(project['root'])):
            raise BridgeError('SCOPE_LOST','The authorized root now resolves elsewhere; local operator review is required.')
        scope = getattr(self, 'project_scope', None)
        if scope and scope != project_id:
            raise BridgeError('PROJECT_ACCESS_DENIED', 'This MCP connection is bound to a different project.')
        if project['mode'] == 'production':
            grants = self.registry.rows('SELECT * FROM authorizations WHERE project_id=? AND enabled=1', (project_id,))
            if scope != project_id or not grants or grants[0]['coordinator_thread_id']!=getattr(self,'coordinator_identity',None) or grants[0]['created']!=self.project_policy['created']:
                raise BridgeError('PROJECT_NOT_AUTHORIZED', 'An active local grant and coordinator registration are required.')
            leases=self.registry.rows('SELECT owner_token FROM coordinator_leases WHERE project_id=?',(project_id,))
            if not leases or leases[0]['owner_token']!=self.instance:
                raise BridgeError('COORDINATOR_CONFLICT','This connection no longer holds the project coordinator lease.')
        return project

    def coordinator_register(self, project_id, coordinator_thread_id):
        if getattr(self, 'project_scope', None) not in (None, project_id):
            raise BridgeError('PROJECT_ACCESS_DENIED', 'An MCP connection cannot switch projects.')
        with self.binding_guard:
            if getattr(self,'project_scope',None) not in (None,project_id):
                raise BridgeError('PROJECT_ACCESS_DENIED','An MCP connection cannot switch projects.')
            if self.project_scope==project_id:
                if self.coordinator_identity!=coordinator_thread_id:
                    raise BridgeError('COORDINATOR_CONFLICT','Coordinator identity cannot change on this connection.')
                grants=self.registry.rows('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,))
                if not grants or grants[0]['coordinator_thread_id']!=coordinator_thread_id:
                    raise BridgeError('PROJECT_NOT_AUTHORIZED','The original enabled coordinator grant is required; re-registration cannot undo revocation or change owner.')
                if grants[0]['created']!=self.project_policy['created']:
                    return self._refresh_registration(project_id,coordinator_thread_id,grants[0])
                project=self._project(project_id)
                return {'project':project,'coordinator_thread_id':coordinator_thread_id,'connection_scope':project_id,'duplicate_prevented':True}
            project = self.registry.one('projects', 'id', project_id)
            grant = self.registry.rows('SELECT * FROM authorizations WHERE project_id=? AND enabled=1', (project_id,))
            if not grant or grant[0]['coordinator_thread_id'] != coordinator_thread_id:
                raise BridgeError('PROJECT_NOT_AUTHORIZED', 'The local operator must authorize this exact project/coordinator first.')
            thread = self.rpc.call('thread/read', {'threadId': coordinator_thread_id, 'includeTurns': False})['thread']
            if path_key(thread['cwd']) != path_key(project['root']):
                raise BridgeError('PROJECT_CONFLICT', 'The coordinator cwd must equal the granted primary root.')
            if self.registry.rows('SELECT * FROM conversations WHERE thread_id=? AND project_id<>?', (coordinator_thread_id, project_id)):
                raise BridgeError('COORDINATOR_CONFLICT', 'The conversation already belongs to another project.')
            with self.registry.transaction() as db:
                lease=db.execute('SELECT owner_token FROM coordinator_leases WHERE project_id=?',(project_id,)).fetchone()
                if lease and lease['owner_token']!=self.instance and self._other_owner(dict(lease)):
                    raise BridgeError('COORDINATOR_CONFLICT','A different live MCP connection already coordinates this project. Close it before handoff.')
                db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities,workspace,desktop_sync_state) VALUES(?,?,'Coordinator',?,'[]',?,'coordinator') ON CONFLICT(thread_id) DO NOTHING",
                           (coordinator_thread_id, project_id, thread.get('name') or 'Project Coordinator', project['root']))
                worker = db.execute('SELECT role FROM conversations WHERE thread_id=?', (coordinator_thread_id,)).fetchone()
                if worker['role'].lower() != 'coordinator':
                    raise BridgeError('ROLE_CONFLICT', 'A worker cannot silently become the coordinator.')
                db.execute('INSERT INTO coordinator_leases VALUES(?,?) ON CONFLICT(project_id) DO UPDATE SET owner_token=excluded.owner_token',(project_id,self.instance))
            self.project_scope = project_id
            self.coordinator_identity = coordinator_thread_id
            self.project_policy = dict(grant[0])
            # Reconnect in the granted root so project configuration is discovered
            # before applying the explicit integration policy to worker sessions.
            if self._transport:
                self._transport.close();self._transport=None;self.loaded.clear();self.loaded_artifacts.clear()
        return {'project': project, 'coordinator_thread_id': coordinator_thread_id,
                'connection_scope': project_id, 'authorization': 'local_operator_grant',
                'desktop_mode': 'headless' if grant[0]['headless'] else 'native_attachment_required'}

    def _refresh_registration(self,project_id,coordinator,grant):
        """Reuse an already designated owner after an operator policy change."""
        project=self.registry.one('projects','id',project_id)
        if os.path.normcase(os.path.abspath(project['root']))!=path_key(project['root']):
            raise BridgeError('SCOPE_LOST','The original project root resolves elsewhere.')
        with self.registry.transaction() as db:
            lease=db.execute('SELECT owner_token FROM coordinator_leases WHERE project_id=?',(project_id,)).fetchone()
            role=db.execute('SELECT project_id,role FROM conversations WHERE thread_id=?',(coordinator,)).fetchone()
            if not lease or lease['owner_token']!=self.instance or not role or role['project_id']!=project_id or role['role'].lower()!='coordinator':
                raise BridgeError('COORDINATOR_CONFLICT','Only the same registered coordinator with its existing lease can refresh policy.')
            if db.execute("SELECT 1 FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE c.project_id=? AND m.state IN ('preparing','sent','unknown')",(project_id,)).fetchone() or db.execute('SELECT 1 FROM operations o JOIN conversations c ON c.thread_id=o.thread_id WHERE c.project_id=?',(project_id,)).fetchone() or db.execute("SELECT 1 FROM creations WHERE state='preparing' AND (project_id=? OR project_id IS NULL)",(project_id,)).fetchone():
                raise BridgeError('PROJECT_BUSY','Reconcile this project sends and lifecycle operations before refreshing its existing policy.')
        # Metadata verification uses a separate transport with default denied
        # integrations. Stale project policy must not prevent this read or be
        # used for worker execution during validation.
        verifier=self.transport_factory(self.data_dir/'logs')
        try:thread=verifier.call('thread/read',{'threadId':coordinator,'includeTurns':False})['thread']
        finally:verifier.close()
        if path_key(thread['cwd'])!=path_key(project['root']):
            raise BridgeError('PROJECT_CONFLICT','The original coordinator moved away from the granted source root.')
        self.bridge_release()
        with self.registry.transaction() as db:
            current=db.execute('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,)).fetchone()
            lease=db.execute('SELECT owner_token FROM coordinator_leases WHERE project_id=?',(project_id,)).fetchone()
            if not current or dict(current)!=grant or current['coordinator_thread_id']!=coordinator or not lease or lease['owner_token']!=self.instance:
                raise BridgeError('COORDINATOR_CONFLICT','The original grant or lease changed during policy refresh.')
            self.project_policy=dict(current)
        return {'project':project,'coordinator_thread_id':coordinator,'connection_scope':project_id,'policy_refreshed':True,
                'additional_human_confirmation_required':False,'restart_required':False,'note':'Existing authorization refreshed; the next worker operation reconnects with its current integration policy. IDs, history and other project grants are unchanged.'}

    def authorize_call(self, name, arguments):
        """Apply scope at the MCP boundary before any resource lookup or mutation."""
        if name in ('coordinator_register', 'coordinator_activate', 'model_list', 'model_route', 'bridge_release','bridge_status'):
            return
        scope = getattr(self, 'project_scope', None)
        if name == 'project_create':
            if scope:
                raise BridgeError('PROJECT_ACCESS_DENIED', 'A registered coordinator cannot create another project.')
            return
        if name in ('project_discover', 'desktop_project_list'):
            if scope and name == 'project_discover':
                project = self._project(scope)
                if arguments.get('coordinator_thread_id') not in (None, project['coordinator_thread_id']):
                    raise BridgeError('PROJECT_ACCESS_DENIED', 'Discover only this project coordinator.')
                arguments.setdefault('coordinator_thread_id', project['coordinator_thread_id'])
            return
        if name in ('project_status', 'conversation_list') and not arguments.get('project_id'):
            if scope:
                arguments['project_id'] = scope
            return
        if arguments.get('project_id'):
            self._project(arguments['project_id'])
        for key in ('thread_id', 'owner'):
            if arguments.get(key):
                workers = self.registry.rows('SELECT project_id FROM conversations WHERE thread_id=?', (arguments[key],))
                if workers:
                    self._project(workers[0]['project_id'])
                elif scope:
                    raise BridgeError('PROJECT_ACCESS_DENIED', 'The conversation is not registered in this project.')
        for key in ('message_key', 'audit_message_key'):
            if arguments.get(key):
                rows = self.registry.rows('SELECT c.project_id FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE m.key=?', (arguments[key],))
                if rows:
                    self._project(rows[0]['project_id'])
        for key in ('task_id', 'audit_task_id'):
            if arguments.get(key):
                rows = self.registry.rows('SELECT project_id FROM tasks WHERE id=?', (arguments[key],))
                if rows:
                    self._project(rows[0]['project_id'])
        if arguments.get('question_key'):
            rows=self.registry.rows('SELECT project_id FROM questions WHERE key=?',(arguments['question_key'],))
            if rows:self._project(rows[0]['project_id'])
        for key in ('plan_key','contract_key','handoff_key','assessment_key','record_key'):
            if arguments.get(key):
                rows=self.registry.rows('SELECT project_id FROM coordination_records WHERE key=?',(arguments[key],))
                if rows:self._project(rows[0]['project_id'])
