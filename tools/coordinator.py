#!/usr/bin/env python3
"""Coordinator — parallel worker dispatch with synthesis.

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

Usage:
    # Start a coordinated task
    python3 tools/coordinator.py start "Improve search relevance" \
        --workers backend frontend devops

    # Worker writes their analysis
    python3 tools/coordinator.py analyze "task-001" backend \
        "Backend analysis: search scoring needs category boost..."

    # Check if all workers are done
    python3 tools/coordinator.py status "task-001"

    # Synthesize all analyses into recommendation
    python3 tools/coordinator.py synthesize "task-001"
"""

import json
import sys
from datetime import datetime
from pathlib import Path


COORD_DIR = Path(".oats/coordinations")


class Coordination:
    """A coordinated task with parallel workers and synthesis."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        self.dir = COORD_DIR / task_id
        self.config_path = self.dir / "config.json"

    def exists(self) -> bool:
        return self.config_path.exists()

    def start(self, description: str, workers: list, subtasks: dict = None):
        """Start a new coordinated task."""
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
        }

        self.config_path.write_text(json.dumps(config, indent=2))

        # Create analysis directory
        (self.dir / "analyses").mkdir(exist_ok=True)

        print(f"Coordination {self.task_id} started")
        print(f"  Description: {description}")
        print(f"  Workers: {', '.join(workers)}")
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


def main():
    if len(sys.argv) < 2:
        print("Coordinator — parallel worker dispatch with synthesis")
        print()
        print("Usage:")
        print("  coordinator.py start <description> --workers w1 w2 w3")
        print("  coordinator.py analyze <task-id> <worker> <analysis>")
        print("  coordinator.py status <task-id>")
        print("  coordinator.py synthesize <task-id>")
        print("  coordinator.py complete <task-id> [decision]")
        print("  coordinator.py list")
        print()
        print("The coordinator pattern:")
        print("  1. Lead decomposes task into subtasks for workers")
        print("  2. Workers analyze independently and write findings")
        print("  3. Lead synthesizes all analyses into recommendation")
        print("  4. Decision: continue, correct, or complete")
        return

    cmd = sys.argv[1]

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

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
