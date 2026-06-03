#!/bin/bash
# SagTask 30s Demo Script — typed out in real time
# Run: bash docs/demo-script.sh
# Record: asciinema rec -c "bash docs/demo-script.sh" docs/demo.cast
#
# All commands shown are REAL and runnable. The "sag_task_*" tools are
# invoked by the LLM (via the hermes-agent tool framework); this terminal
# demo shows the *underlying state* those tools read/write.

export TERM=xterm-256color
export PS1='\[\033[1;36m\]~\[\033[0m\]\[\033[1;34m\]\w\[\033[0m\]$ '

# Demo speed (chars per second of typing)
TYPE_DELAY=0.022
LINE_PAUSE=0.35

# Type one character at a time, then run a command
type_run() {
    local cmd="$1"
    local i
    for ((i=0; i<${#cmd}; i++)); do
        printf "%s" "${cmd:$i:1}"
        sleep "$TYPE_DELAY"
    done
    sleep 0.2
    printf "\n"
    # Run via a sub-bash with || true to ignore non-zero exits
    ( eval "$cmd" ) 2>/dev/null || true
    sleep "$LINE_PAUSE"
}

clear
printf "\n"
sleep 0.4

# 1. STATUS
printf "\n\033[1;33m▸ sag_task_status\033[0m  \033[2m— where am I in the project?\033[0m\n"
sleep 0.2
type_run 'python3 -m json.tool .sag_task_state.json | grep -E "task|status|phase|step" | head -6'

sleep 0.3

# 2. LIST ALL TASKS
printf "\n\033[1;33m▸ sag_task_list\033[0m    \033[2m— all tasks in the shared pool\033[0m\n"
sleep 0.2
type_run 'ls ~/.hermes/sag_tasks/ | grep -v "^[.]"'

sleep 0.3

# 3. GIT LOG = AUDIT TRAIL
printf "\n\033[1;33m▸ sag_task_git_log\033[0m  \033[2m— every step is a commit\033[0m\n"
sleep 0.2
type_run 'git log --oneline | head -6'

sleep 0.3

# 4. THE PROMISE
printf "\n\033[1;32m▸\033[0m  4-week project. Cross-session. 264 tests. 47+ commits.\n"
printf "\033[1;32m▸\033[0m  The agent never loses its place.\n"
printf "\033[1;36m▸\033[0m  \033[1mThat's SagTask.\033[0m\n"
sleep 2
