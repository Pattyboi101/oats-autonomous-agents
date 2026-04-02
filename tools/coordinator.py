#!/usr/bin/env python3
"""Coordinator — parallel worker dispatch, synthesis, and team management.

Two subsystems in one file:

1. PARALLEL DISPATCH (FileCollector, Coordination)
   Inspired by Claude Code's coordinator mode:
   - Lead spawns parallel worker agents independently
   - Workers write findings to ANALYSIS.md files
   - Lead reads all analyses and synthesizes into RECOMMENDATION.md
   - "Coordinator never writes code; it delegates and synthesises"
   - "Parallelism is your superpower. Workers are async."

   The workflow:
   1. DECOMPOSE: Break task into independent subtasks
   2. DISPATCH: Assign subtasks to workers (parallel)
   3. COLLECT: Wait for all workers to write ANALYSIS.md
   4. SYNTHESIZE: Lead combines findings into RECOMMENDATION.md
   5. DECIDE: Continue, correct, or complete

   File-based coordination (primary):
       Message passing between agents fails in unpredictable ways (ghost peers,
       stale IDs, connection drops). File-based coordination is more reliable.
       Each worker writes to /tmp/oats-{task_id}-{worker}.txt.
       The coordinator polls until all files exist or timeout.

2. TEAM MANAGEMENT (Team)
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
    # ── Parallel dispatch ──
    python3 tools/coordinator.py start "Improve search relevance" \\
        --workers backend frontend devops

    python3 tools/coordinator.py start-file "Improve search relevance" \\
        --workers backend frontend --timeout 300

    python3 tools/coordinator.py analyze "task-001" backend \\
        "Backend analysis: search scoring needs category boost..."

    python3 tools/coordinator.py collect "task-id"
    python3 tools/coordinator.py status "task-id"
    python3 tools/coordinator.py synthesize "task-001"

    # ── Team management ──
    python3 tools/coordinator.py team-create "my-team" "Working on feature X"
    python3 tools/coordinator.py team-add "my-team" "agent-name" "backend"
    python3 tools/coordinator.py team-task "my-team" "task title" [owner]
    python3 tools/coordinator.py team-assign "my-team" "task-id" "owner"
    python3 tools/coordinator.py team-claim "my-team" "agent-name"
    python3 tools/coordinator.py team-complete "my-team" "task-id"
    python3 tools/coordinator.py team-status "my-team"
    python3 tools/coordinator.py team-shutdown "my-team"
    python3 tools/coordinator.py team-list
"""

import fcntl
import json
import sys
import time
from datetime import datetime
from pathlib import Path


# ════════════════════════════════════════════════════════════════════════════════
# ── Parallel Dispatch ──
# ════════════════════════════════════════════════════════════════════════════════

COORD_DIR = Path(".oats/coordinations")


class FileCollector:
    """Collect results from workers via predictable file paths.

    More reliable than message passing. Each worker writes to:
    /tmp/oats-{task_id}-{worker_name}.txt

    The coordinator polls until all files exist or timeout.
    """

    def __init__(self, task_id: str, workers: list, result_dir: str = "/tmp"):
        self.task_id = task_id
        self.workers = list(workers)
        self.result_dir = Path(result_dir)

    def get_result_path(self, worker_name: str) -> Path:
        """Predictable file path for a worker's result."""
        return self.result_dir / f"oats-{self.task_id}-{worker_name}.txt"

    def collect(self, timeout_seconds: int = 300, poll_interval: int = 5) -> dict:
        """Poll for all worker result files. Returns {worker: content} when all present.

        Raises TimeoutError if not all files appear within timeout.
        """
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if self.is_complete():
                return self._read_all()
            remaining = int(deadline - time.time())
            missing = [w for w in self.workers if not self.get_result_path(w).exists()]
            print(f"  Waiting for: {', '.join(missing)} ({remaining}s remaining)")
            time.sleep(min(poll_interval, max(1, remaining)))
        # Final check after timeout
        if self.is_complete():
            return self._read_all()
        missing = [w for w in self.workers if not self.get_result_path(w).exists()]
        raise TimeoutError(
            f"Timeout after {timeout_seconds}s. Missing workers: {', '.join(missing)}"
        )

    def collect_available(self) -> dict:
        """Non-blocking -- returns whatever results are available right now."""
        results = {}
        for worker in self.workers:
            path = self.get_result_path(worker)
            if path.exists():
                results[worker] = path.read_text()
        return results

    def cleanup(self):
        """Remove all result files."""
        for worker in self.workers:
            path = self.get_result_path(worker)
            if path.exists():
                path.unlink()

    def is_complete(self) -> bool:
        """All workers have written results."""
        return all(self.get_result_path(w).exists() for w in self.workers)

    def _read_all(self) -> dict:
        """Read all worker result files."""
        return {w: self.get_result_path(w).read_text() for w in self.workers}


