# 验证记录

验证日期：2026-10-16（Asia/Shanghai）。项目根目录：`E:/multi-agent`。

## 最新：真实 DeepSeek 与 PR

后续五阶段已继续推进，最新记录见 [后续本地验收](next-stage/validation.md)。本地回归 99 passed、1 skipped；十案例冻结评测 90/90，补充遗漏的 range 输入契约后，同一批保存修复为 **84/90**。两轮原始生成记录、事后复验和失败均分开保留。PR #2 依用户选择保持草稿；本轮没有远端写入。以下为此前三案例验收的历史记录。

完整记录见 [联网与实际 PR 验收](live-validation.md)。请求与响应模型标识 `deepseek-v4.1-flash`，兼容服务为用户指定的 `muyuan.do`。首轮真实评测 6/9 成功、3 次被不可变测试门禁拒绝；新增拒绝反馈并改进提示后复跑 9/9 成功，18 次调用、25013 Token。两轮所有原始结果均保留。

真实模型生成的另一个 Token 修复经 5 项回归和 3 项独立验收后，已实际创建 [草稿 PR #1](https://github.com/pcwl22/multi-agent/pull/1)，最新 CI 的 Python 3.11 / 3.13、Docker 及专用契约检查通过。新增文件的导入排序曾导致 lint 失败，格式化后复验并更新同一 PR；没有改变测试断言或应用修复。凭据未写入项目文件，短期凭据进程已关闭。

最新本地全量回归 **78 passed、1 skipped**，Ruff 通过。下面保留前两轮的历史验证范围，历史“未验收”不代表当前状态。LangSmith 上传依然未验收。

## 本轮分阶段补齐

Phase 1→4 顺序的完整说明见 [分阶段记录](phases.md)。本轮完整回归 **67 passed、1 skipped**（Docker 测试开启），Ruff 通过。新增真实失败反馈重试、预算终止、空仓库终止、输出截断和审批后幂等发布门禁验证。所有原有测试保持不变。

三个独立 Bug（Token 状态码、分页偏移、折扣换算）的失败基线已实际建立。3 个案例 × 3 个模式 × 3 次重复，共 **27 次真实容器修复与独立验收通过**。记录使用同一镜像 ID，最大上下文 2177 字符；Mock 模型调用和 Token 均为 0。数据与环境信息见 [本轮 report.json](evaluation/phased-20261016/report.json)、[report.md](evaluation/phased-20261016/report.md) 与 [runs.jsonl](evaluation/phased-20261016/runs.jsonl)。完整本地状态和补丁位于 `.repopilot/evaluations/phased-20261016/tasks`。

本轮变更在本地工作区验证，尚未执行新的远端 CI。下文的 GitHub CI 与单案例数据属于此前提交的验证历史，不代表本轮远端验收。真实 LLM 与实际远端 PR 写入仍未验收。

## 前一轮验证历史

- `python -m pytest -q`（设置 `REPOPILOT_RUN_DOCKER_TESTS=1`）：**49 passed, 1 skipped**。跳过项为本机不允许创建符号链接；对应路径校验代码和其他 Windows 逃逸检查已测试。Streamlit HTTP 桥接测试产生 11 条 Starlette TestClient timeout 参数弃用警告，不影响结果。
- `python -m ruff check .`：通过。
- `python -m build --no-isolation`：生成 Python sdist 与 wheel；评测数据和验收用例进入 wheel。
- Docker Engine **29.7.2** 实际容器执行：基础镜像 `python:3.12.14-slim`；FastAPI 0.136.3、httpx 0.28.1、pytest 8.3.4。
- 单独运行独立验收：Bug 修复前 1 项失败、2 项通过；修复后 3 项全部通过。修复流程中的既有测试和新增回归测试均真实通过，进入人工审批；批准和拒绝路径均有实测。
- Streamlit AppTest → FastAPI TestClient → 真实 Docker Runner → Diff 展示 → 人工拒绝：通过。HTTP 传输由 TestClient 桥接，Docker 执行是真实的。
- MCP Python SDK ClientSession → stdio 子进程 → FastMCP 握手、list_tools、search_code：通过；另有输入/输出 Schema 和路径拒绝测试。
- SQLite 重启恢复、Docker 阻塞后恢复、恢复后再次失败的重试、审核反馈、重试上限、审批摘要篡改与无 Docker 不回退宿主机：通过。
- LangChain ChatOpenAI 使用真实适配器与假的 HTTP 传输进行结构化输出合约测试：通过。不是模型联网验收。
- GitHub Issue 限定仓库读取、草稿 PR REST 合约、未批准拒绝及远端基线不一致时零写入：通过假的 HTTP 传输测试。未实际建 PR。
- [GitHub Actions 运行 38843184866](https://github.com/pcwl22/multi-agent/actions/runs/38843184866)：提交 `5e62365` 的三个作业全部成功，包括 Ubuntu / Python 3.11、3.13 的干净依赖安装和测试，以及标准 Dockerfile 在线构建与真实端到端测试。无需依赖本机已有 Python 包或缓存基础镜像。

## 实际评测

`python -m app.evaluation.runner --repeats 3`，三种模式共 9 次真实 Docker 修复测试和 9 次独立验收，均通过。数据集只有一个过期 Token Bug，模型为 Mock，模型调用与 Token 都为 0。

原始数据见 [runs.jsonl](evaluation/runs.jsonl)，汇总见 [report.json](evaluation/report.json) 与 [report.md](evaluation/report.md)。记录含任务 ID 和独立 thread_id，可在本机 `.repopilot` 查询状态。平均耗时约 3.3–3.4 秒，仅反映本机该样例流程；不能据此宣称模式间性能差异或真实 LLM 修复成功率。

Docker 启动前还运行过三模式评测，三次均如实记录为 blocked，成功率/test pass rate 为 null；原始阻塞报告保留在本机 `.repopilot/evaluations/first-verified-run`，未混入成功评测。

首次标准 Docker 构建因 Docker Hub 网络不可达失败。最终使用本机已有基础镜像和宿主 Python 下载的 Linux wheels，采用 `sandbox/Dockerfile.offline` 成功构建。未修改全局网络代理或 Docker 设置。

## 前一轮当时未验证的范围（历史快照）

- 未配置 OPENAI_API_KEY：真实 LLM 联网修复与 LangSmith 上传未验证。
- GitHub PR 模块通过 HTTP 合约测试，但没有向真实远端创建测试 PR；真实写入仍需维护者明确授权测试任务。
- 本地为 Windows / Python 3.13.5，虚拟环境最初复用了已安装系统依赖；后续在虚拟环境内安装缺失及兼容依赖，未修改全局 Python 包。实际项目依赖闭包（98 项）锁定在 `requirements.lock`，不包含无关全局包。Linux Python 3.11 / 3.13 的干净安装和标准 Docker 构建已通过上述 GitHub Actions 实测。
- 此项目提供单 Bug 的可复现工程样例，后续应增加真实 Bug 数据集及 Live 模型评测，再报告成功率、成本或反馈闭环收益。
