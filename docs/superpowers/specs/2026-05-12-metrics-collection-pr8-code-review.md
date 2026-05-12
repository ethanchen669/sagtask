# Metrics Collection PR #8 Code Review

**Reviewed PR:** https://github.com/ethanchen669/sagtask/pull/8  
**Review date:** 2026-05-12  
**Review branch:** `pr-8` / `feature/metrics-collection`  
**Base branch:** `main`  
**Review type:** Code review  
**Status:** Changes requested

## Summary

PR #8 implements metrics collection through `.sag_metrics.jsonl`, a new `sag_task_metrics` tool, handler-level metric emission, context injection, and tests. The implementation addresses several design-review concerns: the handler is registered through `handlers/__init__.py`, metrics are git-ignored for new task repos, `emit_metric()` lives on `SagTaskPlugin`, and malformed JSONL lines are skipped.

Remaining issues are mostly around upgrade behavior and metric semantics. The highest-risk bug is that existing task repos will not receive the new `.gitignore` entry, so `.sag_metrics.jsonl` can still be committed by `git add -A`.

## Findings

### High: Existing Task Repos Can Still Commit `.sag_metrics.jsonl`

The PR adds `.sag_metrics.jsonl` to the gitignore templates for newly created or newly initialized task repos, but existing task repos keep their old `.gitignore`. Once `emit_metric()` writes the file, the next `sag_task_advance` runs `git add -A`, so upgraded long-running tasks can start committing the supposedly local runtime metrics log, including verification commands and pause reasons.

**Evidence:**

- `src/sagtask/plugin.py:305` adds `emit_metric()`.
- `src/sagtask/plugin.py:81` updates the gitignore template for newly initialized repos.
- `src/sagtask/handlers/_lifecycle.py:71` updates the gitignore written on task creation.
- `src/sagtask/handlers/_lifecycle.py:329` runs `git add -A` during advance.

**Required fix:** Add a migration path for existing task repos. For example, ensure `.sag_metrics.jsonl` is present in the task repo `.gitignore` inside `emit_metric()` or before `git add -A`. Add a test for an existing task root whose `.gitignore` lacks the metrics entry.

### Medium: Throughput Total Undercounts Pending Subtasks

`_compute_throughput()` defines `subtasks_total` as the number of subtasks that have at least one `subtask_complete` event. Pending subtasks never emit that event, so a step with five subtasks and three completed can report `3/3 done`, not the expected `3/5 done`. The context summary has the same issue because it also derives the denominator from `len(latest)`.

**Evidence:**

- `src/sagtask/handlers/_metrics.py:109` computes throughput only from `subtask_complete` events.
- `src/sagtask/handlers/_metrics.py:126` returns `subtasks_total` as `len(latest)`.
- `src/sagtask/plugin.py:380` computes context throughput only from `subtask_complete` events.
- `src/sagtask/plugin.py:388` formats the denominator as `len(latest)`.

**Recommended fix:** For current-step scope, use `methodology_state.subtask_progress.total` or read the current plan file so pending and in-progress subtasks are included. For phase/task scope, either aggregate from plan files or rename the field to make clear it is “terminal subtasks observed,” not total subtasks.

### Medium: Coverage Trend Logic Is Duplicated and Inconsistent

`_compute_coverage()` compares the last three coverage values to the preceding three when there are at least six values, but for three to five values it compares the last-three average to the first single value. `_build_metrics_summary()` uses a different algorithm: it compares the last-three average to the first-three average. With longer histories after an improvement plateau, `sag_task_metrics` can report `stable` while context still shows an improving arrow.

**Evidence:**

- `src/sagtask/handlers/_metrics.py:87` uses last-three vs preceding-three for six or more samples.
- `src/sagtask/handlers/_metrics.py:94` uses last-three vs first single value for three to five samples.
- `src/sagtask/plugin.py:370` uses last-three vs first-three for the context summary.

**Recommended fix:** Extract a shared helper for coverage trend calculation and use it in both the metrics handler and context injection. Keep one documented rule, preferably “last three vs preceding three” with a defined fallback for fewer than six samples.

### Low: Final Task Completion Does Not Emit a Step Transition Metric

`_handle_sag_task_advance()` returns immediately when the current step is the last step of the last phase, before the `step_advance` emission block. The event log records intermediate advances but not completion of the final step.

**Evidence:**

- `src/sagtask/handlers/_lifecycle.py:309` enters the final-completion branch.
- `src/sagtask/handlers/_lifecycle.py:352` emits `step_advance` only for non-final transitions.

**Recommended fix:** If `step_advance` is intended to represent every successful advance call, emit before the final return. Otherwise add an explicit `task_complete` or `step_complete` event and include it in the design and tests.

## Tests Run

```bash
python -m pytest tests/test_metrics.py -q
```

Result: 12 passed.

```bash
python -m pytest
```

Result: 219 passed.

```bash
python -m pytest tests/ --cov=src/sagtask --cov-report=term-missing -v
```

Result: 219 passed. Total coverage: 84.69%, above the configured 80% threshold.

## Notes For Fix Agent

- Keep `.sag_metrics.jsonl` local runtime state. The main missing piece is migration for old task repos, not the new-task template.
- Add targeted tests for the existing-task `.gitignore` migration and throughput denominator behavior.
- Prefer one shared coverage trend helper to avoid future divergence between tool output and context injection.
- If adding a final-completion event, update both the spec and the query/context tests.
