#!/bin/bash
# Start LangGraph dev server only
# Usage: ./start-dev-server.sh

set -e

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "🚀 Starting LangGraph dev server..."
echo "📁 Directory: $SCRIPT_DIR"
echo ""

cd "$SCRIPT_DIR"

# Check if .env exists
if [ ! -f .env ]; then
    echo "❌ Error: .env file not found in $SCRIPT_DIR"
    echo "Please create .env with required environment variables."
    exit 1
fi

# Check if langgraph.json exists
if [ ! -f langgraph.json ]; then
    echo "❌ Error: langgraph.json not found in $SCRIPT_DIR"
    exit 1
fi

# Start the server
langgraph dev
