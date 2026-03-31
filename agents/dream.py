#!/usr/bin/env python3
"""Dream Agent — memory consolidation for autonomous agent teams.

Inspired by Claude Code's internal autoDream system. Runs as a background
process that consolidates session memories, resolves contradictions, and
keeps the knowledge base lean.

The 4-phase dream cycle:
1. ORIENT  — read current memory state, understand what exists
2. GATHER  — find new signal from recent work (git log, playbook, department memory)
3. CONSOLIDATE — merge new knowledge into memory files, fix contradictions
4. PRUNE   — keep index under limits, remove stale entries

Usage:
    python3 agents/dream.py                    # run once
    python3 agents/dream.py --watch            # run every 30 minutes
    python3 agents/dream.py --memory-dir .orchestra/memory
"""

import argparse
import json
import os
import re
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path


class DreamGate:
    """Three-gate trigger system from Claude Code's autoDream.

    All three gates must be open before consolidation runs:
    1. Time gate: at least N hours since last consolidation
    2. Session gate: at least N sessions since last consolidation
    3. Lock gate: no other consolidation in progress
    """

    def __init__(self, state_dir: str = ".oats",
                 time_hours: int = 24, session_threshold: int = 5):
        self.state_dir = Path(state_dir)
        self.state_file = self.state_dir / "dream_state.json"
        self.lock_file = self.state_dir / "dream.lock"
        self.time_hours = time_hours
        self.session_threshold = session_threshold

    def _load_state(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                pass
        return {"last_dream": None, "session_count": 0, "total_dreams": 0}

    def _save_state(self, state: dict):
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2))

    def record_session(self):
        """Call this at the end of each agent session to increment the counter."""
        state = self._load_state()
        state["session_count"] = state.get("session_count", 0) + 1
        self._save_state(state)

    def should_dream(self) -> tuple:
        """Check if all three gates are open. Returns (bool, reason)."""
        state = self._load_state()

        # Gate 1: Time
        last = state.get("last_dream")
        if last:
            elapsed = datetime.now() - datetime.fromisoformat(last)
            hours = elapsed.total_seconds() / 3600
            if hours < self.time_hours:
                return False, f"Time gate: {hours:.1f}h elapsed, need {self.time_hours}h"

        # Gate 2: Sessions
        sessions = state.get("session_count", 0)
        if sessions < self.session_threshold:
            return False, f"Session gate: {sessions} sessions, need {self.session_threshold}"

        # Gate 3: Lock
        if self.lock_file.exists():
            # Check if lock is stale (over 1 hour)
            lock_age = time.time() - self.lock_file.stat().st_mtime
            if lock_age < 3600:
                return False, "Lock gate: consolidation already in progress"
            else:
                self.lock_file.unlink()  # Remove stale lock

        return True, "All gates open"

    def acquire_lock(self) -> bool:
        """Acquire the consolidation lock."""
        self.state_dir.mkdir(parents=True, exist_ok=True)
        if self.lock_file.exists():
            return False
        self.lock_file.write_text(datetime.now().isoformat())
        return True

    def release_lock(self):
        """Release the consolidation lock and update state."""
        if self.lock_file.exists():
            self.lock_file.unlink()
        state = self._load_state()
        state["last_dream"] = datetime.now().isoformat()
        state["session_count"] = 0  # Reset session counter
        state["total_dreams"] = state.get("total_dreams", 0) + 1
        self._save_state(state)


