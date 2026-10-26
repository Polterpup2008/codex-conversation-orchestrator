"""Print the current chat identity with a bridge nonce; writes no files/state."""
import argparse
import os
import re
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--challenge', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{32}', args.challenge):
        raise SystemExit('Use the exact challenge from this connection bridge_status.')
    current = os.environ.get('CODEX_THREAD_ID', '')
    try: uuid.UUID(current)
    except ValueError: raise SystemExit('This shell has no genuine CODEX_THREAD_ID; run inside the actual designated chat.')
    print('ORCHESTRATOR_CALLER:'+args.challenge+':'+current)


if __name__ == '__main__': main()
