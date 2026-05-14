# Sparse Context Injection Design Review

**Reviewed document:** `docs/superpowers/specs/2026-05-12-sparse-context-injection-design.md`  
**Review date:** 2026-05-13  
**Review type:** Design review  
**Status:** Redesign requested

## Summary

The original sparse injection design should not be implemented as written. Hermes `pre_llm_call` and `memory.prefetch()` are both called once per turn, not 5-15 times inside the tool-calling loop. Because injected context is appended to the current turn's user message and is not persisted to the session DB, skipping injection across turns would cause SagTask context to disappear from those turns.

The right direction is not an N=4 skip counter. The design should instead inject a small always-on task anchor every turn and selectively add state-aware detail layers.

## Confirmed Hermes Behavior

- `memory.prefetch()` runs once per turn and is cached inside the turn.
- `pre_llm_call` runs once per turn before the tool-calling loop.
- Both inject into the user message, not the system prompt.
- Injected context is ephemeral and not persisted to session storage.
- SagTask currently registers a `pre_llm_call` hook, so `pre_llm_call` is the most important path for task context injection.

## Findings

### High: The N=4 Skip Strategy Solves A Nonexistent Problem

The original design assumes `prefetch()` is called on every LLM request inside a turn. With the confirmed Hermes behavior, an injection counter would count turns, not repeated requests within one turn. The proposed sequence would produce one full injection, then several turns with no SagTask context, then a minimal reminder. That is unsafe because SagTask context is ephemeral.

**Required fix:** Remove the N=4 skip strategy. Do not return empty context for active tasks except when there is no active task or the task state cannot be loaded.

### High: Every Active Task Turn Needs At Least A Minimal Anchor

Since injected context is not persisted, each turn must include enough information for the model to know it is inside an active SagTask. A one-line anchor should always be present.

**Recommended format:**

```text
[SagTask] task=<task_id> status=<status> phase=<phase_id> step=<step_id>
```

### High: Blocking Signals Must Override Compaction

Pending gates and blocking verification states cannot be treated as optional navigation details. If a pending gate exists, or if `verification.must_pass` is true and verification is missing or failed, those signals should be injected every turn until resolved.

**Recommended compact forms:**

```text
- Gate: awaiting approval <gate_id>
- Verify: pending, must pass before advance
- Verify: failed | 3/5 passed, streak -2 | Coverage 72%→
```

### Medium: Cross-Pollination Should Be Split Into Hint And Details

Cross-pollination is the heaviest part of current context injection. It should not be injected in full every turn, but injecting it only once after a step switch is also risky because context is ephemeral.

**Recommended split:**

- **L4a related hint:** lightweight one-line signal when relationships exist.
- **L4b related details:** artifact summaries only when context is likely useful.

Example:

```text
- Related: 2 task(s) available
```

Expanded detail:

```text
[Related]
- related-task: auth_utils.py - shared token validation
- related-task: tests/test_auth.py - reusable edge cases
```

Trigger L4b on step switch, relationship changes, explicit user intent such as "related", "reuse", "参考", "借鉴", or when methodology is brainstorm/debug/design-oriented.

### Medium: Artifacts Need Their Own Lightweight Layer

The design mentions artifact summaries but does not assign them to a layer. Treat current-task artifacts separately from cross-pollination. They are usually one line and useful after advance/resume or after artifact summary changes.

**Suggested layer:** `L1.5 - Recent Output`

```text
- Artifacts: auth.py added token validation; tests updated
```

### Medium: Plan Progress Should Not Expand Only Based On Completion Ratio

Using `completed / total < 0.3` or `> 0.8` as the main expansion trigger is too coarse. A stable early-stage step may not need more plan detail, while a late-stage blocked subtask may need expansion.

**Better triggers for expanded plan detail:**

- plan just created
- progress changed
- active dispatches exist
- failed subtasks exist
- user asks about status, progress, or next work

Stable turns can use compact progress:

```text
- TDD: RED | Plan: 2/8 done, 1 active
```

### Medium: `updated_at` Is Not A Reliable Context Change Signal

Many context-relevant handlers save state without consistently updating `updated_at`, including verification, plan generation, plan updates, dispatch, brainstorm, and debug state transitions. A layered design still needs a reliable way to detect context-relevant changes.

