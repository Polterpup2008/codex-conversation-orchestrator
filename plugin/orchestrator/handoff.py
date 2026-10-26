"""A same-chat, idle-project handoff to a current stdio bridge; no host restart."""
import datetime
import contextlib
import json
import os
import time
import pathlib
import sqlite3
from .appointment import native_path
from .errors import BridgeError
from .projects import path_key

RELEASE_TOOL='mcp__conversation_orchestrator__bridge_release'
RELEASE_COMMAND='text(await tools.'+RELEASE_TOOL+'({}));'


def _released(value):
    """Decode actual tool envelopes, never search arbitrary printed text."""
    if isinstance(value,str):
        try:return _released(json.loads(value))
        except (ValueError,RecursionError):
            if value.startswith('{\\"'):
                try:return _released(json.loads(value.replace('\\"','"')))
                except (ValueError,RecursionError):pass
            return False
    if isinstance(value,list):
        return any(_released(item.get('text')) for item in value if isinstance(item,dict) and item.get('type')=='input_text')
    if not isinstance(value,dict) or value.get('isError') is True:return False
    if value.get('released') is True and value.get('histories_preserved') is True:return True
    return any(_released(item.get('text')) for item in value.get('content',[]) if isinstance(item,dict) and item.get('type')=='text')


def _release_call(item):
    if item.get('name')==RELEASE_TOOL:
        try:args=json.loads(item.get('arguments','{}'))
        except (ValueError,TypeError):return False
        return args=={}
    if item.get('name') not in ('exec','functions.exec'):return False
    # Only this documented standalone wrapper is supported. Reports, another
    # namespace and arbitrary JS are not release evidence.
    command=item.get('arguments') or item.get('input') or ''
    return isinstance(command,str) and command.strip()==RELEASE_COMMAND


def recent_release_proof(thread,after,release,codex_home=None,now=None):
    """Bind native success to the owning bridge's observed control generation."""
    path=native_path(thread,codex_home);calls={};proof=None;meta=None
    with path.open(encoding='utf-8') as stream:
        for number,line in enumerate(stream,1):
            try:packet=json.loads(line)
            except ValueError:continue
            item=packet.get('payload',{})
            if packet.get('type')=='session_meta':meta=item;calls.clear();proof=None;continue
            if not meta or meta.get('id')!=thread['id'] or packet.get('timestamp','')<meta.get('timestamp',''):
                continue
            if packet.get('type')!='response_item':continue
            try:stamp=datetime.datetime.fromisoformat(packet['timestamp'].replace('Z','+00:00')).timestamp()
            except (ValueError,KeyError):continue
            if item.get('type') in ('function_call','custom_tool_call') and _release_call(item):
                calls[item.get('call_id')]=stamp
            elif item.get('type') in ('function_call','custom_tool_call') and RELEASE_TOOL.rsplit('__',1)[0]+'__' in str(item):
                calls.clear();proof=None
            if item.get('type') in ('function_call_output','custom_tool_call_output') and item.get('call_id') in calls and _released(item.get('output')):
                start=calls[item['call_id']]
                # SQLite's Windows VFS clock can lag the native precise clock
                # by a timer tick. The generation fence supplies ordering;
                # this bounded 50ms allowance only correlates the two clocks.
                if release.get('finished') is not None and start-0.050<=release['started']<=release['finished']<=stamp+0.050:
                    proof={'source':'native_owner_bridge_release','call_id':item['call_id'],'line':number,'timestamp':start,
                           'owner_token':release['token'],'control_revision':release['revision']}
    current=time.time() if now is None else now
    if not meta or meta.get('id')!=thread['id'] or path_key(meta['cwd'])!=path_key(thread['cwd']) or not proof or proof['timestamp']<after or not 0<=current-proof['timestamp']<=300:
        raise BridgeError('BRIDGE_RELEASE_REQUIRED','After prepare-handoff and all project sends resolve, execute exactly: '+RELEASE_COMMAND+' Then start --handoff within five minutes. A report or another bridge release is insufficient.')
    return proof


