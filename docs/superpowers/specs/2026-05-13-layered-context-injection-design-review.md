# Layered Context Injection Design Review

**Reviewed document:** `docs/superpowers/specs/2026-05-13-layered-context-injection-design.md`  
**Review date:** 2026-05-13  
**Review type:** Design review  
**Status:** Changes requested

## Summary

The layered context injection direction is correct: keep a minimal SagTask anchor every turn and selectively add detail layers based on current task state. The spec also correctly incorporates the confirmed Hermes behavior that `pre_llm_call` runs once per turn and injected context is ephemeral.

The design still needs tightening before implementation. The largest issue is that user-intent detection for L4b is described through `prefetch()`, but the active SagTask injection path is the `pre_llm_call` hook. The spec also needs task-keyed cache state, precise change detection for metrics/artifacts, and clearer handling for heavy cross-pollination details.

## Findings

### High: L4b User Intent Is Wired To `prefetch()`, Not `pre_llm_call`

The spec says `prefetch()` passes `query` to the context builder for intent detection, but SagTask’s active injection path is `_on_pre_llm_call()`, which currently calls `_build_task_context(state, include_methodology=True)` without passing `user_message` or `session_id`. As written, keywords such as `related`, `reuse`, `参考`, and `借鉴` cannot trigger L4b in the real hook path.

**Required fix:** Update the integration section so `_on_pre_llm_call()` passes `user_message` and `session_id` into the layered builder. Tests should exercise `_on_pre_llm_call`, not only direct builder calls.

### High: Cache State Is Not Keyed By Task

The spec proposes singleton instance fields:

```python
self._last_context_hash: str = ""
self._last_artifacts_summary: str = ""
self._last_step_id: str = ""
```

It also says task switch resets cached hash and triggers expansion, but there is no `_last_task_id`. Switching from one task to another with the same `step_id` and similar context hash could skip L1/L4b despite being a new task. SagTask is implemented as a singleton plugin, so cache state should not be global across tasks.

**Required fix:** Include `active_task_id` in cache state. Prefer cache keyed by `(session_id or sender_id, active_task_id)` even if `session_id` is currently empty.

### Medium: L4b Can Still Inject Heavy Cross-Pollination Every Turn

The decision rule includes L4B when `methodology in ("brainstorm", "debug")`. That can make long brainstorm/debug steps inject 10+ lines of related artifact summaries every turn, recreating the original attention-noise problem.

**Recommended fix:** Trigger L4b for brainstorm/debug only on entry, context change, relationship change, or explicit user intent. Keep L4a as the stable per-turn related-context hint.

### Medium: `metrics_changed` And `artifacts_summary_changed` Are Not Defined

The decision rules depend on `metrics_changed` and `artifacts_summary_changed`, but the instance state only tracks `_last_artifacts_summary`; there is no metrics hash, metrics mtime, last-event timestamp, or summary cache. Metrics are stored in `.sag_metrics.jsonl`, outside task state, so `_compute_context_hash()` will not reliably detect pass-rate, coverage, or throughput changes unless `last_verification` also changes.

**Recommended fix:** Define exact change detection:

- `artifacts_summary_changed`: compare per-task cached artifact summary to current `state["artifacts_summary"]`.
- `metrics_changed`: compare a per-task cached metrics summary hash, last metrics event timestamp, or metrics file mtime.

The cache should be task-keyed.

### Medium: `failed_subtasks` Has No Current State Source

L2 expansion depends on `failed_subtasks > 0`, but current `methodology_state.subtask_progress` tracks only `total`, `completed`, and `in_progress`. A subtask can become `failed`, but the layered builder cannot know that from the denormalized progress dict unless it reads the plan file.

**Recommended fix:** Choose one source of truth before implementation:

- Extend `subtask_progress` with `failed`, and update all progress-sync points.
- Or read `.sag_plans/<step_id>.json` in `_build_l2_execution()` when plan details are needed.

Add tests for failed subtask expansion.

### Medium: Removing `_prefetch_lock` Conflicts With New Mutable Injection Cache

The spec removes `_prefetch_lock`, but the design adds mutable injection cache fields. If multiple turns, sessions, or platforms invoke the singleton plugin concurrently, cache updates can race and cause missed expansions or stale change decisions.

**Recommended fix:** Keep a lock around injection cache reads/writes, or make cache updates isolated per call and stored atomically.

### Low: Context Hash Should Be Canonical And Complete

The spec computes the hash with `str(list/dict)` and truncates MD5 to 8 chars. This is probably adequate for rough change detection, but a canonical JSON payload is cleaner and easier to test. The hash should also include fields that affect layer selection, especially relationships or relationship count, because L4a/L4b output depends on relationships.

**Recommended fix:** Use `json.dumps(payload, sort_keys=True, ensure_ascii=False)` before hashing, and include relationship data or a relationship summary in the payload.

## Recommended Changes

- Make `pre_llm_call` the primary integration path in the spec.
- Change `_on_pre_llm_call()` to pass `user_message`, `session_id`, and optionally `sender_id` to the layered builder.
- Replace singleton cache fields with task-keyed or session/task-keyed state.
- Change L4b trigger from “every brainstorm/debug turn” to “entry/change/intent.”
- Precisely define `metrics_changed`, `artifacts_summary_changed`, and `step_just_switched`.
- Decide how failed subtasks are counted before implementation.
- Keep concurrency protection for injection cache.
- Add relationship data to the context hash.

## Suggested Test Additions

Add tests for:

1. `_on_pre_llm_call()` passes user intent and triggers L4b related context.
2. Task switch triggers L1/L4b expansion even if `step_id` or hash-like fields are identical.
3. Stable brainstorm/debug turns do not repeatedly inject L4b details.
4. Metrics changes trigger L3 when state fields do not otherwise change.
5. Artifact summary changes trigger L1.5 for the correct task only.
6. Failed subtasks trigger L2 expanded.
7. Cache state is isolated per task.
8. Relationship changes affect the context hash or related-layer decision.

## Notes

No files were modified as part of the design review itself. At review time, the working tree already had an unrelated untracked review document:

```text
docs/superpowers/specs/2026-05-12-sparse-context-injection-design-review.md
```
