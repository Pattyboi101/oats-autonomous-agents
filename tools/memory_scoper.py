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
                     max_size: int = MAX_TOTAL_CONTEXT) -> dict:
        """Load all applicable memory for a given context.

        Args:
            agent: Agent/department name (e.g., "backend")
            files_touched: Files the agent is working on
            max_size: Maximum total context size in bytes

        Returns:
            Dict with loaded memory content and metadata
        """
        files_touched = files_touched or []
        loaded = []
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

        return {
            "agent": agent,
            "files_touched": files_touched,
            "loaded": loaded,
            "total_size": total_size,
            "items_loaded": len(loaded),
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


def main():
    if len(sys.argv) < 2:
        print("Usage:")
        print("  memory_scoper.py inventory              # show all memory sources")
        print("  memory_scoper.py health                  # check for bloat/staleness")
        print("  memory_scoper.py context <agent> [files] # load context for agent")
        return

    cmd = sys.argv[1]
    scoper = MemoryScoper()

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