class DreamAgent:
    def __init__(self, memory_dir: str = ".orchestra/memory",
                 dept_dir: str = ".orchestra/departments",
                 max_index_lines: int = 50):
        self.memory_dir = Path(memory_dir)
        self.dept_dir = Path(dept_dir)
        self.max_index_lines = max_index_lines
        self.changes = []
        self.gate = DreamGate()

    def run(self, force: bool = False) -> dict:
        """Execute the full dream cycle.

        Args:
            force: Skip gate checks and run immediately.
        """
        # Check gates (unless forced)
        if not force:
            should, reason = self.gate.should_dream()
            if not should:
                print(f"Dream skipped: {reason}")
                return {"skipped": True, "reason": reason}

            if not self.gate.acquire_lock():
                print("Dream skipped: couldn't acquire lock")
                return {"skipped": True, "reason": "lock held"}

        print("Dream Agent — memory consolidation starting...")
        print()

        # Phase 1: Orient
        state = self.orient()
        print(f"Phase 1 (Orient): {len(state['memory_files'])} memory files, "
              f"{len(state['dept_memories'])} department memories")

        # Phase 2: Gather
        signals = self.gather()
        print(f"Phase 2 (Gather): {len(signals)} new signals found")

        # Phase 3: Consolidate
        consolidated = self.consolidate(state, signals)
        print(f"Phase 3 (Consolidate): {consolidated} updates made")

        # Phase 4: Prune
        pruned = self.prune(state)
        print(f"Phase 4 (Prune): {pruned} entries cleaned")

        summary = {
            "timestamp": datetime.now().isoformat(),
            "memory_files": len(state["memory_files"]),
            "signals_found": len(signals),
            "updates_made": consolidated,
            "entries_pruned": pruned,
            "changes": self.changes,
        }

        # Release lock and update state
        if not force:
            self.gate.release_lock()

        print(f"\nDream complete: {consolidated} updates, {pruned} prunes.")
        return summary

    def orient(self) -> dict:
        """Phase 1: Read current memory state."""
        state = {
            "memory_files": [],
            "dept_memories": [],
            "playbook_entries": [],
            "index_lines": 0,
        }

        # Read master memory files
        if self.memory_dir.exists():
            for f in self.memory_dir.glob("*.md"):
                content = f.read_text()
                state["memory_files"].append({
                    "path": str(f),
                    "name": f.stem,
                    "size": len(content),
                    "lines": content.count("\n"),
                })

            # Count index lines in playbook
            playbook = self.memory_dir / "playbook.md"
            if playbook.exists():
                lines = playbook.read_text().strip().split("\n")
                state["index_lines"] = len(lines)
                # Extract dated entries
                for line in lines:
                    if re.match(r"## \d{4}-\d{2}-\d{2}", line):
                        state["playbook_entries"].append(line)

        # Read department memories
        if self.dept_dir.exists():
            for dept in self.dept_dir.iterdir():
                if dept.is_dir():
                    mem_file = dept / "memory.md"
                    if mem_file.exists():
                        content = mem_file.read_text()
                        state["dept_memories"].append({
                            "dept": dept.name,
                            "path": str(mem_file),
                            "size": len(content),
                            "lines": content.count("\n"),
                        })

        return state

    def gather(self) -> list:
        """Phase 2: Find new signal from recent work."""
        signals = []

        # Recent git commits (last 24h of work)
        try:
            result = subprocess.run(
                ["git", "log", "--oneline", "--since=24 hours ago", "-20"],
                capture_output=True, text=True, timeout=10
            )
            for line in result.stdout.strip().split("\n"):
                if line.strip():
                    signals.append({
                        "source": "git",
                        "content": line.strip(),
                        "type": "commit",
                    })
        except Exception:
            pass

        # Check for contradictions between playbook and current state
        playbook = self.memory_dir / "playbook.md"
        if playbook.exists():
            content = playbook.read_text()

            # Find date references that might be stale
            dates = re.findall(r"\d{4}-\d{2}-\d{2}", content)
            for date_str in dates:
                try:
                    date = datetime.strptime(date_str, "%Y-%m-%d")
                    if datetime.now() - date > timedelta(days=7):
                        signals.append({
                            "source": "playbook",
                            "content": f"Date reference {date_str} is over 7 days old",
                            "type": "stale_date",
                        })
                except ValueError:
                    pass

        # Check department memories for size bloat
        for dept_mem in (self.dept_dir).glob("*/memory.md"):
            content = dept_mem.read_text()
            if len(content) > 5000:
                signals.append({
                    "source": f"dept:{dept_mem.parent.name}",
                    "content": f"Memory file is {len(content)} chars (over 5k limit)",
                    "type": "bloat",
                })

        # Check for duplicate entries across memories
        all_entries = []
        for mem_file in self.memory_dir.glob("*.md"):
            content = mem_file.read_text()
            for line in content.split("\n"):
                if line.startswith("- ") or line.startswith("## "):
                    all_entries.append((str(mem_file), line.strip()))

        # Simple duplicate detection
        seen = {}
        for path, entry in all_entries:
            key = entry.lower()[:50]
            if key in seen and seen[key] != path:
                signals.append({
                    "source": "cross-memory",
                    "content": f"Possible duplicate: '{entry[:60]}' in {path} and {seen[key]}",
                    "type": "duplicate",
                })
            seen[key] = path

        return signals

    def consolidate(self, state: dict, signals: list) -> int:
        """Phase 3: Merge new knowledge, fix contradictions."""
        updates = 0

        # Process bloat signals — trim oversized department memories
        for signal in signals:
            if signal["type"] == "bloat":
                dept = signal["source"].replace("dept:", "")
                mem_path = self.dept_dir / dept / "memory.md"
                if mem_path.exists():
                    content = mem_path.read_text()
                    lines = content.split("\n")
                    # Keep header + last 50 lines
                    header_end = 0
                    for i, line in enumerate(lines):
                        if line.strip() == "---":
                            header_end = i + 1
                            break

                    if len(lines) > header_end + 50:
                        trimmed = lines[:header_end] + [
                            "",
                            f"_Trimmed by Dream Agent on {datetime.now().strftime('%Y-%m-%d')} — "
                            f"kept last 50 entries from {len(lines) - header_end} total._",
                            "",
                        ] + lines[-50:]
                        mem_path.write_text("\n".join(trimmed))
                        self.changes.append(f"Trimmed {dept} memory: {len(lines)} → {len(trimmed)} lines")
                        updates += 1

        # Add recent git activity summary to playbook if significant
        git_signals = [s for s in signals if s["source"] == "git"]
        if len(git_signals) >= 5:
            playbook = self.memory_dir / "playbook.md"
            if playbook.exists():
                content = playbook.read_text()
                today = datetime.now().strftime("%Y-%m-%d")
                if today not in content:
                    summary = f"\n## {today} — Dream consolidation\n"
                    summary += f"Recent activity: {len(git_signals)} commits in last 24h.\n"
                    # Categorise commits
                    feats = sum(1 for s in git_signals if "feat" in s["content"].lower())
                    fixes = sum(1 for s in git_signals if "fix" in s["content"].lower())
                    if feats:
                        summary += f"Features: {feats}. "
                    if fixes:
                        summary += f"Fixes: {fixes}."
                    summary += "\n"
                    content += summary
                    playbook.write_text(content)
                    self.changes.append(f"Added {today} activity summary to playbook")
                    updates += 1

        return updates

    def prune(self, state: dict) -> int:
        """Phase 4: Keep index lean, remove stale entries."""
        pruned = 0

        playbook = self.memory_dir / "playbook.md"
        if not playbook.exists():
            return 0

        content = playbook.read_text()
        lines = content.split("\n")

        if len(lines) > self.max_index_lines * 2:
            # Keep the header + lessons + last N dated entries
            header = []
            lessons = []
            entries = []
            current_section = "header"

            for line in lines:
                if line.startswith("## Strategic Lessons") or line.startswith("## GOTCHA"):
                    current_section = "lessons"
                elif re.match(r"## \d{4}-\d{2}-\d{2}", line):
                    current_section = "entries"

                if current_section == "header":
                    header.append(line)
                elif current_section == "lessons":
                    lessons.append(line)
                else:
                    entries.append(line)

            # Keep only the last 20 dated entries
            if len(entries) > 60:
                old_count = len(entries)
                entries = entries[-60:]
                pruned = (old_count - len(entries)) // 3  # rough entry count
                self.changes.append(f"Pruned playbook: removed ~{pruned} old entries")

            new_content = "\n".join(header + lessons + entries)
            playbook.write_text(new_content)

        return pruned


