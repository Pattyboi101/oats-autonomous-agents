#!/usr/bin/env bash
# CEO Agent Harness — Launcher
# Usage: ./launch-ceo.sh [optional initial prompt]
#
# Launches Claude Code with Opus in the project directory
# with bypass permissions for autonomous operation.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="$REPO_DIR/orchestra/ceo/state.md"

# Reset state for new session
cat > "$STATE_FILE" << 'EOF'
# Session State
## Focus:
## Done:
## Decisions:
## Blocked:
## Next:
EOF

cd "$REPO_DIR"

if [ $# -gt 0 ]; then
    # One-shot mode with initial prompt
    exec claude \
        --model claude-opus-4-6 \
        --dangerously-skip-permissions \
        -p "$*"
else
    # Interactive mode
    exec claude \
        --model claude-opus-4-6 \
        --dangerously-skip-permissions
fi