class Coordination:
    """A coordinated task with parallel workers and synthesis."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.dir = COORD_DIR / task_id
        self.config_path = self.dir / "config.json"

    def exists(self) -> bool:
        return self.config_path.exists()

    def start(self, description: str, workers: list, subtasks: dict = None,
              use_files: bool = False, result_dir: str = "/tmp"):
        """Start a new coordinated task.

        Args:
            use_files: When True, workers should write results to predictable
                       file paths instead of (or in addition to) message passing.
                       File paths: /tmp/oats-{task_id}-{worker}.txt
        """
        self.dir.mkdir(parents=True, exist_ok=True)

        config = {
            "task_id": self.task_id,
            "description": description,
            "status": "dispatched",
            "workers": {w: {"status": "pending", "assigned_at": datetime.now().isoformat()}
                        for w in workers},
            "subtasks": subtasks or {w: description for w in workers},
            "created_at": datetime.now().isoformat(),
            "synthesized_at": None,
            "use_files": use_files,
            "result_dir": result_dir,
        }

        self.config_path.write_text(json.dumps(config, indent=2))

        # Create analysis directory
        (self.dir / "analyses").mkdir(exist_ok=True)

        print(f"Coordination {self.task_id} started")
        print(f"  Description: {description}")
        print(f"  Workers: {', '.join(workers)}")
        if use_files:
            collector = FileCollector(self.task_id, workers, result_dir)
            print(f"  Mode: file-based collection")
            for w in workers:
                print(f"    {w} -> {collector.get_result_path(w)}")
        if subtasks:
            for w, task in subtasks.items():
                print(f"    {w}: {task[:80]}")

    def load(self) -> dict:
        return json.loads(self.config_path.read_text())

    def save(self, config: dict):
        self.config_path.write_text(json.dumps(config, indent=2))

    def submit_analysis(self, worker: str, analysis: str):
        """Worker submits their analysis."""
        if not self.exists():
            print(f"Coordination {self.task_id} not found")
            return

        config = self.load()
        if worker not in config["workers"]:
            print(f"Worker {worker} not in this coordination")
            return

        # Write analysis file
        analysis_path = self.dir / "analyses" / f"{worker}.md"
        content = f"""# Analysis: {worker}
**Task:** {config['subtasks'].get(worker, config['description'])}
**Date:** {datetime.now().isoformat()}

