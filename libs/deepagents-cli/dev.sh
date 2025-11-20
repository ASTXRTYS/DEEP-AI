#!/bin/bash
# DeepAgents Unified Development Script
# Usage: ./dev.sh [mode] [options]
#
# Modes:
#   cli [args...]    Start server in background + CLI (Default)
#   server           Start LangGraph dev server only
#   tmux [args...]   Start server and CLI in tmux split panes
#   help             Show this help message
#
# Examples:
#   ./dev.sh
#   ./dev.sh cli --agent ResearchAgent
#   ./dev.sh server
#   ./dev.sh tmux

set -e

# Colors and formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Icons
ICON_ROCKET="🚀"
ICON_FOLDER="📁"
ICON_CHECK="✅"
ICON_ERROR="❌"
ICON_WAIT="⏳"
ICON_SERVER="📡"
ICON_CLI="🤖"
ICON_TMUX="📺"
ICON_STOP="🛑"

# Get directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

print_header() {
    echo -e "${BOLD}${BLUE}DeepAgents Development Environment${NC}"
    echo -e "${ICON_FOLDER} Directory: $SCRIPT_DIR"
    echo ""
}

check_env() {
    if [ ! -f .env ]; then
        echo -e "${ICON_ERROR} ${RED}Error: .env file not found in $SCRIPT_DIR${NC}"
        echo "Please create .env with required environment variables."
        exit 1
    fi
}

wait_for_server() {
    local max_wait=30
    local waited=0
    
    echo -e "${ICON_WAIT} Waiting for server to be ready..."
    
    while [ $waited -lt $max_wait ]; do
        if curl -s http://127.0.0.1:2024/ok > /dev/null 2>&1; then
            echo -e "${ICON_CHECK} ${GREEN}Server is ready!${NC}"
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
        
        # Show progress
        if [ $((waited % 5)) -eq 0 ]; then
            echo -n "."
        fi
    done
    
    echo ""
    echo -e "${ICON_ERROR} ${RED}Server failed to start within ${max_wait}s${NC}"
    echo "Check logs at /tmp/langgraph-dev.log"
    return 1
}

show_server_info() {
    echo ""
    echo -e "${BOLD}Server URLs:${NC}"
    echo -e "   - API:       ${CYAN}http://127.0.0.1:2024${NC}"
    echo -e "   - Studio UI: ${CYAN}https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024${NC}"
    echo -e "   - API Docs:  ${CYAN}http://127.0.0.1:2024/docs${NC}"
    echo ""
}

# -----------------------------------------------------------------------------
# Modes
# -----------------------------------------------------------------------------

mode_server() {
    echo -e "${ICON_ROCKET} Starting LangGraph dev server..."
    
    if [ ! -f langgraph.json ]; then
        echo -e "${ICON_ERROR} ${RED}Error: langgraph.json not found${NC}"
        exit 1
    fi
    
    langgraph dev
}

mode_cli() {
    echo -e "${ICON_ROCKET} Starting development environment (CLI Mode)..."
    
    # Start server in background
    echo -e "${ICON_SERVER} Starting LangGraph dev server in background..."
    langgraph dev > /tmp/langgraph-dev.log 2>&1 &
    SERVER_PID=$!
    
    # Cleanup function
    cleanup() {
        echo ""
        echo -e "${ICON_STOP} Stopping LangGraph dev server (PID: $SERVER_PID)..."
        kill $SERVER_PID 2>/dev/null || true
        pkill -P $SERVER_PID 2>/dev/null || true
        echo -e "${ICON_CHECK} Server stopped"
        exit 0
    }
    
    trap cleanup EXIT INT TERM
    
    if ! wait_for_server; then
        exit 1
    fi
    
    show_server_info
    
    echo -e "${ICON_CLI} Starting DeepAgents CLI..."
    echo ""
    
    deepagents "$@"
}

mode_tmux() {
    local args="$@"
    local session_name="deepagents-dev"
    
    echo -e "${ICON_ROCKET} Starting DeepAgents in tmux..."
    
    if ! command -v tmux &> /dev/null; then
        echo -e "${ICON_ERROR} ${RED}Error: tmux is not installed${NC}"
        echo "Install with: brew install tmux"
        exit 1
    fi
    
    # Kill existing session
    tmux kill-session -t "$session_name" 2>/dev/null || true
    
    echo -e "${ICON_TMUX} Creating tmux session '$session_name'..."
    
    # Create session
    tmux new-session -d -s "$session_name" -x "$(tput cols)" -y "$(tput lines)"
    tmux split-window -h -t "$session_name"
    
    # Left pane: Server
    tmux send-keys -t "$session_name:0.0" "cd '$SCRIPT_DIR'" C-m
    tmux send-keys -t "$session_name:0.0" "clear" C-m
    tmux send-keys -t "$session_name:0.0" "echo '${ICON_SERVER} LangGraph Dev Server'" C-m
    tmux send-keys -t "$session_name:0.0" "langgraph dev" C-m
    
    # Right pane: CLI
    tmux send-keys -t "$session_name:0.1" "cd '$SCRIPT_DIR'" C-m
    tmux send-keys -t "$session_name:0.1" "clear" C-m
    tmux send-keys -t "$session_name:0.1" "echo '${ICON_CLI} DeepAgents CLI'" C-m
    tmux send-keys -t "$session_name:0.1" "echo 'Waiting for server...'" C-m
    # We use a simpler sleep here as the visual check is enough in tmux
    tmux send-keys -t "$session_name:0.1" "sleep 5" C-m 
    if [ -n "$args" ]; then
        tmux send-keys -t "$session_name:0.1" "deepagents $args" C-m
    else
        tmux send-keys -t "$session_name:0.1" "deepagents" C-m
    fi
    
    # Titles
    tmux select-pane -t "$session_name:0.0" -T "Server"
    tmux select-pane -t "$session_name:0.1" -T "CLI"
    tmux select-pane -t "$session_name:0.1"
    
    echo -e "${ICON_CHECK} tmux session created!"
    echo "Attaching..."
    sleep 1
    
    tmux attach-session -t "$session_name"
}

show_help() {
    echo -e "Usage: ./dev.sh [mode] [options]"
    echo ""
    echo "Modes:"
    echo -e "  ${BOLD}cli${NC} [args...]    Start server + CLI (Default)"
    echo -e "  ${BOLD}server${NC}           Start server only"
    echo -e "  ${BOLD}tmux${NC} [args...]   Start tmux session"
    echo -e "  ${BOLD}help${NC}             Show this help"
    echo ""
}

# -----------------------------------------------------------------------------
# Main Execution
# -----------------------------------------------------------------------------

check_env

MODE=$1

case "$MODE" in
    server)
        print_header
        mode_server
        ;;
    tmux)
        shift
        print_header
        mode_tmux "$@"
        ;;
    help|--help|-h)
        print_header
        show_help
        ;;
    cli)
        shift
        print_header
        mode_cli "$@"
        ;;
    *)
        # If first arg starts with -, assume it's a flag for CLI mode
        # If first arg is not a known command, assume it's for CLI mode
        # This allows `./dev.sh --agent foo` to work as `cli` mode
        print_header
        mode_cli "$@"
        ;;
esac
