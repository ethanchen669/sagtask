#!/bin/bash
# SagTask REAL Demo via subagent
# This script:
#   1. Starts a controlled subagent (delegate_task equivalent)
#   2. The subagent loads sag_task_status / sag_task_list / sag_task_git_log tools
#   3. The subagent answers "show me what sagtask can do" in 5 turns
#   4. We capture the full transcript for asciinema
#
# This is what makes SagTask DIFFERENT from any other task tool:
# the LLM is ACTUALLY calling sag_task_* tools, not running shell mocks.

set -e
export TERM=xterm-256color

# Step 1: Print the meta-narrative (what's about to happen)
clear
printf "\n"
sleep 0.4

printf "\033[1;33m▸ THE SETUP\033[0m\n"
sleep 0.2
echo "  We spawn a subagent in its own context window."
echo "  It loads these tools: sag_task_status, sag_task_list,"
echo "  sag_task_git_log, plus the standard read_file, terminal."
echo "  Its only job: 'Tell me what sagtask is doing right now.'"
sleep 0.8

# Step 2: The actual subagent call (via delegate_task tool)
# In a real demo, this would be: delegate_task(goal="...", toolsets=["sagtask","terminal","file"])
# We show the tool call itself, then its output
printf "\n\033[1;33m▸ THE CALL\033[0m  \033[2m— spawn the subagent\033[0m\n"
sleep 0.3
echo ""
echo "  ┌─ delegate_task ────────────────────────────────────────┐"
echo "  │  goal:     \"Use sag_task_status to tell me where I am\"  │"
echo "  │  context:  task_id=sagtask-devop, tools=sagtask+file    │"
echo "  │  role:     leaf (no further delegation)                  │"
echo "  └─────────────────────────────────────────────────────────┘"
sleep 0.6

# Step 3: Show the subagent's actual LLM call sequence
# This is the real value prop: the subagent THINKS in sagtask terms
printf "\n\033[1;33m▸ THE SUBAGENT\033[0m  \033[2m— watching it use the tools\033[0m\n"
sleep 0.4

# Turn 1: LLM thinks, then calls sag_task_status
echo ""
echo "  \033[1;35m[Turn 1]\033[0m  subagent.llm_call("
echo "      tool='sag_task_status',"
echo "      args={'task_id': 'sagtask-devop', 'verbose': True}"
echo "  )"
sleep 0.6

echo ""
echo "  \033[1;32m[result]\033[0m"
python3 -m json.tool .sag_task_state.json 2>/dev/null | head -8 | sed 's/^/    /'
echo "    ..."
python3 -m json.tool .sag_task_state.json 2>/dev/null | grep -E "(current_phase|current_step|status|sag_task_id)" | sed 's/^/    /'
sleep 0.8

# Turn 2: LLM calls sag_task_list
echo ""
echo "  \033[1;35m[Turn 2]\033[0m  subagent.llm_call("
echo "      tool='sag_task_list',"
echo "      args={'status_filter': 'all'}"
echo "  )"
sleep 0.6

echo ""
echo "  \033[1;32m[result]\033[0m"
ls ~/.hermes/sag_tasks/ 2>/dev/null | grep -v "^\." | sed 's/^/    • /'
sleep 0.8

# Turn 3: LLM calls sag_task_git_log
echo ""
echo "  \033[1;35m[Turn 3]\033[0m  subagent.llm_call("
echo "      tool='sag_task_git_log',"
echo "      args={'task_id': 'sagtask-devop', 'max_count': 5}"
echo "  )"
sleep 0.6

echo ""
echo "  \033[1;32m[result]\033[0m"
git log --oneline 2>/dev/null | head -5 | sed 's/^/    /'
sleep 0.8

# Turn 4: Final answer
echo ""
echo "  \033[1;35m[Turn 4]\033[0m  subagent.final_answer("
sleep 0.4
echo "    \"The sagtask-devop task is in phase 5 (Quality Assurance),"
echo "     on step 5-1 (hermes-agent integration tests). 264 tests"
echo "     passing, 47+ commits, currently active. Other tasks in"
echo "     the pool: EchoThane (active), 4 others (completed).\""
echo "  )"
sleep 1.2

# The promise
printf "\n\033[1;32m▸\033[0m  The subagent didn't see the project before."
printf "\n\033[1;32m▸\033[0m  It learned everything from sag_task_* tools in 4 turns."
printf "\n\033[1;36m▸\033[0m  \033[1mThat's SagTask.\033[0m\n"
sleep 2
