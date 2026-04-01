#!/usr/bin/env python3
"""Team Coordinator — manage agent teams with task lists and message routing.

Inspired by Claude Code's TeamCreate/SendMessage/Task system.
Teams are groups of agents with shared task lists. Agents go idle between
turns and wake when they receive a message or get assigned a task.

Key concepts from Claude Code:
- Teams have a 1:1 correspondence with task lists
- Teammates go idle between turns (don't run continuously)
- Messages are automatically delivered (no polling)
- Any agent can assign tasks to any other agent
- Graceful shutdown via shutdown_request message

Usage:
    python3 tools/team_coordinator.py create "my-team" "Working on feature X"
    python3 tools/team_coordinator.py assign "my-team" "task-id" "agent-name"
    python3 tools/team_coordinator.py status "my-team"
    python3 tools/team_coordinator.py shutdown "my-team"
"""

import fcntl
import json
import sys
from datetime import datetime
from pathlib import Path


TEAMS_DIR = Path(".orchestra/teams")


class Team:
    def __init__(self, name: str):
        self.name = name
        self.dir = TEAMS_DIR / name
        self.config_path = self.dir / "config.json"
        self.tasks_path = self.dir / "tasks.json"
        self.messages_path = self.dir / "messages.json"

    def exists(self) -> bool:
        return self.config_path.exists()

    def create(self, description: str):
        self.dir.mkdir(parents=True, exist_ok=True)
        config = {
            "name": self.name,
            "description": description,
            "created_at": datetime.now().isoformat(),
            "status": "active",
            "members": [],
        }
        self.config_path.write_text(json.dumps(config, indent=2))
        self.tasks_path.write_text(json.dumps([], indent=2))
        self.messages_path.write_text(json.dumps([], indent=2))
        print(f"Team '{self.name}' created.")

    def load_config(self) -> dict:
        return json.loads(self.config_path.read_text())

    def save_config(self, config: dict):
        self.config_path.write_text(json.dumps(config, indent=2))

    # Lifecycle states (from ComposioHQ/agent-orchestrator + Overstory patterns)
    LIFECYCLE_STATES = {
        "idle": "waiting for tasks",
        "working": "executing a task",
        "reviewing": "work complete, awaiting review",
        "stuck": "blocked or errored, needs intervention",
        "done": "task completed successfully",
        "shutdown": "agent shut down",
    }

    def set_member_status(self, agent_name: str, status: str, detail: str = ""):
        """Update a member's lifecycle status."""
        if status not in self.LIFECYCLE_STATES:
            print(f"Invalid status: {status}. Valid: {list(self.LIFECYCLE_STATES.keys())}")
            return
        config = self.load_config()
        for member in config["members"]:
            if member["name"] == agent_name:
                member["status"] = status
                member["status_detail"] = detail
                member["status_updated"] = datetime.now().isoformat()
                self.save_config(config)
                return
        print(f"Member {agent_name} not found")

    def get_stuck_members(self) -> list:
        """Find members that are stuck — need escalation."""
        config = self.load_config()
        return [m for m in config["members"] if m.get("status") == "stuck"]

    def add_member(self, agent_name: str, agent_type: str = "general",
                   peer_id: str = None):
        config = self.load_config()
        member = {
            "name": agent_name,
            "type": agent_type,
            "peer_id": peer_id,
            "status": "idle",
            "status_detail": "",
            "status_updated": datetime.now().isoformat(),
            "joined_at": datetime.now().isoformat(),
            "tasks_completed": 0,
        }
        config["members"].append(member)
        self.save_config(config)
        print(f"Added {agent_name} ({agent_type}) to team '{self.name}'")

    def get_tasks(self) -> list:
        if self.tasks_path.exists():
            return json.loads(self.tasks_path.read_text())
        return []

    def save_tasks(self, tasks: list):
        self.tasks_path.write_text(json.dumps(tasks, indent=2))

    def _lock_tasks(self):
        """Acquire file lock on tasks for safe concurrent access."""
        lock_path = self.dir / "tasks.lock"
        lock_path.touch(exist_ok=True)
        self._lock_fd = open(lock_path, "w")
        fcntl.flock(self._lock_fd, fcntl.LOCK_EX)

    def _unlock_tasks(self):
        """Release file lock on tasks."""
        if hasattr(self, "_lock_fd") and self._lock_fd:
            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            self._lock_fd.close()

    def create_task(self, title: str, description: str = "",
                    owner: str = None, priority: str = "medium",
                    blocked_by: list = None) -> str:
        self._lock_tasks()
        try:
            tasks = self.get_tasks()
            task_id = f"t-{len(tasks) + 1:03d}"
            task = {
                "id": task_id,
                "title": title,
                "description": description,
                "status": "blocked" if blocked_by else "pending",
                "owner": owner,
                "priority": priority,
                "blocked_by": blocked_by or [],
                "blocks": [],
                "created_at": datetime.now().isoformat(),
                "completed_at": None,
            }
            # Update reverse references
            if blocked_by:
                for t in tasks:
                    if t["id"] in blocked_by:
                        if "blocks" not in t:
                            t["blocks"] = []
                        t["blocks"].append(task_id)
            tasks.append(task)
            self.save_tasks(tasks)
            status_msg = f" [blocked by {', '.join(blocked_by)}]" if blocked_by else ""
            owner_msg = f" (assigned to {owner})" if owner else ""
            print(f"Task {task_id}: {title}{owner_msg}{status_msg}")
            return task_id
        finally:
            self._unlock_tasks()

    def assign_task(self, task_id: str, owner: str):
        self._lock_tasks()
        try:
            tasks = self.get_tasks()
            for task in tasks:
                if task["id"] == task_id:
                    if task["status"] == "blocked":
                        print(f"Cannot assign {task_id} — blocked by {task.get('blocked_by', [])}")
                        return
                    if task["status"] == "in_progress" and task.get("owner"):
                        print(f"Cannot assign {task_id} — already claimed by {task['owner']}")
                        return
                    task["owner"] = owner
                    task["status"] = "in_progress"
                    self.save_tasks(tasks)
                    print(f"Assigned {task_id} to {owner}")
                    return
            print(f"Task {task_id} not found")
        finally:
            self._unlock_tasks()

    def claim_next(self, agent_name: str) -> str:
        """Agent self-claims the next available unblocked task."""
        self._lock_tasks()
        try:
            tasks = self.get_tasks()
            # Priority order: high > medium > low
            priority_order = {"high": 0, "medium": 1, "low": 2}
            pending = [t for t in tasks if t["status"] == "pending" and not t.get("owner")]
            pending.sort(key=lambda t: priority_order.get(t.get("priority", "medium"), 1))

            if not pending:
                print(f"No tasks available for {agent_name}")
                return None

            task = pending[0]
            task["owner"] = agent_name
            task["status"] = "in_progress"
            self.save_tasks(tasks)
            print(f"{agent_name} claimed {task['id']}: {task['title']}")
            return task["id"]
        finally:
            self._unlock_tasks()

    def complete_task(self, task_id: str, result: str = ""):
        self._lock_tasks()
        try:
            tasks = self.get_tasks()
            config = self.load_config()
            for task in tasks:
                if task["id"] == task_id:
                    task["status"] = "completed"
                    task["completed_at"] = datetime.now().isoformat()
                    task["result"] = result
                    # Update member stats
                    for member in config["members"]:
                        if member["name"] == task.get("owner"):
                            member["tasks_completed"] += 1
                    # Auto-unblock dependent tasks
                    unblocked = []
                    for other in tasks:
                        if task_id in other.get("blocked_by", []):
                            other["blocked_by"].remove(task_id)
                            if not other["blocked_by"] and other["status"] == "blocked":
                                other["status"] = "pending"
                                unblocked.append(other["id"])
                    self.save_tasks(tasks)
                    self.save_config(config)
                    print(f"Completed {task_id}")
                    if unblocked:
                        print(f"  Unblocked: {', '.join(unblocked)}")
                    return
            print(f"Task {task_id} not found")
        finally:
            self._unlock_tasks()

    def send_message(self, from_agent: str, to_agent: str, message: str):
        messages = json.loads(self.messages_path.read_text()) if self.messages_path.exists() else []
        msg = {
            "from": from_agent,
            "to": to_agent,
            "message": message,
            "timestamp": datetime.now().isoformat(),
            "read": False,
        }
        messages.append(msg)
        # Keep last 100
        messages = messages[-100:]
        self.messages_path.write_text(json.dumps(messages, indent=2))

    def get_messages(self, for_agent: str) -> list:
        messages = json.loads(self.messages_path.read_text()) if self.messages_path.exists() else []
        unread = [m for m in messages if m["to"] == for_agent and not m["read"]]
        # Mark as read
        for m in messages:
            if m["to"] == for_agent:
                m["read"] = True
        self.messages_path.write_text(json.dumps(messages, indent=2))
        return unread

    def status(self):
        if not self.exists():
            print(f"Team '{self.name}' not found.")
            return

        config = self.load_config()
        tasks = self.get_tasks()

        blocked = sum(1 for t in tasks if t["status"] == "blocked")
        pending = sum(1 for t in tasks if t["status"] == "pending")
        in_progress = sum(1 for t in tasks if t["status"] == "in_progress")
        completed = sum(1 for t in tasks if t["status"] == "completed")

        print(f"{'='*50}")
        print(f"  Team: {config['name']}")
        print(f"  Status: {config['status']}")
        print(f"  Description: {config['description']}")
        print(f"{'='*50}")
        print(f"\n  Members ({len(config['members'])}):")
        for m in config["members"]:
            print(f"    {m['name']:20s} {m['type']:12s} {m['status']:8s} "
                  f"done:{m['tasks_completed']}")

        print(f"\n  Tasks ({len(tasks)}):")
        print(f"    Blocked: {blocked} | Pending: {pending} | In Progress: {in_progress} | Completed: {completed}")
        for t in tasks:
            if t["status"] != "completed":
                icons = {"blocked": "🚫", "pending": "⏳", "in_progress": "🔄"}
                icon = icons.get(t["status"], "?")
                owner = f" [{t['owner']}]" if t.get("owner") else ""
                deps = ""
                if t.get("blocked_by"):
                    deps = f" (waiting for {', '.join(t['blocked_by'])})"
                print(f"    {icon} {t['id']}: {t['title']}{owner}{deps}")
        print(f"{'='*50}")

    def shutdown(self):
        config = self.load_config()
        config["status"] = "shutdown"
        for member in config["members"]:
            member["status"] = "shutdown"
        self.save_config(config)
        print(f"Team '{self.name}' shut down.")


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  team_coordinator.py create <name> <description>")
        print("  team_coordinator.py add-member <team> <name> <type>")
        print("  team_coordinator.py task <team> <title> [owner] [--blocked-by t-001,t-002]")
        print("  team_coordinator.py assign <team> <task-id> <owner>")
        print("  team_coordinator.py claim <team> <agent-name>       # self-claim next task")
        print("  team_coordinator.py complete <team> <task-id>")
        print("  team_coordinator.py status <team>")
        print("  team_coordinator.py shutdown <team>")
        print("  team_coordinator.py list")
        return

    cmd = sys.argv[1]

    if cmd == "create" and len(sys.argv) >= 4:
        Team(sys.argv[2]).create(sys.argv[3])

    elif cmd == "add-member" and len(sys.argv) >= 5:
        Team(sys.argv[2]).add_member(sys.argv[3], sys.argv[4])

    elif cmd == "task" and len(sys.argv) >= 4:
        owner = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else None
        blocked_by = None
        for i, arg in enumerate(sys.argv):
            if arg == "--blocked-by" and i + 1 < len(sys.argv):
                blocked_by = [x.strip() for x in sys.argv[i + 1].split(",")]
        Team(sys.argv[2]).create_task(sys.argv[3], owner=owner, blocked_by=blocked_by)

    elif cmd == "assign" and len(sys.argv) >= 5:
        Team(sys.argv[2]).assign_task(sys.argv[3], sys.argv[4])

    elif cmd == "claim" and len(sys.argv) >= 4:
        Team(sys.argv[2]).claim_next(sys.argv[3])

    elif cmd == "complete" and len(sys.argv) >= 4:
        Team(sys.argv[2]).complete_task(sys.argv[3])

    elif cmd == "status" and len(sys.argv) >= 3:
        Team(sys.argv[2]).status()

    elif cmd == "shutdown" and len(sys.argv) >= 3:
        Team(sys.argv[2]).shutdown()

    elif cmd == "list":
        if TEAMS_DIR.exists():
            teams = [d.name for d in TEAMS_DIR.iterdir() if d.is_dir()]
            for t in teams:
                config = json.loads((TEAMS_DIR / t / "config.json").read_text())
                print(f"  {t:20s} {config['status']:10s} {len(config['members'])} members")
        else:
            print("No teams.")
    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
