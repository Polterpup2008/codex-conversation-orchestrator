"""Compatibility entry point for an appointed chat whose tool list is still old.

Run with the installed package's interpreter. This creates no worker or model
turn, preserves existing IDs, and leaves registration to the original MCP chat.
"""
import argparse
import json
import sys
from orchestrator.errors import BridgeError
from orchestrator.service import Service
from orchestrator.tools import invoke


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project-id', required=True)
    parser.add_argument('--coordinator', required=True)
    parser.add_argument('--appointment-quote', required=True)
    parser.add_argument('--desktop-ui-project-id')
    parser.add_argument('--desktop-project-id')
    parser.add_argument('--headless', action='store_true')
    args = parser.parse_args()
    service = Service()
    try:
        values = {'project_id': args.project_id, 'coordinator_thread_id': args.coordinator,
                  'appointment_quote': args.appointment_quote, 'headless': args.headless}
        for key in ('desktop_ui_project_id', 'desktop_project_id'):
            if getattr(args, key):
                values[key] = getattr(args, key)
        result = invoke(service, 'coordinator_activate', values)
        result['next_step'] = 'Call coordinator_register with these same IDs in the original chat. No second user grant is needed.'
        print(json.dumps(result, ensure_ascii=False))
    finally:
        service.close()


if __name__ == '__main__':
    try:
        main()
    except BridgeError as exc:
        print(json.dumps({'error': exc.as_dict()}), file=sys.stderr)
        raise SystemExit(1)
