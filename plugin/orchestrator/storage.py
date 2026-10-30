"""SQLite WAL registry, atomic ownership, optimistic task revisions, durable outbox."""
import contextlib
import hashlib
import json
import pathlib
import os
import sqlite3
import time
from .errors import BridgeError

SCHEMA = '''
CREATE TABLE IF NOT EXISTS projects (
 id TEXT PRIMARY KEY, root TEXT NOT NULL UNIQUE, mode TEXT NOT NULL CHECK(mode IN ('experiment','production')), created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS creations (
 key TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, state TEXT NOT NULL, thread_id TEXT);
CREATE TABLE IF NOT EXISTS conversations (
 thread_id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 role TEXT NOT NULL, name TEXT NOT NULL, capabilities TEXT NOT NULL,
 archived INTEGER NOT NULL DEFAULT 0, latest_completed_turn TEXT);
CREATE TABLE IF NOT EXISTS tasks (
 id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
 owner TEXT NOT NULL REFERENCES conversations(thread_id), requirements TEXT NOT NULL,
 dependencies TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'ready', revision INTEGER NOT NULL DEFAULT 0,
 audit_verdict TEXT, evidence TEXT);
CREATE TABLE IF NOT EXISTS messages (
 key TEXT PRIMARY KEY, thread_id TEXT NOT NULL REFERENCES conversations(thread_id), task_id TEXT REFERENCES tasks(id),
 fingerprint TEXT NOT NULL, text TEXT NOT NULL, state TEXT NOT NULL,
 turn_id TEXT UNIQUE, result TEXT, created REAL NOT NULL, updated REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_turn ON messages(thread_id)
 WHERE state IN ('preparing','sent','unknown');
CREATE TABLE IF NOT EXISTS notes (
 id INTEGER PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL, text TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, method TEXT NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS bridges (
 token TEXT PRIMARY KEY, pid INTEGER NOT NULL, active INTEGER NOT NULL, last_seen REAL NOT NULL);
CREATE TABLE IF NOT EXISTS authorizations (
 project_id TEXT PRIMARY KEY REFERENCES projects(id), coordinator_thread_id TEXT NOT NULL,
 enabled INTEGER NOT NULL, headless INTEGER NOT NULL DEFAULT 0, integrations TEXT NOT NULL DEFAULT '[]', created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS artifact_roots (
 project_id TEXT NOT NULL REFERENCES projects(id), root TEXT NOT NULL,
 enabled INTEGER NOT NULL, identity TEXT NOT NULL, reason TEXT NOT NULL, created REAL NOT NULL,
 PRIMARY KEY(project_id,root));
CREATE TABLE IF NOT EXISTS legacy_bridge_tokens (token TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS current_bridge_tokens (token TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS bridge_control_activity (
 token TEXT PRIMARY KEY, revision INTEGER NOT NULL, name TEXT NOT NULL, started REAL NOT NULL, finished REAL);
CREATE TABLE IF NOT EXISTS bridge_handoffs (
 project_id TEXT PRIMARY KEY REFERENCES projects(id), owner_token TEXT NOT NULL,
 baseline_revision INTEGER NOT NULL, epoch REAL NOT NULL, prepared REAL NOT NULL, process_identity TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS retired_bridge_tokens (token TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS audit_links (
 message_key TEXT PRIMARY KEY REFERENCES messages(key), task_id TEXT NOT NULL REFERENCES tasks(id),
 task_revision INTEGER NOT NULL, work_message_key TEXT NOT NULL REFERENCES messages(key),
 work_turn_id TEXT NOT NULL, artifacts TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS operations (
 thread_id TEXT PRIMARY KEY REFERENCES conversations(thread_id), owner_token TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coordinator_leases (
 project_id TEXT PRIMARY KEY REFERENCES projects(id), owner_token TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS control_lock (
 id INTEGER PRIMARY KEY CHECK(id=1), owner_token TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS questions (
 key TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), thread_id TEXT NOT NULL REFERENCES conversations(thread_id),
 message_key TEXT NOT NULL REFERENCES messages(key), task_id TEXT REFERENCES tasks(id), turn_id TEXT NOT NULL,
 mode TEXT NOT NULL, request_id TEXT, owner_token TEXT, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
 answer_key TEXT, answer_fingerprint TEXT, answer TEXT, reply_message_key TEXT, escalation TEXT, created REAL NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS unique_question_answer_key ON questions(answer_key) WHERE answer_key IS NOT NULL;
CREATE TABLE IF NOT EXISTS worker_profiles (
 thread_id TEXT PRIMARY KEY REFERENCES conversations(thread_id), revision INTEGER NOT NULL, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS coordination_records (
 key TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), kind TEXT NOT NULL,
 revision INTEGER NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS path_claims (
 message_key TEXT NOT NULL REFERENCES messages(key), path TEXT NOT NULL, active INTEGER NOT NULL,
 PRIMARY KEY(message_key,path));
'''


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def artifact_scope_triggers(db):
    """Keep reservations enforced while already-running older bridges finish."""
    def norm(column):
        value=f"lower(replace({column},char(92),'/'))" if os.name=='nt' else column
        return f"rtrim({value},'/')"
    for table,column in (('projects','root'),('conversations','workspace'),('creations','workspace')):
        new=norm('NEW.'+column);root=norm('a.root')
        overlap=f"({new}={root} OR substr({new},1,length({root})+1)={root}||'/' OR substr({root},1,length({new})+1)={new}||'/')"
        for event in ('INSERT','UPDATE OF '+column):
            name='artifact_reserved_'+table+('_insert' if event=='INSERT' else '_update')
            db.execute(f"CREATE TRIGGER IF NOT EXISTS {name} BEFORE {event} ON {table} WHEN NEW.{column} IS NOT NULL AND EXISTS(SELECT 1 FROM artifact_roots a WHERE a.enabled=1 AND {overlap}) BEGIN SELECT RAISE(ABORT,'Artifact directories cannot become project or worker source roots'); END")
    # Old unbound experiment/activation code does filesystem work before its
    # INSERT. Fence only those root-registration operations before their body;
    # bound older coordinators keep their existing project operations available.
    db.execute('DROP TRIGGER IF EXISTS artifact_legacy_registration')
    db.execute("""CREATE TRIGGER artifact_legacy_registration
      BEFORE INSERT ON control_lock
      WHEN NEW.name IN ('project_create','project_link','coordinator_activate')
       AND EXISTS(SELECT 1 FROM artifact_roots WHERE enabled=1)
       AND NOT EXISTS(SELECT 1 FROM current_bridge_tokens WHERE token=NEW.owner_token)
       AND NOT EXISTS(SELECT 1 FROM coordinator_leases WHERE owner_token=NEW.owner_token)
      BEGIN SELECT RAISE(ABORT,'Current bridge required for new project registration while artifact reservations exist'); END""")


