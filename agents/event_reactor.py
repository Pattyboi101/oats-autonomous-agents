#!/usr/bin/env python3
"""Event Reactor — watches production for events and triggers orchestra actions.

Polls the production database for new claims, signups, errors, and traffic
spikes. When something happens, triggers the appropriate response via
Telegram notification and optional orchestra dispatch.

Usage:
    python3 scripts/event_reactor.py                    # run once
    python3 scripts/event_reactor.py --watch             # poll every 60s
    python3 scripts/event_reactor.py --watch --interval 30  # poll every 30s
"""

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# State file to track what we've already reacted to
STATE_FILE = Path(".orchestra/reactor_state.json")

# Telegram notification
TELEGRAM_SCRIPT = os.path.expanduser("~/.claude/telegram.sh")


def load_state() -> dict:
    """Load previous state to avoid duplicate reactions."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "last_check": None,
        "known_users": 0,
        "known_claims": 0,
        "known_signups": [],
        "known_claim_tools": [],
        "reactions_sent": [],
    }


def save_state(state: dict):
    """Persist state between checks."""
    state["last_check"] = datetime.now(timezone.utc).isoformat()
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def query_prod(sql: str) -> str:
    """Run a SQL query against production via Fly SSH."""
    escaped_sql = sql.replace('"', '\\"').replace("'", "'\\''")
    cmd = f"""~/.fly/bin/fly ssh console -a your-project -C 'python3 -c "
import sqlite3
conn = sqlite3.connect(\\"/data/your-project.db\\")
for r in conn.execute(\\"{escaped_sql}\\").fetchall():
    print(\\"|\\".join(str(x) for x in r))
conn.close()
"'"""
    try:
        result = subprocess.run(
            ["bash", "-c", cmd],
            capture_output=True, text=True, timeout=30
        )
        # Filter out Fly warnings
        lines = [l for l in result.stdout.strip().split("\n")
                 if l and not l.startswith(("Warning:", "Connecting", "Error:"))]
        return "\n".join(lines)
    except (subprocess.TimeoutExpired, Exception) as e:
        print(f"  SSH error: {e}")
        return ""


def notify(message: str):
    """Send Telegram notification."""
    try:
        subprocess.run(
            ["bash", TELEGRAM_SCRIPT, message],
            capture_output=True, timeout=10
        )
        print(f"  Notified: {message[:80]}...")
    except Exception as e:
        print(f"  Notification failed: {e}")


def check_new_signups(state: dict) -> list:
    """Check for new user signups."""
    result = query_prod(
        "SELECT id, email, created_at FROM users "
        "WHERE created_at > datetime('now', '-2 hours') "
        "ORDER BY created_at DESC"
    )
    events = []
    for line in result.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            user_id, email, created_at = parts[0], parts[1], parts[2]
            if email not in state.get("known_signups", []):
                events.append({
                    "type": "signup",
                    "user_id": user_id,
                    "email": email,
                    "created_at": created_at,
                })
                state.setdefault("known_signups", []).append(email)
    return events


def check_new_claims(state: dict) -> list:
    """Check for tools being claimed by makers."""
    result = query_prod(
        "SELECT t.slug, t.name, mc.created_at FROM magic_claim_tokens mc "
        "JOIN tools t ON t.id = mc.tool_id "
        "WHERE mc.used = 1 AND mc.created_at > datetime('now', '-2 hours') "
        "ORDER BY mc.created_at DESC"
    )
    events = []
    for line in result.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            slug, name, created_at = parts[0], parts[1], parts[2]
            key = f"{slug}:{created_at}"
            if key not in state.get("known_claim_tools", []):
                events.append({
                    "type": "claim",
                    "slug": slug,
                    "name": name,
                    "created_at": created_at,
                })
                state.setdefault("known_claim_tools", []).append(key)
    return events


def check_traffic_spike(state: dict) -> list:
    """Check for unusual traffic patterns."""
    result = query_prod(
        "SELECT COUNT(*) FROM page_views "
        "WHERE timestamp > datetime('now', '-1 hour')"
    )
    events = []
    try:
        hourly_views = int(result.strip())
        avg = state.get("avg_hourly_views", 50)
        if hourly_views > avg * 3 and hourly_views > 100:
            events.append({
                "type": "traffic_spike",
                "hourly_views": hourly_views,
                "average": avg,
                "multiplier": round(hourly_views / max(avg, 1), 1),
            })
        # Update rolling average
        state["avg_hourly_views"] = int(avg * 0.9 + hourly_views * 0.1)
    except (ValueError, ZeroDivisionError):
        pass
    return events


def check_search_activity(state: dict) -> list:
    """Check for interesting search patterns."""
    result = query_prod(
        "SELECT query, source, COUNT(*) as n FROM search_logs "
        "WHERE created_at > datetime('now', '-1 hour') "
        "GROUP BY query ORDER BY n DESC LIMIT 5"
    )
    events = []
    total_searches = 0
    for line in result.split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) >= 3:
            total_searches += int(parts[2])

    prev = state.get("last_hour_searches", 0)
    if total_searches > prev * 3 and total_searches > 20:
        events.append({
            "type": "search_spike",
            "searches": total_searches,
            "previous": prev,
        })
    state["last_hour_searches"] = total_searches
    return events


def react(events: list, state: dict):
    """React to detected events."""
    for event in events:
        event_type = event["type"]

        if event_type == "signup":
            notify(
                f"NEW SIGNUP: {event['email']} at {event['created_at']}. "
                f"Check /admin for details."
            )

        elif event_type == "claim":
            notify(
                f"TOOL CLAIMED: {event['name']} ({event['slug']}) at {event['created_at']}! "
                f"Draft a personal response — this maker engaged with our outreach. "
                f"your-project.ai/tool/{event['slug']}"
            )

        elif event_type == "traffic_spike":
            notify(
                f"TRAFFIC SPIKE: {event['hourly_views']} views in the last hour "
                f"({event['multiplier']}x normal). Check where it's coming from."
            )

        elif event_type == "search_spike":
            notify(
                f"SEARCH SPIKE: {event['searches']} searches in the last hour "
                f"(was {event['previous']}). Agents are active."
            )

        state.setdefault("reactions_sent", []).append({
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "details": event,
        })
        # Keep only last 50 reactions
        state["reactions_sent"] = state["reactions_sent"][-50:]


def run_check(state: dict) -> int:
    """Run all checks and react to events. Returns event count."""
    all_events = []
    all_events.extend(check_new_signups(state))
    all_events.extend(check_new_claims(state))
    all_events.extend(check_traffic_spike(state))
    all_events.extend(check_search_activity(state))

    if all_events:
        print(f"  {len(all_events)} event(s) detected!")
        react(all_events, state)
    else:
        print(f"  No new events.")

    return len(all_events)


def main():
    parser = argparse.ArgumentParser(description="Event Reactor — watch production for events")
    parser.add_argument("--watch", action="store_true", help="Continuously poll")
    parser.add_argument("--interval", type=int, default=60, help="Poll interval in seconds (default: 60)")
    args = parser.parse_args()

    state = load_state()

    if args.watch:
        print(f"Event Reactor watching (every {args.interval}s). Ctrl+C to stop.")
        try:
            while True:
                now = datetime.now().strftime("%H:%M:%S")
                print(f"[{now}] Checking...")
                run_check(state)
                save_state(state)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\nStopped.")
            save_state(state)
    else:
        print("Event Reactor — single check")
        count = run_check(state)
        save_state(state)
        print(f"Done. {count} event(s).")


if __name__ == "__main__":
    main()
