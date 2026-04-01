#!/usr/bin/env python3
"""Memory Scoper — path-scoped rules and tiered memory loading for OATS agents.

Inspired by Claude Code's three-tier memory hierarchy:
- User memory: ~/.oats/memory/ (all projects)
- Project memory: .orchestra/memory/ (shared via git)
- Session memory: per-agent, per-session state

Key pattern from Claude Code: rules can be scoped to file paths
(e.g., only load database rules when editing db.py). This prevents
context bloat — agents only see what's relevant to their current task.

Usage:
    # Load all applicable memory for a context
    scoper = MemoryScoper()
    context = scoper.load_context(
        agent="backend",
        files_touched=["src/db.py", "src/main.py"]
    )

    # List what would load for a given context
    python3 tools/memory_scoper.py context backend src/db.py

    # Show all memory sources and their sizes
    python3 tools/memory_scoper.py inventory

    # Check memory health (bloat, staleness, conflicts)
    python3 tools/memory_scoper.py health
"""

import fnmatch
import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


# Size limits (bytes)
MAX_INDEX_SIZE = 25_000       # ~200 lines
MAX_MEMORY_FILE = 10_000      # Individual memory file
MAX_TOTAL_CONTEXT = 50_000    # Total loaded context
MAX_DEPT_MEMORY = 5_000       # Department memory file


