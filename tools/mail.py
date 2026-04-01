#!/usr/bin/env python3
"""Mail — SQLite-based inter-agent messaging.

Inspired by jayminwest/overstory's mail system. Each agent has a mailbox.
Messages are stored in SQLite (WAL mode, ~1-5ms per query). Supports
direct messages, group addresses (@all, @builders, @reviewers), and
threaded conversations.

Cleaner than file-based communication:
- Atomic writes (no partial reads)
- Query by sender, recipient, thread, status
- Scales to thousands of messages
- WAL mode = no locking issues with concurrent agents

Usage:
    mail = MailSystem()
    mail.send("master", "backend", "Fix the auth bug", priority="high")
    mail.send("master", "@all", "Stand down for deploy")

    messages = mail.inbox("backend")
    mail.mark_read("backend", msg_id)

CLI:
    python3 tools/mail.py send master backend "Fix the auth bug"
    python3 tools/mail.py inbox backend
    python3 tools/mail.py send master @all "Stand down"
    python3 tools/mail.py threads backend
    python3 tools/mail.py stats
"""

import json
import sqlite3
import sys
import uuid
from datetime import datetime
from pathlib import Path


MAIL_DB = Path(".oats/mail.db")

# Group addresses resolve to agent lists
GROUPS = {
    "@all": None,  # Resolved dynamically from all known agents
    "@builders": ["backend", "frontend", "devops"],
    "@reviewers": ["strategy", "master"],
    "@outreach": ["research", "copy", "tracking"],
}


