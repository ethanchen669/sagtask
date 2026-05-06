# SagTask 项目 Review

## 项目概述

SagTask 是一个 Hermes Agent 的 standalone 用户插件，用于管理多阶段、跨会话的长期任务，每个任务有独立的 Git 仓库和人工审批门控。

---

## 一、关键不足

### 1. 单文件巨型模块 (1,450 行)

所有 schema 定义、插件类、11 个 tool handler、hook 回调全部放在 `__init__.py` 一个文件里。违反了高内聚低耦合原则，可读性和可维护性差。

**建议：**

```
src/sagtask/
├── __init__.py          (register 入口, 50行)
├── plugin.py            (SagTaskPlugin 类)
├── schemas.py           (ALL_TOOL_SCHEMAS)
├── handlers/
│   ├── lifecycle.py     (create, pause, resume, advance, approve)
│   ├── git_ops.py       (commit, branch, git_log)
│   └── discovery.py     (list, status, relate)
└── utils.py             (artifact scanning, state helpers)
```

### 2. 零测试覆盖

没有任何测试文件、pytest 配置或 CI 流水线。对于一个管理用户长期数据（Git 仓库 + 状态文件）的插件来说，这是严重风险。

**建议：**

- 添加 `tests/` 目录，至少覆盖核心路径：create → advance → complete、pause → resume、approve gate
- 使用 `tmp_path` fixture 隔离文件系统操作
- 添加 GitHub Actions CI

### 3. 硬编码 GitHub 用户名

`ensure_git_repo` 中硬编码了 `git@github.com:charlenchen/{task_id}.git`，`create_github_repo` 中硬编码了 `charlenchen/`。任何其他用户无法使用此插件。

**建议：** 从配置文件或环境变量读取 GitHub org/user：

```python
github_owner = os.environ.get("SAGTASK_GITHUB_OWNER", "charlenchen")
```

### 4. subprocess 调用无超时保护

多处 `subprocess.run()` 没有 `timeout` 参数。如果 Git 操作卡住（网络问题、SSH prompt 等），整个插件会无限阻塞。

**建议：** 所有 subprocess 调用加 `timeout=30`（或可配置），并在超时时返回有意义的错误。

### 5. 异常处理过于宽泛

多处 `except Exception: pass`（如 `_handle_sag_task_advance` 第 1068-1071 行、`_scan_git_artifacts` 第 689/714/740 行），静默吞掉了所有错误，使调试极其困难。

**建议：** 最少记录 `logger.warning`，并区分可预期的失败（如 "nothing to commit"）和真正的错误。

### 6. 线程安全隐患

`_sagtask_instance` 是全局可变单例，`_active_task_id` 可被多线程并发修改。`_prefetch_lock` 只保护了 `_prefetch_result`，但 `load_task_state` / `save_task_state` 之间存在 TOCTOU 竞态（读-改-写非原子）。

**建议：** 如果目标是单线程使用，明确文档说明。如果需要并发安全，对 state 文件操作加文件锁（`fcntl.flock` 或 `filelock` 库）。

### 7. `_get_current_step` 有未定义变量引用

第 643 行 `return current_step_id or "—"` — 如果 phases 为空或 `current_phase_id` 不匹配任何 phase，在 `@staticmethod` 中变量 `current_step_id` 只在 `for` 循环内赋值，可能引发 `UnboundLocalError`。

**建议：** 在方法开头提取 `current_step_id = state.get("current_step_id", "")`，确保变量始终有定义。

### 8. 缺少输入验证

- `sag_task_id` 没有格式校验（schema 说 "alphanumeric + hyphens"，但代码不验证）
- 路径注入风险：恶意 `task_id` 如 `../../etc` 可能写入非预期位置

**建议：**

```python
import re
if not re.match(r'^[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}$', task_id):
    return {"ok": False, "error": "Invalid task_id format"}
```

### 9. 状态模型未版本化

`task_state.json` 没有 schema 版本号。后续字段变更时，旧状态文件无法兼容迁移。

**建议：** 添加 `"schema_version": 1` 字段，并在 `load_task_state` 中做版本检查/迁移。

### 10. `git add -A` 过于激进

`_handle_sag_task_commit` 和 `_handle_sag_task_advance` 都使用 `git add -A`，会将 task 目录下所有文件（包括可能意外出现的大文件、敏感文件）全部纳入 Git。

**建议：** 至少在 commit 前检查是否有异常大文件或敏感文件模式（`.env`, `credentials.*`），或使用 `git add .` 配合更严格的 `.gitignore`。

---

## 二、次要问题

| 问题 | 位置 | 建议 |
|------|------|------|
| `datetime.utcnow()` 已废弃 (Python 3.12+) | 全文 | 改用 `datetime.now(timezone.utc)` |
| 重复的 handler map | L517 和 L1309 | 保留一份，另一份引用 |
| `register()` 注释说 "11 task_* tools" 但已重命名为 sag_task_* | L1422 | 更新注释 |
| `_on_pre_llm_call` 重复了 `on_turn_start` 的逻辑 | L1328 vs L541 | 抽取共享方法 |
| `plugin.yaml` version 1.2.0 但无 CHANGELOG | - | 添加版本历史 |
| `MAX_CROSS_POLLINATION` 作为模块级常量而非类常量 | L821 | 移入类中保持一致 |

---

## 三、架构建议

1. **添加配置层** — 将 GitHub owner、projects_root、max_cross_pollination 等抽取到 `~/.hermes/sagtask.yaml` 配置文件
2. **事件/通知机制** — gate 等待审批时，缺少通知用户的手段（可考虑 webhook 或命令行提示）
3. **状态清理策略** — 已完成任务的 `.sag_executions/` 目录会无限增长，需要归档/清理机制
4. **文档改进** — README 应包含 API reference（每个 tool 的输入输出示例）、troubleshooting 指南

---

## 四、优先级排序

| 优先级 | 项目 | 原因 |
|--------|------|------|
| P0 (立即) | 输入验证 + 路径注入防护 | 安全漏洞 |
| P0 (立即) | 硬编码 GitHub 用户名 | 阻止其他用户使用 |
| P1 (短期) | 添加测试 + CI | 无测试 = 无法安全重构 |
| P1 (短期) | subprocess timeout | 生产稳定性 |
| P1 (短期) | 异常处理改进 | 可观测性 |
| P2 (中期) | 模块拆分 | 可维护性 |
| P2 (中期) | 状态 schema 版本化 | 向前兼容 |
| P3 (长期) | 配置层 + 通知机制 | 用户体验 |
| P3 (长期) | 状态清理策略 | 长期运行稳定性 |

---

## 总结

SagTask 的核心设计理念（per-task Git + approval gates + cross-session recovery）是扎实的。主要短板在工程质量层面：单文件架构不可持续、零测试覆盖、硬编码配置、异常处理粗糙、输入未校验。优先修复安全相关问题（路径注入、硬编码凭据）和添加测试，其余可迭代改进。
