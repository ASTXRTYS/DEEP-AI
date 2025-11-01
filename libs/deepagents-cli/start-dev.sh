#!/bin/bash
# Start LangGraph dev server in background, then CLI
# When CLI exits, automatically kills the server
# Usage: ./start-dev.sh [--agent AGENT_NAME] [--auto-approve]

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Starting development environment..."
echo "📁 Directory: $SCRIPT_DIR"
echo ""

cd "$SCRIPT_DIR"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found in $SCRIPT_DIR"
    echo "Please create .env with required environment variables."
    exit 1
fi

# Start LangGraph dev server in background
echo "📡 Starting LangGraph dev server in background..."
langgraph dev > /tmp/langgraph-dev.log 2>&1 &
SERVER_PID=$!

# Function to cleanup on exit
cleanup() {
    echo ""
    echo "🛑 Stopping LangGraph dev server (PID: $SERVER_PID)..."
    kill $SERVER_PID 2>/dev/null || true
    # Also kill any child processes
    pkill -P $SERVER_PID 2>/dev/null || true
    echo "✅ Server stopped"
    exit 0
}

# Set trap to cleanup on script exit
trap cleanup EXIT INT TERM

# Wait for server to start
echo "⏳ Waiting for server to be ready..."
MAX_WAIT=30
WAITED=0
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl -s http://127.0.0.1:2024/ok > /dev/null 2>&1; then
        echo "✅ Server is ready!"
        break
    fi
    sleep 1
    WAITED=$((WAITED + 1))
    if [ $WAITED -eq $MAX_WAIT ]; then
        echo "❌ Server failed to start within ${MAX_WAIT}s"
        echo "Check logs at /tmp/langgraph-dev.log"
        exit 1
    fi
done

echo ""
echo "🎨 Server URLs:"
echo "   - API: http://127.0.0.1:2024"
echo "   - Studio UI: https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024"
echo "   - API Docs: http://127.0.0.1:2024/docs"
echo "   - Server Logs: /tmp/langgraph-dev.log"
echo ""

# Start CLI with passed arguments
echo "🤖 Starting DeepAgents CLI..."
echo ""

deepagents "$@"

# cleanup() will be called automatically when script exits
