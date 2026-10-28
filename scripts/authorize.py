"""Local operator grants. Deliberately unavailable as an MCP tool."""
import argparse,json,os,pathlib,sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parents[1]/'plugin'))
from orchestrator.authorization import grant_project
from orchestrator.artifacts import operator_artifact_change
from orchestrator.errors import BridgeError
from orchestrator.projects import canonical,path_key
from orchestrator.storage import Registry
from orchestrator.transport import AppServer
from orchestrator.tools import validate,KEY


def existing_grant_options(registry,args):
    """Grant updates retain this owner's existing UI and integration choices."""
    previous=registry.rows('SELECT * FROM authorizations WHERE project_id=?',(args.project_id,))
    projects=registry.rows('SELECT * FROM projects WHERE id=?',(args.project_id,))
    prior=previous[0] if previous and previous[0]['enabled'] and previous[0]['coordinator_thread_id']==args.coordinator else None
    project=projects[0] if prior and projects else None
    ui=args.desktop_ui_project_id if args.desktop_ui_project_id is not None else project['desktop_ui_project_id'] if project else None
    headless=bool(args.headless) if args.headless is not None else bool(prior['headless']) if prior and args.desktop_ui_project_id is None else False
    integrations=set(args.allow_integration)
    if prior and not args.replace_integrations:integrations.update(json.loads(prior['integrations']))
    return {'desktop_ui_id':ui,'headless':headless,'integrations':sorted(integrations)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=pathlib.Path,help='Private state directory override.')
    sub=parser.add_subparsers(dest='action',required=True)
    grant=sub.add_parser('grant',help='Authorize one existing project and exact coordinator.')
    grant.add_argument('root',type=pathlib.Path);grant.add_argument('--project-id',required=True)
    grant.add_argument('--coordinator',required=True,help='Actual coordinator thread UUID.')
    grant.add_argument('--desktop-ui-project-id');grant.add_argument('--canonical-project-id')
    grant.add_argument('--headless',action='store_const',const=True,default=None,help='Explicitly omit native sidebar synchronization; existing mode is preserved when omitted.')
    grant.add_argument('--allow-integration',action='append',default=[],help='Exact mcp_servers.NAME or plugins.NAME. Hooks/apps/subagents stay disabled.')
    grant.add_argument('--replace-integrations',action='store_true',help='Deliberately replace the integration list with the supplied entries; otherwise preserve existing approved entries and add new ones.')
    revoke=sub.add_parser('revoke');revoke.add_argument('project_id')
    for action in ('artifact-grant','artifact-revoke'):
        command=sub.add_parser(action,help='Register/revoke one exact external artifact directory under existing human authority; never a source-root change.')
        command.add_argument('project_id');command.add_argument('root',type=pathlib.Path)
        command.add_argument('--reason',required=True,help='Existing human-approved artifact-location authority.')
        if action=='artifact-grant':command.add_argument('--create',action='store_true',help='Create only the final empty directory; its verified parent must exist.')
    sub.add_parser('status');args=parser.parse_args()
    data=args.data_dir or pathlib.Path(os.environ.get('ORCHESTRATOR_DATA_DIR') or pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))/'conversation-orchestrator')
    registry=Registry(data/'registry.sqlite3')
    if args.action=='grant':
        validate(args.project_id,KEY);root=canonical(args.root)
        remote=AppServer(data/'logs')
        try:
            thread=remote.call('thread/read',{'threadId':args.coordinator,'includeTurns':False})['thread']
            if path_key(thread['cwd'])!=path_key(root):raise BridgeError('PROJECT_CONFLICT','Coordinator cwd differs from requested root.')
            if args.canonical_project_id:
                project=remote.call('project/read',{'projectId':args.canonical_project_id})['project']
                if not any(path_key(r['path'])==path_key(root) for r in project['roots']):raise BridgeError('PROJECT_CONFLICT','Canonical project roots differ.')
        finally:remote.close()
        options=existing_grant_options(registry,args)
        result=grant_project(registry,args.project_id,root,args.coordinator,desktop_project_id=args.canonical_project_id,**options)
        print(json.dumps({'authorized':result,'next_step':'Call coordinator_register in the designated coordinator.'},indent=2))
    elif args.action in ('artifact-grant','artifact-revoke'):
        validate(args.project_id,KEY)
        print(json.dumps(operator_artifact_change(registry,data,args.project_id,args.root,args.reason,
            create=getattr(args,'create',False),enabled=args.action=='artifact-grant'),indent=2))
    elif args.action=='revoke':
        with registry.transaction() as db:
            if db.execute('SELECT 1 FROM control_lock').fetchone() or db.execute("SELECT 1 FROM creations WHERE state='preparing' AND (project_id=? OR project_id IS NULL)",(args.project_id,)).fetchone() or db.execute('SELECT 1 FROM operations o JOIN conversations c ON c.thread_id=o.thread_id WHERE c.project_id=?',(args.project_id,)).fetchone():raise BridgeError('PROJECT_BUSY','Resolve this project in-flight or uncertain control operations first.')
            if db.execute("SELECT 1 FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE c.project_id=? AND m.state IN ('preparing','sent','unknown')",(args.project_id,)).fetchone():raise BridgeError('PROJECT_BUSY','Resolve or interrupt pending sends before revocation.')
            if db.execute('UPDATE authorizations SET enabled=0 WHERE project_id=?',(args.project_id,)).rowcount!=1:raise BridgeError('NOT_FOUND','No such production grant.')
        print(json.dumps({'project_id':args.project_id,'authorized':False}))
    else:print(json.dumps(registry.rows('SELECT p.id,p.root,a.coordinator_thread_id,a.enabled,a.headless,a.integrations FROM projects p JOIN authorizations a ON a.project_id=p.id'),indent=2))


if __name__=='__main__':
    try:main()
    except BridgeError as exc:
        print(json.dumps({'error':exc.as_dict()}),file=sys.stderr);raise SystemExit(1)
