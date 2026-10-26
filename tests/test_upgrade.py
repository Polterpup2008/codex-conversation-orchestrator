import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import uuid
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'plugin'))
from orchestrator.errors import BridgeError
from orchestrator.projects import canonical,path_key,allowed_workspace
from orchestrator.routing import select_route
from orchestrator.service import Service
from orchestrator.storage import Registry


CATALOG=[{'model':m,'supportedReasoningEfforts':[{'reasoningEffort':e} for e in efforts],
    'defaultReasoningEffort':default,'isDefault':m=='gpt-6.1-sol'} for m,efforts,default in [
    ('gpt-6-luna',['low','medium','high','xhigh','max'],'medium'),
    ('gpt-6.1-sol',['low','medium','high','xhigh','max','ultra'],'low'),
    ('gpt-6-astra',['low','medium','high','xhigh','max','ultra'],'medium')]]


class RoutingTests(unittest.TestCase):
    def test_service_role_default_routes_an_auditor_to_complex(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Service(pathlib.Path(temp)/'state')
            try:
                s.model_list=lambda refresh=False:{'models':CATALOG}
                route=s.model_route(role='Auditor')
                self.assertEqual((route['model'],route['effort']),('gpt-6-astra','high'))
            finally:s.close()

    def test_explicit_unavailable_and_unsupported_are_rejected(self):
        for model,effort in [('unavailable','low'),('gpt-6-luna','ultra')]:
            with self.assertRaises(BridgeError):select_route(CATALOG,model,effort)

    def test_policy_uses_difficulty_and_advertised_options(self):
        for difficulty,expected in [('routine',('gpt-6-luna','low')),('standard',('gpt-6.1-sol','medium')),('complex',('gpt-6-astra','high')),('demanding',('gpt-6-astra','xhigh'))]:
            route=select_route(CATALOG,difficulty=difficulty)
            self.assertEqual((route['model'],route['effort']),expected)
        limited=[m for m in CATALOG if m['model']=='gpt-6.1-sol']
        route=select_route(limited,difficulty='complex')
        self.assertEqual(route['model'],'gpt-6.1-sol');self.assertIn('preferred gpt-6-astra',route['reason'])

    def test_ultra_and_extreme_require_real_justification(self):
        with self.assertRaises(BridgeError):select_route(CATALOG,difficulty='extreme')
        with self.assertRaises(BridgeError):select_route(CATALOG,'gpt-6-astra','ultra')
        self.assertTrue(select_route(CATALOG,'gpt-6-astra','ultra',justification='Explicit authorized investigation')['ultra_may_delegate'])

    def test_message_task_worker_precedence_and_ultra_gate(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Service(pathlib.Path(temp)/'state')
            try:
                s.model_list=lambda refresh=False:{'models':CATALOG}
                w={'role':'Developer','model':'gpt-6-luna','effort':'low','routing_justification':json.dumps({'justification':None})}
                self.assertEqual(s._message_route(w,None,None,None,None,None)['model'],'gpt-6-luna')
                self.assertEqual(s._message_route(w,None,'gpt-6.1-sol','high',None,None)['source'],'message_override')
                self.assertEqual(s._message_route(w,None,None,None,'complex',None)['model'],'gpt-6-astra')
                with self.assertRaises(BridgeError):s._message_route(w,None,'gpt-6-astra','ultra',None,None)
            finally:s.close()


class ProjectTests(unittest.TestCase):
    def test_absolute_paths_and_windows_prefix(self):
        with self.assertRaises(BridgeError):canonical('relative')
        if os.name=='nt':self.assertEqual(path_key('C:\\Users\\Example'),path_key('\\\\?\\C:\\Users\\EXAMPLE\\'))

    def test_worktree_is_verified_against_common_git_dir(self):
        with tempfile.TemporaryDirectory() as temp:
            root=pathlib.Path(temp)/'repo';root.mkdir();other=pathlib.Path(temp)/'unrelated';other.mkdir()
            subprocess.run(['git','-C',str(root),'init'],capture_output=True,check=True)
            (root/'AGENTS.md').write_text('isolated')
            subprocess.run(['git','-C',str(root),'add','.'],capture_output=True,check=True)
            subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@localhost','commit','-m','test'],capture_output=True,check=True)
            wt=pathlib.Path(temp)/'worktree'
            subprocess.run(['git','-C',str(root),'worktree','add','--detach',str(wt)],capture_output=True,check=True)
            self.assertEqual(allowed_workspace(root,wt),str(wt.resolve()))
            with self.assertRaises(BridgeError):allowed_workspace(root,other)

    def test_ambiguous_project_fails_instead_of_using_plugin_cwd(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Service(pathlib.Path(temp)/'state')
            try:
                class Fake:
                    closed=False
                    def call(self,method,params):
                        if method=='thread/read':return {'thread':{'cwd':temp,'projectId':None}}
                        return {'data':[{'id':'a','roots':[{'path':temp}]},{'id':'b','roots':[{'path':temp}]}],'nextCursor':None}
                    def close(self):pass
                s._transport=Fake()
                with self.assertRaisesRegex(BridgeError,'unique'):s.project_discover(str(uuid.uuid4()))
            finally:s.close()

    def test_pending_desktop_membership_blocks_dispatch(self):
        with tempfile.TemporaryDirectory() as temp:
            s=Service(pathlib.Path(temp)/'state')
            try:
                p=s.project_create('p',str(pathlib.Path(temp)/'root'));tid=str(uuid.uuid4())
                with s.registry.connect() as db:db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities,desktop_sync_state) VALUES(?,'p','Developer','test','[]','pending')",(tid,))
                with self.assertRaisesRegex(BridgeError,'attachment'):s.message_send(tid,'work','key')
                self.assertFalse(s.registry.rows('SELECT * FROM messages'))
            finally:s.close()


class MigrationTests(unittest.TestCase):
    def test_baseline_registry_migrates_without_losing_workers_or_tasks(self):
        from legacy_fixture import create_legacy_registry,AUDITOR
        with tempfile.TemporaryDirectory() as temp:
            target=pathlib.Path(temp)/'registry.sqlite3'
            create_legacy_registry(target,temp)
            source=sqlite3.connect(target)
            before={t:source.execute('SELECT * FROM '+t).fetchall() for t in ['projects','conversations','messages','tasks','notes']}
            columns={t:[r[1] for r in source.execute('PRAGMA table_info('+t+')')] for t in before};source.close()
            registry=Registry(target)
            with registry.connect() as db:
                for t,rows in before.items():
                    self.assertEqual([tuple(r) for r in db.execute('SELECT '+','.join(columns[t])+' FROM '+t)],rows)
                self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],11)
                self.assertFalse(db.execute('PRAGMA foreign_key_check').fetchall())
            self.assertEqual(registry.one('conversations','thread_id',AUDITOR)['role'],'Auditor')

    def test_same_message_with_changed_model_intent_is_not_duplicate(self):
        with tempfile.TemporaryDirectory() as temp:
            r=Registry(pathlib.Path(temp)/'r.sqlite3');tid=str(uuid.uuid4())
            with r.connect() as db:
                db.execute("INSERT INTO projects(id,root,mode,created) VALUES('p',?,'experiment',0)",(temp,))
                db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities) VALUES(?,'p','Developer','test','[]')",(tid,))
            r.reserve_message('k',tid,'work',None,routing_input={'model':'gpt-6-luna'})
            with self.assertRaises(BridgeError):r.reserve_message('k',tid,'work',None,routing_input={'model':'gpt-6.1-sol'})


if __name__=='__main__':unittest.main()
