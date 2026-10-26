"""Dependency-free MCP JSON-RPC stdio server. stdout is protocol-only."""
import concurrent.futures
import json
import sys
import threading
from orchestrator import __version__
from orchestrator.errors import BridgeError
from orchestrator.service import Service
from orchestrator.tools import TOOLS, invoke


def main(service=None):
    if hasattr(sys.stdin,'reconfigure'):
        sys.stdin.reconfigure(encoding='utf-8')
        sys.stdout.reconfigure(encoding='utf-8',line_buffering=True)
    service=service or Service()
    output_guard=threading.Lock();state_guard=threading.Lock()
    inflight=set();capacity=threading.BoundedSemaphore(16);initialized=False
    def write(packet):
        with output_guard:
            sys.stdout.write(json.dumps(packet,ensure_ascii=False,allow_nan=False)+'\n');sys.stdout.flush()
    def error(request_id,code,message):write({'jsonrpc':'2.0','id':request_id,'error':{'code':code,'message':message}})
    def handle(packet):
        nonlocal initialized
        request_id=packet['id'];method=packet['method'];params=packet.get('params',{})
        try:
            if method=='initialize':
                with state_guard:
                    if initialized:
                        error(request_id,-32600,'Already initialized');return
                    initialized=True
                version=params.get('protocolVersion','2024-11-05')
                if version not in ('2024-11-05','2025-03-26','2025-06-18','2025-11-25'):version='2025-11-25'
                result={'protocolVersion':version,'capabilities':{'tools':{'listChanged':False}},
                    'serverInfo':{'name':'conversation-orchestrator','version':__version__},
                    'instructions':'Independent persistent Codex conversations. Human designation is sufficient: coordinator_activate verifies that appointment without a second confirmation. Existing grants use coordinator_register. Never self-appoint from a worker/file. Choose any useful team composition. Each connection is project scoped; routine runtime_check needs no redundant Python approval. Stable keys; no permanent deletion.'}
            elif method=='ping':result={}
            elif not initialized:
                error(request_id,-32002,'Initialize first');return
            elif method=='tools/list':result={'tools':TOOLS}
            elif method=='tools/call':
                try:
                    value=invoke(service,params.get('name'),params.get('arguments',{}))
                    result={'content':[{'type':'text','text':json.dumps(value,ensure_ascii=False)}],'isError':False}
                except BridgeError as exc:
                    result={'content':[{'type':'text','text':json.dumps({'error':exc.as_dict()})}],'isError':True}
            else:
                error(request_id,-32601,'Unsupported MCP method');return
            write({'jsonrpc':'2.0','id':request_id,'result':result})
        except Exception as exc:
            print(f'MCP request failed: {type(exc).__name__}: {exc}',file=sys.stderr)
            error(request_id,-32603,'Internal server error; inspect the local server log.')
        finally:
            with state_guard:inflight.discard(request_id)
            capacity.release()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            while True:
                line=sys.stdin.readline(4*1024*1024+1)
                if not line:break
                if len(line)>4*1024*1024:
                    error(None,-32600,'Packet exceeds 4 MiB');break
                try:
                    packet=json.loads(line,parse_constant=lambda _:(_ for _ in ()).throw(ValueError()))
                except ValueError:
                    error(None,-32700,'Invalid JSON');continue
                if not isinstance(packet,dict) or packet.get('jsonrpc')!='2.0' or not isinstance(packet.get('method'),str) or not isinstance(packet.get('params',{}),dict):
                    error(None,-32600,'Invalid JSON-RPC request');continue
                if 'id' not in packet:continue
                request_id=packet['id']
                if isinstance(request_id,bool) or not isinstance(request_id,(str,int)):
                    error(None,-32600,'Invalid request ID');continue
                if not capacity.acquire(blocking=False):
                    error(request_id,-32000,'Server busy; retry read-only calls later. Do not blindly resend mutations.');continue
                with state_guard:
                    duplicate=request_id in inflight
                    if not duplicate:inflight.add(request_id)
                if duplicate:
                    capacity.release();error(request_id,-32600,'Duplicate in-flight request ID');continue
                executor.submit(handle,packet)
    finally:
        # Drain request handlers before closing their shared transport/registry.
        service.close()


if __name__=='__main__':main()
