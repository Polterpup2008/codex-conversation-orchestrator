"""Multiplexed JSONL App Server transport. No credentials or private endpoints."""
import json
import os
import pathlib
import queue
import shutil
import subprocess
import threading
import time
import uuid
import tomllib
import logging
import logging.handlers
from .errors import BridgeError
from . import __version__


def toml_value(value):
    if isinstance(value,str):return json.dumps(value,ensure_ascii=True)
    if isinstance(value,bool):return str(value).lower()
    if isinstance(value,(int,float)):return str(value)
    if isinstance(value,list):return '['+','.join(toml_value(v) for v in value)+']'
    if isinstance(value,dict):return '{'+','.join(json.dumps(k)+'='+toml_value(v) for k,v in value.items() if v is not None)+'}'
    raise BridgeError('UNSUPPORTED_CONFIG_VALUE','Integration configuration contains an unsupported TOML value.')


def merge_config(target,source):
    for key,value in source.items():
        if isinstance(value,dict) and isinstance(target.get(key),dict):merge_config(target[key],value)
        else:target[key]=value


def integration_policy(config,allow_integrations=()):
    return {section:{name:{'enabled':f'{section}.{name}' in allow_integrations and 'conversation-orchestrator' not in name and name!='conversation_orchestrator'} for name in config.get(section,{})} for section in ('mcp_servers','plugins') if config.get(section)}


