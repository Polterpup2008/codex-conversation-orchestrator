"""Check the staged/tracked public distribution without printing detected secrets."""
import fnmatch
import json
import pathlib
import re
import subprocess
import sys

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'plugin'))
from orchestrator.appointment import is_appointment, direct_directive, qualified_appointment, withdraws_appointment
ALLOWED=['.gitignore','.agents/plugins/marketplace.json','.github/workflows/ci.yml',
         'README.md','INSTALL.md','LICENSE','CONTRIBUTING.md','ORCHESTRATOR_PROMPT.md','orchestrator.md',
         'plugin/*.py','plugin/*.json','plugin/orchestrator/*.py',
         'plugin/skills/conversation-coordinate/SKILL.md','plugin/skills/conversation-coordinate/agents/openai.yaml',
         'plugin/skills/conversation-coordinate/references/*.md',
         'plugin/skills/reply-question/SKILL.md','plugin/skills/reply-question/agents/openai.yaml',
         'plugin/skills/context-handoff/SKILL.md','plugin/skills/context-handoff/agents/openai.yaml',
         'plugin/skills/task-planner/SKILL.md','plugin/skills/task-planner/agents/openai.yaml',
         'plugin/skills/audit-arbiter/SKILL.md','plugin/skills/audit-arbiter/agents/openai.yaml',
         'plugin/skills/architecture-guard/SKILL.md','plugin/skills/architecture-guard/agents/openai.yaml',
         'docs/*.md','templates/orchestrator/README.md','templates/orchestrator/orchestrator.md',
         'templates/orchestrator/ORCHESTRATOR_PROMPT.md','scripts/install.py','scripts/authorize.py','scripts/check_release.py',
         'tests/test_registry.py','tests/test_upgrade.py','tests/test_production.py','tests/test_advanced.py','tests/test_autonomy.py','tests/test_artifacts.py','tests/test_handoff.py','tests/test_native_approvals.py','tests/legacy_fixture.py','tests/mcp_client.py','tests/live_smoke.py']
REQUIRED=['README.md','INSTALL.md','LICENSE','ORCHESTRATOR_PROMPT.md','orchestrator.md',
          'templates/orchestrator/README.md','templates/orchestrator/orchestrator.md','templates/orchestrator/ORCHESTRATOR_PROMPT.md',
          'docs/VALIDATION.md','plugin/plugin.json','plugin/mcp.json','plugin/server.py','tests/test_artifacts.py','tests/test_handoff.py',
          'plugin/skills/conversation-coordinate/SKILL.md','scripts/install.py','scripts/authorize.py','tests/legacy_fixture.py']
SECRET_PATTERNS=[r'gh[pousr]_[A-Za-z0-9]{20,}',r'github_pat_[A-Za-z0-9_]{20,}',
                 r'sk-(?:proj-)?[A-Za-z0-9_-]{20,}',r'-----BEGIN [A-Z ]*PRIVATE KEY-----']
UUID=re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b',re.I)
SYNTHETIC={'22222222-2222-4222-8222-222222222222'}


def git(*args):return subprocess.check_output(['git',*args],cwd=ROOT)


def main():
    files=git('ls-files','-z').decode().split('\0');files=[p for p in files if p]
    if not files:raise SystemExit('No staged/tracked public files; stage an explicit release file list first.')
    errors=[];contents={}
    home=str(pathlib.Path.home()).replace('\\','/').casefold()
    workspace=str(ROOT).replace('\\','/').casefold()
    for path in files:
        if not any(fnmatch.fnmatchcase(path,pattern) for pattern in ALLOWED):errors.append((path,'outside public file allowlist'))
        if any(part in ('__pycache__','evidence','state','sessions','private') for part in pathlib.PurePosixPath(path).parts):errors.append((path,'private/generated directory'))
        if pathlib.PurePosixPath(path).suffix in ('.sqlite3','.db','.zip','.log','.exe','.cmd'):errors.append((path,'private/runtime artifact'))
        try:text=git('show',':'+path).decode('utf-8')
        except (UnicodeDecodeError,subprocess.CalledProcessError):errors.append((path,'not a staged UTF-8 source file'));continue
        contents[path]=text
        normalized=re.sub('/+','/',text.replace('\\','/')).casefold()
        if home in normalized or workspace in normalized:errors.append((path,'machine-specific private path'))
        if any(re.search(pattern,text) for pattern in SECRET_PATTERNS):errors.append((path,'secret-like value'))
        if any(value.lower() not in SYNTHETIC for value in UUID.findall(text)):errors.append((path,'non-synthetic conversation UUID'))
    for required in REQUIRED:
        if required not in contents:errors.append((required,'required public file missing'))
    for name in ('orchestrator.md','ORCHESTRATOR_PROMPT.md'):
        if contents.get(name)!=contents.get('templates/orchestrator/'+name):
            errors.append(('templates/orchestrator/'+name,'portable template differs from root contract'))
    prompts=re.findall(r'```text\s*\n(.*?)```',contents.get('ORCHESTRATOR_PROMPT.md',''),re.S)
    if len(prompts)!=2 or any(not is_appointment(p.splitlines()[0]) or
                             not direct_directive(p,p.splitlines()[0]) or
                             qualified_appointment(p) or withdraws_appointment(p) for p in prompts):
        errors.append(('ORCHESTRATOR_PROMPT.md','both activation prompts must contain a supported direct appointment'))
    if 'plugin/plugin.json' in contents:
        manifest=json.loads(contents['plugin/plugin.json'])
        if manifest['version'] not in contents.get('plugin/orchestrator/__init__.py',''):errors.append(('plugin/plugin.json','version mismatch'))
        mcp=json.loads(contents['plugin/mcp.json'])['mcpServers']['conversation_orchestrator']
        if mcp['command']!='python' or 'env' in mcp:errors.append(('plugin/mcp.json','distributable configuration must remain generic'))
    if errors:
        print(json.dumps({'passed':False,'findings':[{'file':p,'reason':r} for p,r in errors]},indent=2));raise SystemExit(1)
    print(json.dumps({'passed':True,'files_scanned':len(files),'version':manifest['version'],'private_artifacts':0}))


if __name__=='__main__':main()
