# Contributing to OATS

PRs welcome. Here's how to contribute.

## Adding a Skill

1. Create `skills/your-skill-name/SKILL.md` following the [authoring standard](reference/skill-authoring-standard.md)
2. Run the validator: `python3 tools/orchestra_skill_validator.py skills/your-skill-name/SKILL.md`
3. Score must be 70%+ (grade B or higher)
4. Submit PR with: what the skill does, where you used it, what score it gets

## Adding an Agent

Agents go in `agents/`. They should:
- Be standalone (runnable with `python3 agents/your-agent.py`)
- Have clear CLI usage in the docstring
- Accept `--help` via argparse
- Write output to `/tmp/` or configurable path
- Never modify project files (agents observe, they don't edit)

## Adding a Tool

Tools go in `tools/`. They should:
- Be importable (`from tools.your_tool import YourClass`)
- Have a `main()` function with CLI interface
- Include docstring with usage examples
- Support the orchestrator integration pattern

## Running Tests

```bash
# Validate all skills
python3 orchestrator.py improve --target skills

# System health check
python3 orchestrator.py health

# Test imports
python3 -c "from tools.hooks import HookEngine; print('OK')"
python3 -c "from tools.coordinator import Coordination; print('OK')"
python3 -c "from agents.dream import DreamAgent; print('OK')"
```

## Code Style

- Python 3.10+
- No external dependencies (stdlib only)
- Type hints on public methods
- Docstrings on classes and public functions

## Commit Messages

Follow conventional commits:
- `feat:` new features
- `fix:` bug fixes
- `docs:` documentation only
- `refactor:` code changes that don't add features or fix bugs