def _idle(db,project_id):
    if db.execute('SELECT 1 FROM control_lock').fetchone() or db.execute('SELECT 1 FROM operations o JOIN conversations c ON c.thread_id=o.thread_id WHERE c.project_id=?',(project_id,)).fetchone() or db.execute("SELECT 1 FROM creations WHERE state='preparing' AND (project_id=? OR project_id IS NULL)",(project_id,)).fetchone():
        raise BridgeError('PROJECT_BUSY','Resolve control and lifecycle operations before handing off this project.')
    if db.execute("SELECT 1 FROM messages m JOIN conversations c ON c.thread_id=m.thread_id WHERE c.project_id=? AND m.state IN ('preparing','sent','unknown')",(project_id,)).fetchone():
        raise BridgeError('PROJECT_BUSY','All this project sends must be terminal before handoff.')


def _handoff_release(db,project_id,grant):
    intent=db.execute('SELECT * FROM bridge_handoffs WHERE project_id=?',(project_id,)).fetchone()
    lease=db.execute('SELECT owner_token FROM coordinator_leases WHERE project_id=?',(project_id,)).fetchone()
    if not intent or not lease or intent['owner_token']!=lease['owner_token'] or intent['epoch']!=grant['created']:
        raise BridgeError('BRIDGE_HANDOFF_NOT_PREPARED','Run project_bridge.py --project ORIGINAL_ID --prepare-handoff in the original coordinator shell before releasing the old bridge.')
    activity=db.execute('SELECT * FROM bridge_control_activity WHERE token=?',(intent['owner_token'],)).fetchone()
    if not activity or activity['revision']<=intent['baseline_revision'] or activity['name']!='bridge_release' or activity['finished'] is None:
        raise BridgeError('BRIDGE_RELEASE_REQUIRED','The owning bridge must complete bridge_release after prepare-handoff, with no subsequent control call.')
    return dict(intent),dict(activity)


