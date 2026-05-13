# Layered Context Injection Design

**Date:** 2026-05-13  
**Status:** Approved (revised after design review)  
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
| L4b - Related Details | cross-pollination artifact summaries | Step just switched; user intent keywords; brainstorm/debug entry only |

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
    elif metrics_summary_hash_changed:
        layers += [L3]

# L4: Cross-pollination
if has_relationships:
    layers += [L4A]
if step_just_switched or user_intent_related:
    layers += [L4B]
if methodology in ("brainstorm", "debug") and step_just_entered_methodology:
    layers += [L4B]  # only on entry, not every turn
```

### Context Hash

Compute a canonical hash over the fields that affect injected content. Compare with the cached hash from the previous turn to detect meaningful state changes without modifying any handler.

```python
def _compute_context_hash(self, state: Dict[str, Any]) -> str:
    """Hash of fields that affect context injection content."""
    import hashlib, json
    ms = state.get("methodology_state", {})
    payload = {
        "status": state.get("status", ""),
        "phase_id": state.get("current_phase_id", ""),
        "step_id": state.get("current_step_id", ""),
        "pending_gates": state.get("pending_gates", []),
        "artifacts_summary": state.get("artifacts_summary", ""),
        "methodology": ms.get("current_methodology", ""),
        "tdd_phase": ms.get("tdd_phase") or "",
        "debug_phase": ms.get("debug_phase") or "",
        "brainstorm_phase": ms.get("brainstorm_phase") or "",
        "subtask_progress": ms.get("subtask_progress", {}),
        "last_verification": ms.get("last_verification") or {},
        "relationship_count": len(state.get("relationships", [])),
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(canonical.encode()).hexdigest()[:8]
```

### Injection Cache State

Cache is keyed by `(session_id, active_task_id)` to prevent cross-task bleed on task switch. Although `session_id` is currently empty, including it costs nothing and future-proofs the design.

```python
@dataclass
class _InjectionCache:
    context_hash: str = ""
    artifacts_summary: str = ""
    step_id: str = ""
    metrics_summary_hash: str = ""
    methodology: str = ""  # for detecting methodology entry

# Keyed by (session_id, task_id)
self._injection_cache: Dict[Tuple[str, str], _InjectionCache] = {}
```

**Change detection definitions:**

- `context_hash_changed`: current hash != cached `context_hash`
- `first_turn_for_task`: cache key `(session_id, task_id)` not in `_injection_cache`
- `artifacts_summary_changed`: current `state["artifacts_summary"]` != cached `artifacts_summary`
- `step_just_switched`: current `step_id` != cached `step_id`
- `metrics_summary_hash_changed`: md5 of `_build_metrics_summary()` output != cached `metrics_summary_hash`
- `step_just_entered_methodology`: current `methodology` != cached `methodology` (detects entry into brainstorm/debug)

### Failed Subtasks

Extend `methodology_state.subtask_progress` to include a `failed` count. Update `_handle_sag_task_plan_update` to maintain this field when subtask status becomes "failed".

```python
"subtask_progress": {"total": 5, "completed": 2, "in_progress": 2, "failed": 1}
```

This is a small additive change to one handler (`_plan.py`) and keeps the execution layer self-contained without needing to read plan files at injection time.

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

**Primary injection path:** `_on_pre_llm_call()` in `src/sagtask/hooks.py`.

This hook already receives `user_message` and `session_id`. The change is to pass them through to the layered context builder:

```python
def _on_pre_llm_call(session_id, user_message, ...) -> Dict[str, Any]:
    p = _get_provider()
    # ... existing init logic ...
    context_text = p._build_layered_context(state, user_message=user_message, session_id=session_id)
    return {"context": context_text} if context_text else {}
```

**What changes:**
- `src/sagtask/__init__.py`: Change `toolset="memory"` to `toolset="sagtask"` in tool registration. SagTask is a plugin, not a memory provider.
- `src/sagtask/hooks.py`: Pass `user_message` and `session_id` to context builder.
- `src/sagtask/plugin.py`: Replace `_build_task_context()` with `_build_layered_context()`. Add `_compute_context_hash()`, layer builder methods, `_InjectionCache`, `_user_wants_related()`. Remove dead code: `prefetch()`, `on_turn_start()`, `sync_turn()`, `_prefetch_result`, `_prefetch_lock`.
- `src/sagtask/handlers/_plan.py`: Add `failed` to `subtask_progress` dict in `_handle_sag_task_plan_update`.

**What stays:**
- `_build_metrics_summary()` → still used by L3, unchanged internally
- `_build_cross_pollination_context()` → adapted for L4b (compact format)
- `emit_metric()` and all handlers → unchanged

**Dead code removal:**
- `prefetch()`, `on_turn_start()`, `sync_turn()` — these are memory-provider interface methods. SagTask is a plugin, not a memory provider. They are never called by Hermes.
- `_prefetch_result`, `_prefetch_lock` — only used by the above dead methods.

**Semantic fix:**
- `toolset="memory"` → `toolset="sagtask"` in `__init__.py` tool registration. This corrects the architectural misrepresentation that caused confusion about SagTask's role (plugin vs memory provider).

### Files Modified

- `src/sagtask/hooks.py`: Pass `user_message`, `session_id` to builder.
- `src/sagtask/plugin.py`: Add `_build_layered_context()`, `_compute_context_hash()`, `_InjectionCache`, layer builder methods, `_user_wants_related()`.
- `src/sagtask/handlers/_plan.py`: Add `failed` count to `subtask_progress`.
- `tests/test_injection.py` (new): Layer selection tests via `_on_pre_llm_call`.
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
9. User intent keywords trigger L4b via `_on_pre_llm_call(user_message=...)`.
10. Artifacts change triggers L1.5.
11. Plan with active dispatches or failed subtasks triggers L2 expanded.
12. Task switch resets cached state and triggers full expansion (even with same step_id).
13. Stable brainstorm/debug turns do NOT repeatedly inject L4b (only on entry).
14. Metrics summary change triggers L3 even when other state fields unchanged.
15. Cache state is isolated per task (switching tasks doesn't carry stale cache).
16. Relationship changes affect context hash and layer decisions.

## Design Decisions

**Why context hash over `context_revision` counter:**
- Non-invasive: no changes to any of the 11 handlers (except adding `failed` to subtask_progress).
- Impossible to forget bumping — hash is derived from state, not manually maintained.
- Canonical JSON + md5 truncated to 8 chars is sufficient for change detection (not security).

**Why cache is keyed by `(session_id, task_id)`:**
- Task switch must reset all cached state. Keying by task_id makes this automatic.
- `session_id` is currently empty but is already available in `_on_pre_llm_call` args. Including it costs nothing and prevents future cross-session bleed.

**Why remove `prefetch()`, `on_turn_start()`, `sync_turn()`:**
- SagTask is a Hermes plugin, not a memory provider. These are MemoryProvider interface methods that Hermes never calls on plugins.
- The only active injection path is `_on_pre_llm_call` registered via `ctx.register_hook()`.
- Keeping dead code creates confusion about which path is actually active.

**Why not skip turns entirely:**
- Injected context is ephemeral. Skipping a turn = LLM has zero task awareness that turn.
- Even L0 alone (1 line, ~50 chars) is negligible cost for guaranteed awareness.
