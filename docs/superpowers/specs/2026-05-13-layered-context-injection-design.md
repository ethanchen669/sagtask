# Layered Context Injection Design

**Date:** 2026-05-13  
**Status:** Approved  
**Goal:** Replace the current flat, always-full task context injection with a layered, state-aware system that injects only contextually relevant information each turn.

## Problem

`SagTaskPlugin`'s `pre_llm_call` hook injects the full task context (~15-20 lines) every turn regardless of whether the information is relevant to the current work. This causes:

1. **Attention dilution** — static, unchanged context competes with task-relevant content for LLM attention.
2. **Irrelevant noise** — cross-pollination details during focused TDD execution, verbose plan progress when nothing changed, verification status when no verification is configured.

## Confirmed Hermes Behavior

- `pre_llm_call` fires once per turn (before the tool-calling loop), not per LLM request.
- Injected context is ephemeral — not persisted to session DB, not retained in historical messages.
- Each API call within a turn re-injects the same content into the current user message.
- Consequence: every turn MUST include at least a minimal anchor, because no historical message retains prior injections.

## Design

### Layer Model

| Layer | Content | Trigger |
|-------|---------|---------|
| L0 - Anchor | task_id, status, phase_id, step_id | Every active-task turn |
| L1 - Navigation | phase/step names, pending gates | Context hash changed; pending gates unconditionally |
| L1.5 - Recent Output | artifacts summary (1 line) | After advance/resume; artifacts_summary field changed |
| L2 - Execution | methodology, tdd/debug/brainstorm phase, plan progress, active dispatches | methodology != "none" or plan_progress.total > 0 |
| L3 - Quality | verification status, compact metrics | Step has verification config; failed/pending states unconditionally |
| L4a - Related Hint | "N task(s) available" | Relationships exist |
| L4b - Related Details | cross-pollination artifact summaries | Step just switched; user intent keywords; brainstorm/debug methodology |

### Decision Rules

```python
layers = [L0]

# L1: Navigation — on change or blocking
if context_hash_changed or first_turn_for_task:
    layers += [L1]
if pending_gates:
    layers += [L1]  # blocking: every turn

# L1.5: Artifacts — on change
if artifacts_summary_changed:
    layers += [L1_5]

# L2: Execution — when methodology active
if methodology != "none" or plan_total > 0:
    if active_dispatches > 0 or failed_subtasks > 0:
        layers += [L2_EXPANDED]
    else:
        layers += [L2_COMPACT]

# L3: Quality — when verification configured
if step_has_verification:
    if must_pass and (not last_verification or not last_verification.passed):
        layers += [L3]  # blocking: every turn
    elif metrics_changed:
        layers += [L3]

# L4: Cross-pollination
if has_relationships:
    layers += [L4A]
if step_just_switched or methodology in ("brainstorm", "debug") or user_intent_related:
    layers += [L4B]
```

### Context Hash

Compute a hash over the fields that affect injected content. Compare with the cached hash from the previous turn to detect meaningful state changes without modifying any handler.

```python
def _compute_context_hash(self, state: Dict[str, Any]) -> str:
    """Hash of fields that affect context injection content."""
    import hashlib
    ms = state.get("methodology_state", {})
    parts = [
        state.get("status", ""),
        state.get("current_phase_id", ""),
        state.get("current_step_id", ""),
        str(state.get("pending_gates", [])),
        state.get("artifacts_summary", ""),
        ms.get("current_methodology", ""),
        ms.get("tdd_phase") or "",
        ms.get("debug_phase") or "",
        ms.get("brainstorm_phase") or "",
        str(ms.get("subtask_progress", {})),
        str(ms.get("last_verification", {})),
    ]
    return hashlib.md5("|".join(parts).encode()).hexdigest()[:8]
```

Instance state:

```python
self._last_context_hash: str = ""
self._last_artifacts_summary: str = ""
self._last_step_id: str = ""
```

### Output Formats

**L0 — Anchor (always):**
```
[SagTask] task=<id> status=<status> phase=<phase_id> step=<step_id>
```

**L1 — Navigation (on change / blocking):**
```
- Phase: <phase_name> | Step: <step_name>
- Gate: awaiting approval <gate_id>
```

**L1.5 — Recent Output (on change):**
```
- Artifacts: <summary text>
```

**L2 Compact — Execution (stable):**
```
- TDD: RED | Plan: 2/8 done, 1 active
```

