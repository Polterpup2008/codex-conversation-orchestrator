"""Install a clean checkout using a verified local Python executable."""
import argparse,hashlib,json,os,pathlib,re,shlex,shutil,subprocess,sys
ROOT=pathlib.Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex-home',type=pathlib.Path,help='Separate profile; copies no credentials.')
    parser.add_argument('--data-dir',type=pathlib.Path,help='Explicit private registry directory for the installed MCP server.')
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
    print(f'Installed with {version} and Python {sys.version.split()[0]}.')
    print('Start a new Codex chat. Sign in with ChatGPT using codex login before running workers.')
    print('Production use requires a separate local grant; installation activates no project. No API-key fallback.')


if __name__=='__main__':main()
