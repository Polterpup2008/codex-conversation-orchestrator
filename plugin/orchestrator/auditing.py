"""Bind an independent audit to one delivery revision and current artifact hashes."""
import hashlib
import json
import pathlib
from .errors import BridgeError
from .projects import canonical, contained


def artifact_hash(path):
    digest = hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


class AuditOperations:
    def _audit_artifacts(self, project, artifacts):
        roots=[project['root']]+[r['workspace'] for r in self.registry.rows('SELECT workspace FROM conversations WHERE project_id=? AND workspace IS NOT NULL',(project['id'],))]
        result=[]
        for artifact in artifacts or []:
            path=canonical(artifact['path'])
            if not any(contained(path,root) for root in roots):
                raise BridgeError('ARTIFACT_SCOPE','Audit artifacts must belong to this project.')
            try:
                actual=artifact_hash(path)
            except PermissionError as exc:
                raise BridgeError('ARTIFACT_READ_DENIED', 'The coordinator process cannot read this delivered artifact for audit binding.',
                    {'path': path, 'recovery': 'Have its original managed writer repair read access for the coordinator OS account on this artifact only, within existing host permissions. Send a separate stable-key maintenance message without task_id while the implementation task is needs_audit. Preserve content, rehash, then retry the original audit key; do not reset ACLs, grant broad write rights, fabricate a binding or request routine human approval.'}) from exc
            if actual!=artifact['sha256']:
                raise BridgeError('ARTIFACT_CHANGED','An audit artifact differs from the requested SHA256.')
            result.append({'path':path,'sha256':actual})
        return result

    def _audit_request(self, worker, task_id, artifacts):
        if not task_id:
            if artifacts:raise BridgeError('AUDIT_TASK_REQUIRED','Artifact binding requires an audit task.')
            return None
        task=self.registry.one('tasks','id',task_id)
        project=self._project(task['project_id'])
        if worker['project_id']!=task['project_id'] or worker['thread_id']==task['owner'] or 'audit' not in worker['role'].lower():
            raise BridgeError('INDEPENDENT_AUDIT_REQUIRED','Use a separate auditor in the task project.')
        if task['state']!='needs_audit':raise BridgeError('TASK_STATE','Only delivered work can be audited.')
        checked=self._audit_artifacts(project,artifacts)
        if project['mode']=='production' and not checked:
            raise BridgeError('AUDIT_ARTIFACTS_REQUIRED','Production task audits require explicit artifact hashes.')
        delivery=self.registry.rows("SELECT key,turn_id FROM messages WHERE task_id=? AND state='completed' ORDER BY created DESC LIMIT 1",(task_id,))
        if not delivery:raise BridgeError('AUDIT_DELIVERY_REQUIRED','No completed delivery exists.')
        return {'task_id':task_id,'task_revision':task['revision'],'work_message_key':delivery[0]['key'],
                'work_turn_id':delivery[0]['turn_id'],'artifacts':checked}

    def _validate_audit_link(self, task, audit):
        links=self.registry.rows('SELECT * FROM audit_links WHERE message_key=?',(audit['key'],))
        project=self._project(task['project_id'])
        if not links:
            if project['mode']=='production':raise BridgeError('AUDIT_BINDING_REQUIRED','Dispatch a task-bound audit of this delivery before review.')
            return
        link=links[0]
        latest=self.registry.rows("SELECT key,turn_id FROM messages WHERE task_id=? AND state='completed' ORDER BY created DESC LIMIT 1",(task['id'],))
        if link['task_id']!=task['id'] or link['task_revision']!=task['revision'] or not latest or latest[0]['key']!=link['work_message_key'] or latest[0]['turn_id']!=link['work_turn_id']:
            raise BridgeError('STALE_AUDIT','This audit does not cover the current task delivery/revision.')
        self._audit_artifacts(project,json.loads(link['artifacts']))
