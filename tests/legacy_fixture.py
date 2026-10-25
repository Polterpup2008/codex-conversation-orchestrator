"""Synthetic public v0.1 registry; contains no real user/session data."""
import sqlite3

AUDITOR='22222222-2222-4222-8222-222222222222'


def create_legacy_registry(path, root):
    db=sqlite3.connect(path)
    db.executescript('''
    CREATE TABLE projects(id TEXT PRIMARY KEY,root TEXT NOT NULL UNIQUE,mode TEXT NOT NULL CHECK(mode='experiment'),created REAL NOT NULL);
    CREATE TABLE conversations(thread_id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),role TEXT NOT NULL,name TEXT NOT NULL,capabilities TEXT NOT NULL,archived INTEGER NOT NULL DEFAULT 0,latest_completed_turn TEXT);
    CREATE TABLE tasks(id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),owner TEXT NOT NULL REFERENCES conversations(thread_id),requirements TEXT NOT NULL,dependencies TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'ready',revision INTEGER NOT NULL DEFAULT 0,audit_verdict TEXT,evidence TEXT);
    CREATE TABLE messages(key TEXT PRIMARY KEY,thread_id TEXT NOT NULL REFERENCES conversations(thread_id),task_id TEXT REFERENCES tasks(id),fingerprint TEXT NOT NULL,text TEXT NOT NULL,state TEXT NOT NULL,turn_id TEXT UNIQUE,result TEXT,created REAL NOT NULL,updated REAL NOT NULL);
    CREATE TABLE notes(id INTEGER PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),kind TEXT NOT NULL,text TEXT NOT NULL,created REAL NOT NULL);
    ''')
    db.execute("INSERT INTO projects VALUES('legacy',?,'experiment',0)",(str(root),))
    db.execute("INSERT INTO conversations(thread_id,project_id,role,name,capabilities) VALUES(?,'legacy','Auditor','Synthetic auditor','[]')",(AUDITOR,))
    db.execute("INSERT INTO tasks(id,project_id,owner,requirements,dependencies) VALUES('task','legacy',?,'Synthetic contract','[]')",(AUDITOR,))
    db.execute("INSERT INTO messages(key,thread_id,fingerprint,text,state,created,updated) VALUES('message',?,'synthetic','No real content','completed',0,0)",(AUDITOR,))
    db.execute("INSERT INTO notes VALUES(1,'legacy','decision','Synthetic decision',0)")
    db.commit();db.close()
