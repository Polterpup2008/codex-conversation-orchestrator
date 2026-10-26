"""Current MCP stdio bridge for the SAME original coordinator; no app restart."""
import argparse
import json
import pathlib
import os
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from orchestrator.errors import BridgeError
from orchestrator.handoff import project_bridge_register,project_bridge_prepare,preflight_project_bridge
from orchestrator.service import Service
from orchestrator.tools import validate,KEY
import server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    modes=parser.add_mutually_exclusive_group()
    modes.add_argument('--handoff',action='store_true',help='Fence the old idle scope after preparation and its recent successful bridge_release.')
    modes.add_argument('--prepare-handoff',action='store_true',help='Install release observation while this project is idle, without changing its owner or grants; exits before MCP.')
    parser.add_argument('--data-dir',type=pathlib.Path)
    args=parser.parse_args();validate(args.project,KEY)
    data=args.data_dir or pathlib.Path(os.environ.get('ORCHESTRATOR_DATA_DIR') or pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))/'conversation-orchestrator')
    preflight_project_bridge(data,args.project,args.handoff,args.prepare_handoff)
    service=Service(data)
    try:
        if args.prepare_handoff:
            print(json.dumps(project_bridge_prepare(service,args.project)));return
        project_bridge_register(service,args.project,args.handoff)
        server.main(service)
    finally:service.close()


if __name__=='__main__':
    try:main()
    except BridgeError as exc:
        print(json.dumps({'error':exc.as_dict()}),file=sys.stderr);raise SystemExit(1)
