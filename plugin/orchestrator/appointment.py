"""Corroborate a human appointment in the caller's native local conversation.

This is an accidental-role guard for a trusted OS account, not authentication
against someone able to rewrite Codex session files.
"""
import hashlib
import json
import os
import pathlib
import re
import unicodedata
from .errors import BridgeError
from .projects import canonical, contained, path_key


def native_path(thread, codex_home=None):
    home = pathlib.Path(codex_home or os.environ.get('CODEX_HOME', pathlib.Path.home()/'.codex'))
    path = pathlib.Path(canonical(thread.get('path') or ''))
    if not contained(path, home/'sessions') and not contained(path, home/'archived_sessions'):
        raise BridgeError('APPOINTMENT_UNVERIFIED', 'The native conversation path is outside this Codex profile.')
    return path


def caller_proof(thread, challenge, codex_home=None):
    """Bind a bridge nonce to a native shell output in the claimed current chat."""
    path = native_path(thread, codex_home)
    expected = 'ORCHESTRATOR_CALLER:'+challenge+':'+thread['id']
    metadata = None; calls = set(); proof = None
    try:
        for number, line in enumerate(path.open(encoding='utf-8'), 1):
            try: packet = json.loads(line)
            except ValueError: continue
            item = packet.get('payload', {})
            if packet.get('type') == 'session_meta':
                metadata = item; calls.clear(); proof = None
                continue
            if not metadata or metadata.get('id') != thread['id'] or packet.get('timestamp', '') < metadata.get('timestamp', ''):
                continue
            if packet.get('type') != 'response_item': continue
            if item.get('type') in ('function_call', 'custom_tool_call') and item.get('name') in ('exec', 'exec_command', 'functions.exec', 'functions.exec_command'):
                calls.add(item.get('call_id'))
            if item.get('type') in ('function_call_output', 'custom_tool_call_output') and item.get('call_id') in calls and expected in str(item.get('output', '')):
                proof = {'source': 'native_shell_challenge', 'call_id': item['call_id'], 'line': number,
                         'challenge_sha256': hashlib.sha256(challenge.encode()).hexdigest()}
    except OSError as exc:
        raise BridgeError('APPOINTMENT_CALLER_UNAVAILABLE', 'Cannot read the native caller UUID proof.', {'reason': str(exc)}) from exc
    if not proof or not metadata or metadata.get('id') != thread['id'] or path_key(metadata['cwd']) != path_key(thread['cwd']):
        raise BridgeError('APPOINTMENT_CALLER_UNAVAILABLE', 'The MCP host did not supply its caller UUID. Read bridge_status.caller_probe and run its read-only command in THIS chat shell, then retry coordinator_activate on this SAME connection. No registry write or second human authorization is needed.')
    return proof


def plain(value):
    return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))


def is_appointment(quote):
    text = plain(quote).strip()
    if any(mark in text for mark in ('?', '`', '<', '>', '\n')):
        return False
    if re.search(r'\b(?:not|never|pas|jamais|ne|neither|but|mais|unless|sauf)\b', text):
        return False
    prefix = r'(?:(?:ok|okay|bon|maintenant|desormais|now|please|a partir de maintenant)[,:]?\s+)*'
    french_role = r'(?:orchestrateur|orchestratrice|coordinateur|coordinatrice)'
    english_role = r'(?:orchestrator|coordinator)'
    fr_article = r'(?:(?:le|la|mon|notre|votre|unique|seul|un|une|desormais|maintenant)\s+|l[’\x27]){0,5}'
    en_article = r'(?:(?:the|a|an|my|our|now|sole|only|project)\s+){0,5}(?:technical director/)?'
    # Explicit grammar: no arbitrary verb-to-role gap or third-party recipient.
    french = (r'(?:je (?:te|vous) (?:nomme|designe) (?:comme )?|'
              r'je designe (?:ce|cet) chat comme |je veux que tu (?:sois|deviennes) |'
              r'(?:tu (?:es|seras|deviens)|vous (?:etes|serez|devenez)|deviens) |'
              r'(?:(?:prends|prend|assume|endosse|adopte) (?:desormais )?(?:(?:le|ton) )?|je (?:te|vous) confie le |je veux que tu prennes le )role d[’\x27])')
    english = r'(?:i (?:hereby )?appoint (?:this chat|you) (?:as )?|i want you to (?:be|become|act as) |you (?:are|will be) |(?:act|serve) as |become )'
    tail = r'(?:\s+(?:of|for|in|on|du|de|pour|dans)\s+[^.!?;:<>]{1,180})?[.!;]?'
    return bool(re.fullmatch(prefix + '(?:'+french+fr_article+french_role+'|'+english+en_article+english_role+')'+tail, text))


