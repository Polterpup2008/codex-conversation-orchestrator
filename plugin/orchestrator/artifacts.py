"""Operator-authorized external artifact directories, separate from source roots."""
import json
import os
import pathlib
import time
from .errors import BridgeError
from .projects import canonical, contained, path_key


def lexical_root(value):
    value=os.fspath(value)
    if os.name=='nt' and value.startswith('\\\\?\\'):value=value[4:]
    path=pathlib.Path(value)
    if not path.is_absolute() or '..' in path.parts or (os.name=='nt' and value.startswith('\\\\')):
        raise BridgeError('INVALID_ARTIFACT_ROOT','Use an absolute local directory without parent traversal.')
    return pathlib.Path(os.path.abspath(path))


def checked_root(value, missing_leaf=False):
    path=lexical_root(value)
    for item in [path,*path.parents]:
        try:info=item.lstat()
        except FileNotFoundError:
            if item==path and missing_leaf:continue
            raise BridgeError('INVALID_ARTIFACT_ROOT','The directory and its parent must exist.')
        except OSError as exc:
            raise BridgeError('INVALID_ARTIFACT_ROOT','Cannot inspect the artifact path safely.',{'reason':str(exc)}) from exc
        if item.is_symlink() or getattr(info,'st_file_attributes',0)&0x400:
            raise BridgeError('ARTIFACT_ROOT_REDIRECTED','Artifact roots cannot follow symlinks, junctions or reparse points.')
    if os.path.normcase(str(path))!=path_key(path):
        raise BridgeError('ARTIFACT_ROOT_REDIRECTED','The artifact path resolves elsewhere.')
    if path.exists() and not path.is_dir():
        raise BridgeError('INVALID_ARTIFACT_ROOT','The artifact root must be a directory.')
    return path


def overlaps(left,right):
    return contained(left,right) or contained(right,left)


def directory_identity(path):
    info=path.stat()
    return json.dumps([info.st_dev,info.st_ino])


def reserved_artifact_overlap(db,path):
    return any(overlaps(path,row['root']) for row in db.execute('SELECT root FROM artifact_roots WHERE enabled=1'))


