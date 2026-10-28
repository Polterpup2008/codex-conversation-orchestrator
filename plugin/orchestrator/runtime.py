"""Version-only sandbox probes and narrowly bounded Windows Python RX repair."""
import base64
import hashlib
import json
import os
import pathlib
import re
import subprocess
import time
from .errors import BridgeError
from .projects import canonical, contained, path_key


PROBE = 'import json,sys; print(json.dumps({"executable":sys.executable,"version":sys.version,"version_info":list(sys.version_info[:3])}))'
WINDOWS = os.name == 'nt'


def lexical_path(value):
    value = os.fspath(value)
    if os.name == 'nt':
        if value.startswith('\\\\?\\UNC\\'): value = '\\\\'+value[8:]
        elif value.startswith('\\\\?\\'): value = value[4:]
    if not pathlib.Path(value).is_absolute():
        raise BridgeError('INVALID_RUNTIME', 'Runtime paths must be absolute.')
    return pathlib.Path(os.path.abspath(value))


def unredirected_path(value):
    original = lexical_path(value)
    if os.path.normcase(str(original)) != path_key(original):
        raise BridgeError('RUNTIME_REPAIR_UNSUPPORTED', 'Automatic ACL repair does not follow redirected runtime paths.')
    try:
        for item in [original, *original.parents]:
            if getattr(item.lstat(), 'st_file_attributes', 0) & 0x400:
                raise BridgeError('RUNTIME_REPAIR_UNSUPPORTED', 'Automatic ACL repair does not follow reparse points.')
    except OSError as exc:
        raise BridgeError('RUNTIME_REPAIR_UNSUPPORTED', 'Cannot inspect all original runtime path components.') from exc
    return original


def python_files(executable):
    target = lexical_path(executable)
    if not target.is_file() or not re.fullmatch(r'python(?:3(?:\.\d+)?)?(?:\.exe)?', target.name, re.I):
        raise BridgeError('INVALID_RUNTIME', 'Select an existing absolute Python executable, not a shell command or directory.')
    cfg = target.parent.parent/'pyvenv.cfg' if target.parent.name.casefold() in ('scripts', 'bin') else target.parent/'pyvenv.cfg'
    base = target.parent
    if cfg.is_file():
        values = dict(line.split('=', 1) for line in cfg.read_text(encoding='utf-8-sig').splitlines() if '=' in line)
        home = next((v.strip() for k, v in values.items() if k.strip().casefold() == 'home'), None)
        if not home:
            raise BridgeError('INVALID_RUNTIME', 'The existing venv does not declare its base Python home.')
        base = lexical_path(home)
    files = [target]
    if cfg.is_file():
        files.append(cfg)
    base_exe = base/'python.exe'
    if base_exe.is_file() and base_exe not in files:
        files.append(base_exe)
    for item in [base/'Lib/os.py', base/'Lib/encodings/__init__.py', *base.glob('python*.dll')]:
        if item.is_file() and item not in files:
            files.append(item)
    return target, base, files


def repairable_python_root(base, local_appdata=None):
    """Never grant RX to project trees, home directories or arbitrary runtimes."""
    parent = pathlib.Path(local_appdata or os.environ.get('LOCALAPPDATA', pathlib.Path.home()/'AppData/Local'))/'Programs/Python'
    base = unredirected_path(base)
    if path_key(base.parent) != path_key(parent) or not re.fullmatch(r'Python\d{2,4}', base.name, re.I):
        raise BridgeError('RUNTIME_REPAIR_UNSUPPORTED', 'Automatic ACL repair is limited to a standard per-user Programs/Python/PythonNN installation. Diagnose other paths under the existing project/host permissions.')
    if not (base/'python.exe').is_file() or not (base/'Lib/os.py').is_file():
        raise BridgeError('INVALID_RUNTIME', 'The base directory is not a complete standard Python installation.')
    return base