class MailSystem:
    """SQLite-based mailbox for inter-agent messaging."""

    def __init__(self, db_path: str = None):
        self.db_path = Path(db_path) if db_path else MAIL_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            from_agent TEXT NOT NULL,
            to_agent TEXT NOT NULL,
            subject TEXT NOT NULL DEFAULT '',
            body TEXT NOT NULL DEFAULT '',
            msg_type TEXT NOT NULL DEFAULT 'message',
            priority TEXT NOT NULL DEFAULT 'normal',
            thread_id TEXT,
            read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        )""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_mail_to
            ON messages(to_agent, read, created_at DESC)""")
        conn.execute("""CREATE INDEX IF NOT EXISTS idx_mail_thread
            ON messages(thread_id, created_at)""")
        conn.commit()
        conn.close()

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5)
        conn.row_factory = sqlite3.Row
        return conn

    def send(self, from_agent: str, to_agent: str, body: str,
             subject: str = "", msg_type: str = "message",
             priority: str = "normal", thread_id: str = None) -> str:
        """Send a message. Supports group addresses (@all, @builders)."""
        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        if not thread_id:
            thread_id = msg_id  # New thread

        # Resolve group addresses
        recipients = self._resolve_recipients(to_agent, from_agent)

        conn = self._conn()
        for recipient in recipients:
            conn.execute(
                "INSERT INTO messages (id, from_agent, to_agent, subject, body, msg_type, priority, thread_id) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (f"{msg_id}-{recipient}" if len(recipients) > 1 else msg_id,
                 from_agent, recipient, subject, body, msg_type, priority, thread_id),
            )
        conn.commit()
        conn.close()
        return msg_id

    def _resolve_recipients(self, to_agent: str, from_agent: str) -> list:
        """Resolve group addresses to individual agents."""
        if to_agent in GROUPS:
            if GROUPS[to_agent] is None:
                # @all — get all known agents except sender
                conn = self._conn()
                rows = conn.execute(
                    "SELECT DISTINCT to_agent FROM messages UNION SELECT DISTINCT from_agent FROM messages"
                ).fetchall()
                conn.close()
                agents = list(set(r[0] for r in rows) - {from_agent})
                return agents if agents else ["master"]  # Fallback
            return [a for a in GROUPS[to_agent] if a != from_agent]
        return [to_agent]

    def inbox(self, agent: str, unread_only: bool = True, limit: int = 20) -> list:
        """Get messages for an agent."""
        conn = self._conn()
        if unread_only:
            rows = conn.execute(
                "SELECT * FROM messages WHERE to_agent = ? AND read = 0 ORDER BY created_at DESC LIMIT ?",
                (agent, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM messages WHERE to_agent = ? ORDER BY created_at DESC LIMIT ?",
                (agent, limit),
            ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def mark_read(self, agent: str, msg_id: str = None):
        """Mark messages as read. If no msg_id, mark all."""
        conn = self._conn()
        if msg_id:
            conn.execute("UPDATE messages SET read = 1 WHERE id = ? AND to_agent = ?", (msg_id, agent))
        else:
            conn.execute("UPDATE messages SET read = 1 WHERE to_agent = ?", (agent,))
        conn.commit()
        conn.close()

    def thread(self, thread_id: str) -> list:
        """Get all messages in a thread."""
        conn = self._conn()
        rows = conn.execute(
            "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at",
            (thread_id,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def reply(self, from_agent: str, thread_id: str, body: str, **kwargs) -> str:
        """Reply to a thread."""
        # Find original recipient to reply to
        conn = self._conn()
        original = conn.execute(
            "SELECT from_agent FROM messages WHERE thread_id = ? ORDER BY created_at LIMIT 1",
            (thread_id,),
        ).fetchone()
        conn.close()
        to_agent = original["from_agent"] if original else "master"
        return self.send(from_agent, to_agent, body, thread_id=thread_id, **kwargs)

    def stats(self) -> dict:
        """Get mail system statistics."""
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) as cnt FROM messages").fetchone()["cnt"]
        unread = conn.execute("SELECT COUNT(*) as cnt FROM messages WHERE read = 0").fetchone()["cnt"]
        agents = conn.execute(
            "SELECT to_agent, COUNT(*) as cnt, SUM(CASE WHEN read = 0 THEN 1 ELSE 0 END) as unread "
            "FROM messages GROUP BY to_agent ORDER BY cnt DESC"
        ).fetchall()
        conn.close()
        return {
            "total": total,
            "unread": unread,
            "by_agent": {r["to_agent"]: {"total": r["cnt"], "unread": r["unread"]} for r in agents},
        }


def main():
    if len(sys.argv) < 2:
        print("Mail — SQLite inter-agent messaging")
        print()
        print("Usage:")
        print("  mail.py send <from> <to> <body> [--subject S] [--priority high|normal|low]")
        print("  mail.py inbox <agent> [--all]")
        print("  mail.py read <agent> [msg-id]          # mark read")
        print("  mail.py thread <thread-id>")
        print("  mail.py reply <from> <thread-id> <body>")
        print("  mail.py stats")
        print()
        print(f"Groups: {', '.join(GROUPS.keys())}")
        return

    cmd = sys.argv[1]
    mail = MailSystem()

    if cmd == "send":
        if len(sys.argv) < 5:
            print("Usage: mail.py send <from> <to> <body>")
            return
        subject = ""
        priority = "normal"
        if "--subject" in sys.argv:
            subject = sys.argv[sys.argv.index("--subject") + 1]
        if "--priority" in sys.argv:
            priority = sys.argv[sys.argv.index("--priority") + 1]
        body = " ".join(a for a in sys.argv[4:] if a not in ("--subject", subject, "--priority", priority))
        msg_id = mail.send(sys.argv[2], sys.argv[3], body, subject=subject, priority=priority)
        print(f"  Sent {msg_id}: {sys.argv[2]} → {sys.argv[3]}")

    elif cmd == "inbox":
        if len(sys.argv) < 3:
            return
        show_all = "--all" in sys.argv
        messages = mail.inbox(sys.argv[2], unread_only=not show_all)
        if not messages:
            print(f"  No {'unread ' if not show_all else ''}messages for {sys.argv[2]}")
            return
        for m in messages:
            pri = f" [{m['priority'].upper()}]" if m["priority"] != "normal" else ""
            read = "" if m["read"] else " *NEW*"
            print(f"  {m['id'][:12]:12s} from:{m['from_agent']:10s}{pri}{read}")
            print(f"    {m['body'][:80]}")

    elif cmd == "read":
        if len(sys.argv) < 3:
            return
        msg_id = sys.argv[3] if len(sys.argv) > 3 else None
        mail.mark_read(sys.argv[2], msg_id)
        print(f"  Marked {'all' if not msg_id else msg_id} as read for {sys.argv[2]}")

    elif cmd == "thread":
        if len(sys.argv) < 3:
            return
        msgs = mail.thread(sys.argv[2])
        for m in msgs:
            print(f"  [{m['created_at']}] {m['from_agent']} → {m['to_agent']}: {m['body'][:60]}")

    elif cmd == "reply":
        if len(sys.argv) < 5:
            return
        msg_id = mail.reply(sys.argv[2], sys.argv[3], " ".join(sys.argv[4:]))
        print(f"  Reply sent: {msg_id}")

    elif cmd == "stats":
        s = mail.stats()
        print(f"Total: {s['total']} messages ({s['unread']} unread)")
        for agent, data in s["by_agent"].items():
            print(f"  {agent:15s} {data['total']:3d} total  {data['unread']:3d} unread")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