class MemoryScoper:
    """Load and scope memory for OATS agents."""

    def __init__(self, project_dir: str = "."):
        self.project_dir = Path(project_dir)
        self.sources = self._discover_sources()

    def _discover_sources(self) -> dict:
        """Discover all memory sources."""
        sources = {
            "user": [],
            "project": [],
            "department": [],
            "rules": [],
        }

        # User-level memory (~/.oats/memory/)
        user_dir = Path.home() / ".oats" / "memory"
        if user_dir.exists():
            for f in sorted(user_dir.glob("*.md")):
                sources["user"].append(self._parse_memory_file(f, "user"))

        # Project memory (.orchestra/memory/)
        proj_dir = self.project_dir / ".orchestra" / "memory"
        if proj_dir.exists():
            for f in sorted(proj_dir.glob("*.md")):
                sources["project"].append(self._parse_memory_file(f, "project"))

        # Department memories (.orchestra/departments/*/memory.md)
        dept_dir = self.project_dir / ".orchestra" / "departments"
        if dept_dir.exists():
            for dept in sorted(dept_dir.iterdir()):
                if dept.is_dir():
                    mem = dept / "memory.md"
                    if mem.exists():
                        sources["department"].append(
                            self._parse_memory_file(mem, "department", dept=dept.name))

        # Rules (.orchestra/rules/*.md or .claude/rules/*.md)
        for rules_dir in [
            self.project_dir / ".orchestra" / "rules",
            self.project_dir / ".claude" / "rules",
        ]:
            if rules_dir.exists():
                for f in sorted(rules_dir.glob("*.md")):
                    sources["rules"].append(self._parse_memory_file(f, "rules"))

        return sources

    def _parse_memory_file(self, path: Path, source_type: str,
                           dept: str = None) -> dict:
        """Parse a memory file, extracting frontmatter and metadata."""
        content = path.read_text()
        meta = {
            "path": str(path),
            "name": path.stem,
            "source_type": source_type,
            "department": dept,
            "size": len(content),
            "lines": content.count("\n"),
            "paths": [],       # Path scope patterns
            "always_load": source_type in ("user", "project"),
        }

        # Parse frontmatter for path scoping
        if content.startswith("---"):
            try:
                fm_end = content.index("---", 3)
                fm = content[3:fm_end]
                for line in fm.split("\n"):
                    line = line.strip()
                    if line.startswith("paths:"):
                        # Inline list: paths: ["src/db.py", "src/*.py"]
                        rest = line.split(":", 1)[1].strip()
                        if rest.startswith("["):
                            try:
                                meta["paths"] = json.loads(rest)
                            except json.JSONDecodeError:
                                pass
                    elif line.startswith("- ") and meta.get("_in_paths"):
                        meta["paths"].append(line[2:].strip().strip('"\''))
                    elif line == "paths:":
                        meta["_in_paths"] = True
                    else:
                        meta["_in_paths"] = False

                    if line.startswith("always_load:"):
                        meta["always_load"] = line.split(":")[1].strip().lower() == "true"

            except ValueError:
                pass

        meta.pop("_in_paths", None)

        # If rules have path scopes, they only load when relevant
        if meta["paths"]:
            meta["always_load"] = False

        return meta

    def load_context(self, agent: str = None, files_touched: list = None,
                     max_size: int = MAX_TOTAL_CONTEXT,
                     optimizer: Optional["ContextOptimizer"] = None) -> dict:
        """Load all applicable memory for a given context.

        Args:
            agent: Agent/department name (e.g., "backend")
            files_touched: Files the agent is working on
            max_size: Maximum total context size in bytes
            optimizer: If provided, uses usefulness scores to prune low-value context

        Returns:
            Dict with loaded memory content and metadata
        """
        files_touched = files_touched or []
        loaded = []
        pruned_items = []
        total_size = 0

        # 1. Always-load memories (user + project)
        for source_type in ("user", "project"):
            for mem in self.sources[source_type]:
                if mem["always_load"] and total_size + mem["size"] <= max_size:
                    content = Path(mem["path"]).read_text()
                    loaded.append({
                        "name": mem["name"],
                        "source": source_type,
                        "content": content,
                        "size": mem["size"],
                    })
                    total_size += mem["size"]

        # 2. Department memory (if agent matches)
        if agent:
            for mem in self.sources["department"]:
                if mem["department"] == agent and total_size + mem["size"] <= max_size:
                    content = Path(mem["path"]).read_text()
                    loaded.append({
                        "name": f"{mem['department']}/memory",
                        "source": "department",
                        "content": content,
                        "size": mem["size"],
                    })
                    total_size += mem["size"]

        # 3. Path-scoped rules (only if files match)
        for mem in self.sources["rules"]:
            if mem["always_load"]:
                if total_size + mem["size"] <= max_size:
                    content = Path(mem["path"]).read_text()
                    loaded.append({
                        "name": mem["name"],
                        "source": "rules",
                        "content": content,
                        "size": mem["size"],
                    })
                    total_size += mem["size"]
            elif mem["paths"] and files_touched:
                # Check if any touched file matches any path pattern
                if self._files_match_patterns(files_touched, mem["paths"]):
                    if total_size + mem["size"] <= max_size:
                        content = Path(mem["path"]).read_text()
                        loaded.append({
                            "name": mem["name"],
                            "source": "rules (path-scoped)",
                            "content": content,
                            "size": mem["size"],
                        })
                        total_size += mem["size"]

        # Apply context optimizer if available — prune low-value items
        if optimizer and loaded:
            loaded, pruned_items = optimizer.filter_context(loaded)
            total_size = sum(item["size"] for item in loaded)

        return {
            "agent": agent,
            "files_touched": files_touched,
            "loaded": loaded,
            "pruned": pruned_items,
            "total_size": total_size,
            "items_loaded": len(loaded),
            "items_pruned": len(pruned_items),
        }

    def _files_match_patterns(self, files: list, patterns: list) -> bool:
        """Check if any file matches any glob pattern."""
        for f in files:
            for pattern in patterns:
                if fnmatch.fnmatch(f, pattern):
                    return True
        return False

    def inventory(self) -> dict:
        """Show all memory sources and their sizes."""
        total = 0
        items = []

        for source_type, memories in self.sources.items():
            for mem in memories:
                items.append(mem)
                total += mem["size"]

        return {
            "total_files": len(items),
            "total_size": total,
            "by_type": {
                t: {"count": len(mems), "size": sum(m["size"] for m in mems)}
                for t, mems in self.sources.items()
            },
            "items": items,
        }

    def health_check(self) -> list:
        """Check memory health: bloat, staleness, conflicts."""
        issues = []

        for source_type, memories in self.sources.items():
            for mem in memories:
                # Size checks
                limit = MAX_DEPT_MEMORY if source_type == "department" else MAX_MEMORY_FILE
                if mem["size"] > limit:
                    issues.append({
                        "type": "bloat",
                        "severity": "warning",
                        "file": mem["path"],
                        "message": f"{mem['name']} is {mem['size']} bytes (limit: {limit})",
                    })

                # Check for stale dates in content
                content = Path(mem["path"]).read_text()
                dates = re.findall(r"\d{4}-\d{2}-\d{2}", content)
                for date_str in dates:
                    try:
                        date = datetime.strptime(date_str, "%Y-%m-%d")
                        if datetime.now() - date > timedelta(days=14):
                            issues.append({
                                "type": "stale",
                                "severity": "info",
                                "file": mem["path"],
                                "message": f"Date reference {date_str} is over 14 days old",
                            })
                            break  # One stale warning per file
                    except ValueError:
                        pass

        # Check total context size
        inv = self.inventory()
        if inv["total_size"] > MAX_TOTAL_CONTEXT * 2:
            issues.append({
                "type": "bloat",
                "severity": "error",
                "file": "all",
                "message": f"Total memory is {inv['total_size']} bytes — over 2x the {MAX_TOTAL_CONTEXT} byte limit",
            })

        return issues


