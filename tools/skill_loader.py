#!/usr/bin/env python3
"""Skill Loader — discover and load skills from multiple sources.

Inspired by Claude Code's loadSkillsDir.ts which loads skills from:
- Local project skills/
- User-level ~/.claude/skills/
- Plugins
- Bundled defaults
- MCP servers

This loader discovers OATS skills from:
1. Local: ./skills/ (project-specific)
2. Orchestra: .orchestra/departments/*/skills/ (department-specific)
3. Master: .orchestra/master/skills/ (orchestrator skills)
4. User: ~/.oats/skills/ (user-level, shared across projects)
5. Remote: GitHub repos (installable)

Usage:
    python3 tools/skill_loader.py                    # list all available skills
    python3 tools/skill_loader.py search "deploy"    # search skills
    python3 tools/skill_loader.py info "deploy-safely"  # show skill details
    python3 tools/skill_loader.py install <github-url>  # install from GitHub
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path


class SkillLoader:
    def __init__(self, project_dir: str = "."):
        self.project_dir = Path(project_dir)
        self.sources = self._discover_sources()

    def _discover_sources(self) -> list:
        """Find all skill sources."""
        sources = []

        # 1. Local project skills
        local = self.project_dir / "skills"
        if local.exists():
            sources.append({"type": "local", "path": str(local), "priority": 1})

        # 2. Orchestra department skills
        dept_dir = self.project_dir / ".orchestra" / "departments"
        if dept_dir.exists():
            for dept in dept_dir.iterdir():
                skills_dir = dept / "skills"
                if skills_dir.exists() and any(skills_dir.glob("*.md")):
                    sources.append({
                        "type": "department",
                        "dept": dept.name,
                        "path": str(skills_dir),
                        "priority": 2,
                    })

        # 3. Master skills
        master = self.project_dir / ".orchestra" / "master" / "skills"
        if master.exists():
            sources.append({"type": "master", "path": str(master), "priority": 3})

        # 4. User-level skills
        user_skills = Path.home() / ".oats" / "skills"
        if user_skills.exists():
            sources.append({"type": "user", "path": str(user_skills), "priority": 4})

        return sources

    def load_all(self) -> list:
        """Load all skills from all sources."""
        skills = []

        for source in self.sources:
            path = Path(source["path"])
            for skill_path in sorted(path.iterdir()):
                # Skills can be: dir with SKILL.md, or standalone .md file
                if skill_path.is_dir():
                    skill_md = skill_path / "SKILL.md"
                    if skill_md.exists():
                        skill = self._parse_skill(skill_md, source)
                        if skill:
                            skills.append(skill)
                elif skill_path.suffix == ".md" and skill_path.name != ".gitkeep":
                    skill = self._parse_skill(skill_path, source)
                    if skill:
                        skills.append(skill)

        return skills

    def _parse_skill(self, path: Path, source: dict) -> dict:
        """Parse a skill file and extract metadata."""
        content = path.read_text()

        # Parse frontmatter
        name = path.stem
        description = ""
        version = "0.0.0"
        category = "uncategorised"
        author = "unknown"

        if content.startswith("---"):
            try:
                fm_end = content.index("---", 3)
                fm = content[3:fm_end]
                for line in fm.split("\n"):
                    if line.startswith("name:"):
                        name = line.split(":", 1)[1].strip().strip('"')
                    elif line.startswith("description:"):
                        description = line.split(":", 1)[1].strip().strip('"')
                    elif "version:" in line:
                        version = line.split("version:", 1)[1].strip()
                    elif "category:" in line:
                        category = line.split("category:", 1)[1].strip()
                    elif "author:" in line:
                        author = line.split("author:", 1)[1].strip()
            except ValueError:
                pass

        if not description:
            # Try to extract from first paragraph
            lines = content.split("\n")
            for line in lines:
                if line.strip() and not line.startswith("#") and not line.startswith("---"):
                    description = line.strip()[:100]
                    break

        return {
            "name": name,
            "description": description,
            "version": version,
            "category": category,
            "author": author,
            "source_type": source["type"],
            "source_dept": source.get("dept"),
            "path": str(path),
            "size": len(content),
            "has_frontmatter": content.startswith("---"),
            "has_modes": "### Mode" in content,
            "has_triggers": "Proactive Trigger" in content.lower() or "proactive" in content.lower(),
        }

    def search(self, query: str) -> list:
        """Search skills by name, description, or category."""
        query = query.lower()
        skills = self.load_all()
        return [s for s in skills if
                query in s["name"].lower() or
                query in s["description"].lower() or
                query in s["category"].lower()]

    def get_info(self, name: str) -> dict:
        """Get detailed info about a specific skill."""
        skills = self.load_all()
        for s in skills:
            if s["name"] == name:
                # Read full content
                content = Path(s["path"]).read_text()
                s["content_preview"] = content[:500]
                s["full_size"] = len(content)
                s["line_count"] = content.count("\n")
                return s
        return None

    def install(self, source_url: str, target: str = "skills"):
        """Install a skill from a GitHub URL or local path."""
        target_dir = self.project_dir / target

        if source_url.startswith("https://github.com/"):
            # Clone from GitHub
            parts = source_url.rstrip("/").split("/")
            repo_name = parts[-1]
            print(f"Installing from {source_url}...")

            tmp_dir = Path(f"/tmp/oats-install-{repo_name}")
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir)

            try:
                subprocess.run(
                    ["git", "clone", "--depth=1", source_url, str(tmp_dir)],
                    capture_output=True, timeout=30
                )

                # Find SKILL.md files
                skill_files = list(tmp_dir.rglob("SKILL.md"))
                if not skill_files:
                    skill_files = list(tmp_dir.rglob("*.md"))
                    skill_files = [f for f in skill_files if f.name not in
                                   ("README.md", "LICENSE.md", "CHANGELOG.md")]

                installed = 0
                for sf in skill_files:
                    skill_name = sf.parent.name if sf.name == "SKILL.md" else sf.stem
                    dest = target_dir / skill_name
                    dest.mkdir(parents=True, exist_ok=True)

                    if sf.name == "SKILL.md":
                        shutil.copytree(sf.parent, dest, dirs_exist_ok=True)
                    else:
                        shutil.copy2(sf, dest / "SKILL.md")

                    installed += 1
                    print(f"  Installed: {skill_name}")

                # Cleanup
                shutil.rmtree(tmp_dir, ignore_errors=True)
                print(f"\n{installed} skill(s) installed to {target_dir}/")

            except Exception as e:
                print(f"Install failed: {e}")
                shutil.rmtree(tmp_dir, ignore_errors=True)

        elif Path(source_url).exists():
            # Copy from local path
            src = Path(source_url)
            if src.is_dir():
                name = src.name
                dest = target_dir / name
                shutil.copytree(src, dest, dirs_exist_ok=True)
            else:
                name = src.stem
                dest = target_dir / name
                dest.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest / "SKILL.md")
            print(f"Installed: {name}")
        else:
            print(f"Unknown source: {source_url}")


def print_skills_table(skills: list):
    """Pretty-print a skills table."""
    if not skills:
        print("No skills found.")
        return

    print(f"{'Name':25s} {'Version':10s} {'Source':12s} {'Category':15s} {'Quality':8s}")
    print("-" * 75)
    for s in sorted(skills, key=lambda x: (x["source_type"], x["name"])):
        quality = "A" if s["has_frontmatter"] and s["has_modes"] and s["has_triggers"] else \
                  "B" if s["has_frontmatter"] else "C"
        src = f"{s['source_type']}"
        if s.get("source_dept"):
            src += f"/{s['source_dept']}"
        print(f"{s['name']:25s} {s['version']:10s} {src:12s} {s['category']:15s} {quality:8s}")

    print(f"\n{len(skills)} skill(s) from {len(set(s['source_type'] for s in skills))} source(s)")


def main():
    parser = argparse.ArgumentParser(description="OATS Skill Loader")
    parser.add_argument("command", nargs="?", default="list",
                        choices=["list", "search", "info", "install", "sources"])
    parser.add_argument("query", nargs="?", default="")
    args = parser.parse_args()

    loader = SkillLoader()

    if args.command == "list":
        skills = loader.load_all()
        print_skills_table(skills)

    elif args.command == "search":
        if not args.query:
            print("Usage: skill_loader.py search <query>")
            return
        results = loader.search(args.query)
        print_skills_table(results)

    elif args.command == "info":
        if not args.query:
            print("Usage: skill_loader.py info <skill-name>")
            return
        info = loader.get_info(args.query)
        if info:
            print(f"Name: {info['name']}")
            print(f"Version: {info['version']}")
            print(f"Category: {info['category']}")
            print(f"Author: {info['author']}")
            print(f"Source: {info['source_type']}")
            print(f"Path: {info['path']}")
            print(f"Size: {info['full_size']} bytes, {info['line_count']} lines")
            print(f"Frontmatter: {'Yes' if info['has_frontmatter'] else 'No'}")
            print(f"Modes: {'Yes' if info['has_modes'] else 'No'}")
            print(f"Triggers: {'Yes' if info['has_triggers'] else 'No'}")
            print(f"\nPreview:\n{info['content_preview']}")
        else:
            print(f"Skill '{args.query}' not found.")

    elif args.command == "install":
        if not args.query:
            print("Usage: skill_loader.py install <github-url-or-path>")
            return
        loader.install(args.query)

    elif args.command == "sources":
        print("Skill Sources:")
        for s in loader.sources:
            print(f"  [{s['type']}] {s['path']}")


if __name__ == "__main__":
    main()
