#!/bin/bash
#
# Integration Test: Handoff Workflow
#
# This script tests that the /handoff command workflow is working end-to-end:
# 1. Clears any existing summary from agent.md (edge case handling)
# 2. Triggers /handoff --preview to test summary generation
# 3. Verifies workflow completes without errors
#
# Usage: ./test-handoff-workflow.sh [agent_name]
#

set -e  # Exit on error

AGENT_NAME="${1:-agent}"
AGENT_DIR="$HOME/.deepagents/$AGENT_NAME"
AGENT_MD="$AGENT_DIR/agent.md"
THREADS_JSON="$AGENT_DIR/threads.json"

echo "========================================="
echo "Handoff Workflow Integration Test"
echo "========================================="
echo ""

# Check if agent directory exists
if [ ! -d "$AGENT_DIR" ]; then
    echo "❌ Error: Agent directory not found: $AGENT_DIR"
    echo "   Run 'deepagents' at least once to create the agent."
    exit 1
fi

# Backup agent.md before modifications
BACKUP_FILE="$AGENT_MD.backup.$(date +%Y%m%d_%H%M%S)"
echo "📋 Creating backup: $BACKUP_FILE"
cp "$AGENT_MD" "$BACKUP_FILE"

# Count threads before
THREADS_BEFORE=$(jq '.threads | length' "$THREADS_JSON" 2>/dev/null || echo "0")
echo "🔢 Threads before: $THREADS_BEFORE"
echo ""

# Step 1: Clear existing summary block
echo "🧹 Step 1: Clearing existing summary from agent.md..."
python3 << 'PYTHON_SCRIPT'
import re
import sys

agent_md_path = sys.argv[1]

with open(agent_md_path, 'r') as f:
    content = f.read()

# Clear content between <current_thread_summary> tags
pattern = r'(<current_thread_summary>).*?(</current_thread_summary>)'
cleared = re.sub(pattern, r'\1\n\2', content, flags=re.DOTALL)

with open(agent_md_path, 'w') as f:
    f.write(cleared)

print(f"✅ Cleared summary block in {agent_md_path}")
PYTHON_SCRIPT "$AGENT_MD"

echo ""

# Step 2: Check if LangGraph server is running
echo "🔍 Step 2: Checking LangGraph server status..."
if curl -s http://127.0.0.1:2024/ok > /dev/null 2>&1; then
    echo "✅ LangGraph server is running"
else
    echo "⚠️  LangGraph server not detected - starting it..."
    echo "   (Server required for thread creation)"

    # Start server in background
    cd libs/deepagents-cli
    langgraph dev > /dev/null 2>&1 &
    SERVER_PID=$!
    echo "   Server PID: $SERVER_PID"

    # Wait for server to be ready
    echo -n "   Waiting for server to start"
    for i in {1..30}; do
        if curl -s http://127.0.0.1:2024/ok > /dev/null 2>&1; then
            echo " ✅"
            break
        fi
        echo -n "."
        sleep 1
    done

    if ! curl -s http://127.0.0.1:2024/ok > /dev/null 2>&1; then
        echo ""
        echo "❌ Failed to start LangGraph server"
        exit 1
    fi

    # Register cleanup
    trap "kill $SERVER_PID 2>/dev/null" EXIT
    cd ../..
fi

echo ""

# Step 3: Run handoff preview
echo "🚀 Step 3: Testing /handoff --preview command..."
echo "   This will:"
echo "   - Generate a summary of the current thread"
echo "   - Show preview without creating new thread"
echo "   - Verify the workflow completes without errors"
echo ""

# Create a test input that triggers handoff
cat << 'EOF' | timeout 30 deepagents --agent "$AGENT_NAME" 2>&1 | tee /tmp/handoff-test.log || true
/handoff --preview
/quit
EOF

echo ""

# Step 4: Verify results
echo "📊 Step 4: Verifying results..."

# Check if command completed
if grep -q "Preparing handoff summary" /tmp/handoff-test.log; then
    echo "✅ Handoff command was triggered"
else
    echo "❌ Handoff command was NOT triggered"
    echo ""
    echo "--- Test Output ---"
    cat /tmp/handoff-test.log
    exit 1
fi

# Check for errors
if grep -i "error\|exception\|traceback" /tmp/handoff-test.log > /dev/null; then
    echo "⚠️  Potential errors detected in output:"
    grep -i "error\|exception\|traceback" /tmp/handoff-test.log
    echo ""
    echo "--- Full Output ---"
    cat /tmp/handoff-test.log
    exit 1
fi

# Count threads after
THREADS_AFTER=$(jq '.threads | length' "$THREADS_JSON" 2>/dev/null || echo "0")
echo "🔢 Threads after: $THREADS_AFTER"

# Note: --preview should NOT create a new thread, just show the summary
if [ "$THREADS_AFTER" -eq "$THREADS_BEFORE" ]; then
    echo "✅ Preview mode: No new thread created (expected)"
else
    echo "⚠️  Thread count changed: $THREADS_BEFORE → $THREADS_AFTER"
    echo "   (Preview mode should not create threads)"
fi

echo ""
echo "========================================="
echo "✅ Test Complete!"
echo "========================================="
echo ""
echo "Summary:"
echo "  - Existing summary cleared: ✅"
echo "  - Handoff command triggered: ✅"
echo "  - Workflow completed: ✅"
echo "  - No errors detected: ✅"
echo ""
echo "Backup saved to: $BACKUP_FILE"
echo ""
echo "Next steps:"
echo "  1. Review test output above"
echo "  2. To test full handoff (with thread creation):"
echo "     deepagents --agent $AGENT_NAME"
echo "     /handoff"
echo "  3. Restore backup if needed:"
echo "     cp $BACKUP_FILE $AGENT_MD"
echo ""
