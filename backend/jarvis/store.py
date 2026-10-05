"""Separate durable records, transactional idempotency and FTS5 retrieval."""

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS migrations(version INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS conversations(id INTEGER PRIMARY KEY, session TEXT, turn TEXT, role TEXT, content TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS summaries(session TEXT PRIMARY KEY, content TEXT);
CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY, key TEXT UNIQUE, value TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS notes(id TEXT PRIMARY KEY, title TEXT, content TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS reminders(id TEXT PRIMARY KEY, title TEXT, due TEXT, timezone TEXT, state TEXT DEFAULT 'pending', notified TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, kind TEXT, args TEXT, state TEXT, result TEXT, error TEXT, created TEXT, updated TEXT);
CREATE TABLE IF NOT EXISTS executions(key TEXT PRIMARY KEY, tool TEXT, args TEXT, state TEXT, result TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS directories(path TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS documents(path TEXT PRIMARY KEY, root TEXT, fingerprint TEXT, content TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS document_fts USING fts5(path UNINDEXED, content);
CREATE VIRTUAL TABLE IF NOT EXISTS note_fts USING fts5(id UNINDEXED, title, content);
CREATE TABLE IF NOT EXISTS control_requests(id TEXT PRIMARY KEY,args TEXT,state TEXT,result TEXT,created TEXT,updated TEXT);
CREATE TABLE IF NOT EXISTS news(id TEXT PRIMARY KEY,category TEXT,source TEXT,title TEXT,url TEXT,published TEXT,fetched TEXT,excerpt TEXT);
CREATE TABLE IF NOT EXISTS news_meta(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE IF NOT EXISTS generated_documents(id TEXT PRIMARY KEY,title TEXT,format TEXT,path TEXT,sha256 TEXT,size INTEGER,created TEXT);
CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(id UNINDEXED,title,excerpt);
CREATE TABLE IF NOT EXISTS workflows(id TEXT PRIMARY KEY,definition TEXT,next_due TEXT,created TEXT,updated TEXT,last_state TEXT);
CREATE TABLE IF NOT EXISTS workflow_runs(id TEXT PRIMARY KEY,workflow_id TEXT,trigger_slot TEXT,definition TEXT,state TEXT,job_id TEXT,result TEXT,error TEXT,created TEXT,updated TEXT,UNIQUE(workflow_id,trigger_slot));
CREATE TABLE IF NOT EXISTS workflow_steps(run_id TEXT,step TEXT,state TEXT,result TEXT,created TEXT,PRIMARY KEY(run_id,step));
CREATE TABLE IF NOT EXISTS workflow_notifications(id TEXT PRIMARY KEY,run_id TEXT UNIQUE,title TEXT,text TEXT,read INTEGER,created TEXT);
CREATE TABLE IF NOT EXISTS paired_devices(id TEXT PRIMARY KEY,name TEXT,token_hash TEXT UNIQUE,state TEXT,created TEXT,expires REAL);
CREATE TABLE IF NOT EXISTS connectors(id TEXT PRIMARY KEY,config TEXT,connected INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS connector_usage(id TEXT,day TEXT,count INTEGER,PRIMARY KEY(id,day));
CREATE TABLE IF NOT EXISTS external_actions(id TEXT PRIMARY KEY,run_id TEXT,kind TEXT,args TEXT,state TEXT,result TEXT,created TEXT,updated TEXT);
INSERT OR IGNORE INTO migrations VALUES(5);
INSERT OR IGNORE INTO migrations VALUES(1);
INSERT OR IGNORE INTO migrations VALUES(2);
INSERT OR IGNORE INTO migrations VALUES(3);
INSERT OR IGNORE INTO migrations VALUES(4);

"""


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return str(uuid.uuid4())


def fts_query(query):
    # Treat query words as literal text, not user-controlled FTS syntax.
    return (
        " OR ".join('"' + word.replace('"', '""') + '"' for word in query.split()[:20])
        or '""'
    )


class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.context_revision = 0
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self.lock:
            self.db.executescript(
                "PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;" + SCHEMA
            )
            # Index every past user turn, including chats recorded before this migration.
            # Assistant prose is never promoted into personal knowledge.
            self.db.executescript("""
                CREATE VIRTUAL TABLE IF NOT EXISTS conversation_fts USING fts5(content);
                CREATE TRIGGER IF NOT EXISTS conversation_insert AFTER INSERT ON conversations
                WHEN NEW.role='user' BEGIN
                    INSERT INTO conversation_fts(rowid,content) VALUES(NEW.id,NEW.content);
                END;
                CREATE TRIGGER IF NOT EXISTS conversation_delete AFTER DELETE ON conversations
                WHEN OLD.role='user' BEGIN
                    DELETE FROM conversation_fts WHERE rowid=OLD.id;
                END;
                CREATE TRIGGER IF NOT EXISTS conversation_update AFTER UPDATE ON conversations BEGIN
                    DELETE FROM conversation_fts WHERE rowid=OLD.id;
                    INSERT INTO conversation_fts(rowid,content)
                        SELECT NEW.id,NEW.content WHERE NEW.role='user';
                END;
            """)
            if not self.db.execute(
                "SELECT 1 FROM migrations WHERE version=6"
            ).fetchone():
                self.db.execute("DELETE FROM conversation_fts")
                self.db.execute(
                    "INSERT INTO conversation_fts(rowid,content) SELECT id,content FROM conversations WHERE role='user'"
                )
                self.db.execute("INSERT INTO migrations VALUES(6)")
            self.db.execute("INSERT OR IGNORE INTO migrations VALUES(7)")
            self.db.execute("PRAGMA user_version=7")
            self.db.execute(
                "UPDATE jobs SET state='interrupted', error='Application restarted; not replayed', updated=? WHERE state IN ('running','queued')",
                (now(),),
            )
            self.db.execute(
                "UPDATE executions SET state='interrupted', result=? WHERE state='running'",
                (
                    json.dumps(
                        {
                            "ok": False,
                            "error": "Interrupted; inspect state before retry",
                        }
                    ),
                ),
            )
            self.db.commit()

    def all(self, sql, args=()):
        with self.lock:
            return [dict(row) for row in self.db.execute(sql, args).fetchall()]

    def run(self, sql, args=()):
        with self.lock:
            self.db.execute(sql, args)
            self.db.commit()

    def snapshot(self):
        return {
            name: self.all(f"SELECT * FROM {name} ORDER BY created DESC LIMIT 100")
            for name in (
                "notes",
                "memory",
                "reminders",
                "jobs",
                "executions",
                "generated_documents",
            )
        } | {
            "directories": self.all("SELECT path FROM directories"),
            "control_requests": self.all(
                "SELECT * FROM control_requests ORDER BY created DESC LIMIT 20"
            ),
        }

    def conversation(self, session, turn, role, content):
        self.run(
            "INSERT INTO conversations(session,turn,role,content,created) VALUES(?,?,?,?,?)",
            (session, turn, role, content, now()),
        )

    def context(self, session):
        rows = self.all(
            "SELECT role,content FROM conversations WHERE session=? ORDER BY id DESC LIMIT 8",
            (session,),
        )
        return list(reversed(rows))

    def conversation_recall(self, query, limit=5):
        """Retrieve sourced user statements, not inferred facts or model answers."""
        terms = re.findall(r"\w{3,}", query.lower())
        stop = {
            "the",
            "what",
            "which",
            "please",
            "tell",
            "can",
            "you",
            "about",
            "and",
            "was",
            "have",
            "from",
            "that",
            "this",
            "said",
            "remember",
            "conversation",
            "know",
            "our",
            "with",
            "does",
            "how",
        }
        words = [t for t in terms if t not in stop][:16]
        if not words:
            return []
        return self.all(
            "SELECT c.id,c.created,c.session,snippet(conversation_fts,0,'','', ' … ',55) content "
            "FROM conversation_fts JOIN conversations c ON c.id=conversation_fts.rowid "
            "WHERE conversation_fts MATCH ? AND c.role='user' ORDER BY rank,c.id DESC LIMIT ?",
            (fts_query(" ".join(words)), min(20, max(1, limit))),
        )

    def conversation_archive(self, query=""):
        if query:
            matches = self.conversation_recall(query, 20)
            return [
                self.all(
                    "SELECT id,session,created,content FROM conversations WHERE id=? AND role='user'",
                    (r["id"],),
                )[0]
                for r in matches
            ]
        return self.all(
            "SELECT id,session,created,content FROM conversations WHERE role='user' ORDER BY id DESC LIMIT 100"
        )

    def edit_conversation(self, id, content=None):
        with self.lock:
            row = self.db.execute(
                "SELECT session,turn FROM conversations WHERE id=? AND role='user'",
                (id,),
            ).fetchone()
            if not row:
                raise ValueError("Conversation record not found")
            self.db.execute(
                "DELETE FROM conversations WHERE session=? AND turn=? AND role='assistant'",
                (row["session"], row["turn"]),
            )
            if content is None:
                self.db.execute("DELETE FROM conversations WHERE id=?", (id,))
            else:
                self.db.execute(
                    "UPDATE conversations SET content=? WHERE id=?", (content, id)
                )
            self.db.execute("DELETE FROM summaries")
            self.context_revision += 1
            self.db.commit()

    def clear_conversations(self):
        with self.lock:
            self.db.execute("DELETE FROM conversations")
            self.db.execute("DELETE FROM summaries")
            self.context_revision += 1
            self.db.commit()

    def compact(self, session):
        # Deterministic extractive summary: never synthesizes guessed facts.
        rows = self.all(
            "SELECT role,content FROM conversations WHERE session=? ORDER BY id DESC LIMIT 24 OFFSET 8",
            (session,),
        )
        content = "\n".join(
            f"{r['role']}: {r['content'][:180]}" for r in reversed(rows)
        )[-1600:]
        self.run("INSERT OR REPLACE INTO summaries VALUES(?,?)", (session, content))

    def memory_context(self, query):
        """Rank explicit memories across chats; bounded excerpts never create facts."""
        terms = set(re.findall(r"\w{3,}", query.lower())) - {
            "the",
            "what",
            "which",
            "please",
            "tell",
            "can",
            "you",
            "about",
            "and",
        }
        rows = self.all("SELECT key,value FROM memory ORDER BY created DESC LIMIT 1000")
        rows.sort(
            key=lambda r: (
                -sum(t in (r["key"] + " " + r["value"]).lower() for t in terms)
            )
        )
        result = []
        for row in rows[:4]:
            value = row["value"]
            matches = [value.lower().find(t) for t in terms if t in value.lower()]
            start = max(0, min(matches, default=0) - 100)
            excerpt = value[start : start + 400]
            result.append(
                {
                    "key": row["key"][:100],
                    "value": excerpt,
                    "excerpt": start > 0 or len(excerpt) < len(value),
                }
            )
        return result

    def search_notes(self, query):
        return self.all(
            "SELECT n.id,n.title,snippet(note_fts,2,'','', ' … ',30) excerpt FROM note_fts JOIN notes n ON n.id=note_fts.id WHERE note_fts MATCH ? ORDER BY rank LIMIT 8",
            (fts_query(query),),
        )

    def search_documents(self, query):
        return self.all(
            "SELECT path,snippet(document_fts,1,'','', ' … ',45) excerpt FROM document_fts WHERE document_fts MATCH ? ORDER BY rank LIMIT 8",
            (fts_query(query),),
        )

    def note(self, title, content):
        id = uid()
        with self.lock:
            self.db.execute(
                "INSERT INTO notes VALUES(?,?,?,?)", (id, title, content, now())
            )
            self.db.execute("INSERT INTO note_fts VALUES(?,?,?)", (id, title, content))
            self.db.commit()
        return {"id": id, "title": title, "content": content}

    def delete_record(self, kind, id):
        if kind not in {"notes", "memory"}:
            raise ValueError("Only notes and explicit memory can be deleted here")
        with self.lock:
            self.db.execute(f"DELETE FROM {kind} WHERE id=?", (id,))
            if kind == "notes":
                self.db.execute("DELETE FROM note_fts WHERE id=?", (id,))
            self.context_revision += 1
            # Prevent a forgotten record from reappearing through summaries/history.
            self.db.execute("DELETE FROM conversations")
            self.db.execute("DELETE FROM summaries")
            self.db.execute("DELETE FROM executions")
            self.db.commit()

    def due_reminders(self):
        return self.all(
            "SELECT * FROM reminders WHERE state='pending' AND due<=?", (now(),)
        )

    def acknowledge(self, id):
        self.run(
            "UPDATE reminders SET state='delivered',notified=? WHERE id=? AND state='pending'",
            (now(), id),
        )

    def close(self):
        with self.lock:
            self.db.close()
