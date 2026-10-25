"""Project grants are created by the local operator, never by an MCP tool.

Scopes prevent accidental cross-project API use. This is a same-OS-user tool,
not a security boundary against a person who can edit its database or run shell.
"""
import json
import pathlib
import time
from .errors import BridgeError
from .projects import canonical, contained, path_key


def grant_project(registry, project_id, root, coordinator, desktop_ui_id=None,
                  desktop_project_id=None, headless=False, integrations=()):
    from .service import identifier
    identifier(coordinator)
    if '::' in project_id:raise BridgeError('INVALID_PROJECT_ID','Project IDs cannot contain the reserved :: separator.')
    root = canonical(root)
    path = pathlib.Path(root)
    if not path.is_dir() or path == path.parent or path_key(path) == path_key(pathlib.Path.home()):
        raise BridgeError('INVALID_WORKSPACE', 'Authorize a specific existing project directory.')
    if not headless and not desktop_ui_id:
        raise BridgeError('DESKTOP_PROJECT_REQUIRED', 'Supply the native desktop project ID, or explicitly select headless mode.')
    with registry.transaction() as db:
        if db.execute('SELECT 1 FROM control_lock').fetchone():
            raise BridgeError('PROJECT_BUSY','A control operation is in progress. Close a crashed bridge and reconcile it before changing grants.')
        if db.execute("SELECT 1 FROM creations WHERE state='preparing'").fetchone() or db.execute('SELECT 1 FROM operations').fetchone():
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
        prior = db.execute('SELECT * FROM authorizations WHERE project_id=?', (project_id,)).fetchone()
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
        if existing and (existing['desktop_ui_project_id']!=desktop_ui_id or prior and bool(prior['headless'])!=bool(headless)):
            db.execute("UPDATE conversations SET desktop_sync_state=?,desktop_evidence=NULL WHERE project_id=? AND lower(role)<>'coordinator'",('headless' if headless else 'pending',project_id))
    return registry.one('projects', 'id', project_id)


class AuthorizationOperations:
    def _project(self, project_id):
        project = self.registry.one('projects', 'id', project_id)
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
                project=self._project(project_id)
                if self.coordinator_identity!=coordinator_thread_id:
                    raise BridgeError('COORDINATOR_CONFLICT','Coordinator identity cannot change on this connection.')
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
                self._transport.close();self._transport=None;self.loaded.clear()
        return {'project': project, 'coordinator_thread_id': coordinator_thread_id,
                'connection_scope': project_id, 'authorization': 'local_operator_grant',
                'desktop_mode': 'headless' if grant[0]['headless'] else 'native_attachment_required'}

    def authorize_call(self, name, arguments):
        """Apply scope at the MCP boundary before any resource lookup or mutation."""
        if name in ('coordinator_register', 'model_list', 'model_route', 'bridge_release'):
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
