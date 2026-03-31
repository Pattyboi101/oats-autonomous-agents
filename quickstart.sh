#!/bin/bash
# OATS Quickstart — set up a working demo in 30 seconds
set -e

echo "=== OATS Quickstart ==="
echo

# 1. Create a sample project structure
echo "Creating sample project structure..."
mkdir -p .orchestra/memory
mkdir -p .orchestra/departments/backend
mkdir -p .orchestra/departments/frontend
mkdir -p .orchestra/departments/devops
mkdir -p .oats

# 2. Create sample memory files
cat > .orchestra/memory/playbook.md << 'PLAYBOOK'
# Playbook

## Strategic Lessons
- Always test before deploying
- Keep memory files lean

## $(date +%Y-%m-%d) — Project initialized
Set up OATS framework. Ready for autonomous work.
PLAYBOOK

cat > .orchestra/departments/backend/memory.md << 'MEM'
# Backend Memory
- Project uses Python 3 / FastAPI
- Database: SQLite with WAL mode
MEM

cat > .orchestra/departments/frontend/memory.md << 'MEM'
# Frontend Memory
- CSS variables for theming
- Touch targets >= 44px for mobile
MEM

cat > .orchestra/departments/devops/memory.md << 'MEM'
# DevOps Memory
- Deploy to Fly.io with --remote-only
- Always run smoke tests before deploy
MEM

# 3. Create sample hooks config
cat > .oats/hooks.json << 'HOOKS'
{
  "PreToolUse": [
    {
      "matcher": {"tool": "Edit|Write"},
      "hooks": [
        {"type": "command", "command": "echo 'Pre-edit check passed'", "timeout": 5}
      ]
    }
  ],
  "Stop": [
    {
      "hooks": [
        {"type": "command", "command": "echo 'Stop gate: all checks passed'"}
      ]
    }
  ],
  "TaskCompleted": [
    {
      "hooks": [
        {"type": "command", "command": "echo 'Task {task_id} completed by {owner}'"}
      ]
    }
  ]
}
HOOKS

echo "Done."
echo

# 4. Run health check
echo "Running health check..."
python3 orchestrator.py health
echo

# 5. Run skill validator
echo "Running skill improvement scan..."
python3 orchestrator.py improve --target skills
echo

# 6. Check memory health
echo "Checking memory health..."
python3 tools/memory_scoper.py health
echo

# 7. Validate hooks
echo "Validating hooks..."
python3 tools/hooks.py validate .oats/hooks.json
echo

# 8. Test dream gate
echo "Dream gate status:"
python3 agents/dream.py --gate-status
echo

echo "=== Quickstart Complete ==="
echo
echo "Next steps:"
echo "  1. Add your skills to skills/"
echo "  2. Configure hooks in .oats/hooks.json"
echo "  3. Run: python3 orchestrator.py run 'Your task here'"
echo "  4. Start a team: python3 orchestrator.py team start my-team 'Description'"
echo "  5. Run an agent: python3 agents/verification.py --full"
