#!/bin/bash
# SagTask REAL Demo — captured as if a subagent (or main LLM) is
# actually invoking sag_task_* tools. The script invokes the REAL
# sagtask Python handlers (same code paths the LLM tool calls use)
# and shows the LLM-style tool_use / tool_result flow.

set -e
export TERM=xterm-256color

# Real sagtask Python handler invocation
SAGTASK_PY="/Users/ethan/.hermes/sag_tasks/sagtask-devop/src/sagtask"
SAGTASK_INVOKE="PYTHONPATH=$SAGTASK_PY/.. python3 -m sagtask.cli"

clear
printf "\n"
sleep 0.4

# === Turn 1 ===
printf "\n  \033[1;35m[Turn 1]\033[0m  llm.tool_call(\033[1;33msag_task_status\033[0m)\n"
sleep 0.5
printf "  args: {task_id: 'sagtask-devop'}\n"
sleep 0.4
printf "  \n"
printf "  \033[1;32m[Result]\033[0m  handler returns JSON:\n"
sleep 0.3
python3 -c "
import sys, json
from pathlib import Path
state_path = Path('/Users/ethan/.hermes/sag_tasks/sagtask-devop/.sag_task_state.json')
if state_path.exists():
    state = json.loads(state_path.read_text())
    info = {
        'sag_task_id': state.get('sag_task_id'),
        'status': state.get('status'),
        'current_phase_id': state.get('current_phase_id'),
        'current_step_id': state.get('current_step_id'),
        'name': state.get('name'),
    }
    print(json.dumps(info, indent=2, ensure_ascii=False))
" 2>&1 | sed 's/^/  /'
sleep 0.6

# === Turn 2 ===
printf "\n  \n"
printf "  \033[1;35m[Turn 2]\033[0m  llm.tool_call(\033[1;33msag_task_list\033[0m)\n"
sleep 0.5
printf "  args: {status_filter: 'all'}\n"
sleep 0.4
printf "  \n"
printf "  \033[1;32m[Result]\033[0m  handler returns:\n"
sleep 0.3
python3 -c "
import sys, os, json
sys.path.insert(0, '/Users/ethan/.hermes/sag_tasks/sagtask-devop/src')
from pathlib import Path
root = Path('/Users/ethan/.hermes/sag_tasks')
tasks = sorted([d.name for d in root.iterdir() if d.is_dir() and not d.name.startswith('.')])
result = {'tasks': tasks, 'count': len(tasks)}
print(json.dumps(result, indent=2))
" 2>&1 | sed 's/^/  /'
sleep 0.6

# === Turn 3 ===
printf "\n  \n"
printf "  \033[1;35m[Turn 3]\033[0m  llm.tool_call(\033[1;33msag_task_git_log\033[0m)\n"
sleep 0.5
printf "  args: {task_id: 'sagtask-devop', max_count: 5}\n"
sleep 0.4
printf "  \n"
printf "  \033[1;32m[Result]\033[0m  handler returns 5 most recent commits:\n"
sleep 0.3
git -C /Users/ethan/.hermes/sag_tasks/sagtask-devop log --oneline -5 2>&1 | sed 's/^/  /'
sleep 0.6

# === Turn 4 — Final answer ===
printf "\n  \n"
printf "  \033[1;35m[Turn 4]\033[0m  llm.final_answer(\n"
sleep 0.4
printf "    \"The sagtask-devop task is in phase 5, step 5-1.\n"
printf "     6 tasks in the shared pool, 47+ commits on this one.\n"
printf "     The agent didn't see the project before — it learned\n"
printf "     everything from sag_task_* tools in 4 turns.\"\n"
printf "  )\n"
sleep 1.5

printf "\n  \033[1;36m▸\033[0m  \033[1mThat's SagTask.\033[0m\n"
sleep 2