def main():
    parser = argparse.ArgumentParser(description="Dream Agent — memory consolidation")
    parser.add_argument("--memory-dir", default=".orchestra/memory")
    parser.add_argument("--dept-dir", default=".orchestra/departments")
    parser.add_argument("--watch", action="store_true", help="Run every 30 minutes")
    parser.add_argument("--interval", type=int, default=1800, help="Watch interval in seconds")
    parser.add_argument("--force", action="store_true", help="Skip gate checks, run immediately")
    parser.add_argument("--record-session", action="store_true",
                        help="Record a session (increment session counter for gate)")
    parser.add_argument("--gate-status", action="store_true",
                        help="Show current gate status without running")
    args = parser.parse_args()

    # Record session mode — just increment counter and exit
    if args.record_session:
        gate = DreamGate()
        gate.record_session()
        state = gate._load_state()
        print(f"Session recorded. Count: {state['session_count']}")
        return

    # Gate status mode — show gate state
    if args.gate_status:
        gate = DreamGate()
        should, reason = gate.should_dream()
        state = gate._load_state()
        print(f"Gate status: {'OPEN' if should else 'CLOSED'}")
        print(f"  Reason: {reason}")
        print(f"  Last dream: {state.get('last_dream', 'never')}")
        print(f"  Sessions since: {state.get('session_count', 0)}")
        print(f"  Total dreams: {state.get('total_dreams', 0)}")
        return

    if args.watch:
        print(f"Dream Agent watching (every {args.interval}s). Ctrl+C to stop.")
        print("Gate system active: will only consolidate when all 3 gates open.")
        while True:
            try:
                agent = DreamAgent(args.memory_dir, args.dept_dir)
                summary = agent.run(force=args.force)
                # Save summary
                log_path = Path(".orchestra/logs/dream_log.json")
                log_path.parent.mkdir(parents=True, exist_ok=True)
                logs = []
                if log_path.exists():
                    try:
                        logs = json.loads(log_path.read_text())
                    except Exception:
                        logs = []
                logs.append(summary)
                logs = logs[-50:]  # Keep last 50
                log_path.write_text(json.dumps(logs, indent=2))
                print(f"\nNext dream in {args.interval}s...\n")
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nDream agent stopped.")
                break
    else:
        agent = DreamAgent(args.memory_dir, args.dept_dir)
        summary = agent.run(force=args.force)
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