class AppServer:
    def __init__(self, data_dir, on_event=lambda *_: None, executable=None, workspace=None, allow_integrations=(),on_question=None,generation=None,strict_windows_sandbox=None):
        self.pending, self.completed, self.active = {}, {}, set()
        self.guard, self.write_guard = threading.RLock(), threading.Lock()
        self.changed = threading.Condition(self.guard)
        self.counter, self.closed, self.on_event = 0, False, on_event
        self.on_question=on_question;self.input_requests={}
        self.generation=generation or str(uuid.uuid4())
        executable = executable or os.environ.get('ORCHESTRATOR_CODEX') or shutil.which('codex')
        if not executable:
            raise BridgeError('CODEX_NOT_FOUND', 'Install the official Codex CLI and sign in with ChatGPT.')
        # Workers need shell/files only. Disabling inherited integrations prevents recursive
        # bridge startups and unrelated MCP side effects; this is a process-local override.
        command = [executable, 'app-server', '--listen', 'stdio://']
        # Legacy elevated workers share an OS account: OWNER RIGHTS can leave
        # their new files writable to later read-only/foreign-project commands.
        # MXC enforces the per-command policy independently of creator ACLs.
        # Explicit selection fails if unsupported; never silently weaken it.
        self.strict_windows_sandbox = os.name=='nt' if strict_windows_sandbox is None else bool(strict_windows_sandbox)
        if self.strict_windows_sandbox:command += ['-c','windows.sandbox="mxc"']
        command += ['-c','features.hooks=false','-c','features.multi_agent=false','-c','features.apps=false']
        home = pathlib.Path(os.environ.get('CODEX_HOME', pathlib.Path.home()/'.codex'))
        config_files=[home/'config.toml']
        if workspace:
            path=pathlib.Path(workspace)
            config_files += [p/'.codex/config.toml' for p in reversed([path,*path.parents])]
        effective={}
        for config_file in config_files:
            if not config_file.is_file():continue
            config=tomllib.loads(config_file.read_text(encoding='utf-8-sig'))
            merge_config(effective,config)
        profile=effective.get('profiles',{}).get(effective.get('profile'),{})
        merge_config(effective,profile)
        for section,overrides in integration_policy(effective,allow_integrations).items():
            # CLI override paths split on dots without parsing quoted components.
            # Override the complete table with a TOML literal instead.
            # Tables merge with existing config. Pass only enablement booleans:
            # original env/arguments may contain credentials and must stay out of
            # the parent App Server command line.
            if overrides:command+=['-c',section+'='+toml_value(overrides)]
        data_dir = pathlib.Path(data_dir); data_dir.mkdir(parents=True, exist_ok=True,mode=0o700)
        for old in sorted(data_dir.glob('app-server-v03-*.log*'),key=lambda p:p.stat().st_mtime,reverse=True)[60:]:
            try:old.unlink()
            except OSError:pass
        self.stderr=logging.handlers.RotatingFileHandler(data_dir/f'app-server-v03-{os.getpid()}-{time.time_ns()}.log',maxBytes=2*1024*1024,backupCount=2,encoding='utf-8')
        try:
            self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, encoding='utf-8', bufsize=1,cwd=workspace,
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        except OSError as e:
            self.stderr.close()
            raise BridgeError('CONNECTION_FAILED', str(e)) from e
        def drain_stderr():
            for line in self.process.stderr:
                self.stderr.emit(logging.LogRecord('app-server',logging.INFO,'',0,line.rstrip(),(),None))
        self._stderr_thread=threading.Thread(target=drain_stderr,daemon=True);self._stderr_thread.start()
        self._reader_thread=threading.Thread(target=self._read,daemon=True);self._reader_thread.start()
        try:
            self.identity = self.call('initialize', {'clientInfo': {'name': 'conversation_orchestrator',
                'version': __version__}, 'capabilities': {'experimentalApi': True}})
            self._write({'method': 'initialized', 'params': {}})
            account = self.call('account/read', {}).get('account') or {}
            if account.get('type') != 'chatgpt':
                raise BridgeError('SUBSCRIPTION_REQUIRED', 'Bridge requires existing ChatGPT authentication. API-key billing is disabled.')
        except Exception:
            self.close()
            raise

    def _write(self, packet):
        with self.write_guard:
            try:
                self.process.stdin.write(json.dumps(packet, ensure_ascii=False)+'\n')
                self.process.stdin.flush()
            except (OSError, ValueError) as e:
                raise BridgeError('CONNECTION_LOST', str(e)) from e

    def call(self, method, params, timeout=40):
        with self.guard:
            if self.closed:
                raise BridgeError('CONNECTION_LOST', 'App Server connection is closed; resume/reconcile before retrying mutations.')
            self.counter += 1; key = self.counter
            response = self.pending[key] = queue.Queue(maxsize=1)
        try:
            self._write(dict(id=key, method=method, params=params))
            try:
                packet = response.get(timeout=timeout)
            except queue.Empty as e:
                raise BridgeError('RPC_TIMEOUT', f'{method} timed out; its outcome may be unknown. No automatic retry.', {'method': method}) from e
            if 'error' in packet:
                raise BridgeError('RPC_ERROR', packet['error'].get('message', str(packet['error'])), {'method':method, **packet['error']})
            return packet['result']
        finally:
            with self.guard:
                self.pending.pop(key, None)

    def _read(self):
        failure = 'App Server closed its output stream.'
        try:
            for line in self.process.stdout:
                packet = json.loads(line)
                if 'id' in packet and 'method' not in packet:
                    with self.guard:
                        destination = self.pending.get(packet['id'])
                    if destination:
                        try:destination.put_nowait(packet)
                        except queue.Full:pass
                elif 'id' in packet:
                    if packet.get('method')=='item/tool/call' and packet.get('params',{}).get('tool')=='orchestrator_question' and packet['params'].get('namespace') in (None,'') and self.on_question:
                        try:
                            with self.guard:
                                if len(self.input_requests)>=64:raise BridgeError('QUESTION_CAPACITY','Too many pending worker questions.')
                                if packet['id'] in self.input_requests:raise BridgeError('QUESTION_ID_CONFLICT','Duplicate live server request ID; refusing to overwrite its question.')
                                self.input_requests[packet['id']]=packet['params']
                            self.on_question(packet['id'],packet['params'],self.generation)
                            continue
                        except Exception:
                            with self.guard:self.input_requests.pop(packet['id'],None)
                    # There is no user approval UI here. Never silently approve requests.
                    self._write({'id': packet['id'], 'error': {'code': -32601,
                        'message': 'Unattended bridge cannot fulfill interactive server requests.'}})
                    self.on_event('bridge/unsupportedRequest', {'method': packet.get('method')})
                else:
                    method, params = packet.get('method'), packet.get('params', {})
                    if method=='serverRequest/resolved':
                        with self.guard:self.input_requests.pop(params.get('requestId'),None)
                    if method == 'turn/started':
                        with self.guard:
                            self.active.add((params['threadId'], params['turn']['id']))
                    # Commit lifecycle evidence before waking waiters; avoids event/result races.
                    self.on_event(method, params)
                    if method == 'turn/completed':
                        with self.changed:
                            for key,value in list(self.input_requests.items()):
                                if value['threadId']==params['threadId'] and value['turnId']==params['turn']['id']:self.input_requests.pop(key,None)
                            self.active.discard((params['threadId'], params['turn']['id']))
                            self.completed[(params['threadId'], params['turn']['id'])] = params['turn']
                            while len(self.completed)>256:self.completed.pop(next(iter(self.completed)))
                            self.changed.notify_all()
        except Exception as e:
            failure = f'App Server reader failed: {type(e).__name__}: {e}'
        finally:
            with self.changed:
                self.closed = True
                for destination in self.pending.values():
                    try:
                        destination.put_nowait({'error': {'code': -32001, 'message': failure}})
                    except queue.Full:
                        pass
                self.changed.notify_all()

    def has_question(self,request_id,*,generation,thread_id,turn_id,call_id):
        with self.guard:
            pending=self.input_requests.get(request_id)
            return not self.closed and generation==self.generation and pending is not None and (pending['threadId'],pending['turnId'],pending['callId'])==(thread_id,turn_id,call_id)

    def reply_question(self,request_id,result,**identity):
        with self.guard:
            if not self.has_question(request_id,**identity):raise BridgeError('QUESTION_EXPIRED','The exact originating worker question/transport generation is no longer pending.')
            self._write({'id':request_id,'result':result})
            self.input_requests.pop(request_id,None)

    def wait(self, thread_id, turn_id, seconds):
        deadline = time.monotonic()+seconds
        with self.changed:
            while (thread_id, turn_id) not in self.completed:
                if self.closed:
                    raise BridgeError('CONNECTION_LOST', 'App Server disconnected while waiting. Resume and reconcile the saved message key.')
                remaining = deadline-time.monotonic()
                if remaining <= 0:
                    return None
                self.changed.wait(remaining)
            return self.completed[(thread_id, turn_id)]

    def close(self):
        if not hasattr(self, 'process'):
            return
        try:
            self.process.stdin.close()
            self.process.wait(timeout=4)
        except (OSError, subprocess.TimeoutExpired):
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill(); self.process.wait(timeout=5)
        if hasattr(self,'_stderr_thread'):self._stderr_thread.join(timeout=2)
        if hasattr(self,'_reader_thread') and threading.current_thread()!=self._reader_thread:self._reader_thread.join(timeout=2)
        self.stderr.close()
