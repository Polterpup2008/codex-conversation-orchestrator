"""Actual MCP client for protocol and end-to-end tests."""
import json
import os
import pathlib
import queue
import subprocess
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parents[1]


class MCPClient:
    def __init__(self, data_dir=None, server_path=None, extra_env=None):
        env = os.environ.copy()
        env.update(extra_env or {})
        if data_dir:
            env['ORCHESTRATOR_DATA_DIR'] = str(data_dir)
        (ROOT/'evidence').mkdir(exist_ok=True)
        self.stderr = (ROOT/'evidence'/f'mcp-client-{os.getpid()}.log').open('a', encoding='utf-8')
        self.process = subprocess.Popen([sys.executable, str(server_path or ROOT/'plugin'/'server.py')],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr, text=True,
            encoding='utf-8', env=env, creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.counter = 0; self.pending = {}; self.lock = threading.Lock()
        def reader():
            for line in self.process.stdout:
                packet = json.loads(line)
                with self.lock:
                    target = self.pending.get(packet.get('id'))
                if target:
                    target.put(packet)
        threading.Thread(target=reader, daemon=True).start()
        self.initialization=self.request('initialize', {'protocolVersion': '2025-03-26', 'clientInfo': {'name': 'experiment', 'version': '1'}, 'capabilities': {}})
        self.process.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n'); self.process.stdin.flush()

    def request(self, method, params, timeout=65):
        with self.lock:
            self.counter += 1; key = self.counter; out = queue.Queue()
            self.pending[key] = out
            self.process.stdin.write(json.dumps({'jsonrpc':'2.0','id':key,'method':method,'params':params})+'\n'); self.process.stdin.flush()
        try:
            return out.get(timeout=timeout)
        finally:
            with self.lock:
                self.pending.pop(key, None)

    def call(self, tool_name, **arguments):
        packet = self.request('tools/call', {'name':tool_name,'arguments':arguments})
        if 'error' in packet:
            raise RuntimeError(packet['error'])
        result = packet['result']; value = json.loads(result['content'][0]['text'])
        if result.get('isError'):
            raise RuntimeError(value)
        return value

    def close(self):
        self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate(); self.process.wait(timeout=10)
        self.stderr.close()