def artifact_root_grant(registry,project_id,root,reason,create=False,enabled=True):
    """Trusted local operator action, never exposed as a worker/MCP self-grant."""
    if not isinstance(reason,str) or not reason.strip() or len(reason)>4000:
        raise BridgeError('ARTIFACT_REASON_REQUIRED','Record the existing human-approved artifact-location authority.')
    raw=lexical_root(root)
    with registry.transaction() as db:
        grant=db.execute('SELECT * FROM authorizations WHERE project_id=?',(project_id,)).fetchone()
        project=db.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        if not grant or not project or project['mode']!='production' or (enabled and not grant['enabled']):
            raise BridgeError('PROJECT_NOT_AUTHORIZED','An enabled existing production project is required.')
        if enabled and os.path.normcase(os.path.abspath(project['root']))!=path_key(project['root']):
            raise BridgeError('SCOPE_LOST','The source root now resolves elsewhere; preserve the original grant.')
        prior=next((dict(x) for x in db.execute('SELECT * FROM artifact_roots WHERE project_id=?',(project_id,))
                    if os.path.normcase(str(raw))==os.path.normcase(x['root'])),None)
        if not enabled and not prior:raise BridgeError('NOT_FOUND','This exact artifact directory has no grant.')
        raw=pathlib.Path(prior['root']) if prior else raw
        path=checked_root(raw,missing_leaf=create) if enabled else raw
        identity=directory_identity(path) if enabled and path.exists() else None
        if prior and bool(prior['enabled'])==enabled:
            if enabled and identity!=prior['identity']:raise BridgeError('SCOPE_LOST','The artifact directory identity changed.')
            return prior
        if db.execute('SELECT 1 FROM control_lock').fetchone() or db.execute('SELECT 1 FROM operations o JOIN conversations c ON c.thread_id=o.thread_id WHERE c.project_id=?',(project_id,)).fetchone() or db.execute("SELECT 1 FROM creations WHERE state='preparing' AND (project_id=? OR project_id IS NULL)",(project_id,)).fetchone():
            raise BridgeError('PROJECT_BUSY','Resolve control operations before changing artifact grants.')
        if db.execute("SELECT 1 FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE c.project_id=? AND m.state IN ('preparing','sent','unknown')",(project_id,)).fetchone():
            raise BridgeError('PROJECT_BUSY','Resolve this project sends before changing artifact grants.')
        if enabled:
            home=pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))
            if path==path.parent or overlaps(path,home):
                raise BridgeError('INVALID_ARTIFACT_ROOT','Do not grant a volume, home ancestor or Codex profile.')
            associations=list(db.execute('SELECT root AS path FROM projects UNION ALL SELECT workspace AS path FROM conversations WHERE workspace IS NOT NULL UNION ALL SELECT workspace AS path FROM creations WHERE workspace IS NOT NULL'))
            if any(overlaps(path,x['path']) for x in associations):
                raise BridgeError('ARTIFACT_ROOT_OVERLAP','Artifact roots must be separate from all source roots and worker workspaces.')
            if any(overlaps(path,x['root']) for x in db.execute('SELECT * FROM artifact_roots WHERE enabled=1')):
                raise BridgeError('ARTIFACT_ROOT_OVERLAP','An enabled artifact grant already covers an overlapping directory.')
            if not path.exists():path.mkdir()
            path=checked_root(path)
            identity=directory_identity(path)
            if (not prior or identity!=prior['identity']) and any(path.iterdir()):
                raise BridgeError('ARTIFACT_ROOT_NOT_EMPTY','A first grant requires an empty dedicated directory; existing data stays outside the grant.')
        db.execute('INSERT INTO artifact_roots VALUES(?,?,?,?,?,?) ON CONFLICT(project_id,root) DO UPDATE SET enabled=excluded.enabled,identity=excluded.identity,reason=excluded.reason,created=excluded.created',
                   (project_id,str(path),int(enabled),identity or prior['identity'],reason,time.time()))
        db.execute("INSERT INTO notes(project_id,kind,text,created) VALUES(?,'decision',?,?)",
                   (project_id,json.dumps({'artifact_root':str(path),'enabled':enabled,'reason':reason}),time.time()))
        return dict(db.execute('SELECT * FROM artifact_roots WHERE project_id=? AND root=?',(project_id,str(path))).fetchone())


def operator_artifact_change(registry,data_dir,project_id,root,reason,create=False,enabled=True):
    """Verify the original coordinator metadata before an operator adds writes."""
    if enabled:
        from .transport import AppServer
        project=registry.one('projects','id',project_id)
        grants=registry.rows('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,))
        if not grants:raise BridgeError('PROJECT_NOT_AUTHORIZED','An enabled original project grant is required.')
        remote=AppServer(pathlib.Path(data_dir)/'logs')
        try:
            thread=remote.call('thread/read',{'threadId':grants[0]['coordinator_thread_id'],'includeTurns':False})['thread']
            if path_key(thread['cwd'])!=path_key(project['root']):raise BridgeError('PROJECT_CONFLICT','Original coordinator moved away from its source root.')
        finally:remote.close()
    result=artifact_root_grant(registry,project_id,root,reason,create=create,enabled=enabled)
    return {'artifact_root':result,'source_root_changed':False,'worker_turn_started':False,
            'next_step':'Use an actually loaded 0.6+ bridge. Existing registered coordinators read this grant before future managed turns; no repeated nomination. Auditors remain read-only.'}


class ArtifactOperations:
    def _artifact_roots(self,project):
        roots=[]
        for row in self.registry.rows('SELECT * FROM artifact_roots WHERE project_id=? AND enabled=1',(project['id'],)):
            path=checked_root(row['root'])
            if directory_identity(path)!=row['identity']:
                raise BridgeError('SCOPE_LOST','An authorized artifact directory was replaced; operator recovery is required.')
            roots.append(str(path))
        return roots

    def _worker_write_roots(self,worker,project):
        return [worker.get('workspace') or project['root'],*self._artifact_roots(project)]

    def _worker_sandbox(self,worker,project):
        if any(r in worker['role'].lower() for r in ('audit','architect','review')):
            return {'type':'readOnly','networkAccess':False}
        return {'type':'workspaceWrite','writableRoots':self._worker_write_roots(worker,project),
                'networkAccess':False,'excludeTmpdirEnvVar':True,'excludeSlashTmp':True}
