# 分阶段交付与验收

本记录针对 2026-10-16 的阶段补齐工作。保留已有实现与测试，每一阶段验证通过后才开始下一阶段。

| 阶段 | 交付与验收范围 | 本轮状态 |
|---|---|---|
| Phase 1 | 配置、模型适配、文件工具、Planner/Locator/Coder、真实 Docker MVP | 通过：27 passed，1 skipped；后续 Live 验收已完成 |
| Phase 2 | Supervisor、真实测试反馈与有限重试、Reviewer、SQLite 恢复 | 通过：10 passed，含真实失败→修复与预算终止 |
| Phase 3 | MCP、API/UI、人工审批、执行资源边界、GitHub 发布约束 | 通过：20 passed；后续已实际创建 PR #1 |
| Phase 4 | 多 Bug 数据集、三模式对照、原始记录与报告 | 通过：10 项针对性测试；27/27 真实 Docker 修复与独立验收 |

## 该阶段记录的时间范围

以下 Phase 1–4 明细记录最初的确定性阶段。后续用户提供兼容服务并明确要求真实 LLM 与 PR 验收，已另行完成：[联网与 PR 验收](live-validation.md)。确定性 Mock 数据和真实 LLM 数据分开保留；LangSmith 上传仍未验收。

## Phase 1 记录

修复编辑大小检查的字节/字符不一致：原文件与修改后内容都受 100000 UTF-8 字节预算约束，超限在任何文件写入前拒绝。新增测试覆盖多字节新文件及多文件补丁的预验证，不改动既有测试。

验收：`python -m pytest tests/unit/test_repository.py tests/unit/test_edit_limits.py tests/unit/test_model.py tests/unit/test_settings.py tests/integration/test_mvp.py tests/e2e/test_docker_repair.py::test_real_container_repair_and_holdout -q`（设置 Docker 测试开关）。结果 27 passed、1 skipped；跳过为 Windows 符号链接权限。模型适配合约使用假的 HTTP，Docker 执行及独立验收是真实的。

## Phase 2 记录

空仓库现在由 Locator 返回明确失败，不再依靠 Graph 递归上限结束。新增真实 Docker 用例验证第一次错误补丁的 pytest 失败确实进入第二次 Coder 输入；第二次修复通过，重试计数为 1。另一个永久失败的独立契约测试在两次实际执行后触发重试上限。审批 checkpoint 关闭服务后可重新加载并拒绝任务，不重复生成补丁。

验收：`python -m pytest tests/integration/test_feedback.py tests/integration/test_phase2_termination.py tests/e2e/test_phase2_feedback.py -q`（设置 Docker 开关），10 passed。补丁生成器在这些用例中是明确标注的脚本模型；pytest 及其 stdout/JUnit 来自真实容器。

## Phase 3 记录

新增固定保留字节数的管道输出收集器，持续丢弃超额内容并标记 `output_truncated`，避免宿主临时日志无限增长；容器设置 `--log-driver=none`。真实容器的大输出测试通过。发布服务会释放自有 HTTP 客户端；批准依赖真实 Docker 证据，外部发布调用使用替身验证未批准拒绝、跨重启幂等和不确定写入拒绝重放。

验收：沙箱/输出/GitHub 单元测试，MCP stdio、API、Streamlit 集成测试，UI→Docker 流程，以及 `tests/e2e/test_phase3_boundaries.py`。结果 20 passed；11 条警告为已有 TestClient timeout 参数弃用提示。没有创建真实 GitHub PR。

## Phase 4 记录

数据集从一个案例扩展到三个独立问题，分别修改不同模块。每个案例在修复前先用独立测试建立失败基线；基线已经通过或无法证明缺陷时，不运行修复并记录 invalid_case/blocked。Mock 只提供这三个案例的显式规则，不声称通用推理能力。

| 案例 | 修改模块 | 独立基线：通过 / 失败 / 错误 |
|---|---|---|
| Token 过期状态码 | auth.py | 2 / 1 / 0 |
| 从 1 开始的分页偏移 | pagination.py | 2 / 3 / 0 |
| 折扣百分比换算 | pricing.py | 2 / 2 / 0 |

成功率分母纳入已建立失败基线但修复失败的任务，不因未进入最终验收而将其排除；没有执行证据时保持 null。新增测试覆盖统计分母、未知 usage 与已通过基线的拒绝。修复前基线作为案例建立步骤，其耗时独立记录；任务平均耗时包括修复及修复后验收。

正式命令：`python -m app.evaluation.runner --repeats 3 --output .repopilot/evaluations/phased-20261016`。3 个案例 × 3 个模式 × 3 次重复，共 27 次实际修复及独立验收全部通过。Mock 调用与 Token 都为 0，各模式每次修复平均耗时约 3.26–3.34 秒；本次同时运行了回归测试，不能用这些时间比较模式性能。

27 条原始记录中的 baseline/test/acceptance 使用同一镜像 ID，最大上下文 2177 字符，未超过默认 24000 字符预算。每条记录关联独立 task_id/thread_id，完整状态和补丁保存在本机评测目录的 tasks 子目录。报告同时记录数据集 SHA-256、依赖版本、配置和每次容器镜像 ID。

针对性命令：`python -m pytest tests/unit/test_evaluation.py tests/unit/test_phase4_dataset.py tests/unit/test_evaluation_baseline_gate.py tests/e2e/test_phase4_cases.py -q`，10 passed。一次新测试的 Path 类型断言错误在验收中发现并已修复，没有修改原有测试。

原始记录与报告：[runs.jsonl](evaluation/phased-20261016/runs.jsonl)、[report.json](evaluation/phased-20261016/report.json)、[report.md](evaluation/phased-20261016/report.md)。原先的单案例报告保留用于追溯，不与本轮记录混合。

## 最终回归

设置 `REPOPILOT_RUN_DOCKER_TESTS=1` 后执行 `python -m pytest -q`：**67 passed，1 skipped**。跳过为 Windows 创建符号链接权限限制；11 条警告为 TestClient 参数弃用提示。`python -m ruff check .` 通过。所有原有测试文件均保持不变，新增测试覆盖本轮改动。

四阶段已完成实现与上述本地验收。后续真实 LLM、实际草稿 PR 和 CI 结果见 [新增验收记录](live-validation.md)，更新后的完整回归为 78 passed、1 skipped。没有合并 PR。

之后的 PR #2 审查、十案例评测、真实反馈、本地浏览器验收和发布候选准备，见 [后续五阶段记录](next-stage/validation.md)。新回归为 99 passed、1 skipped；十案例补充契约后 84/90。用户明确选择保留草稿、继续本地验证，本轮未合并、推送或新增远端 PR。
