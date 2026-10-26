"""Install a clean checkout using a verified local Python executable."""
import argparse,hashlib,json,os,pathlib,re,shlex,shutil,subprocess,sys
import copy,tomllib,tempfile,contextlib
ROOT=pathlib.Path(__file__).resolve().parents[1]


def publish_missing_file(source, target):
    """Publish complete bytes atomically; never replace a racing live file."""
    source=pathlib.Path(source);target=pathlib.Path(target)
    descriptor,name=tempfile.mkstemp(prefix='.orchestrator-restore-',dir=target.parent)
    temporary=pathlib.Path(name)
    try:
        with os.fdopen(descriptor,'wb') as output,source.open('rb') as input_stream:
            shutil.copyfileobj(input_stream,output);output.flush();os.fsync(output.fileno())
        if os.name!='nt':shutil.copymode(source,temporary)
        try:os.link(temporary,target)
        except FileExistsError:return False
        return True
    finally:
        temporary.unlink(missing_ok=True)


@contextlib.contextmanager
def preserve_loaded_packages(home, new_version):
    """Keep exact old files readable while the host still has old processes."""
    home=pathlib.Path(home)
    cache=home/'plugins/cache/conversation-orchestrator-lab/conversation-orchestrator'
    cache_root=home.resolve()/'plugins/cache/conversation-orchestrator-lab/conversation-orchestrator'
    if cache.resolve()!=cache_root:raise SystemExit('Plugin cache root was redirected; installation did not change it.')
    retained_root=home.resolve()/'conversation-orchestrator/retained-packages'
    if retained_root.resolve()!=retained_root:raise SystemExit('Retained package storage was redirected.')
    retained_root.mkdir(parents=True,exist_ok=True)
    # Immutable snapshots must not share a writable backup during two upgrades.
    attempt=pathlib.Path(tempfile.mkdtemp(prefix='upgrade-',dir=retained_root))
    retained=[]
    for source in cache.iterdir() if cache.is_dir() else ():
        if source.name==new_version or not source.is_dir() or source.resolve()!=cache_root/source.name:continue
        manifest=source/'plugin.json'
        if not manifest.is_file():continue
        package=json.loads(manifest.read_text(encoding='utf-8'))
        if package.get('name')!='conversation-orchestrator' or package.get('version')!=source.name:continue
        backup=attempt/source.name
        if backup.resolve().parent!=attempt:
            raise SystemExit('Retained package storage was redirected; installation did not change the cache.')
        backup.mkdir(parents=True,exist_ok=True)
        for item in source.rglob('*'):
            if '__pycache__' in item.parts or item.name.startswith('.orchestrator-restore-'):continue
            if item.is_symlink() or item.resolve()!=source.resolve()/item.relative_to(source):
                raise SystemExit('Previous package member was redirected; installation did not change the cache.')
            if item.is_file():
                target=backup/item.relative_to(source)
                if target.resolve()!=backup/item.relative_to(source):raise SystemExit('Retained package member was redirected.')
                target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,target)
        retained.append((source,backup))
    try:yield
    finally:
        for destination,backup in retained:
            if cache.resolve()!=cache_root or destination.resolve()!=cache_root/destination.name:
                raise SystemExit('Previous cache root was redirected; retained files were not restored there.')
            if backup.resolve()!=backup:raise SystemExit('Retained snapshot root was redirected.')
            for item in backup.rglob('*'):
                if item.is_symlink() or item.resolve()!=backup/item.relative_to(backup):
                    raise SystemExit('Retained snapshot member was redirected.')
                if not item.is_file():continue
                target=destination/item.relative_to(backup)
                if target.resolve()!=cache_root/destination.name/item.relative_to(backup):
                    raise SystemExit('Previous cache member was redirected; retained files remain in private backup.')
                if target.exists():continue  # publication also enforces this atomically
                target.parent.mkdir(parents=True,exist_ok=True);publish_missing_file(item,target)


