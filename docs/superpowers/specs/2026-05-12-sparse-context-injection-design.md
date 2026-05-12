# Sparse Context Injection Design

**Date:** 2026-05-12  
**Status:** Approved  
**Goal:** Reduce repeated task context injection in `prefetch()` to avoid LLM attention dilution during multi-request turns.

## Problem

`SagTaskPlugin.prefetch()` is called on every LLM request (5-15 per turn). Each call returns the full task context (~10-20 lines). When the active task hasn't changed, this creates redundant context that dilutes LLM attention on the actual work content. The plugin cannot detect context compression, so it cannot react to lost context.

## Design

### Three-Level Injection Strategy

| Condition | Injection | Trigger |
|-----------|-----------|---------|
| State changed | Full context | `state["updated_at"]` differs from cached value |
| Counter hit | Minimal reminder (1 line) | Every N-th request (N=4) |
| Counter miss | Nothing (empty string) | All other requests |

### New Instance State

```python
self._injection_counter: int = 0
self._last_injected_updated_at: str = ""
self._injection_interval: int = 4
```

### Modified `prefetch()` Logic

```python
def prefetch(self, query: str, *, session_id: str = "") -> str:
    if not self._active_task_id:
        return ""

    state = self.load_task_state(self._active_task_id)
    if not state:
        return ""

    updated_at = state.get("updated_at", "")
    self._injection_counter += 1

    # State change → full injection, reset counter
    if updated_at != self._last_injected_updated_at:
        self._last_injected_updated_at = updated_at
        self._injection_counter = 0
        return self._build_task_context(state)

    # Counter hit → minimal reminder
    if self._injection_counter % self._injection_interval == 0:
        return self._build_minimal_reminder(state)

    # Counter miss → skip
    return ""
```

### Minimal Reminder Format

```
[SagTask] task=<task_id> step=<step_id> status=<status>
```

Single line, ~50-60 characters. Serves as a lightweight anchor for task awareness without consuming attention budget.

### `_build_minimal_reminder()` Method

```python
def _build_minimal_reminder(self, state: Dict[str, Any]) -> str:
    step_id = state.get("current_step_id", "")
    status = state.get("status", "unknown")
    return f"[SagTask] task={self._active_task_id} step={step_id} status={status}"
```

## Behavior in Typical Scenarios

**Single turn, 10 LLM requests, no state change:**

| Request # | Counter | Action |
|-----------|---------|--------|
| 1 | 0 (reset) | Full context (first call, `_last_injected_updated_at` is empty → treated as change) |
| 2 | 1 | Skip |
| 3 | 2 | Skip |
| 4 | 3 | Skip |
| 5 | 4 | Minimal reminder (4 % 4 == 0) |
| 6 | 5 | Skip |
| 7 | 6 | Skip |
| 8 | 7 | Skip |
| 9 | 8 | Minimal reminder (8 % 4 == 0) |
| 10 | 9 | Skip |

**State change mid-turn (e.g., after `sag_task_advance`):**

| Request # | Counter | Action |
|-----------|---------|--------|
| 1 | 0 | Full context |
| 2-4 | 1-3 | Skip |
| 5 | 4 | Minimal reminder |
| 6 | — | `sag_task_advance` changes `updated_at` |
| 7 | 0 (reset) | Full context (state changed) |
| 8-10 | 1-3 | Skip |

## Edge Cases

- **No active task:** Short-circuit returns empty string (existing behavior unchanged).
- **First call in session:** `_last_injected_updated_at` is empty, so any non-empty `updated_at` triggers full injection.
- **Task switch:** Changing `_active_task_id` implies a state load with different `updated_at`, triggering full injection.
- **Context compression:** Plugin cannot detect this. N=4 ensures a minimal reminder appears roughly every 4 requests, limiting maximum blindness to 3 consecutive skipped requests.

## Changes to `on_turn_start`

`on_turn_start` currently pre-computes context and stores in `_prefetch_result`. This pre-computation is no longer needed since `prefetch()` now handles its own logic. Remove the `_prefetch_result` / `_prefetch_lock` mechanism and let `prefetch()` do the work directly.

## Files Modified

- `src/sagtask/plugin.py`: Add instance attributes, rewrite `prefetch()`, add `_build_minimal_reminder()`, remove `_prefetch_result`/`_prefetch_lock`/`on_turn_start` pre-computation.
- `tests/test_metrics.py` or new `tests/test_injection.py`: Tests for injection frequency, state change detection, minimal reminder format.

## Why N=4

- Typical turn: 5-15 LLM requests
- N=4 means: 1 full injection + 1-3 minimal reminders per turn
- Maximum consecutive skips: 3 (between counter hits)
- Aggressive enough to meaningfully reduce redundancy (~60-75% reduction)
- Conservative enough that LLM is never more than 3 requests away from a reminder
- Simple, predictable, no adaptive complexity

## Why Not Adaptive

- Plugin cannot detect context compression (confirmed: no hook)
- Plugin has no access to context window size or token count
- Fixed N=4 is predictable and debuggable
- The problem space (5-15 requests/turn) is narrow enough that a fixed strategy works well

## Testing Plan

1. **First call returns full context** — empty `_last_injected_updated_at` triggers full injection
2. **Subsequent calls without state change skip** — requests 2, 3 return empty
3. **Counter hit returns minimal reminder** — request 4 returns the one-liner
4. **State change resets counter and injects full** — simulate `updated_at` change mid-sequence
5. **Minimal reminder format** — assert single line, contains task_id, step_id, status
6. **No active task returns empty** — existing behavior preserved
