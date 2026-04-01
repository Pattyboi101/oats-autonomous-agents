#!/usr/bin/env python3
"""Reflect — schedule continuation of thought across sessions.

The idea: an agent finishes a task, writes down what it did and what
it's unsure about, then schedules a future session to come back with
fresh eyes. The new session reads the reflection cold — no confirmation
bias, no anchoring to decisions made during building.

This is self-review with a time gap. Not a cron that runs forever.
A single deferred thought that fires once.

How it works:
1. Agent finishes a task
2. Agent writes a reflection: what was built, what's uncertain, what to check
3. Reflection is saved to .oats/reflections/pending/
4. A cron fires after N hours, reads the reflection, and acts on it
5. The new session has full context window — fresh perspective
6. After acting, reflection moves to .oats/reflections/done/

The reflection file IS the continuation of thought. It's the bridge
between sessions — what the agent would think about in the shower if
agents took showers.

Usage:
    # Schedule a reflection (agent calls this after finishing work)
    reflect = Reflection()
    reflect.create(
        topic="search ranking SQL performance",
        context="Added a subquery to _engagement_expr that hits agent_actions table on every search. Might be slow at scale.",
        questions=["Is the subquery indexed?", "Should we cache success rates?", "Load test it."],
        delay_hours=2,
    )

    # Later session reads pending reflections
    pending = Reflection.get_pending()
    for r in pending:
        print(r)  # fresh eyes on the problem

    # After acting on it
    reflect.complete("reflection-id", outcome="Added index. Load tested. 3ms overhead. Acceptable.")

CLI:
    python3 tools/reflect.py create "topic" "context" --questions "Q1" "Q2" --delay 2
    python3 tools/reflect.py pending
    python3 tools/reflect.py read <reflection-id>
    python3 tools/reflect.py complete <reflection-id> "what I did about it"
    python3 tools/reflect.py history
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path


REFLECT_DIR = Path(".oats/reflections")
PENDING_DIR = REFLECT_DIR / "pending"
DONE_DIR = REFLECT_DIR / "done"


class Reflection:
    """A deferred thought — scheduled continuation across sessions."""

    def __init__(self):
        PENDING_DIR.mkdir(parents=True, exist_ok=True)
        DONE_DIR.mkdir(parents=True, exist_ok=True)

    def create(self, topic: str, context: str, questions: list = None,
               delay_hours: float = 2, related_files: list = None,
               related_commits: list = None) -> str:
        """Create a new reflection to revisit later.

        Args:
            topic: What to think about (short title)
            context: What was built/changed and why
            questions: Specific things to check with fresh eyes
            delay_hours: How long to wait before revisiting
            related_files: Files to re-read when reflecting
            related_commits: Git commits to review
        """
        ref_id = f"reflect-{uuid.uuid4().hex[:8]}"
        fire_at = datetime.now() + timedelta(hours=delay_hours)

        reflection = {
            "id": ref_id,
            "topic": topic,
            "context": context,
            "questions": questions or [],
            "related_files": related_files or [],
            "related_commits": related_commits or [],
            "created_at": datetime.now().isoformat(),
            "fire_at": fire_at.isoformat(),
            "delay_hours": delay_hours,
            "status": "pending",
            "outcome": None,
        }

        path = PENDING_DIR / f"{ref_id}.json"
        path.write_text(json.dumps(reflection, indent=2))

        print(f"Reflection scheduled: {ref_id}")
        print(f"  Topic: {topic}")
        print(f"  Fire at: {fire_at.strftime('%H:%M')} ({delay_hours}h from now)")
        if questions:
            print(f"  Questions:")
            for q in questions:
                print(f"    - {q}")

        return ref_id

    @staticmethod
    def get_pending() -> list:
        """Get all pending reflections that are ready to fire."""
        if not PENDING_DIR.exists():
            return []

        ready = []
        now = datetime.now()

        for path in sorted(PENDING_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text())
                fire_at = datetime.fromisoformat(data["fire_at"])
                data["_ready"] = now >= fire_at
                data["_path"] = str(path)
                ready.append(data)
            except Exception:
                pass

        return ready

    @staticmethod
    def get_ready() -> list:
        """Get only reflections that have passed their fire_at time."""
        return [r for r in Reflection.get_pending() if r["_ready"]]

    @staticmethod
    def read(ref_id: str) -> dict:
        """Read a specific reflection."""
        path = PENDING_DIR / f"{ref_id}.json"
        if not path.exists():
            path = DONE_DIR / f"{ref_id}.json"
        if not path.exists():
            return None
        return json.loads(path.read_text())

    def complete(self, ref_id: str, outcome: str):
        """Mark a reflection as done with what was learned/changed."""
        src = PENDING_DIR / f"{ref_id}.json"
        if not src.exists():
            print(f"Reflection {ref_id} not found in pending.")
            return

        data = json.loads(src.read_text())
        data["status"] = "completed"
        data["outcome"] = outcome
        data["completed_at"] = datetime.now().isoformat()

        # Move to done
        dst = DONE_DIR / f"{ref_id}.json"
        dst.write_text(json.dumps(data, indent=2))
        src.unlink()

        print(f"Reflection {ref_id} completed.")
        print(f"  Outcome: {outcome[:100]}")

    @staticmethod
    def render_prompt(reflection: dict) -> str:
        """Render a reflection as a prompt for a new session.

        This is what the continuation session reads to pick up the thought.
        """
        lines = [
            f"# Reflection: {reflection['topic']}",
            f"**Created:** {reflection['created_at']}",
            f"**Delay:** {reflection['delay_hours']}h (fresh eyes)",
            "",
            "## Context (what was built)",
            reflection["context"],
            "",
        ]

        if reflection.get("questions"):
            lines.append("## Questions to answer with fresh eyes")
            for q in reflection["questions"]:
                lines.append(f"- [ ] {q}")
            lines.append("")

        if reflection.get("related_files"):
            lines.append("## Files to re-read")
            for f in reflection["related_files"]:
                lines.append(f"- `{f}`")
            lines.append("")

        if reflection.get("related_commits"):
            lines.append("## Commits to review")
            for c in reflection["related_commits"]:
                lines.append(f"- `{c}`")
            lines.append("")

        lines.append("## Instructions")
        lines.append("Read the context above with fresh eyes. You did NOT build this — ")
        lines.append("approach it as a reviewer. Check the questions. If something is wrong,")
        lines.append("fix it and commit. If everything is fine, note why and complete the reflection.")

        return "\n".join(lines)

    @staticmethod
    def history(limit: int = 20) -> list:
        """Get completed reflections."""
        done = []
        if DONE_DIR.exists():
            for path in sorted(DONE_DIR.glob("*.json"), reverse=True)[:limit]:
                try:
                    done.append(json.loads(path.read_text()))
                except Exception:
                    pass
        return done


def main():
    if len(sys.argv) < 2:
        print("Reflect — schedule continuation of thought across sessions")
        print()
        print("Usage:")
        print("  reflect.py create <topic> <context> [--questions Q1 Q2] [--delay N] [--files f1 f2]")
        print("  reflect.py pending                    # show all pending reflections")
        print("  reflect.py ready                      # show reflections ready to fire")
        print("  reflect.py read <reflection-id>       # read a specific reflection")
        print("  reflect.py prompt <reflection-id>     # render as a session prompt")
        print("  reflect.py complete <id> <outcome>    # mark done with outcome")
        print("  reflect.py history                    # show completed reflections")
        return

    cmd = sys.argv[1]
    ref = Reflection()

    if cmd == "create":
        if len(sys.argv) < 4:
            print("Usage: reflect.py create <topic> <context> [--questions Q1 Q2] [--delay N]")
            return
        topic = sys.argv[2]
        context = sys.argv[3]
        questions = []
        delay = 2.0
        files = []
        commits = []

        i = 4
        while i < len(sys.argv):
            if sys.argv[i] == "--questions":
                i += 1
                while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                    questions.append(sys.argv[i])
                    i += 1
            elif sys.argv[i] == "--delay" and i + 1 < len(sys.argv):
                delay = float(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--files":
                i += 1
                while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                    files.append(sys.argv[i])
                    i += 1
            elif sys.argv[i] == "--commits":
                i += 1
                while i < len(sys.argv) and not sys.argv[i].startswith("--"):
                    commits.append(sys.argv[i])
                    i += 1
            else:
                i += 1

        ref.create(topic, context, questions=questions, delay_hours=delay,
                   related_files=files, related_commits=commits)

    elif cmd == "pending":
        pending = Reflection.get_pending()
        if not pending:
            print("No pending reflections.")
            return
        now = datetime.now()
        for r in pending:
            fire = datetime.fromisoformat(r["fire_at"])
            status = "READY" if r["_ready"] else f"in {(fire - now).seconds // 60}min"
            print(f"  {r['id']:25s} [{status:>8s}] {r['topic']}")
            if r.get("questions"):
                for q in r["questions"][:2]:
                    print(f"    ? {q}")

    elif cmd == "ready":
        ready = Reflection.get_ready()
        if not ready:
            print("No reflections ready to fire.")
            return
        for r in ready:
            print(f"\n{'='*50}")
            print(Reflection.render_prompt(r))
            print(f"{'='*50}")

    elif cmd == "read":
        if len(sys.argv) < 3:
            return
        r = Reflection.read(sys.argv[2])
        if r:
            print(json.dumps(r, indent=2))
        else:
            print("Not found.")

    elif cmd == "prompt":
        if len(sys.argv) < 3:
            return
        r = Reflection.read(sys.argv[2])
        if r:
            print(Reflection.render_prompt(r))
        else:
            print("Not found.")

    elif cmd == "complete":
        if len(sys.argv) < 4:
            print("Usage: reflect.py complete <id> <outcome>")
            return
        ref.complete(sys.argv[2], " ".join(sys.argv[3:]))

    elif cmd == "history":
        history = Reflection.history()
        if not history:
            print("No completed reflections.")
            return
        for r in history:
            print(f"  {r['id']:25s} {r['topic']}")
            print(f"    Outcome: {(r.get('outcome') or '')[:80]}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
