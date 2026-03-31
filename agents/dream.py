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


class DreamAgent:
    def __init__(self, memory_dir: str = ".orchestra/memory",
                 dept_dir: str = ".orchestra/departments",
                 max_index_lines: int = 50):
        self.memory_dir = Path(memory_dir)
        self.dept_dir = Path(dept_dir)
        self.max_index_lines = max_index_lines
        self.changes = []

    def run(self) -> dict:
        """Execute the full dream cycle."""
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
    args = parser.parse_args()

    if args.watch:
        print(f"Dream Agent watching (every {args.interval}s). Ctrl+C to stop.")
        while True:
            try:
                agent = DreamAgent(args.memory_dir, args.dept_dir)
                summary = agent.run()
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
        summary = agent.run()
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