**L2 Expanded — Execution (dispatches/failures):**
```
- Methodology: tdd | TDD phase: RED
- Plan: 2/8 done, 1 active, 1 failed
```

**L3 — Quality (blocking or changed):**
```
- Verify: pending, must pass before advance
- Verify: failed | 3/5 passed, streak -2 | Coverage 72%→
```

**L4a — Related Hint:**
```
- Related: 2 task(s) available
```

**L4b — Related Details:**
```
[Related]
- <task_id>: <path> - <summary>
- <task_id>: <path> - <summary>
```

### Example Outputs

**Stable TDD execution, no changes for several turns:**
```
[SagTask] task=my-task status=active phase=impl step=add-auth
- TDD: RED | Plan: 2/8 done, 1 active
- Verify: failed | 3/5 passed, streak -2 | Coverage 72%→
- Related: 1 task(s) available
```
(4 lines)

**Just advanced to a new step:**
```
[SagTask] task=my-task status=active phase=impl step=add-auth
- Phase: Implementation | Step: Add auth module
- Methodology: tdd | Plan: 0/8 done
- Verify: pending, must pass before advance
- Artifacts: previous step added auth schema and token fixtures
[Related]
- related-task: auth_utils.py - shared token validation
```
(7 lines)

**Pending approval gate:**
```
[SagTask] task=my-task status=active phase=design step=api-contract
- Phase: Design | Step: API contract review
- Gate: awaiting approval gate-api-contract
```
(3 lines)

**Minimal — stable, no methodology, no verification:**
```
[SagTask] task=my-task status=active phase=p1 step=s1
```
(1 line)

### User Intent Detection for L4b

Detect keywords in the current turn's user message to trigger cross-pollination details:

```python
_RELATED_INTENT_KEYWORDS = {"related", "reuse", "reference", "参考", "借鉴", "相关"}

def _user_wants_related(self, query: str) -> bool:
    q_lower = query.lower()
    return any(kw in q_lower for kw in _RELATED_INTENT_KEYWORDS)
```

### Integration with Existing Code

**What changes:**
- `_build_task_context()` → rewritten to implement layered logic
- `prefetch()` → passes `query` to the context builder for intent detection
- `on_turn_start()` → removed (no longer pre-computes; `prefetch` builds context directly)
- `_prefetch_result` / `_prefetch_lock` → removed

**What stays:**
- `_build_metrics_summary()` → still used by L3, unchanged internally
- `_build_cross_pollination_context()` → adapted for L4b (truncated format)
- `emit_metric()` and all handlers → unchanged

### Files Modified

- `src/sagtask/plugin.py`: Rewrite `_build_task_context()`, add `_compute_context_hash()`, `_build_minimal_anchor()`, `_build_l1_navigation()`, `_build_l2_execution()`, `_build_l3_quality()`, `_build_l4_related()`, `_user_wants_related()`. Remove `_prefetch_result`, `_prefetch_lock`, `on_turn_start` pre-computation.
- `tests/test_injection.py` (new): Layer selection tests.
- `tests/test_metrics.py`: Update `test_context_injection_includes_metrics` if format changes.

## Testing Plan

1. Every active-task turn includes L0 anchor.
2. No active task returns empty string.
3. Pending gates injected every turn (L1 unconditional).
4. `must_pass=True` with no verification → L3 "pending, must pass" every turn.
5. Failed verification → L3 injected every turn.
6. Stable execution with no changes → L0 + L2 compact + relevant L3/L4a only.
7. Context hash change triggers L1 navigation expansion.
8. Step switch triggers L4b related details.
9. User intent keywords trigger L4b.
10. Artifacts change triggers L1.5.
11. Plan with active dispatches or failures triggers L2 expanded.
12. Task switch resets cached hash and triggers full expansion.

## Design Decisions

**Why context hash over `context_revision` counter:**
- Non-invasive: no changes to any of the 11 handlers.
- Impossible to forget bumping — hash is derived from state, not manually maintained.
- md5 truncated to 8 chars is sufficient for change detection (not security).

**Why no per-session keying:**
- SagTask operates with one active task per session.
- `session_id` is always empty in current Hermes integration.
- Adding session keying now is YAGNI; easy to add later if needed.

**Why not skip turns entirely:**
- Injected context is ephemeral. Skipping a turn = LLM has zero task awareness that turn.
- Even L0 alone (1 line, ~50 chars) is negligible cost for guaranteed awareness.
