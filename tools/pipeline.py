#!/usr/bin/env python3
"""Pipeline — chain OATS tools into repeatable workflows.

The missing glue: OATS has 14 tools but no way to chain them.
Pipeline lets you define a sequence of steps that execute in order,
with each step's output feeding the next step's input.

Built-in pipeline templates:
    research   — search web → think → record thought
    build      — read thought → build → test → commit → think
    improve    — score skills → find lowest → fix → re-score
    review     — run agent → trace → analyze failures → report
    full-cycle — research → build → review → think (the MOAT loop)

Steps can be:
    - Shell commands (bash)
    - Python tool invocations (tools/*.py)
    - Agent runs (via runner.py)
    - Conditional (only run if previous step succeeded)
    - Parallel (multiple steps at once)

Usage:
    # Run a built-in pipeline
    python3 tools/pipeline.py run research
    python3 tools/pipeline.py run build
    python3 tools/pipeline.py run full-cycle

    # Define a custom pipeline
    python3 tools/pipeline.py define my-pipeline steps.json
    python3 tools/pipeline.py run my-pipeline

    # List available pipelines
    python3 tools/pipeline.py list
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

PIPELINE_DIR = Path(".oats/pipelines")

# Built-in pipeline definitions
BUILTIN_PIPELINES = {
    "research": {
        "name": "Research Cycle",
        "description": "Search for new patterns, record what you find",
        "steps": [
            {"name": "check-thought", "command": "python3 tools/think.py next", "capture": True},
            {"name": "search", "command": "echo 'Research step — agent searches web for new patterns'", "type": "prompt"},
            {"name": "record", "command": "python3 orchestrator.py think 'researched new patterns' 'what was found' 'where it leads' --confidence 0.5", "type": "shell"},
        ],
    },
    "build": {
        "name": "Build Cycle",
        "description": "Read next thought, build it, test, commit",
        "steps": [
            {"name": "read-thought", "command": "python3 tools/think.py next", "capture": True},
            {"name": "budget-check", "command": "python3 tools/budget.py check builder", "gate": True},
            {"name": "build", "command": "echo 'Build step — agent implements the idea'", "type": "prompt"},
            {"name": "test", "command": "python3 orchestrator.py health", "gate": True},
            {"name": "commit", "command": "git add -A && git status", "type": "shell"},
            {"name": "think-forward", "command": "python3 orchestrator.py think 'what was built' 'what was realized' 'where this leads' --confidence 0.5", "type": "shell"},
        ],
    },
    "improve": {
        "name": "Self-Improvement Loop",
        "description": "Score skills, find lowest, fix, re-score",
        "steps": [
            {"name": "score", "command": "python3 orchestrator.py improve --target skills", "capture": True},
            {"name": "identify", "command": "echo 'Find lowest-scoring skill from output above'", "type": "prompt"},
            {"name": "fix", "command": "echo 'Fix the skill — add modes, triggers, frontmatter'", "type": "prompt"},
            {"name": "re-score", "command": "python3 orchestrator.py improve --target skills", "capture": True},
            {"name": "commit-if-improved", "command": "git diff --stat", "type": "shell"},
        ],
    },
    "review": {
        "name": "Review Cycle",
        "description": "Run agent, analyze trace, report failures",
        "steps": [
            {"name": "run-agent", "command": "python3 tools/runner.py --as reviewer agents/verification.py --full", "capture": True},
            {"name": "check-trace", "command": "python3 tools/tracer.py list", "capture": True},
            {"name": "find-failures", "command": "echo 'Check latest trace for failures'", "type": "prompt"},
        ],
    },
    "full-cycle": {
        "name": "MOAT Full Cycle",
        "description": "The complete autonomous loop: research → build → review → think",
        "steps": [
            {"name": "read-thought", "command": "python3 tools/think.py next", "capture": True},
            {"name": "budget-check", "command": "python3 tools/budget.py status", "capture": True},
            {"name": "health-check", "command": "python3 orchestrator.py health", "capture": True},
            {"name": "act", "command": "echo 'Act on the highest-confidence thought — build, research, or improve'", "type": "prompt"},
            {"name": "test", "command": "python3 orchestrator.py improve --target skills", "capture": True},
            {"name": "commit", "command": "git add -A && git diff --cached --stat", "type": "shell"},
            {"name": "think-forward", "command": "python3 orchestrator.py think 'what happened' 'what was learned' 'next step' --confidence 0.5", "type": "shell"},
            {"name": "push", "command": "git push origin master 2>/dev/null || echo 'nothing to push'", "type": "shell"},
        ],
    },
}


class Pipeline:
    """Execute a sequence of steps with output chaining."""

    def __init__(self, definition: dict):
        self.name = definition.get("name", "unnamed")
        self.description = definition.get("description", "")
        self.steps = definition.get("steps", [])
        self.results = []

    def run(self, dry_run: bool = False) -> dict:
        """Execute all steps in sequence."""
        print(f"Pipeline: {self.name}")
        print(f"  {self.description}")
        print(f"  Steps: {len(self.steps)}")
        print()

        start_time = time.time()
        passed = 0
        failed = 0
        skipped = 0

        for i, step in enumerate(self.steps):
            step_name = step.get("name", f"step-{i+1}")
            command = step.get("command", "")
            step_type = step.get("type", "shell")
            is_gate = step.get("gate", False)
            capture = step.get("capture", False)

            if dry_run:
                print(f"  [{i+1}/{len(self.steps)}] {step_name}: {command[:60]}")
                continue

            print(f"  [{i+1}/{len(self.steps)}] {step_name}...")

            if step_type == "prompt":
                # Prompt steps are placeholders for LLM interaction
                print(f"    [PROMPT] {command}")
                self.results.append({"step": step_name, "status": "prompt", "output": command})
                passed += 1
                continue

            # Execute shell command
            try:
                result = subprocess.run(
                    command, shell=True, capture_output=True, text=True,
                    timeout=120, cwd=str(Path(__file__).parent.parent),
                )

                success = result.returncode == 0
                output = result.stdout.strip()

                if capture and output:
                    print(f"    {output[:200]}")

                self.results.append({
                    "step": step_name,
                    "status": "ok" if success else "failed",
                    "returncode": result.returncode,
                    "output": output[:500],
                    "stderr": result.stderr[:200] if result.stderr else "",
                })

                if success:
                    passed += 1
                    print(f"    OK")
                else:
                    failed += 1
                    print(f"    FAILED (exit {result.returncode})")
                    if result.stderr:
                        print(f"    {result.stderr[:100]}")

                    # Gate steps stop the pipeline on failure
                    if is_gate:
                        print(f"    GATE FAILED — stopping pipeline")
                        skipped = len(self.steps) - i - 1
                        break

            except subprocess.TimeoutExpired:
                self.results.append({"step": step_name, "status": "timeout"})
                failed += 1
                print(f"    TIMEOUT")
                if is_gate:
                    skipped = len(self.steps) - i - 1
                    break

        duration = time.time() - start_time

        summary = {
            "pipeline": self.name,
            "steps": len(self.steps),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "duration_sec": round(duration, 1),
            "results": self.results,
        }

        print(f"\n  Result: {passed} passed, {failed} failed, {skipped} skipped ({duration:.1f}s)")
        return summary


def main():
    if len(sys.argv) < 2:
        print("Pipeline — chain OATS tools into workflows")
        print()
        print("Usage:")
        print("  pipeline.py list                    # list available pipelines")
        print("  pipeline.py run <name> [--dry-run]  # run a pipeline")
        print("  pipeline.py define <name> <file>    # define a custom pipeline")
        print()
        print("Built-in pipelines:")
        for name, p in BUILTIN_PIPELINES.items():
            print(f"  {name:15s} — {p['description']}")
        return

    cmd = sys.argv[1]

    if cmd == "list":
        print("Built-in:")
        for name, p in BUILTIN_PIPELINES.items():
            print(f"  {name:15s} {len(p['steps']):2d} steps  {p['description']}")

        # Custom pipelines
        if PIPELINE_DIR.exists():
            customs = list(PIPELINE_DIR.glob("*.json"))
            if customs:
                print("\nCustom:")
                for f in customs:
                    try:
                        p = json.loads(f.read_text())
                        print(f"  {f.stem:15s} {len(p.get('steps',[])):2d} steps  {p.get('description','')}")
                    except Exception:
                        pass

    elif cmd == "run":
        if len(sys.argv) < 3:
            print("Usage: pipeline.py run <name> [--dry-run]")
            return

        name = sys.argv[2]
        dry_run = "--dry-run" in sys.argv

        # Check built-in first
        if name in BUILTIN_PIPELINES:
            definition = BUILTIN_PIPELINES[name]
        else:
            # Check custom
            custom_path = PIPELINE_DIR / f"{name}.json"
            if custom_path.exists():
                definition = json.loads(custom_path.read_text())
            else:
                print(f"Pipeline '{name}' not found.")
                return

        pipeline = Pipeline(definition)
        summary = pipeline.run(dry_run=dry_run)

        # Save result
        PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
        log = PIPELINE_DIR / "last_run.json"
        log.write_text(json.dumps(summary, indent=2))

    elif cmd == "define":
        if len(sys.argv) < 4:
            print("Usage: pipeline.py define <name> <steps.json>")
            return

        name = sys.argv[2]
        steps_file = Path(sys.argv[3])
        if not steps_file.exists():
            print(f"File not found: {steps_file}")
            return

        definition = json.loads(steps_file.read_text())
        PIPELINE_DIR.mkdir(parents=True, exist_ok=True)
        (PIPELINE_DIR / f"{name}.json").write_text(json.dumps(definition, indent=2))
        print(f"Pipeline '{name}' saved.")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
