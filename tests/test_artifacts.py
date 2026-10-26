import json
import os
import pathlib
import subprocess
import sys
import tempfile
import sqlite3
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'plugin'))
from orchestrator.artifacts import artifact_root_grant
from orchestrator.auditing import artifact_hash
from orchestrator.authorization import grant_project
from orchestrator.errors import BridgeError
from orchestrator.service import Service
from orchestrator.storage import Registry
from orchestrator.transport import AppServer
from test_production import RecordedTransport


class ArtifactTransport(RecordedTransport):
    def call(self,method,params):
        if method in ('thread/resume','turn/start','thread/start'):
            self.calls.append((method,params))
            if method=='thread/resume':return {'thread':self.metadata[params['threadId']]}
            if method=='turn/start':
                tid=str(uuid.uuid4());self.active.add((params['threadId'],tid))
                return {'turn':{'id':tid,'status':'inProgress','items':[]}}
            tid=str(uuid.uuid4())
            self.metadata[tid]={'id':tid,'cwd':params['cwd'],'status':{'type':'idle'}}
            return {'thread':self.metadata[tid],'model':params['model'],'reasoningEffort':params['config']['model_reasoning_effort']}
        return super().call(method,params)


class ArtifactRootTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=pathlib.Path(self.temp.name);self.state=self.base/'state'
        self.roots={x:self.base/x for x in ('alpha','beta')}
        self.coordinators={x:str(uuid.uuid4()) for x in self.roots};self.meta={}
        for name,root in self.roots.items():
            root.mkdir();self.meta[self.coordinators[name]]={'id':self.coordinators[name],'cwd':str(root),'status':{'type':'idle'}}
        self.a=Service(self.state,transport_factory=lambda *a,**k:ArtifactTransport(self.meta));self.addCleanup(self.a.close)
        self.b=Service(self.state,transport_factory=lambda *a,**k:ArtifactTransport(self.meta));self.addCleanup(self.b.close)
        for name,root in self.roots.items():grant_project(self.a.registry,name,root,self.coordinators[name],headless=True)
        self.a.coordinator_register('alpha',self.coordinators['alpha']);self.b.coordinator_register('beta',self.coordinators['beta'])
        self.workers={}
        with self.a.registry.connect() as db:
            for project,role in (('alpha','Developer'),('alpha','Auditor'),('beta','Developer')):
                tid=str(uuid.uuid4());self.workers[(project,role)]=tid
                self.meta[tid]={'id':tid,'cwd':str(self.roots[project]),'status':{'type':'idle'}}
                db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities,workspace,desktop_sync_state) VALUES(?,?,?,?,'[]',?,'headless')",(tid,project,role,role,str(self.roots[project])))
        (self.base/'exports').mkdir();self.external=self.base/'exports/alpha'

    def grant(self,**kw):
        return artifact_root_grant(self.a.registry,'alpha',self.external,'Human approved a dedicated artifact directory',create=True,**kw)

    def worker(self,project='alpha',role='Developer'):
        return self.a.registry.one('conversations','thread_id',self.workers[(project,role)])

    def test_exact_writer_roots_readonly_auditor_and_project_isolation(self):
        before=self.a.registry.rows('SELECT * FROM authorizations ORDER BY project_id')
        self.grant();project=self.a._project('alpha')
        policy=self.a._worker_sandbox(self.worker(),project)
        self.assertEqual(policy,{'type':'workspaceWrite','writableRoots':[str(self.roots['alpha']),str(self.external)],'networkAccess':False,'excludeTmpdirEnvVar':True,'excludeSlashTmp':True})
        self.assertEqual(self.a._worker_sandbox(self.worker(role='Auditor'),project),{'type':'readOnly','networkAccess':False})
        self.assertEqual(self.b._worker_sandbox(self.worker('beta'),self.b._project('beta'))['writableRoots'],[str(self.roots['beta'])])
        self.assertEqual(self.a.registry.rows('SELECT * FROM authorizations ORDER BY project_id'),before)
        self.assertEqual(self.a._project('alpha')['root'],str(self.roots['alpha']))
        self.assertEqual(len(self.a.project_status('alpha')['artifact_roots']),1)
        self.assertEqual(self.b.project_status('beta')['artifact_roots'],[])

    def test_external_artifacts_remain_hash_bound_and_cross_project_denied(self):
        self.grant();file=self.external/'checkpoint.bin';file.write_bytes(b'fixture')
        entry={'path':str(file),'sha256':artifact_hash(file)}
        self.assertEqual(self.a._audit_artifacts(self.a._project('alpha'),[entry]),[entry])
        with self.assertRaisesRegex(BridgeError,'belong'):self.b._audit_artifacts(self.b._project('beta'),[entry])
        file.write_bytes(b'changed')
        with self.assertRaisesRegex(BridgeError,'differs'):self.a._audit_artifacts(self.a._project('alpha'),[entry])
        sibling=self.external.parent/'unrelated.bin';sibling.write_bytes(b'preserved')
        with self.assertRaises(BridgeError):self.a._audit_artifacts(self.a._project('alpha'),[{'path':str(sibling),'sha256':artifact_hash(sibling)}])

    def test_actual_dispatch_and_resume_receive_only_exact_artifact_root(self):
        self.grant();worker=self.workers[('alpha','Developer')]
        result=self.a.message_send(worker,'Write new artifact','fixture-send')
        self.assertEqual(result['delivery_state'],'sent')
        calls=self.a.rpc.calls
        resume=next(p for m,p in calls if m=='thread/resume')
        start=next(p for m,p in calls if m=='turn/start')
        self.assertEqual(resume['cwd'],str(self.roots['alpha']))
        self.assertEqual(resume['config']['sandbox_workspace_write']['writable_roots'],[str(self.roots['alpha']),str(self.external)])
        self.assertEqual(start['sandboxPolicy']['writableRoots'],[str(self.roots['alpha']),str(self.external)])
        self.assertIn(json.dumps([str(self.external)]),resume['developerInstructions'])
        self.assertFalse(start['sandboxPolicy']['networkAccess'])

    def test_new_auditor_has_no_writable_artifact_config(self):
        self.grant()
        result=self.a.conversation_create('alpha','Independent fixture auditor','Auditor','create-auditor')
        params=next(p for m,p in self.a.rpc.calls if m=='thread/start')
        self.assertEqual(params['sandbox'],'read-only')
        self.assertEqual(params['config']['sandbox_workspace_write']['writable_roots'],[])
        self.assertEqual(params['runtimeWorkspaceRoots'],[str(self.roots['alpha'])])
        self.assertEqual(result['worker']['workspace'],str(self.roots['alpha']))

    def test_idle_loaded_worker_refreshes_instructions_after_root_change(self):
        worker=self.workers[('alpha','Developer')]
        self.a.conversation_resume(worker)
        self.grant();self.a.conversation_resume(worker)
        calls=[p for m,p in self.a.rpc.calls if m=='thread/resume']
        self.assertEqual(len(calls),2)
        self.assertIn(json.dumps([str(self.external)]),calls[-1]['developerInstructions'])
        self.assertEqual(calls[-1]['config']['sandbox_workspace_write']['writable_roots'][-1],str(self.external))

    def test_busy_mutations_are_denied_but_unchanged_grant_is_idempotent(self):
        first=self.grant();(self.external/'existing').write_text('keep')
        self.a.registry.reserve_message('pending',self.workers[('alpha','Developer')],'instruction',None,self.a.instance)
        self.assertEqual(self.grant(),first)
        with self.assertRaisesRegex(BridgeError,'Resolve'):artifact_root_grant(self.a.registry,'alpha',self.external.parent/'other','Approved other directory',create=True)
        self.assertFalse((self.external.parent/'other').exists())
        with self.assertRaisesRegex(BridgeError,'Resolve'):self.grant(enabled=False)
        self.a.registry.set_message('pending','failed')
        self.grant(enabled=False)
        self.assertEqual(self.a._worker_sandbox(self.worker(),self.a._project('alpha'))['writableRoots'],[str(self.roots['alpha'])])
        self.grant()
        self.assertEqual((self.external/'existing').read_text(),'keep')

    def test_nonempty_parent_source_and_foreign_grants_are_rejected(self):
        old=self.external.parent/'old-data';old.mkdir();(old/'keep').write_text('original')
        with self.assertRaisesRegex(BridgeError,'empty'):artifact_root_grant(self.a.registry,'alpha',old,'Approved new artifacts')
        self.assertEqual((old/'keep').read_text(),'original')
        with self.assertRaises(BridgeError):artifact_root_grant(self.a.registry,'alpha',self.roots['alpha'],'No source root expansion')
        self.grant();child=self.external/'foreign';child.mkdir()
        with self.assertRaisesRegex(BridgeError,'overlap'):artifact_root_grant(self.a.registry,'beta',child,'Foreign directory denied')
        with self.assertRaisesRegex(BridgeError,'reserved'):grant_project(self.a.registry,'other',child,str(uuid.uuid4()),headless=True)
        other=Service(self.state);self.addCleanup(other.close)
        with self.assertRaisesRegex(BridgeError,'reserved'):other.project_create('nested-experiment',str(self.external/'empty-source'))
        self.assertFalse((self.external/'empty-source').exists())

    def test_redirected_root_is_rejected_before_dispatch(self):
        self.grant();moved=self.external.with_name('original');self.external.rename(moved)
        target=self.external.with_name('unrelated');target.mkdir()
        if os.name=='nt':
            subprocess.run(['cmd','/d','/c','mklink','/J',str(self.external),str(target)],check=True,capture_output=True)
        else:self.external.symlink_to(target,target_is_directory=True)
        try:
            with self.assertRaisesRegex(BridgeError,'symlinks|reparse'):self.a._worker_sandbox(self.worker(),self.a._project('alpha'))
            with self.assertRaises(BridgeError):artifact_root_grant(self.a.registry,'beta',self.external,'Do not follow redirect')
        finally:
            if os.name=='nt':self.external.rmdir()
            else:self.external.unlink()
        self.assertTrue(moved.is_dir());self.assertTrue(target.is_dir())

    def test_revoke_missing_root_and_reject_replaced_directory(self):
        self.grant();self.external.rename(self.external.with_name('preserved'))
        self.external.mkdir()
        with self.assertRaisesRegex(BridgeError,'replaced'):self.a._worker_sandbox(self.worker(),self.a._project('alpha'))
        self.external.rmdir()
        record=self.grant(enabled=False)
        self.assertFalse(record['enabled'])
        self.assertFalse(self.external.exists())

    def test_declared_external_writes_and_revocation_preserve_plan_gate(self):
        self.grant();task={'id':'write','owner':self.workers[('alpha','Developer')],'requirements':'Produce approved artifacts',
            'inputs':[],'outputs':['checkpoint.bin'],'acceptance':['Validate checkpoint'],'dependencies':[],
            'write_paths':[str(self.external/'checkpoint.bin')]}
        plan=self.a.plan_record('alpha','artifact-plan','Approved export','Human request',[task])
        planned=plan['payload']['tasks'][0]
        self.a.task_assign('alpha','write',task['owner'],planned['requirements'],plan_key='artifact-plan')
        self.assertEqual(self.a._planned_paths('write'),task['write_paths'])
        self.grant(enabled=False)
        with self.assertRaisesRegex(BridgeError,'authorized'):self.a._planned_paths('write')

    def test_schema10_upgrade_retains_grants_history_and_foreign_keys(self):
        before=self.a.registry.rows('SELECT * FROM authorizations ORDER BY project_id')
        with self.a.registry.connect() as db:
            db.execute('DROP TABLE artifact_roots');db.execute('PRAGMA user_version=10')
        upgraded=Registry(self.state/'registry.sqlite3')
        self.assertEqual(upgraded.rows('SELECT * FROM authorizations ORDER BY project_id'),before)
        with upgraded.connect() as db:
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],11)
            self.assertEqual(db.execute('PRAGMA foreign_key_check').fetchall(),[])
        self.assertTrue(list(self.state.glob('registry.sqlite3.before-v11-*')))

    def test_strict_windows_backend_has_no_legacy_fallback(self):
        with patch('orchestrator.transport.subprocess.Popen',side_effect=OSError('unsupported probe')) as launch:
            with self.assertRaises(BridgeError):AppServer(self.base/'logs',executable='unavailable-test-cli',strict_windows_sandbox=True)
        command=launch.call_args.args[0]
        self.assertIn('windows.sandbox="mxc"',command)
        self.assertNotIn('danger-full-access',' '.join(command))

    def test_database_reservations_protect_against_legacy_root_inserts(self):
        self.grant();child=self.external/'legacy-source'
        with self.a.registry.connect() as db:
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Artifact directories'):
                db.execute("INSERT INTO projects(id,root,mode,created) VALUES('legacy',?,'experiment',0)",(str(child),))
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Artifact directories'):
                db.execute('UPDATE conversations SET workspace=? WHERE thread_id=?',(str(child),self.workers[('beta','Developer')]))

    def test_late_legacy_constructor_is_fenced_before_root_registration(self):
        self.grant();late=str(uuid.uuid4())
        with self.a.registry.connect() as db:
            # Old code passed its schema10 check before migration, but only
            # publishes its bridge row afterward. It is not in the snapshot.
            db.execute('INSERT INTO bridges VALUES(?,?,1,0)',(late,os.getpid()))
            self.assertIsNone(db.execute('SELECT 1 FROM legacy_bridge_tokens WHERE token=?',(late,)).fetchone())
            with self.assertRaisesRegex(sqlite3.IntegrityError,'Current bridge'):
                db.execute("INSERT INTO control_lock VALUES(1,?,'project_create')",(late,))
            self.assertIsNone(db.execute('SELECT 1 FROM control_lock').fetchone())


if __name__=='__main__':unittest.main()
