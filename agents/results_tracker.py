#!/usr/bin/env python3
"""Results Tracker — mini CRM for outreach and conversions.

Tracks every outreach email, contact attempt, claim, and conversion.
Answers: which template works? which targets convert? what's the pipeline?

Usage:
    python3 scripts/results_tracker.py                    # show dashboard
    python3 scripts/results_tracker.py add "email" "zeno@resend.com" "Resend" "data-led"
    python3 scripts/results_tracker.py update "zeno@resend.com" "replied"
    python3 scripts/results_tracker.py stats               # conversion stats
"""

import json
import sys
from datetime import datetime
from pathlib import Path
from collections import Counter

DB_FILE = Path(".orchestra/results_tracker.json")


def load() -> dict:
    if DB_FILE.exists():
        try:
            return json.loads(DB_FILE.read_text())
        except (json.JSONDecodeError, IOError):
            pass
    return {"contacts": [], "events": []}


def save(data: dict):
    DB_FILE.parent.mkdir(parents=True, exist_ok=True)
    DB_FILE.write_text(json.dumps(data, indent=2))


def add_contact(data: dict, channel: str, target: str, tool: str, template: str):
    contact = {
        "channel": channel,       # email, dm, pr, post
        "target": target,         # email address or handle
        "tool": tool,             # tool slug or name
        "template": template,     # which template used
        "status": "sent",         # sent, opened, replied, claimed, converted, ignored
        "sent_at": datetime.now().isoformat(),
        "updated_at": None,
        "notes": "",
    }
    data["contacts"].append(contact)
    data["events"].append({
        "type": "outreach",
        "target": target,
        "timestamp": datetime.now().isoformat(),
    })
    save(data)
    print(f"Added: {channel} to {target} about {tool} (template: {template})")


def update_contact(data: dict, target: str, new_status: str, notes: str = ""):
    found = False
    for c in reversed(data["contacts"]):
        if c["target"] == target:
            old_status = c["status"]
            c["status"] = new_status
            c["updated_at"] = datetime.now().isoformat()
            if notes:
                c["notes"] = notes
            data["events"].append({
                "type": "status_change",
                "target": target,
                "from": old_status,
                "to": new_status,
                "timestamp": datetime.now().isoformat(),
            })
            save(data)
            print(f"Updated: {target} {old_status} → {new_status}")
            found = True
            break
    if not found:
        print(f"Not found: {target}")


def show_dashboard(data: dict):
    contacts = data.get("contacts", [])
    if not contacts:
        print("No contacts tracked yet.")
        print("Add one: results_tracker.py add 'email' 'who@example.com' 'tool-name' 'template-type'")
        return

    print("=" * 60)
    print("  OUTREACH PIPELINE")
    print("=" * 60)

    # Status breakdown
    statuses = Counter(c["status"] for c in contacts)
    total = len(contacts)
    print(f"\n  Total contacts: {total}")
    for status in ["sent", "opened", "replied", "claimed", "converted", "ignored"]:
        count = statuses.get(status, 0)
        pct = f"({100*count//total}%)" if total else ""
        bar = "#" * (count * 2)
        if count:
            print(f"  {status:12s} {count:3d} {pct:5s} {bar}")

    # Template effectiveness
    print(f"\n  TEMPLATE EFFECTIVENESS:")
    templates = {}
    for c in contacts:
        t = c.get("template", "unknown")
        templates.setdefault(t, {"sent": 0, "replied": 0, "claimed": 0})
        templates[t]["sent"] += 1
        if c["status"] in ("replied", "claimed", "converted"):
            templates[t]["replied"] += 1
        if c["status"] in ("claimed", "converted"):
            templates[t]["claimed"] += 1

    print(f"  {'Template':20s} {'Sent':>5s} {'Replied':>8s} {'Claimed':>8s} {'Rate':>6s}")
    for t, stats in sorted(templates.items(), key=lambda x: -x[1]["sent"]):
        rate = f"{100*stats['replied']//stats['sent']}%" if stats["sent"] else "0%"
        print(f"  {t:20s} {stats['sent']:5d} {stats['replied']:8d} {stats['claimed']:8d} {rate:>6s}")

    # Recent activity
    recent = sorted(contacts, key=lambda c: c.get("updated_at") or c["sent_at"], reverse=True)[:10]
    print(f"\n  RECENT CONTACTS:")
    for c in recent:
        status_icon = {"sent": "📤", "replied": "💬", "claimed": "✅", "ignored": "❌", "converted": "💰"}.get(c["status"], "⏳")
        print(f"  {status_icon} {c['target'][:30]:30s} {c['status']:10s} {c.get('tool', ''):15s} {c.get('template', '')}")

    print("=" * 60)


def show_stats(data: dict):
    contacts = data.get("contacts", [])
    if not contacts:
        print("No data yet.")
        return

    total = len(contacts)
    replied = sum(1 for c in contacts if c["status"] in ("replied", "claimed", "converted"))
    claimed = sum(1 for c in contacts if c["status"] in ("claimed", "converted"))
    converted = sum(1 for c in contacts if c["status"] == "converted")

    print(f"Outreach Stats:")
    print(f"  Sent: {total}")
    print(f"  Reply rate: {100*replied//total}% ({replied}/{total})")
    print(f"  Claim rate: {100*claimed//total}% ({claimed}/{total})")
    print(f"  Conversion rate: {100*converted//total}% ({converted}/{total})")

    # By channel
    channels = Counter(c["channel"] for c in contacts)
    print(f"\n  By channel:")
    for ch, count in channels.most_common():
        ch_replied = sum(1 for c in contacts if c["channel"] == ch and c["status"] in ("replied", "claimed", "converted"))
        print(f"    {ch}: {count} sent, {ch_replied} replied ({100*ch_replied//count}%)")


def main():
    data = load()

    if len(sys.argv) < 2:
        show_dashboard(data)
        return

    cmd = sys.argv[1]

    if cmd == "add" and len(sys.argv) >= 6:
        add_contact(data, sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif cmd == "update" and len(sys.argv) >= 4:
        notes = sys.argv[4] if len(sys.argv) > 4 else ""
        update_contact(data, sys.argv[2], sys.argv[3], notes)
    elif cmd == "stats":
        show_stats(data)
    else:
        print("Usage:")
        print("  results_tracker.py                                    # dashboard")
        print("  results_tracker.py add 'email' 'who@x.com' 'tool' 'template'")
        print("  results_tracker.py update 'who@x.com' 'replied'")
        print("  results_tracker.py stats                              # conversion stats")


if __name__ == "__main__":
    main()
