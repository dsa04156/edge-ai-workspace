"""Single-writer durable route and request journal, with no ambiguous replay."""
import fcntl
import json
import sqlite3
import time
from pathlib import Path


class Journal:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.lock = open(path + ".lock", "a+")
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise RuntimeError("another controller owns this journal") from None
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS services(uid TEXT PRIMARY KEY, state TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS requests(uid TEXT, id TEXT, fingerprint TEXT,
            target TEXT, state TEXT, status INTEGER, body TEXT, at REAL,
            PRIMARY KEY(uid,id));
          CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY, at REAL, uid TEXT,
            event TEXT, detail TEXT);
        """)
        with self.db:
            self.db.execute("UPDATE requests SET state='unknown',status=503,body=? WHERE state='dispatched'",
                            (json.dumps({"reason": "controller_restarted_outcome_unknown"}),))

    def states(self):
        return {uid: json.loads(state) for uid, state in self.db.execute("SELECT uid,state FROM services")}

    def save(self, uid, state, event=None):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO services VALUES (?,?)", (uid, json.dumps(state)))
            if event:
                self.db.execute("INSERT INTO events(at,uid,event,detail) VALUES (?,?,?,?)",
                                (time.time(), uid, event, json.dumps(state)))

    def request(self, uid, request_id):
        row = self.db.execute("SELECT fingerprint,target,state,status,body FROM requests WHERE uid=? AND id=?",
                              (uid, request_id)).fetchone()
        if not row:
            return None
        return dict(zip(("fingerprint", "target", "state", "status", "body"), row))

    def dispatch(self, uid, request_id, fingerprint, target):
        with self.db:
            self.db.execute("INSERT INTO requests VALUES (?,?,?,?,?,NULL,NULL,?)",
                            (uid, request_id, fingerprint, target, "dispatched", time.time()))

    def finish(self, uid, request_id, state, status, body):
        with self.db:
            self.db.execute("UPDATE requests SET state=?,status=?,body=? WHERE uid=? AND id=?",
                            (state, status, json.dumps(body), uid, request_id))

    def close(self):
        self.db.close()
        self.lock.close()
