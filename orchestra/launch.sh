#!/bin/bash
# Launch the Orchestra Persistent Orchestra
# Opens 7 Claude Code sessions in tmux panes connected via claude-peers
#
# Usage:
#   .orchestra/launch.sh          # launch all 7
#   .orchestra/launch.sh master   # launch just master
#   .orchestra/launch.sh frontend backend  # launch specific departments

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="orchestra"
CLAUDE_FLAGS="--dangerously-skip-permissions --dangerously-load-development-channels server:claude-peers"

# Department order and models
declare -a DEPT_ORDER=(master strategy frontend backend devops content mcp)
declare -A MODELS=(
  [master]="opus"
  [strategy]="opus"
  [frontend]="sonnet"
  [backend]="sonnet"
  [devops]="haiku"
  [content]="sonnet"
  [mcp]="sonnet"
)
declare -A LABELS=(
  [master]="MASTER"
  [strategy]="S&QA"
  [frontend]="FRONTEND"
  [backend]="BACKEND"
  [devops]="DEVOPS"
  [content]="CONTENT"
  [mcp]="MCP"
)

# Filter departments if args provided
if [ $# -gt 0 ]; then
  DEPT_ORDER=("$@")
fi

# Kill existing session if running
tmux kill-session -t "$SESSION" 2>/dev/null || true

echo "╔══════════════════════════════════════════╗"
echo "║   Orchestra Orchestra — Launching...    ║"
echo "╠══════════════════════════════════════════╣"

FIRST=true
for dept in "${DEPT_ORDER[@]}"; do
  model="${MODELS[$dept]}"
  label="${LABELS[$dept]}"

  if [ -z "$model" ]; then
    echo "║  Unknown department: $dept — skipping    ║"
    continue
  fi

  # Build the init prompt file path
  if [ "$dept" = "master" ]; then
    init_file="$REPO_DIR/.orchestra/master/init-prompt.md"
  else
    init_file="$REPO_DIR/.orchestra/departments/$dept/init-prompt.md"
  fi

  # Build the claude command
  cmd="cd $REPO_DIR && claude $CLAUDE_FLAGS --model $model"

  if [ "$FIRST" = true ]; then
    # Create session with first window
    tmux new-session -d -s "$SESSION" -n "$dept" "$cmd"
    FIRST=false
  else
    # Add new window for each department
    tmux new-window -t "$SESSION" -n "$dept" "$cmd"
  fi

  echo "║  ✓ ${label} (${model})                        ║" | head -c 45
  echo "║"
done

echo "╠══════════════════════════════════════════╣"
echo "║  ${#DEPT_ORDER[@]} agents launched in tmux session     ║"
echo "║                                          ║"
echo "║  Attach:  tmux attach -t orchestra       ║"
echo "║  Switch:  Ctrl+B then window number      ║"
echo "║  List:    Ctrl+B then W                  ║"
echo "║  Detach:  Ctrl+B then D                  ║"
echo "╚══════════════════════════════════════════╝"
echo ""
echo "Once attached, paste each agent's init prompt:"
for dept in "${DEPT_ORDER[@]}"; do
  if [ "$dept" = "master" ]; then
    echo "  $dept: cat .orchestra/master/init-prompt.md"
  else
    echo "  $dept: cat .orchestra/departments/$dept/init-prompt.md"
  fi
done
echo ""
echo "Or send init prompts manually in each window."
