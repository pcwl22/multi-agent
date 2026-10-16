# 验证记录

验证日期：2026-10-16（Asia/Shanghai）。项目根目录：`E:/multi-agent`。

## 已实际通过

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

## 实际评测

`python -m app.evaluation.runner --repeats 3`，三种模式共 9 次真实 Docker 修复测试和 9 次独立验收，均通过。数据集只有一个过期 Token Bug，模型为 Mock，模型调用与 Token 都为 0。

原始数据见 [runs.jsonl](evaluation/runs.jsonl)，汇总见 [report.json](evaluation/report.json) 与 [report.md](evaluation/report.md)。记录含任务 ID 和独立 thread_id，可在本机 `.repopilot` 查询状态。平均耗时约 3.3–3.4 秒，仅反映本机该样例流程；不能据此宣称模式间性能差异或真实 LLM 修复成功率。

Docker 启动前还运行过三模式评测，三次均如实记录为 blocked，成功率/test pass rate 为 null；原始阻塞报告保留在本机 `.repopilot/evaluations/first-verified-run`，未混入成功评测。

首次标准 Docker 构建因 Docker Hub 网络不可达失败。最终使用本机已有基础镜像和宿主 Python 下载的 Linux wheels，采用 `sandbox/Dockerfile.offline` 成功构建。未修改全局网络代理或 Docker 设置。

## 未验证与后续

- 未配置 OPENAI_API_KEY：真实 LLM 联网修复与 LangSmith 上传未验证。
- GitHub PR 模块通过 HTTP 合约测试，但没有向真实远端创建测试 PR；真实写入仍需维护者明确授权测试任务。
- 本地为 Windows / Python 3.13.5，虚拟环境最初复用了已安装系统依赖；后续在虚拟环境内安装缺失及兼容依赖，未修改全局 Python 包。实际项目依赖闭包（98 项）锁定在 `requirements.lock`，不包含无关全局包。Linux Python 3.11 / 3.13 与标准 Docker 构建由 GitHub Actions 验证。
- 此项目提供单 Bug 的可复现工程样例，后续应增加真实 Bug 数据集及 Live 模型评测，再报告成功率、成本或反馈闭环收益。