def direct_directive(text, quote):
    """A designation starts the actionable request, not a later pasted report."""
    raw_lines = [line for line in text.splitlines() if line.strip()]
    if any(line.startswith(('    ', '\t')) for line in raw_lines[:4]):
        return False
    lines = [line.strip() for line in raw_lines]
    for index, line in enumerate(lines):
        if line == quote or (quote.endswith(('.', '!', ';')) and line.startswith(quote)):
            return is_appointment(quote)
        # Common activation prompts ask to read the contract before appointing.
        if index >= 3 or len(line) > 250 or not re.fullmatch(
                r'(?:lis|lisez|read|charge|load)\s+(?:(?:integralement|entierement|le|fichier|the|file|this project.s)\s+)*'
                r'["\x27]?orchestrator\.md["\x27]?(?:\s+(?:completely|integralement|de ce projet|of this project))*[.!]?', plain(line)):
            return False
    return False


def withdraws_appointment(text):
    first = plain(text.strip().splitlines()[0]) if text.strip() else ''
    return bool(re.search(r'^(?:you (?:are no longer|are not|will no longer be|must not be) (?:the |my |our |a |an )?(?:coordinator|orchestrator)|'
                          r'(?:stop|cease) (?:acting|serving) as (?:the )?(?:coordinator|orchestrator)|'
                          r'i (?:revoke|withdraw) (?:that|the|your|this) appointment|'
                          r'(?:do not|don.t) (?:act|serve) as (?:the )?(?:coordinator|orchestrator)|'
                          r'je (?:retire|revoque) (?:ta|votre|cette|la) (?:nomination|designation)|'
                          r'(?:tu n.es (?:plus|pas)|vous n.etes (?:plus|pas)|ne sois (?:plus|pas)) (?:l.|mon |le |la )?(?:orchestrateur|coordinateur|coordinatrice))\b', first))


def appointment_proof(thread, quote, codex_home=None):
    if not is_appointment(quote):
        raise BridgeError('APPOINTMENT_REQUIRED', 'Use the exact direct human designation already present in this chat, such as Je te nomme orchestrateur de ce projet. Reading a file or a worker report is not an appointment.')
    path = native_path(thread, codex_home)
    metadata = None
    proof = None
    try:
        with path.open(encoding='utf-8') as stream:
            for number, line in enumerate(stream, 1):
                try:
                    packet = json.loads(line)
                except ValueError:
                    continue  # an in-flight final line can be incomplete
                item = packet.get('payload', {})
                if packet.get('type') == 'session_meta':
                    metadata = item
                    proof = None  # no designation can cross a fork/session header
                    continue
                if packet.get('type') != 'response_item' or item.get('role') != 'user':
                    continue
                if metadata is None or metadata.get('id') != thread['id'] or packet.get('timestamp', '') < metadata.get('timestamp', ''):
                    continue  # do not reuse a designation inherited from a fork
                provenance = item.get('internal_chat_message_metadata_passthrough') or {}
                parts = provenance.get('content_item_metadata')
                kinds = provenance.get('content_item_kinds')
                if not isinstance(parts, list) or not isinstance(kinds, list):
                    continue  # role=user alone can be a forwarded/generated message
                for index, content in enumerate(item.get('content', [])):
                    if content.get('type') != 'input_text':
                        continue
                    if parts is not None:
                        if index >= len(parts) or parts[index].get('provenance', {}).get('type') != 'user':
                            continue
                    if kinds is not None and (index >= len(kinds) or kinds[index] != 'user.text'):
                        continue
                    text = content.get('text', '')
                    if any(marker in text for marker in ('<codex_delegation', '[orchestrator-message:', 'ORCHESTRATOR_MESSAGE_', 'Assigned registry role:', '<send_user_message_question_reply>')):
                        continue
                    # Desktop attachment headers are provenance, not directives.
                    if '# Files ' in text:
                        text = text.split('## My request:', 1)[-1] if '## My request:' in text else ''
                    if withdraws_appointment(text):
                        proof = None
                    if direct_directive(text, quote):
                        proof = {'source': 'native_human_appointment', 'message_id': item.get('id'),
                                 'line': number, 'quote_sha256': hashlib.sha256(quote.encode()).hexdigest()}
    except OSError as exc:
        raise BridgeError('APPOINTMENT_UNVERIFIED', 'Cannot read the native appointment record.', {'reason': str(exc)}) from exc
    if not metadata or metadata.get('id') != thread['id'] or path_key(metadata['cwd']) != path_key(thread['cwd']):
        raise BridgeError('APPOINTMENT_UNVERIFIED', 'Session identity/root does not match the actual coordinator.')
    if not proof:
        raise BridgeError('APPOINTMENT_UNVERIFIED', 'The supplied designation was not found as a direct human instruction in this conversation. Do not fabricate evidence or ask for a redundant grant; retrieve the original human wording.')
    return proof
