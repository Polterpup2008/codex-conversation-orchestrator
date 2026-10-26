"""Installed operator entry point for already approved artifact locations."""
import argparse
import json
import os
import pathlib
import sys
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
from orchestrator.artifacts import operator_artifact_change
from orchestrator.errors import BridgeError
from orchestrator.storage import Registry
from orchestrator.tools import validate, KEY


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir',type=pathlib.Path)
    parser.add_argument('action',choices=('grant','revoke'))
    parser.add_argument('project_id');parser.add_argument('root',type=pathlib.Path)
    parser.add_argument('--reason',required=True,help='Existing human-approved artifact-location authority.')
    parser.add_argument('--create',action='store_true',help='Create only a new final directory with a verified existing parent.')
    args=parser.parse_args();validate(args.project_id,KEY)
    data=args.data_dir or pathlib.Path(os.environ.get('ORCHESTRATOR_DATA_DIR') or pathlib.Path(os.environ.get('CODEX_HOME',pathlib.Path.home()/'.codex'))/'conversation-orchestrator')
    result=operator_artifact_change(Registry(data/'registry.sqlite3'),data,args.project_id,args.root,args.reason,
        create=args.create,enabled=args.action=='grant')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    try:main()
    except BridgeError as exc:
        print(json.dumps({'error':exc.as_dict()}),file=sys.stderr);raise SystemExit(1)