RX_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$target = $env:ORCH_PYTHON_RX_TARGET
$backup = $env:ORCH_PYTHON_RX_BACKUP
$account = New-Object System.Security.Principal.NTAccount($env:COMPUTERNAME, 'CodexSandboxUsers')
$sid = $account.Translate([System.Security.Principal.SecurityIdentifier])
$acl = Get-Acl -LiteralPath $target
$before = [ordered]@{target=$target; sid=$sid.Value; owner=$acl.Owner; protected=$acl.AreAccessRulesProtected; sddl=$acl.Sddl}
$before | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $backup -Encoding utf8
# icacls changes only the DACL; Set-Acl can unnecessarily require the SACL
# SeSecurityPrivilege on an otherwise owner-writable directory.
$grant = '*' + $sid.Value + ':(OI)(CI)(RX)'
& ($env:SystemRoot + '\System32\icacls.exe') $target '/grant' $grant | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'icacls RX grant failed' }
$after = Get-Acl -LiteralPath $target
if ($after.Owner -ne $before.owner -or $after.AreAccessRulesProtected -ne $before.protected) { throw 'Unexpected ACL owner/inheritance change' }
[ordered]@{target=$target; sid=$sid.Value; owner=$after.Owner; protected=$after.AreAccessRulesProtected; sddl=$after.Sddl; rights='ReadAndExecute'; recursive=$false; backup=$backup} | ConvertTo-Json -Depth 5 -Compress
'''


def add_python_read_execute(base, evidence_dir):
    if not WINDOWS:
        raise BridgeError('RUNTIME_REPAIR_UNSUPPORTED', 'Windows NTFS repair is unavailable on this platform.')
    base = repairable_python_root(base)
    evidence_dir = pathlib.Path(evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = evidence_dir/f'python-rx-before-{time.time_ns()}.json'
    env = os.environ.copy()
    # pwsh can export its own incompatible module paths. Windows PowerShell must
    # discover its built-in Security module from its own default environment.
    for key in list(env):
        if key.casefold() == 'psmodulepath':
            del env[key]
    env.update(ORCH_PYTHON_RX_TARGET=str(base), ORCH_PYTHON_RX_BACKUP=str(backup))
    encoded = base64.b64encode(RX_SCRIPT.encode('utf-16-le')).decode('ascii')
    result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
                            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise BridgeError('RUNTIME_REPAIR_FAILED', 'The narrow RX repair failed under current OS permissions; no elevation or sandbox-policy change was attempted.',
                          {'backup': str(backup), 'stderr': result.stderr[-3000:]})
    return json.loads(result.stdout.lstrip('\ufeff'))


class RuntimeOperations:
    def runtime_check(self, python_executable, repair_read_execute=True):
        if not self.project_scope:
            raise BridgeError('PROJECT_NOT_AUTHORIZED', 'Activate the human-designated project before checking its runtime.')
        project = self._project(self.project_scope)
        target, base, files = python_files(python_executable)
        hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}

        def probe():
            records = []
            for role in ('Developer', 'Auditor'):
                self._project(self.project_scope)
                policy = {'type': 'readOnly', 'networkAccess': False} if role == 'Auditor' else {
                    'type': 'workspaceWrite', 'writableRoots': [project['root']], 'networkAccess': False,
                    'excludeTmpdirEnvVar': True, 'excludeSlashTmp': True}
                params = {'command': [str(target), '-I', '-B', '-S', '-c', PROBE], 'cwd': project['root'],
                          'sandboxPolicy': policy, 'timeoutMs': 15000}
                try:
                    result = self.rpc.call('command/exec', params, timeout=25)
                    observed = None
                    if result.get('exitCode') == 0:
                        try:
                            observed = json.loads(result.get('stdout', ''))
                        except ValueError:
                            pass
                    ready = isinstance(observed, dict) and path_key(observed.get('executable') or '') == path_key(target)
                    records.append({'role': role, 'policy': policy, 'ready': ready, 'result': result, 'observed': observed})
                except BridgeError as exc:
                    records.append({'role': role, 'policy': policy, 'ready': False, 'error': exc.as_dict()})
            return records

        before = probe()
        repair = None
        records = before
        denied = re.search(r'access.+denied|permission denied|unable to create process|winerror.?5|acc[eè]s.+refus',
                           json.dumps(before, ensure_ascii=False), re.I)
        if not all(r['ready'] for r in before) and repair_read_execute and denied and WINDOWS:
            with self._control_operation('runtime_read_execute_repair'):
                self._project(self.project_scope)
                unredirected_path(target)
                unredirected_path(base)
                repair = add_python_read_execute(base, self.data_dir/'runtime-repairs')
            records = probe()
        self._project(self.project_scope)
        after = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        if hashes != after:
            raise BridgeError('RUNTIME_CHANGED', 'Runtime files changed during preflight; retain the evidence and recheck before dispatch.')
        result = {'project_id': project['id'], 'python_executable': str(target), 'ready': all(r['ready'] for r in records),
                  'probes': records, 'before': before, 'repair': repair, 'file_hashes': after,
                  'runtime_files_unchanged': True, 'worker_turns_started': False,
                  'hash_coverage': 'Listed executable(s), venv configuration when present, base os/encoding entry points and Python DLLs. This is not a recursive dependency/library integrity scan.',
                  'scope': 'Version-only isolated stdlib probes. No site/.pth, dependency imports, GPU workload or training. Worker approvalPolicy stays never; sandbox/network policies are unchanged.'}
        if not result['ready']:
            result['next_step'] = 'Inspect the actual failure and resolve it within existing project/host authority. Ask the human only for a genuinely missing right or product decision, never for a repeated routine Python confirmation.'
        return result