OPTIMIZER_FILE = Path(".oats/context_scores.json")


class ContextOptimizer:
    """Data-driven context pruning — track which context items influence agent output.

    Every framework loads all context and hopes it fits. This optimizer tracks
    which items actually get referenced in agent outputs, and over time stops
    loading the ones that never influence decisions.

    Scores are in [0, 1]:
      1.0 = always referenced, always load
      0.5 = neutral (new item, no data yet)
      0.0 = never referenced, safe to skip

    The score decays toward 0.0 over time if unused, and jumps back up
    if a failure correlates with a recently-pruned item (self-correction).
    """

    def __init__(self, state_file: str = None, prune_threshold: float = 0.15,
                 decay_rate: float = 0.05):
        self.state_file = Path(state_file) if state_file else OPTIMIZER_FILE
        self.prune_threshold = prune_threshold
        self.decay_rate = decay_rate
        self.scores: dict = {}  # name -> {score, loads, references, last_used, pruned_count}
        self._load()

    def _load(self):
        if self.state_file.exists():
            try:
                self.scores = json.loads(self.state_file.read_text())
            except Exception:
                self.scores = {}

    def _save(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(self.scores, indent=2))

    def _ensure_item(self, name: str):
        if name not in self.scores:
            self.scores[name] = {
                "score": 0.5,
                "loads": 0,
                "references": 0,
                "last_used": None,
                "last_loaded": None,
                "pruned_count": 0,
            }

    def record_load(self, name: str):
        """Record that a context item was loaded into an agent's context."""
        self._ensure_item(name)
        self.scores[name]["loads"] += 1
        self.scores[name]["last_loaded"] = datetime.now().isoformat()
        self._save()

    def record_reference(self, name: str):
        """Record that an agent's output referenced this context item.

        Call this after scanning agent output for keywords from the loaded context.
        """
        self._ensure_item(name)
        item = self.scores[name]
        item["references"] += 1
        item["last_used"] = datetime.now().isoformat()

        # Score = observed reference rate, recalculated from actuals each time
        # This is the ground truth — no EMA drift, no accumulation bugs
        if item["loads"] > 0:
            item["score"] = item["references"] / item["loads"]

        item["score"] = min(1.0, item["score"])
        self._save()

    def record_miss(self, name: str):
        """Record that a context item was loaded but NOT referenced in output."""
        self._ensure_item(name)
        item = self.scores[name]
        # Score = observed reference rate (same as record_reference)
        # No separate decay — the rate naturally drops as misses accumulate
        if item["loads"] > 0:
            item["score"] = item["references"] / item["loads"]
        self._save()

    def record_failure_correlation(self, name: str):
        """A failure happened and this recently-pruned item might have prevented it.

        Jumps the item's score back up so it gets loaded next time.
        """
        self._ensure_item(name)
        item = self.scores[name]
        item["score"] = min(1.0, item["score"] + 0.3)  # significant boost
        item["pruned_count"] = max(0, item["pruned_count"] - 1)  # forgive one prune
        self._save()

    def should_load(self, name: str) -> bool:
        """Should this context item be loaded? Based on usefulness score."""
        self._ensure_item(name)
        return self.scores[name]["score"] >= self.prune_threshold

    def filter_context(self, items: list) -> tuple:
        """Filter a list of context items, returning (kept, pruned).

        Items are dicts with at least a "name" key.
        """
        kept = []
        pruned = []
        for item in items:
            name = item.get("name", "")
            if self.should_load(name):
                kept.append(item)
                self.record_load(name)
            else:
                pruned.append(item)
                self._ensure_item(name)
                self.scores[name]["pruned_count"] += 1
        self._save()
        return kept, pruned

    def observe_output(self, loaded_items: list, agent_output: str):
        """Scan agent output for references to loaded context items.

        This is the key feedback loop: did the agent actually USE the context
        we loaded? Items that never get referenced have their scores decayed.
        """
        output_lower = agent_output.lower()

        for item in loaded_items:
            name = item.get("name", "")
            # Check if any significant keywords from this item appear in output
            content = item.get("content", "")
            # Extract keywords: lines that start with - or ## (headings and list items)
            keywords = []
            for line in content.split("\n"):
                line = line.strip()
                if line.startswith("- ") and len(line) > 10:
                    # Extract the key phrase (first 40 chars after "- ")
                    keywords.append(line[2:42].lower().strip())
                elif line.startswith("## ") and len(line) > 5:
                    keywords.append(line[3:].lower().strip())

            # Also use the item name itself as a keyword
            keywords.append(name.lower())

            referenced = any(kw in output_lower for kw in keywords if len(kw) > 3)

            if referenced:
                self.record_reference(name)
            else:
                self.record_miss(name)

    def decay_all(self):
        """Apply time decay to all scores. Call periodically (e.g., daily)."""
        for name, item in self.scores.items():
            if item["score"] > 0.1:
                item["score"] = max(0.0, item["score"] - self.decay_rate * 0.5)
        self._save()

    def stats(self) -> dict:
        """Get optimizer statistics."""
        if not self.scores:
            return {"items": 0, "avg_score": 0, "prunable": 0, "total_loads": 0}

        scores = [v["score"] for v in self.scores.values()]
        return {
            "items": len(self.scores),
            "avg_score": round(sum(scores) / len(scores), 3),
            "prunable": sum(1 for s in scores if s < self.prune_threshold),
            "high_value": sum(1 for s in scores if s >= 0.7),
            "total_loads": sum(v["loads"] for v in self.scores.values()),
            "total_references": sum(v["references"] for v in self.scores.values()),
            "estimated_savings_pct": round(
                sum(1 for s in scores if s < self.prune_threshold) / max(1, len(scores)) * 100
            ),
        }

    def leaderboard(self) -> list:
        """Rank context items by usefulness score."""
        return sorted(
            [(name, data) for name, data in self.scores.items()],
            key=lambda x: x[1]["score"],
            reverse=True,
        )


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  memory_scoper.py inventory              # show all memory sources")
        print("  memory_scoper.py health                  # check for bloat/staleness")
        print("  memory_scoper.py context <agent> [files] # load context for agent")
        print("  memory_scoper.py optimize                # show context optimizer stats")
        print("  memory_scoper.py optimize scores         # show per-item usefulness scores")
        print("  memory_scoper.py optimize simulate <agent> [files]  # show what would be pruned")
        return

    cmd = sys.argv[1]
    scoper = MemoryScoper()

    if cmd == "optimize":
        optimizer = ContextOptimizer()
        subcmd = sys.argv[2] if len(sys.argv) > 2 else "stats"

        if subcmd == "stats":
            s = optimizer.stats()
            if s["items"] == 0:
                print("No optimization data yet. Run agents via the runner to collect data.")
                return
            print(f"Context Optimizer Stats:")
            print(f"  Items tracked:     {s['items']}")
            print(f"  Average score:     {s['avg_score']:.3f}")
            print(f"  High-value (>0.7): {s['high_value']}")
            print(f"  Prunable (<0.15):  {s['prunable']}")
            print(f"  Total loads:       {s['total_loads']:,}")
            print(f"  Total references:  {s['total_references']:,}")
            print(f"  Est. savings:      ~{s['estimated_savings_pct']}% of context could be pruned")

        elif subcmd == "scores":
            board = optimizer.leaderboard()
            if not board:
                print("No scores yet.")
                return
            print(f"{'Item':30s} {'Score':>7s} {'Loads':>7s} {'Refs':>7s} {'Rate':>7s}")
            print("-" * 62)
            for name, data in board:
                rate = f"{data['references']/max(1,data['loads'])*100:.0f}%" if data["loads"] else "n/a"
                marker = " [PRUNE]" if data["score"] < optimizer.prune_threshold else ""
                print(f"  {name:28s} {data['score']:>7.3f} {data['loads']:>7d} "
                      f"{data['references']:>7d} {rate:>7s}{marker}")

        elif subcmd == "simulate":
            agent = sys.argv[3] if len(sys.argv) > 3 else None
            files = sys.argv[4:] if len(sys.argv) > 4 else []
            ctx_without = scoper.load_context(agent=agent, files_touched=files)
            ctx_with = scoper.load_context(agent=agent, files_touched=files, optimizer=optimizer)
            saved = ctx_without["total_size"] - ctx_with["total_size"]
            print(f"Context simulation for agent={agent}:")
            print(f"  Without optimizer: {ctx_without['items_loaded']} items, {ctx_without['total_size']:,} bytes")
            print(f"  With optimizer:    {ctx_with['items_loaded']} items, {ctx_with['total_size']:,} bytes")
            print(f"  Saved:             {saved:,} bytes ({saved*100//max(1,ctx_without['total_size'])}%)")
            if ctx_with.get("pruned"):
                print(f"\n  Pruned items:")
                for p in ctx_with["pruned"]:
                    print(f"    {p['name']:25s} {p['size']:>6,}b")

        elif subcmd == "decay":
            optimizer.decay_all()
            print("Time decay applied to all context scores.")

        else:
            print(f"Unknown optimize subcommand: {subcmd}")
        return

    if cmd == "inventory":
        inv = scoper.inventory()
        print(f"Memory Inventory: {inv['total_files']} files, {inv['total_size']:,} bytes\n")
        for source_type, stats in inv["by_type"].items():
            if stats["count"]:
                print(f"  {source_type:15s} {stats['count']:3d} files  {stats['size']:>8,} bytes")

        print()
        for item in inv["items"]:
            scope = ""
            if item["paths"]:
                scope = f" [scoped: {', '.join(item['paths'][:2])}]"
            dept = f" ({item['department']})" if item.get("department") else ""
            load = "always" if item["always_load"] else "on-demand"
            print(f"  {item['name']:25s} {item['source_type']:12s}{dept:12s} "
                  f"{item['size']:>6,}b  [{load}]{scope}")

    elif cmd == "health":
        issues = scoper.health_check()
        if not issues:
            print("Memory health: all clear")
            return

        print(f"Memory health: {len(issues)} issue(s)\n")
        for issue in issues:
            icon = {"error": "!!!", "warning": " ! ", "info": " i "}.get(issue["severity"], " ? ")
            print(f"  [{icon}] {issue['type']:8s} {issue['message']}")
            print(f"           {issue['file']}")

    elif cmd == "context":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        files = sys.argv[3:] if len(sys.argv) > 3 else []

        ctx = scoper.load_context(agent=agent, files_touched=files)
        print(f"Context for agent={agent}, files={files}")
        print(f"Loaded: {ctx['items_loaded']} items, {ctx['total_size']:,} bytes\n")

        for item in ctx["loaded"]:
            print(f"  {item['name']:25s} [{item['source']:20s}] {item['size']:>6,}b")
            # Show first 2 lines of content
            lines = item["content"].strip().split("\n")
            for line in lines[:2]:
                if line.strip() and not line.startswith("---"):
                    print(f"    {line.strip()[:80]}")

    else:
        print(f"Unknown command: {cmd}")


if __name__ == "__main__":
    main()