def approve_coordination_tools(home):
    """Explicit operator opt-in, limited to this plugin's MCP server."""
    path=pathlib.Path(home)/'config.toml'
    source=path.read_text(encoding='utf-8-sig') if path.is_file() else ''
    before=tomllib.loads(source);expected=copy.deepcopy(before)
    server=expected.setdefault('plugins',{}).setdefault('conversation-orchestrator@conversation-orchestrator-lab',{}).setdefault('mcp_servers',{}).setdefault('conversation_orchestrator',{})
    if server.get('default_tools_approval_mode')=='approve':return False
    server['default_tools_approval_mode']='approve'
    header='[plugins."conversation-orchestrator@conversation-orchestrator-lab".mcp_servers.conversation_orchestrator]'
    match=re.search(r'(?m)^'+re.escape(header)+r'[ \t]*$',source)
    if match:
        end=re.search(r'(?m)^\s*\[',source[match.end():])
        stop=match.end()+end.start() if end else len(source)
        body=source[match.end():stop]
        if re.search(r'(?m)^default_tools_approval_mode\s*=',body):
            body=re.sub(r'(?m)^default_tools_approval_mode\s*=.*$', 'default_tools_approval_mode = "approve"',body)
        else:body+='\ndefault_tools_approval_mode = "approve"\n'
        changed=source[:match.end()]+body+source[stop:]
    else:changed=source.rstrip()+'\n\n'+header+'\ndefault_tools_approval_mode = "approve"\n'
    try:
        if tomllib.loads(changed)!=expected:raise ValueError('unexpected unrelated change')
    except (ValueError,tomllib.TOMLDecodeError) as exc:
        raise SystemExit('Cannot safely update this TOML layout. Existing configuration preserved; set only this plugin MCP server default_tools_approval_mode to approve through your supported settings.') from exc
    path.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,delete=False) as stream:
        stream.write(changed);temporary=pathlib.Path(stream.name)
    try:
        if (path.read_text(encoding='utf-8-sig') if path.is_file() else '')!=source:
            raise SystemExit('Configuration changed concurrently; it was not overwritten. Retry the same installer opt-in.')
        os.replace(temporary,path)
    finally:
        if temporary.exists():temporary.unlink()
    return True


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home',type=pathlib.Path,help='Separate profile; copies no credentials.')
    parser.add_argument('--data-dir',type=pathlib.Path,help='Explicit private registry directory for the installed MCP server.')
    parser.add_argument('--approve-coordination-tools',action='store_true',help='Explicitly pre-approve only this plugin MCP tools. Project appointment/scope gates and OS/sandbox approvals remain enforced.')
    args=parser.parse_args()
    if sys.version_info<(3,11):raise SystemExit('Python 3.11+ required.')
    if os.name=='nt' and not sys.executable.isascii():raise SystemExit('This Windows launcher requires Python installed at an ASCII path. Install/select an ASCII-path interpreter, then rerun the installer.')
    codex=shutil.which('codex')
    if not codex:raise SystemExit('Install the official Codex CLI on PATH first.')
    version=subprocess.run([codex,'--version'],capture_output=True,text=True,check=True).stdout.strip()
    found=re.search(r'(\d+)\.(\d+)\.(\d+)',version)
    if not found or tuple(map(int,found.groups()))<(0,164,0):raise SystemExit('Codex CLI 0.164.0+ required; see compatibility notes.')
    env=os.environ.copy()
    if args.codex_home:env['CODEX_HOME']=str(args.codex_home.resolve())
    home=pathlib.Path(env.get('CODEX_HOME',pathlib.Path.home()/'.codex'))
    package_version=json.loads((ROOT/'plugin/plugin.json').read_text(encoding='utf-8'))['version']
    stage=home/'conversation-orchestrator/install-source'/package_version;stage.mkdir(parents=True,exist_ok=True)
    shutil.copytree(ROOT/'plugin',stage/'plugin',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    (stage/'.agents/plugins').mkdir(parents=True,exist_ok=True)
    shutil.copy2(ROOT/'.agents/plugins/marketplace.json',stage/'.agents/plugins/marketplace.json')
    manifest=stage/'plugin/mcp.json';config=json.loads(manifest.read_text(encoding='utf-8'))
    if os.name=='nt':
        launcher=stage/'plugin/run-server.cmd'
        python_path=sys.executable.replace('%','%%')
        launcher.write_text('@echo off\nsetlocal DisableDelayedExpansion\n"'+python_path+'" "%~dp0server.py"\n',encoding='utf-8')
    else:
        launcher=stage/'plugin/run-server'
        launcher.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' "$(dirname "$0")/server.py"\n',encoding='utf-8')
        launcher.chmod(0o700)
    # Plugin manifests accept bare executables or contained ./ paths, not absolute commands.
    config['mcpServers']['conversation_orchestrator']['command']='./'+launcher.name
    config['mcpServers']['conversation_orchestrator']['args']=[]
    config['mcpServers']['conversation_orchestrator']['env']={'CODEX_HOME':str(home.resolve())}
    if args.data_dir:
        config['mcpServers']['conversation_orchestrator']['env']['ORCHESTRATOR_DATA_DIR']=str(args.data_dir.resolve())
    manifest.write_text(json.dumps(config,indent=2)+'\n',encoding='utf-8')
    installed=home/'plugins/cache/conversation-orchestrator-lab/conversation-orchestrator'/package_version
    package_files=[p for p in (stage/'plugin').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    identical=installed.is_dir() and all((installed/p.relative_to(stage/'plugin')).is_file() and hashlib.sha256(p.read_bytes()).digest()==hashlib.sha256((installed/p.relative_to(stage/'plugin')).read_bytes()).digest() for p in package_files)
    subprocess.run([sys.executable,'-c','import sys; assert sys.version_info >= (3,11)'],check=True)
    with preserve_loaded_packages(home,package_version):
        listing=json.loads(subprocess.run([codex,'plugin','marketplace','list','--json'],capture_output=True,text=True,check=True,env=env).stdout)
        previous=next((p for p in listing['marketplaces'] if p['name']=='conversation-orchestrator-lab'),None)
        different=previous and os.path.normcase(os.path.normpath(previous['root']))!=os.path.normcase(os.path.normpath(str(stage)))
        if different:
            subprocess.run([codex,'plugin','marketplace','remove','conversation-orchestrator-lab','--json'],check=True,env=env)
        try:
            subprocess.run([codex,'plugin','marketplace','add',str(stage)],check=True,env=env)
        except subprocess.CalledProcessError:
            if different:subprocess.run([codex,'plugin','marketplace','add',previous['root']],check=True,env=env)
            raise
        if not identical:
            try:subprocess.run([codex,'plugin','add','conversation-orchestrator@conversation-orchestrator-lab','--json'],check=True,env=env)
            except subprocess.CalledProcessError as exc:
                raise SystemExit('Plugin installation failed. Close Codex chats using this version before replacing its cache; maintainers should use a new version for changed packages.') from exc
        else:print('The identical package is already installed; cache replacement skipped.')
    if args.approve_coordination_tools:
        approve_coordination_tools(home)
        print('Coordination tools pre-approved for this plugin only; project, host and sandbox permission controls remain enforced.')
    print(f'Installed with {version} and Python {sys.version.split()[0]}.')
    print('Installation preserves already-loaded bridge processes. For an idle project, use project_bridge.py --prepare-handoff then --handoff in its SAME designated chat; see docs/ARTIFACT_ROOTS.md. A host refresh may be deferred until all projects are idle. Sign in with ChatGPT using codex login if needed before running workers.')
    print('A direct human appointment activates its exact project through coordinator_activate; no second local grant is needed. Installation alone appoints nobody. No API-key fallback.')


if __name__=='__main__':main()
