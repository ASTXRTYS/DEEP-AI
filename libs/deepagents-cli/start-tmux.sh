#!/bin/bash
# Start LangGraph dev server and CLI in tmux split panes
# Usage: ./start-tmux.sh

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Session name
SESSION_NAME="deepagents-dev"

echo "🚀 Starting DeepAgents in tmux..."
echo "📁 Directory: $SCRIPT_DIR"
echo ""

cd "$SCRIPT_DIR"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found in $SCRIPT_DIR"
    echo "Please create .env with required environment variables."
    exit 1
fi

# Check if tmux is installed
if ! command -v tmux &> /dev/null; then
    echo "❌ Error: tmux is not installed"
    echo "Install with: brew install tmux"
    exit 1
fi

# Kill existing session if it exists
tmux kill-session -t "$SESSION_NAME" 2>/dev/null || true

# Create new tmux session with split panes
echo "📺 Creating tmux session '$SESSION_NAME'..."

# Create session with first window
tmux new-session -d -s "$SESSION_NAME" -x "$(tput cols)" -y "$(tput lines)"

# Split window horizontally (side by side)
tmux split-window -h -t "$SESSION_NAME"

# Left pane: LangGraph dev server
tmux send-keys -t "$SESSION_NAME:0.0" "cd '$SCRIPT_DIR'" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "echo '📡 LangGraph Dev Server'" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "echo '========================'" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "echo ''" C-m
tmux send-keys -t "$SESSION_NAME:0.0" "langgraph dev" C-m

# Right pane: Wait a bit, then start CLI
tmux send-keys -t "$SESSION_NAME:0.1" "cd '$SCRIPT_DIR'" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "echo '🤖 DeepAgents CLI'" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "echo '================'" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "echo ''" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "echo 'Waiting for server to start...'" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "sleep 10" C-m
tmux send-keys -t "$SESSION_NAME:0.1" "deepagents" C-m

# Set pane titles
tmux select-pane -t "$SESSION_NAME:0.0" -T "LangGraph Server"
tmux select-pane -t "$SESSION_NAME:0.1" -T "DeepAgents CLI"

# Focus on CLI pane (right)
tmux select-pane -t "$SESSION_NAME:0.1"

echo "✅ tmux session created!"
echo ""
echo "📝 tmux Controls:"
echo "   - Ctrl+b, arrow keys : Navigate between panes"
echo "   - Ctrl+b, d          : Detach from session (keeps running)"
echo "   - tmux attach -t $SESSION_NAME : Reattach to session"
echo "   - Ctrl+b, x          : Kill current pane"
echo "   - Ctrl+b, &          : Kill entire window"
echo ""
echo "🎯 Attaching to session..."
sleep 1

# Attach to the session
tmux attach-session -t "$SESSION_NAME"