def handoff_triggers(db):
    """Observe even old control calls and fence retired owners atomically."""
    clock="((julianday('now')-2440587.5)*86400.0)"
    db.execute("""CREATE TRIGGER IF NOT EXISTS handoff_retired_owner
      BEFORE INSERT ON control_lock
      WHEN EXISTS(SELECT 1 FROM retired_bridge_tokens WHERE token=NEW.owner_token)
      BEGIN SELECT RAISE(ABORT,'This bridge was retired by a project handoff'); END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS handoff_control_enter
      AFTER INSERT ON control_lock BEGIN
      INSERT INTO bridge_control_activity VALUES(NEW.owner_token,1,NEW.name,{clock},NULL)
      ON CONFLICT(token) DO UPDATE SET revision=revision+1,name=NEW.name,started={clock},finished=NULL;
      END""")
    db.execute(f"""CREATE TRIGGER IF NOT EXISTS handoff_control_exit
      AFTER DELETE ON control_lock BEGIN
      UPDATE bridge_control_activity SET finished={clock} WHERE token=OLD.owner_token;
      END""")


class Registry:
    def __init__(self, path):
        self.path = pathlib.Path(path); self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            prior_version=db.execute('PRAGMA user_version').fetchone()[0]
            if prior_version > 11:
                raise BridgeError('REGISTRY_VERSION', 'Registry is newer than this plugin. Use the matching plugin version.')
            if 0<prior_version<11:
                # Keep a consistent private snapshot before the additive upgrade.
                # Existing live older instances retain their original tables;
                # newly started older software refuses schema11 instead of
                # registering roots without understanding artifact reservations.
                backup=self.path.with_name(self.path.name+'.before-v11-'+str(time.time_ns()))
                fd=os.open(backup,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
                with contextlib.closing(sqlite3.connect(self.path)) as source,contextlib.closing(sqlite3.connect(backup)) as target:source.backup(target)
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript(SCHEMA)
            # Rebuild only the parent table to extend its old experiment-only CHECK.
            # Foreign keys are restored and checked before this connection is released.
            old_check = "CHECK(mode='experiment')" in db.execute("SELECT sql FROM sqlite_master WHERE name='projects'").fetchone()[0]
            if old_check:
                db.execute('PRAGMA foreign_keys=OFF')
            db.execute('BEGIN IMMEDIATE')
            try:
                if 'owner_token' not in {row['name'] for row in db.execute('PRAGMA table_info(messages)')}:
                    db.execute('ALTER TABLE messages ADD COLUMN owner_token TEXT')
                if 'stage' not in {row['name'] for row in db.execute('PRAGMA table_info(messages)')}:
                    db.execute("ALTER TABLE messages ADD COLUMN stage TEXT NOT NULL DEFAULT 'legacy'")
                additions={
                    'projects':{'desktop_project_id':'TEXT','coordinator_thread_id':'TEXT','desktop_ui_project_id':'TEXT'},
                    'conversations':{'workspace':'TEXT','desktop_project_id':'TEXT','model':'TEXT','effort':'TEXT','routing_revision':'INTEGER NOT NULL DEFAULT 0','routing_justification':'TEXT','desktop_sync_state':"TEXT NOT NULL DEFAULT 'legacy'",'desktop_evidence':'TEXT'},
                    'tasks':{'model':'TEXT','effort':'TEXT','difficulty':'TEXT','routing_justification':'TEXT','plan_key':'TEXT'},
                    'messages':{'routing':'TEXT'},
                    'creations':{'project_id':'TEXT','workspace':'TEXT'},
                    'operations':{'stage':"TEXT NOT NULL DEFAULT 'dispatching'"},
                    'questions':{'transport_token':'TEXT','call_id':'TEXT'},
                }
                for table,columns in additions.items():
                    present={r['name'] for r in db.execute(f'PRAGMA table_info({table})')}
                    for name,kind in columns.items():
                        if name not in present:db.execute(f'ALTER TABLE {table} ADD COLUMN {name} {kind}')
                if old_check:
                    columns = [r['name'] for r in db.execute('PRAGMA table_info(projects)')]
                    definitions = ['id TEXT PRIMARY KEY', 'root TEXT NOT NULL UNIQUE', "mode TEXT NOT NULL CHECK(mode IN ('experiment','production'))", 'created REAL NOT NULL',
                                   'desktop_project_id TEXT', 'coordinator_thread_id TEXT', 'desktop_ui_project_id TEXT']
                    db.execute('CREATE TABLE projects_v6 ('+','.join(definitions)+')')
                    db.execute('INSERT INTO projects_v6('+','.join(columns)+') SELECT '+','.join(columns)+' FROM projects')
                    db.execute('DROP TABLE projects')
                    db.execute('ALTER TABLE projects_v6 RENAME TO projects')
                if db.execute('PRAGMA foreign_key_check').fetchone():
                    raise BridgeError('REGISTRY_INTEGRITY', 'Foreign-key validation failed during migration.')
                if prior_version<8:db.execute("UPDATE operations SET stage='dispatching' WHERE stage='preparing'")
                if prior_version<11:db.execute('INSERT OR IGNORE INTO legacy_bridge_tokens SELECT token FROM bridges')
                artifact_scope_triggers(db)
                handoff_triggers(db)
                db.execute('PRAGMA user_version=11'); db.commit()
            except Exception:
                db.rollback();raise
            finally:
                db.execute('PRAGMA foreign_keys=ON')

    @contextlib.contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA synchronous=FULL')
        try:
            yield db
        finally:
            db.close()

    @contextlib.contextmanager
    def transaction(self):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                yield db
                db.commit()
            except Exception:
                db.rollback(); raise

    def rows(self, sql, params=()):
        with self.connect() as db:
            return [dict(r) for r in db.execute(sql, params)]

    def one(self, table, key, value):
        # table/key are internal constants, never tool input.
        rows = self.rows(f'SELECT * FROM {table} WHERE {key}=?', (value,))
        if not rows:
            raise BridgeError('NOT_FOUND', f'{table}: {value} is not registered.')
        return rows[0]

    def reserve_message(self, key, thread_id, text, task_id, owner_token=None, routing_input=None, audit_link=None,write_paths=()):
        digest = fingerprint([thread_id, text, task_id]+([routing_input] if routing_input else []))
        with self.transaction() as db:
            old = db.execute('SELECT * FROM messages WHERE key=?', (key,)).fetchone()
            if old:
                if old['fingerprint'] != digest:
                    raise BridgeError('IDEMPOTENCY_CONFLICT', 'Message key was already used with different content.')
                return dict(old), False
            if db.execute('SELECT 1 FROM operations WHERE thread_id=?',(thread_id,)).fetchone():
                raise BridgeError('CONVERSATION_BUSY','A lifecycle operation owns this conversation.')
            if task_id:
                task = db.execute('SELECT * FROM tasks WHERE id=?', (task_id,)).fetchone()
                if not task or task['owner'] != thread_id:
                    raise BridgeError('OWNERSHIP_CONFLICT', 'Task is not assigned to this conversation.')
                if task['state'] not in ('ready', 'rejected'):
                    raise BridgeError('TASK_STATE', f"Cannot dispatch task in state {task['state']}.")
                for dep in json.loads(task['dependencies']):
                    row = db.execute('SELECT state FROM tasks WHERE id=?', (dep,)).fetchone()
                    if not row or row['state'] != 'accepted':
                        raise BridgeError('DEPENDENCY_BLOCKED', f'Dependency {dep} has not passed verification.')
            from .projects import contained
            for path in write_paths:
                if any(contained(path,r['path']) or contained(r['path'],path) for r in db.execute('SELECT path FROM path_claims WHERE active=1')):
                    raise BridgeError('WRITE_CONFLICT','Declared write paths overlap unresolved work. Resolve that delivery before dispatch.')
            try:
                now = time.time()
                db.execute("INSERT INTO messages(key,thread_id,task_id,fingerprint,text,state,created,updated,owner_token,stage) VALUES (?,?,?,?,?,?,?,?,?,'prepared')",
                    (key, thread_id, task_id, digest, text, 'preparing', now, now, owner_token))
            except sqlite3.IntegrityError as e:
                raise BridgeError('CONVERSATION_BUSY', 'An unresolved message already owns this conversation. Reconcile it first.') from e
            if task_id:
                db.execute("UPDATE tasks SET state='running',revision=revision+1 WHERE id=?", (task_id,))
            db.executemany('INSERT INTO path_claims VALUES(?,?,1)',[(key,p) for p in write_paths])
            if audit_link:
                task=db.execute('SELECT state,revision FROM tasks WHERE id=?',(audit_link['task_id'],)).fetchone()
                if task['state']!='needs_audit' or task['revision']!=audit_link['task_revision']:
                    raise BridgeError('REVISION_CONFLICT','The delivery changed before audit dispatch.')
                db.execute('INSERT INTO audit_links VALUES(?,?,?,?,?,?)',(key,audit_link['task_id'],audit_link['task_revision'],audit_link['work_message_key'],audit_link['work_turn_id'],json.dumps(audit_link['artifacts'])))
            return dict(db.execute('SELECT * FROM messages WHERE key=?', (key,)).fetchone()), True

    def set_message(self, key, state, turn_id=None, result=None):
        with self.transaction() as db:
            # Completion event may precede turn/start response. Never downgrade terminal state.
            row = db.execute('SELECT state,task_id FROM messages WHERE key=?', (key,)).fetchone()
            if row and row['state'] in ('completed', 'failed', 'interrupted') and state in ('sent', 'unknown'):
                return
            db.execute('UPDATE messages SET state=?,turn_id=coalesce(?,turn_id),result=coalesce(?,result),updated=? WHERE key=?',
                       (state, turn_id, json.dumps(result) if result is not None else None, time.time(), key))
            if row and row['task_id'] and row['state'] not in ('completed','failed','interrupted') and state in ('failed','interrupted'):
                db.execute("UPDATE tasks SET state='blocked',revision=revision+1 WHERE id=?",(row['task_id'],))
            if state in ('completed','failed','interrupted'):
                db.execute('UPDATE path_claims SET active=0 WHERE message_key=?',(key,))
            if state=='completed' and result:
                full=dict(db.execute('SELECT * FROM messages WHERE key=?',(key,)).fetchone())
                if self._classify_question(db,full,result) and full['task_id']:
                    latest=db.execute('SELECT key FROM messages WHERE task_id=? ORDER BY created DESC LIMIT 1',(full['task_id'],)).fetchone()
                    if latest and latest['key']==key:
                        db.execute("UPDATE tasks SET state='waiting_input',revision=revision+1 WHERE id=? AND state='needs_audit'",(full['task_id'],))
            self._settle_question_answers(db,key)

    def mark_dispatching(self, key, owner_token=None):
        with self.transaction() as db:
            sql="UPDATE messages SET stage='dispatching',updated=? WHERE key=? AND state='preparing' AND stage='prepared'"
            values=[time.time(),key]
            if owner_token:
                sql+=" AND owner_token=? AND EXISTS(SELECT 1 FROM bridges WHERE token=? AND active=1)";values.extend([owner_token,owner_token])
            if db.execute(sql,values).rowcount!=1:
                raise BridgeError('DISPATCH_FENCED','This message no longer owns a live prepared dispatch; no turn was sent.')

    def routing(self,key,values):
        with self.transaction() as db:
            row=db.execute('SELECT routing FROM messages WHERE key=?',(key,)).fetchone()
            current=json.loads(row['routing']) if row and row['routing'] else {}
            current.update(values)
            db.execute('UPDATE messages SET routing=? WHERE key=?',(json.dumps(current),key))

    def completed(self, thread_id, turn):
        with self.transaction() as db:
            row = db.execute('SELECT * FROM messages WHERE thread_id=? AND turn_id=?',
                             (thread_id, turn['id'])).fetchone()
            if not row:
                return
            if row['state'] in ('completed','failed','interrupted'):
                return  # Duplicate lifecycle events must not advance task revisions twice.
            db.execute('UPDATE messages SET state=?,turn_id=?,result=?,updated=? WHERE key=?',
                (turn['status'], turn['id'], json.dumps(turn), time.time(), row['key']))
            if turn['status'] == 'completed':
                db.execute('UPDATE conversations SET latest_completed_turn=? WHERE thread_id=?', (turn['id'], thread_id))
            db.execute('UPDATE path_claims SET active=0 WHERE message_key=?',(row['key'],))
            db.execute("UPDATE questions SET state='unavailable' WHERE thread_id=? AND turn_id=? AND mode='active' AND state IN ('pending','escalated','answering')",(thread_id,turn['id']))
            question=self._classify_question(db,dict(row),turn) if turn['status']=='completed' else None
            if row['task_id']:
                task_state = 'waiting_input' if question else 'needs_audit' if turn['status'] == 'completed' else 'blocked'
                db.execute('UPDATE tasks SET state=?,revision=revision+1 WHERE id=?', (task_state, row['task_id']))
            self._settle_question_answers(db,row['key'])

    def _settle_question_answers(self,db,message_key):
        from .questions import continuation_matches
        message=db.execute('SELECT * FROM messages WHERE key=?',(message_key,)).fetchone()
        if not message:return
        state='answered' if message['state']=='completed' or (message['state']=='sent' and message['turn_id']) else 'unavailable' if message['state'] in ('failed','interrupted') else None
        if not state:return
        for row in db.execute("SELECT * FROM questions WHERE reply_message_key=? AND mode='turn_based' AND state='answering'",(message_key,)).fetchall():
            link=db.execute('SELECT * FROM audit_links WHERE message_key=?',(row['message_key'],)).fetchone()
            if continuation_matches(row,message,link):db.execute('UPDATE questions SET state=? WHERE key=?',(state,row['key']))

    def reconcile_question_answer(self,key):
        with self.transaction() as db:
            row=db.execute('SELECT reply_message_key FROM questions WHERE key=?',(key,)).fetchone()
            if row and row['reply_message_key']:self._settle_question_answers(db,row['reply_message_key'])

    def _classify_question(self,db,message,turn):
        from .questions import fallback_question
        question=fallback_question(turn)
        if not question:return None
        worker=db.execute('SELECT project_id FROM conversations WHERE thread_id=?',(message['thread_id'],)).fetchone()
        key=worker['project_id']+'::question-'+fingerprint([message['key'],turn['id']])[:24]
        db.execute("INSERT OR IGNORE INTO questions(key,project_id,thread_id,message_key,task_id,turn_id,mode,payload,created) VALUES(?,?,?,?,?,?,'turn_based',?,?)",(key,worker['project_id'],message['thread_id'],message['key'],message['task_id'],turn['id'],json.dumps(question),time.time()))
        linked=db.execute('SELECT a.task_revision,t.revision,t.state FROM audit_links a JOIN tasks t ON t.id=a.task_id WHERE a.message_key=?',(message['key'],)).fetchone()
        task=db.execute('SELECT state FROM tasks WHERE id=?',(message['task_id'],)).fetchone() if message['task_id'] else None
        if (linked and (linked['state']!='needs_audit' or linked['task_revision']!=linked['revision'])) or (task and task['state'] in ('accepted','cancelled')):
            db.execute("UPDATE questions SET state='unavailable' WHERE key=? AND state IN ('pending','escalated','answering')",(key,))
            return None
        return question

    def reconcile_questions(self,key):
        with self.transaction() as db:
            message=db.execute('SELECT * FROM messages WHERE key=?',(key,)).fetchone()
            if not message or message['state']!='completed' or not message['result']:return
            if self._classify_question(db,dict(message),json.loads(message['result'])) and message['task_id']:
                latest=db.execute('SELECT key FROM messages WHERE task_id=? ORDER BY created DESC LIMIT 1',(message['task_id'],)).fetchone()
                if latest and latest['key']==key:
                    db.execute("UPDATE tasks SET state='waiting_input',revision=revision+1 WHERE id=? AND state='needs_audit'",(message['task_id'],))

    def event(self, method, params):
        if method == 'turn/completed':
            self.completed(params['threadId'], params['turn'])
        if method=='thread/settings/updated':
            rows=self.rows("SELECT key FROM messages WHERE thread_id=? AND state IN ('preparing','sent','unknown')",(params['threadId'],))
            for row in rows:
                settings=params['threadSettings']
                self.routing(row['key'],{'observed_settings':{k:settings.get(k) for k in ['model','effort','cwd','modelProvider']},
                    'observed_source':'thread/settings/updated'})
        if method in ('turn/started', 'turn/completed', 'thread/settings/updated', 'bridge/unsupportedRequest', 'bridge/nativeAppApproval', 'error'):
            with self.connect() as db:
                db.execute('INSERT INTO events(method,payload,created) VALUES(?,?,?)', (method, json.dumps(params), time.time()))