**Recommended fix:** Add `context_revision` to task state and bump it for every mutation that affects injected context:

- `sag_task_advance`
- `sag_task_pause`
- `sag_task_resume`
- `sag_task_verify`
- `sag_task_plan`
- `sag_task_plan_update`
- `sag_task_dispatch`
- `sag_task_approve`
- `sag_task_brainstorm`
- `sag_task_debug`
- `sag_task_relate`

If schema changes are undesirable, compute a context hash from the fields used by context builders.

### Medium: Injection State Should Be Per Session And Task

Any cache of "last injected revision" should be keyed by at least `(session_id, active_task_id)`. A singleton plugin-level value can cause cross-session or cross-task bleed.

**Recommended shape:**

```python
self._last_injected_context_revision_by_session: dict[tuple[str, str], str]
```

## Recommended Layer Model

| Layer | Content | Trigger |
|---|---|---|
| L0 - Anchor | task id, status, phase id, step id | Every active-task turn |
| L1 - Blocking/Nav | phase/step names, pending gates, paused/completed status | State changed; pending gate every turn |
| L1.5 - Recent Output | current task artifacts summary | advance/resume, artifact summary change |
| L2 - Execution | methodology, TDD/debug/brainstorm phase, plan progress, active dispatches | methodology/plan/dispatch state exists |
| L3 - Quality | verification status, compact metrics | verification configured; failed/pending states every turn |
| L4a - Related Hint | related tasks exist | relationships exist |
| L4b - Related Details | cross-pollination artifact summaries | step switch, explicit user intent, design/debug/brainstorm contexts |

## Recommended Decision Rules

```python
layers = [L0]

if first_turn_for_session or task_changed or context_revision_changed:
    layers += [L1]

if pending_gates:
    layers += [L1]  # blocking; every turn

if artifacts_summary_changed or just_advanced_or_resumed:
    layers += [L1_ARTIFACTS]

if methodology != "none" or plan_progress.total > 0:
    layers += [L2_COMPACT]

if active_dispatches > 0 or failed_subtasks > 0 or user_asks_progress:
    layers += [L2_EXPANDED]

if step_has_verification:
    if must_pass and not last_verification:
        layers += [L3_BLOCKING_PENDING]
    elif last_verification.failed:
        layers += [L3_BLOCKING_FAILED]
    elif metrics_changed or user_asks_verify:
        layers += [L3_COMPACT]

if has_cross_pollination:
    layers += [L4A_RELATED_HINT]

if just_entered_step or user_asks_related or methodology in ("brainstorm", "debug"):
    layers += [L4B_RELATED_DETAILS]
```

## Example Outputs

Stable execution:

```text
[SagTask] task=my-task status=active step=add-auth
- TDD: RED | Plan: 2/8 done, 1 active
- Verify: failed | 3/5 passed, streak -2 | Coverage 72%→
- Related: 1 task available
```

Just advanced:

```text
[SagTask] task=my-task status=active step=add-auth
- Phase: Implementation | Step: Add auth module
- Methodology: tdd | Plan: 0/8 done
- Verify: pending, must pass before advance
- Artifacts: previous step added auth schema and token fixtures
[Related]
- related-task: auth_utils.py - shared token validation
```

Pending approval:

```text
[SagTask] task=my-task status=active step=api-design
- Gate: awaiting approval gate-api-contract
- Phase: Design | Step: API contract review
```

## Testing Recommendations

Add tests for:

1. Every active-task turn includes L0 anchor.
2. Pending gates are injected every turn.
3. `verification.must_pass=True` with no verification injects pending verification.
4. Failed verification is injected every turn.
5. Stable plan progress uses compact format.
6. Plan creation or progress change triggers expanded/changed context.
7. Cross-pollination defaults to L4a hint.
8. Step switch triggers L4b related details once.
9. Related-user intent triggers L4b related details.
10. Task switch triggers expanded context even if `updated_at` is identical.
11. `context_revision` changes trigger expanded context.
12. No active task returns empty context.

## Conclusion

The layered approach is the correct direction, but the design should be reframed around per-turn compact context, not sparse skipping. Keep an always-on anchor, elevate blocking information, split cross-pollination into hint/detail layers, add a current-task artifacts layer, and use `context_revision` or a context hash instead of `updated_at`.