{analysis}
"""
        analysis_path.write_text(content)

        # Update status
        config["workers"][worker]["status"] = "completed"
        config["workers"][worker]["completed_at"] = datetime.now().isoformat()
        config["workers"][worker]["analysis_size"] = len(analysis)
        self.save(config)

        print(f"Analysis submitted by {worker} ({len(analysis)} chars)")

        # Check if all done
        all_done = all(w["status"] == "completed" for w in config["workers"].values())
        if all_done:
            print(f"All workers complete — ready for synthesis")

    def collect_results(self, timeout_seconds: int = 300, poll_interval: int = 5) -> dict:
        """Collect results using FileCollector. Only works for file-based coordinations."""
        if not self.exists():
            print(f"Coordination {self.task_id} not found")
            return {}

        config = self.load()
        if not config.get("use_files"):
            print(f"Coordination {self.task_id} is not file-based. "
                  f"Use 'start-file' to create file-based coordinations.")
            return {}

        workers = list(config["workers"].keys())
        result_dir = config.get("result_dir", "/tmp")
        collector = FileCollector(self.task_id, workers, result_dir)

        available = collector.collect_available()
        total = len(workers)
        done = len(available)
        print(f"File collection for {self.task_id}: {done}/{total} workers")

        if done == total:
            print(f"All results collected:")
            for worker, content in available.items():
                print(f"\n{'='*50}")
                print(f"  Worker: {worker}")
                print(f"  Size: {len(content)} chars")
                print(f"{'='*50}")
                print(content[:500])
                if len(content) > 500:
                    print(f"  ... ({len(content) - 500} more chars)")
            return available

        # Blocking wait
        print(f"Waiting for remaining workers (timeout: {timeout_seconds}s)...")
        try:
            results = collector.collect(timeout_seconds, poll_interval)
            print(f"\nAll {total} results collected:")
            for worker, content in results.items():
                print(f"\n{'='*50}")
                print(f"  Worker: {worker}")
                print(f"  Size: {len(content)} chars")
                print(f"{'='*50}")
                print(content[:500])
                if len(content) > 500:
                    print(f"  ... ({len(content) - 500} more chars)")
            return results
        except TimeoutError as e:
            print(f"Timeout: {e}")
            return collector.collect_available()

    def status(self):
        """Show coordination status."""
        if not self.exists():
            print(f"Coordination {self.task_id} not found")
            return

        config = self.load()
        total = len(config["workers"])
        done = sum(1 for w in config["workers"].values() if w["status"] == "completed")

        print(f"{'='*50}")
        print(f"  Coordination: {self.task_id}")
        print(f"  Status: {config['status']}")
        print(f"  Description: {config['description'][:80]}")
        print(f"  Progress: {done}/{total} workers complete")
        print(f"{'='*50}")

        for name, info in config["workers"].items():
            icon = {"pending": "⏳", "completed": "✅", "failed": "❌"}.get(info["status"], "?")
            size = f" ({info.get('analysis_size', 0)} chars)" if info["status"] == "completed" else ""
            subtask = config["subtasks"].get(name, "")
            print(f"  {icon} {name:15s} {info['status']:12s}{size}")
            if subtask and subtask != config["description"]:
                print(f"     task: {subtask[:70]}")

        # File-based collection status
        if config.get("use_files"):
            workers = list(config["workers"].keys())
            result_dir = config.get("result_dir", "/tmp")
            collector = FileCollector(self.task_id, workers, result_dir)
            available = collector.collect_available()
            file_done = len(available)
            print(f"\n  File collection: {file_done}/{total} files written")
            for w in workers:
                path = collector.get_result_path(w)
                exists = path.exists()
                status_icon = "[x]" if exists else "[ ]"
                size_str = f" ({path.stat().st_size} bytes)" if exists else ""
                print(f"    {status_icon} {path}{size_str}")

        if config.get("synthesized_at"):
            print(f"\n  Synthesized: {config['synthesized_at']}")
            rec_path = self.dir / "RECOMMENDATION.md"
            if rec_path.exists():
                print(f"  Recommendation: {rec_path}")

        print(f"{'='*50}")

    def synthesize(self) -> str:
        """Lead synthesizes all analyses into a recommendation."""
        if not self.exists():
            print(f"Coordination {self.task_id} not found")
            return ""

        config = self.load()

        # Check all workers are done
        pending = [n for n, w in config["workers"].items() if w["status"] != "completed"]
        if pending:
            print(f"Cannot synthesize — waiting for: {', '.join(pending)}")
            return ""

        # Read all analyses
        analyses = {}
        analysis_dir = self.dir / "analyses"
        for analysis_file in sorted(analysis_dir.glob("*.md")):
            worker = analysis_file.stem
            analyses[worker] = analysis_file.read_text()

        # Build synthesis
        sections = []
        sections.append(f"# Recommendation: {config['description']}")
        sections.append(f"**Synthesized:** {datetime.now().isoformat()}")
        sections.append(f"**Workers:** {', '.join(config['workers'].keys())}")
        sections.append("")

        # Individual analyses
        sections.append("## Worker Analyses")
        sections.append("")
        for worker, analysis in analyses.items():
            sections.append(f"### {worker}")
            # Extract just the content (skip header)
            lines = analysis.split("\n")
            content_lines = [l for l in lines if not l.startswith("#") and not l.startswith("**")]
            sections.append("\n".join(content_lines).strip())
            sections.append("")

        # Cross-cutting themes
        sections.append("## Cross-Cutting Themes")
        sections.append("")
        sections.append("_The coordinator should identify common themes, conflicts,_")
        sections.append("_and complementary insights across worker analyses._")
        sections.append("")

        # Action items
        sections.append("## Recommended Actions")
        sections.append("")
        sections.append("_Ranked by impact. Include owner and effort estimate._")
        sections.append("")
        sections.append("| # | Action | Owner | Effort | Impact |")
        sections.append("|---|--------|-------|--------|--------|")
        sections.append("| 1 | [TBD — synthesize from analyses] | | | |")
        sections.append("")

        recommendation = "\n".join(sections)

        # Write recommendation
        rec_path = self.dir / "RECOMMENDATION.md"
        rec_path.write_text(recommendation)

        # Update config
        config["status"] = "synthesized"
        config["synthesized_at"] = datetime.now().isoformat()
        self.save(config)

        print(f"Synthesis complete: {rec_path}")
        print(f"  {len(analyses)} analyses combined")
        print(f"  Recommendation: {len(recommendation)} chars")

        return recommendation

    def complete(self, decision: str = "accepted"):
        """Mark coordination as complete with a decision."""
        config = self.load()
        config["status"] = "completed"
        config["decision"] = decision
        config["completed_at"] = datetime.now().isoformat()
        self.save(config)
        print(f"Coordination {self.task_id} completed: {decision}")


def generate_task_id() -> str:
    """Generate a unique task ID."""
    import hashlib
    ts = datetime.now().isoformat()
    return "coord-" + hashlib.md5(ts.encode()).hexdigest()[:8]


# ════════════════════════════════════════════════════════════════════════════════
# ── Team Management ──
# ════════════════════════════════════════════════════════════════════════════════

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


# ════════════════════════════════════════════════════════════════════════════════
# ── CLI ──
# ════════════════════════════════════════════════════════════════════════════════

def main():
    if len(sys.argv) < 2:
        print("Coordinator — parallel dispatch, synthesis, and team management")
        print()
        print("Parallel dispatch:")
        print("  coordinator.py start <description> --workers w1 w2 w3")
        print("  coordinator.py start-file <description> --workers w1 w2 [--timeout 300]")
        print("  coordinator.py analyze <task-id> <worker> <analysis>")
        print("  coordinator.py collect <task-id> [--timeout 300]")
        print("  coordinator.py status <task-id>")
        print("  coordinator.py synthesize <task-id>")
        print("  coordinator.py complete <task-id> [decision]")
        print("  coordinator.py list")
        print()
        print("Team management:")
        print("  coordinator.py team-create <name> <description>")
        print("  coordinator.py team-add <team> <name> <type>")
        print("  coordinator.py team-task <team> <title> [owner] [--blocked-by t-001,t-002]")
        print("  coordinator.py team-assign <team> <task-id> <owner>")
        print("  coordinator.py team-claim <team> <agent-name>")
        print("  coordinator.py team-complete <team> <task-id>")
        print("  coordinator.py team-status <team>")
        print("  coordinator.py team-shutdown <team>")
        print("  coordinator.py team-list")
        print()
        print("The coordinator pattern:")
        print("  1. Lead decomposes task into subtasks for workers")
        print("  2. Workers analyze independently and write findings")
        print("  3. Lead synthesizes all analyses into recommendation")
        print("  4. Decision: continue, correct, or complete")
        print()
        print("File-based mode (recommended):")
        print("  start-file creates predictable paths: /tmp/oats-{id}-{worker}.txt")
        print("  Workers write results to those paths. More reliable than messaging.")
        print("  collect waits for all files to appear, or shows what's available.")
        return

    cmd = sys.argv[1]

    # ── Parallel dispatch commands ──

    if cmd == "start":
        if len(sys.argv) < 3:
            print("Usage: coordinator.py start <description> --workers w1 w2 ...")
            return

        desc = sys.argv[2]
        workers = []
        subtasks = {}

        # Parse --workers
        if "--workers" in sys.argv:
            idx = sys.argv.index("--workers")
            workers = sys.argv[idx + 1:]
            # Filter out any other flags
            workers = [w for w in workers if not w.startswith("--")]

        if not workers:
            workers = ["backend", "frontend", "devops"]

        task_id = generate_task_id()
        coord = Coordination(task_id)
        coord.start(desc, workers, subtasks)

    elif cmd == "start-file":
        if len(sys.argv) < 3:
            print("Usage: coordinator.py start-file <description> --workers w1 w2 [--timeout 300]")
            return

        desc = sys.argv[2]
        workers = []
        timeout = 300

        # Parse --workers (collect args until next flag or end)
        if "--workers" in sys.argv:
            idx = sys.argv.index("--workers")
            workers = []
            for arg in sys.argv[idx + 1:]:
                if arg.startswith("--"):
                    break
                workers.append(arg)

        # Parse --timeout
        if "--timeout" in sys.argv:
            idx = sys.argv.index("--timeout")
            if idx + 1 < len(sys.argv):
                timeout = int(sys.argv[idx + 1])

        if not workers:
            workers = ["backend", "frontend", "devops"]

        task_id = generate_task_id()
        coord = Coordination(task_id)
        coord.start(desc, workers, use_files=True)
        print(f"\n  Task ID: {task_id}")
        print(f"  Workers should write results to their file paths above.")
        print(f"  Then run: python3 tools/coordinator.py collect {task_id}")

    elif cmd == "collect":
        if len(sys.argv) < 3:
            print("Usage: coordinator.py collect <task-id> [--timeout 300]")
            return

        task_id = sys.argv[2]
        timeout = 300
        if "--timeout" in sys.argv:
            idx = sys.argv.index("--timeout")
            if idx + 1 < len(sys.argv):
                timeout = int(sys.argv[idx + 1])

        Coordination(task_id).collect_results(timeout_seconds=timeout)

    elif cmd == "analyze":
        if len(sys.argv) < 5:
            print("Usage: coordinator.py analyze <task-id> <worker> <analysis-text>")
            return
        task_id = sys.argv[2]
        worker = sys.argv[3]
        analysis = " ".join(sys.argv[4:])
        Coordination(task_id).submit_analysis(worker, analysis)

    elif cmd == "status":
        if len(sys.argv) < 3:
            print("Usage: coordinator.py status <task-id>")
            return
        Coordination(sys.argv[2]).status()

    elif cmd == "synthesize":
        if len(sys.argv) < 3:
            print("Usage: coordinator.py synthesize <task-id>")
            return
        Coordination(sys.argv[2]).synthesize()

    elif cmd == "complete":
        if len(sys.argv) < 3:
            print("Usage: coordinator.py complete <task-id> [decision]")
            return
        decision = sys.argv[3] if len(sys.argv) > 3 else "accepted"
        Coordination(sys.argv[2]).complete(decision)

    elif cmd == "list":
        if not COORD_DIR.exists():
            print("No coordinations.")
            return

        for d in sorted(COORD_DIR.iterdir()):
            if d.is_dir() and (d / "config.json").exists():
                config = json.loads((d / "config.json").read_text())
                workers = config.get("workers", {})
                done = sum(1 for w in workers.values() if w["status"] == "completed")
                print(f"  {d.name:20s} {config['status']:15s} "
                      f"{done}/{len(workers)} workers  {config['description'][:40]}")

    # ── Team management commands ──

    elif cmd == "team-create" and len(sys.argv) >= 4:
        Team(sys.argv[2]).create(sys.argv[3])

    elif cmd == "team-add" and len(sys.argv) >= 5:
        Team(sys.argv[2]).add_member(sys.argv[3], sys.argv[4])

    elif cmd == "team-task" and len(sys.argv) >= 4:
        owner = sys.argv[4] if len(sys.argv) > 4 and not sys.argv[4].startswith("--") else None
        blocked_by = None
        for i, arg in enumerate(sys.argv):
            if arg == "--blocked-by" and i + 1 < len(sys.argv):
                blocked_by = [x.strip() for x in sys.argv[i + 1].split(",")]
        Team(sys.argv[2]).create_task(sys.argv[3], owner=owner, blocked_by=blocked_by)

    elif cmd == "team-assign" and len(sys.argv) >= 5:
        Team(sys.argv[2]).assign_task(sys.argv[3], sys.argv[4])

    elif cmd == "team-claim" and len(sys.argv) >= 4:
        Team(sys.argv[2]).claim_next(sys.argv[3])

    elif cmd == "team-complete" and len(sys.argv) >= 4:
        Team(sys.argv[2]).complete_task(sys.argv[3])

    elif cmd == "team-status" and len(sys.argv) >= 3:
        Team(sys.argv[2]).status()

    elif cmd == "team-shutdown" and len(sys.argv) >= 3:
        Team(sys.argv[2]).shutdown()

    elif cmd == "team-list":
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
