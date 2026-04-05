#!/bin/bash
# Launch the OATS Orchestra
# Opens Manager + CEO + department agents in tmux via claude-peers
#
# Architecture:
#   CEO (Opus)     — strategic gate, consulted sparingly
#   Manager (Sonnet) — operational coordinator, handles 80%+ of work
#   Departments    — specialist agents, execute in parallel
#
# Usage:
#   orchestra/launch.sh                    # launch all (CEO + Manager + 5 depts)
#   orchestra/launch.sh manager            # launch just manager
#   orchestra/launch.sh ceo frontend       # launch specific agents
#   RAG=1 orchestra/launch.sh             # launch with RAG MCP server

set -e

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SESSION="orchestra"
CLAUDE_FLAGS="--dangerously-skip-permissions --dangerously-load-development-channels server:claude-peers"

# Agent order: CEO first (Opus), then Manager, then departments
declare -a AGENT_ORDER=(ceo manager frontend backend devops content mcp)
declare -A MODELS=(
  [ceo]="opus"
  [manager]="sonnet"
  [frontend]="sonnet"
  [backend]="sonnet"
  [devops]="haiku"
  [content]="sonnet"
  [mcp]="sonnet"
)
declare -A LABELS=(
  [ceo]="CEO"
  [manager]="MANAGER"
  [frontend]="FRONTEND"
  [backend]="BACKEND"
  [devops]="DEVOPS"
  [content]="CONTENT"
  [mcp]="MCP"
)

# Filter agents if args provided
if [ $# -gt 0 ]; then
  AGENT_ORDER=("$@")
fi

# Kill existing session if running
tmux kill-session -t "$SESSION" 2>/dev/null || true

# Build MCP config for RAG if enabled
MCP_FLAGS=""
if [ "${RAG:-0}" = "1" ]; then
  MCP_CONFIG="$REPO_DIR/.oats-mcp-config.json"
  cat > "$MCP_CONFIG" <<MCPEOF
{
  "mcpServers": {
    "oats-rag": {
      "command": "python3",
      "args": ["$REPO_DIR/tools/rag_server.py"]
    }
  }
}
MCPEOF
  MCP_FLAGS="--mcp-config $MCP_CONFIG"
  echo "RAG MCP server enabled for all agents"
fi

echo ""
echo "  OATS Orchestra — Launching..."
echo "  ================================"
echo ""

FIRST=true
for agent in "${AGENT_ORDER[@]}"; do
  model="${MODELS[$agent]}"
  label="${LABELS[$agent]}"

  if [ -z "$model" ]; then
    echo "  ? Unknown agent: $agent — skipping"
    continue
  fi

  # Build the init prompt file path
  if [ "$agent" = "manager" ]; then
    init_file="$REPO_DIR/orchestra/master/init-prompt.md"
  elif [ "$agent" = "ceo" ]; then
    init_file="$REPO_DIR/orchestra/ceo/init-prompt.md"
  else
    init_file="$REPO_DIR/orchestra/departments/$agent/init-prompt.md"
  fi

  # Build the claude command
  cmd="cd $REPO_DIR && claude $CLAUDE_FLAGS $MCP_FLAGS --model $model"

  if [ "$FIRST" = true ]; then
    tmux new-session -d -s "$SESSION" -n "$agent" "$cmd"
    FIRST=false
  else
    tmux new-window -t "$SESSION" -n "$agent" "$cmd"
  fi

  echo "  + ${label} (${model})"
done

echo ""
echo "  ${#AGENT_ORDER[@]} agents launched in tmux session"
echo ""
echo "  Attach:  tmux attach -t orchestra"
echo "  Switch:  Ctrl+B then window number"
echo "  List:    Ctrl+B then W"
echo "  Detach:  Ctrl+B then D"
echo ""
# Wait for agents, confirm dev-channels dialog, then send init prompts
echo "  Waiting 8 seconds for agents to start..."
sleep 8

echo "  Confirming dev-channels dialog..."
for agent in "${AGENT_ORDER[@]}"; do
  tmux send-keys -t "$SESSION:$agent" "Enter"
  sleep 0.5
done

echo "  Waiting 5 more seconds for agents to load..."
sleep 5

echo "  Sending init prompts..."
for agent in "${AGENT_ORDER[@]}"; do
  if [ "$agent" = "manager" ]; then
    init_file="$REPO_DIR/orchestra/master/init-prompt.md"
  elif [ "$agent" = "ceo" ]; then
    init_file="$REPO_DIR/orchestra/ceo/init-prompt.md"
  else
    init_file="$REPO_DIR/orchestra/departments/$agent/init-prompt.md"
  fi
  if [ -f "$init_file" ]; then
    init_content=$(cat "$init_file")
    tmux send-keys -t "$SESSION:$agent" "$init_content" Enter
    echo "  Sent init prompt to $agent"
    sleep 2
  fi
done
echo ""
