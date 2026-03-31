#!/usr/bin/env python3
"""Session State Manager — persistent state that survives restarts.

Tracks what's in progress, recent decisions, blockers, and department status.
Master reads this on cold start instead of re-reading everything.

Usage:
    python3 scripts/session_state.py                # show current state
    python3 scripts/session_state.py save            # save snapshot
    python3 scripts/session_state.py set key value   # set a field
    python3 scripts/session_state.py log "message"   # append to activity log
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STATE_FILE = Path(".orchestra/session_state.json")


def load() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "last_updated": None,
        "current_focus": "Not set",
        "in_progress": [],
        "blocked_on": [],
        "recent_decisions": [],
        "departments_online": [],
        "session_cost": 0.0,
        "deploys_today": 0,
        "activity_log": [],
    }


def save(state: dict):
    state["last_updated"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def show(state: dict):
    print("=" * 50)
    print("  SESSION STATE")
    print("=" * 50)
    print(f"  Last updated: {state.get('last_updated', 'never')}")
    print(f"  Focus: {state.get('current_focus', 'Not set')}")
    print()

    if state.get("in_progress"):
        print("  IN PROGRESS:")
        for item in state["in_progress"]:
            print(f"    - {item}")
    else:
        print("  IN PROGRESS: (nothing)")

    if state.get("blocked_on"):
        print("  BLOCKED ON:")
        for item in state["blocked_on"]:
            print(f"    - {item}")

    if state.get("recent_decisions"):
        print("  RECENT DECISIONS:")
        for d in state["recent_decisions"][-5:]:
            print(f"    - {d}")

    print(f"\n  Deploys today: {state.get('deploys_today', 0)}")
    print(f"  Session cost: ${state.get('session_cost', 0):.2f}")

    if state.get("activity_log"):
        print("\n  ACTIVITY LOG (last 10):")
        for entry in state["activity_log"][-10:]:
            print(f"    [{entry.get('time', '?')}] {entry.get('message', '')}")
    print("=" * 50)


def main():
    state = load()

    if len(sys.argv) < 2:
        show(state)
        return

    cmd = sys.argv[1]

    if cmd == "save":
        save(state)
        print("State saved.")

    elif cmd == "set" and len(sys.argv) >= 4:
        key = sys.argv[2]
        value = sys.argv[3]
        if key in ("session_cost", "deploys_today"):
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                pass
        state[key] = value
        save(state)
        print(f"Set {key} = {value}")

    elif cmd == "log" and len(sys.argv) >= 3:
        message = " ".join(sys.argv[2:])
        state.setdefault("activity_log", []).append({
            "time": datetime.now().strftime("%H:%M"),
            "message": message,
        })
        # Keep last 50
        state["activity_log"] = state["activity_log"][-50:]
        save(state)
        print(f"Logged: {message}")

    elif cmd == "add-progress" and len(sys.argv) >= 3:
        item = " ".join(sys.argv[2:])
        state.setdefault("in_progress", []).append(item)
        save(state)
        print(f"Added to in_progress: {item}")

    elif cmd == "done" and len(sys.argv) >= 3:
        item = " ".join(sys.argv[2:])
        state["in_progress"] = [i for i in state.get("in_progress", []) if item.lower() not in i.lower()]
        state.setdefault("activity_log", []).append({
            "time": datetime.now().strftime("%H:%M"),
            "message": f"Completed: {item}",
        })
        save(state)
        print(f"Marked done: {item}")

    elif cmd == "block" and len(sys.argv) >= 3:
        blocker = " ".join(sys.argv[2:])
        state.setdefault("blocked_on", []).append(blocker)
        save(state)
        print(f"Added blocker: {blocker}")

    elif cmd == "unblock" and len(sys.argv) >= 3:
        blocker = " ".join(sys.argv[2:])
        state["blocked_on"] = [b for b in state.get("blocked_on", []) if blocker.lower() not in b.lower()]
        save(state)
        print(f"Removed blocker: {blocker}")

    elif cmd == "decide" and len(sys.argv) >= 3:
        decision = " ".join(sys.argv[2:])
        state.setdefault("recent_decisions", []).append(decision)
        state["recent_decisions"] = state["recent_decisions"][-10:]
        save(state)
        print(f"Logged decision: {decision}")

    elif cmd == "reset":
        STATE_FILE.unlink(missing_ok=True)
        print("State reset.")

    else:
        print("Usage:")
        print("  session_state.py              # show state")
        print("  session_state.py save         # save snapshot")
        print("  session_state.py set key val  # set field")
        print("  session_state.py log 'msg'    # append to log")
        print("  session_state.py add-progress 'task'")
        print("  session_state.py done 'task'")
        print("  session_state.py block 'reason'")
        print("  session_state.py unblock 'reason'")
        print("  session_state.py decide 'decision'")
        print("  session_state.py reset        # clear all state")


if __name__ == "__main__":
    main()
