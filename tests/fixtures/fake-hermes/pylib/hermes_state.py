"""Fake hermes_state.SessionDB (same create_session / append_message / close calls the seeder uses)."""
import sqlite3
from pathlib import Path


class SessionDB:
    def __init__(self, db_path: Path = None, read_only: bool = False):
        self.con = sqlite3.connect(db_path)
        self.con.execute("create table if not exists sessions (id text primary key, source text)")
        self.con.execute("create table if not exists messages (session_id text, role text, content text, tool_name text)")

    def create_session(self, session_id, source, **kwargs):
        self.con.execute("insert into sessions values (?, ?)", (session_id, source))
        return session_id

    def append_message(self, session_id, role, content=None, **kwargs):
        self.con.execute("insert into messages values (?, ?, ?, null)", (session_id, role, content))

    def close(self):
        self.con.commit(); self.con.close()