def _original(service,project_id):
    caller=os.environ.get('CODEX_THREAD_ID')
    grants=service.registry.rows('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,))
    if not caller or not grants or grants[0]['coordinator_thread_id']!=caller:
        raise BridgeError('COORDINATOR_CONFLICT','Run this helper only in the original human-designated coordinator native shell. Reading a file or specifying another UUID is insufficient.')
    project=service.registry.one('projects','id',project_id)
    if os.path.normcase(os.path.abspath(project['root']))!=path_key(project['root']):
        raise BridgeError('SCOPE_LOST','The original source root resolves elsewhere.')
    identities=service.registry.rows('SELECT project_id,role FROM conversations WHERE thread_id=?',(caller,))
    if any(x['project_id']!=project_id or x['role'].lower()!='coordinator' for x in identities):
        raise BridgeError('ROLE_CONFLICT','A worker or foreign project member cannot take this coordinator connection.')
    thread=service.rpc.call('thread/read',{'threadId':caller,'includeTurns':False})['thread']
    if path_key(thread['cwd'])!=path_key(project['root']):raise BridgeError('PROJECT_CONFLICT','Original coordinator root differs from the existing grant.')
    return caller,grants[0],thread


def project_bridge_prepare(service,project_id):
    """Install observation before the old release; retain all existing leases."""
    caller,grant,thread=_original(service,project_id)
    with service.registry.transaction() as db:
        _idle(db,project_id)
        current=db.execute('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,)).fetchone()
        if not current or current['coordinator_thread_id']!=caller or current['created']!=grant['created']:
            raise BridgeError('COORDINATOR_CONFLICT','The authorization changed during preparation.')
        lease=db.execute('SELECT owner_token FROM coordinator_leases WHERE project_id=?',(project_id,)).fetchone()
        if not lease:raise BridgeError('COORDINATOR_CONFLICT','No existing coordinator lease to hand off.')
        activity=db.execute('SELECT revision FROM bridge_control_activity WHERE token=?',(lease['owner_token'],)).fetchone()
        prepared=time.time()
        db.execute('INSERT INTO bridge_handoffs VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET owner_token=excluded.owner_token,baseline_revision=excluded.baseline_revision,epoch=excluded.epoch,prepared=excluded.prepared',
                   (project_id,lease['owner_token'],activity['revision'] if activity else 0,grant['created'],prepared))
    return {'prepared':True,'project_id':project_id,'coordinator_thread_id':caller,'previous_bridge':lease['owner_token'],
            'grants_unchanged':True,'next_release_command':RELEASE_COMMAND,'next_step':'Run that exact standalone functions.exec command, then start this helper with --handoff within five minutes. Do not use old control tools between release and handoff.'}


def project_bridge_register(service,project_id,handoff=False):
    caller,grant,thread=_original(service,project_id)
    if handoff:
        with service.registry.connect() as db:intent,release=_handoff_release(db,project_id,grant)
        proof=recent_release_proof(thread,max(grant['created'],intent['prepared']),release)
        with service.registry.transaction() as db:
            current=db.execute('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,)).fetchone()
            if not current or current['coordinator_thread_id']!=caller or current['created']!=grant['created']:
                raise BridgeError('COORDINATOR_CONFLICT','The authorization changed while checking the release.')
            _idle(db,project_id)
            current_intent,current_release=_handoff_release(db,project_id,current)
            if current_intent!=intent or current_release!=release:
                raise BridgeError('BRIDGE_RELEASE_REQUIRED','The old bridge was used again while checking release. Release it again, then retry handoff.')
            # The same transaction validates the generation, fences any future
            # old control INSERT (including legacy code), and transfers this
            # lease. A finished or racing resume cannot escape the fence.
            db.execute('INSERT OR IGNORE INTO retired_bridge_tokens VALUES(?)',(release['token'],))
            epoch=max(time.time(),current['created']+0.000001)
            db.execute('UPDATE authorizations SET created=? WHERE project_id=?',(epoch,project_id))
            db.execute('UPDATE coordinator_leases SET owner_token=? WHERE project_id=?',(service.instance,project_id))
            db.execute('DELETE FROM bridge_handoffs WHERE project_id=?',(project_id,))
            db.execute("INSERT INTO notes(project_id,kind,text,created) VALUES(?,'decision',?,?)",(project_id,json.dumps({'same_chat_bridge_handoff':proof,'previous_epoch':current['created'],'previous_bridge':release['token'],'new_bridge':service.instance}),epoch))
    return service.coordinator_register(project_id,caller)


def preflight_project_bridge(data_dir,project_id,handoff=False,prepare=False):
    """Refuse a wrong caller or busy handoff before initializing/migrating state."""
    from .transport import AppServer
    caller=os.environ.get('CODEX_THREAD_ID');path=pathlib.Path(data_dir)/'registry.sqlite3'
    if not caller or not path.is_file():raise BridgeError('COORDINATOR_CONFLICT','Use the original coordinator shell and existing state directory.')
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        grant=db.execute('SELECT * FROM authorizations WHERE project_id=? AND enabled=1',(project_id,)).fetchone()
        project=db.execute('SELECT * FROM projects WHERE id=?',(project_id,)).fetchone()
        if not grant or not project or grant['coordinator_thread_id']!=caller:
            raise BridgeError('COORDINATOR_CONFLICT','This shell does not own the original enabled project grant.')
        if os.path.normcase(os.path.abspath(project['root']))!=path_key(project['root']):raise BridgeError('SCOPE_LOST','The original source root resolves elsewhere.')
        if any(x['project_id']!=project_id or x['role'].lower()!='coordinator' for x in db.execute('SELECT project_id,role FROM conversations WHERE thread_id=?',(caller,))):
            raise BridgeError('ROLE_CONFLICT','The original coordinator identity no longer has its registered role.')
        if handoff or prepare:_idle(db,project_id)
        if handoff:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='bridge_handoffs'").fetchone():
                raise BridgeError('BRIDGE_HANDOFF_NOT_PREPARED','Run --prepare-handoff before releasing the old bridge.')
            intent,release=_handoff_release(db,project_id,grant)
        root=project['root'];epoch=grant['created']
    remote=AppServer(pathlib.Path(data_dir)/'logs')
    try:thread=remote.call('thread/read',{'threadId':caller,'includeTurns':False})['thread']
    finally:remote.close()
    if path_key(thread['cwd'])!=path_key(root):raise BridgeError('PROJECT_CONFLICT','Original coordinator root differs from the grant.')
    if handoff:recent_release_proof(thread,max(epoch,intent['prepared']),release)
