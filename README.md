# RepoPilot

基于 **LangGraph + MCP** 的本地代码定位、修复与验证系统。输入 Bug 描述，系统在任务副本中检索代码、生成受控修改、运行 Docker 测试，提供 Diff、执行轨迹和人工审批。

这是一个可开发、可测试的 Python 开源项目原型。当前交付不是生产级托管服务；实际验证范围见下文，不宣称未经评测的性能提升。

## 快速开始

要求 Python 3.11+、Git、Docker Desktop/Linux Docker。Windows 使用 PowerShell 7。以下命令从项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m pytest -q
python -m ruff check .
```

Linux/macOS 使用 `source .venv/bin/activate`；其余 Python 和 Docker 命令相同。依赖范围在 `pyproject.toml`，本次实际验证版本在 `docs/verified-environment.txt`。干净环境可使用 `requirements.lock` 固定 Python 依赖版本。

启动 Docker 引擎并构建测试镜像（**构建阶段**需要网络下载依赖；**测试阶段**禁用网络）：

```powershell
docker build -t repopilot-sandbox:local -f sandbox/Dockerfile .
python -m app.cli --repo demo_repository --issue "Token 过期时返回 500，预期返回 401，请补充测试"
```

如果 Docker Hub 不可达，但本机已有 `python:3.12.14-slim` 镜像，可以执行 `pwsh -File scripts/prepare-offline-sandbox.ps1`，由宿主 Python 下载 Linux wheels 后离线构建。wheels 不进入 Git；测试时仍禁用网络。本次实机使用这条路径验证。

默认 `mock` 模式无需 API Key，只支持内置的过期 Token 示例。它使用显式规则生成补丁，**测试仍由 Docker 真实执行**。不支持的问题会报错。默认不会执行任意宿主机仓库测试；Docker 不可用时任务停在 `blocked`，CLI 退出码为 2，保留实际补丁和任务 ID：

```powershell
python -m app.cli --resume <task_id>
```

启动演示的两个终端：

```powershell
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --workers 1
python -m streamlit run frontend/demo.py --server.address 127.0.0.1
```

访问 Streamlit 显示的本地地址，提交描述后点击“刷新执行进度”。可输入旧任务 ID 加载状态。API 文档位于 `http://127.0.0.1:8000/docs`；POST 由本地 CLI/Streamlit 服务端调用，浏览器 Origin 写请求被拒绝，因此 Swagger 的浏览器写入操作可能受限。服务仅用于本地开发，不要开放公网或使用共享可写的任务目录。

## 真实模型模式

在 `.env` 或进程环境配置：

```dotenv
REPOPILOT_MODEL_MODE=live
REPOPILOT_MODEL_NAME=gpt-4.1-mini
OPENAI_API_KEY=your-key
# 可选兼容服务地址，需支持 LangChain function_calling 结构化输出
# REPOPILOT_MODEL_BASE_URL=https://your-provider.example/v1
```

使用相同 CLI/API 即可。模型通过实际 `ChatOpenAI.with_structured_output` 输出 Pydantic 计划、补丁和审核，单次模型超时、传输重试和输出解析重试均有上限。调用次数统计结构化模型请求；SDK 内部 HTTP 重试不单独算一次模型调用。Token 来自响应 `usage_metadata`；缺失时标记不完整，评测不将缺失量当成零。真实模型会接收选中的仓库源码，请自行选择允许发送的受控仓库。

可选 LangSmith：显式设置 `LANGSMITH_TRACING=true` 和 `LANGSMITH_API_KEY`。默认关闭，事件与状态始终保存在本地。模型联网和 LangSmith 上传未在本机进行实测。

## 已实现

| 能力 | 实现方式 |
|---|---|
| Multi-Agent | StateGraph Supervisor、Planner、Locator、Coder、Test、Reviewer、Human |
| 确定性控制 | 测试/审核失败共享有限重试预算；阻塞、失败、拒绝和批准有终态 |
| 状态持久化 | 官方 SqliteSaver；独立 task_id/thread_id；节点 checkpoint |
| 代码工具 | 文件列表、字面搜索、AST 符号定位、限额读取、依赖检查、受控替换 |
| 变更 | baseline/workspace 双副本；唯一前置文本匹配；先验证全部编辑再写入；统一 Diff |
| Docker 测试 | 命令白名单、禁网络、非 root、只读源码、资源限制、超时清理、JUnit 解析 |
| MCP | 六个只读 stdio 工具，自动输入/输出 Schema，路径检查、超时和日志 |
| API / UI | 七个要求的 API 接口；Streamlit 进度、日志、Diff、测试、计量与审批 |
| 人工审批 | LangGraph interrupt/Command；批准绑定当前 Diff SHA-256；拒绝不提交 |
| 评测 | Single、无 Reviewer 的 Multi、完整 Multi；独立验收；JSONL/JSON/Markdown 报告 |
| GitHub 扩展 | 固定仓库 Issue 导入；人工批准后单独确认创建草稿 PR；远端基线检查与幂等记录 |

审批记录对任务副本的决定，不修改原始仓库。审核通过的补丁可下载，由维护者审查后应用。可选 GitHub 功能默认关闭：配置固定目标仓库和凭据后，用户还须单独点击“创建草稿 PR”；普通批准操作不会自动发布。

## 目录

```text
app/
  agents/          Mock / LangChain 实际模型适配
  api/             FastAPI 本地接口
  config/          Pydantic Settings
  evaluation/      数据集、独立验收、报告
  graph/           LangGraph 节点、路由、中断
  mcp_server/      只读 MCP 传输层
  models/          Pydantic Schema / AgentState
  sandbox/         Docker Runner / JUnit
  services/        任务副本、SQLite registry、恢复与审批
  tools/           与 MCP 解耦的内部工具
frontend/          Streamlit
demo_repository/   带 Token 过期 Bug 的 FastAPI 示例
sandbox/           测试镜像 Dockerfile
tests/             单元、集成、Docker E2E
docs/              架构、验证记录、简历草稿
```

## 使用其他仓库

配置 `REPOPILOT_REPOSITORY_ROOT` 为明确的受控仓库父目录，选择其下的目标目录；`REPOPILOT_DATA_DIR` 必须位于目标仓库之外。当前快照仅复制允许后缀的文本文件，单文件最大 100 KB、最多扫描 10000 文件、总快照最多 20 MB。二进制、Git 元数据、虚拟环境与敏感目录不复制。当前修复仅支持 Python 源码和新增 Python 测试；既有测试和 conftest 不允许修改。

自定义镜像需由维护者预先构建并配置 `REPOPILOT_SANDBOX_IMAGE`；系统不会运行仓库的安装脚本，也不会联网安装模型推荐的依赖。测试入口固定为 `python -m pytest tests -q`。需要数据库、可写源码、复杂构建流程或二进制资源的仓库暂不支持。

## API

| 方法 | 路径 | 行为 |
|---|---|---|
| POST | `/api/tasks` | 创建独立副本并后台执行；返回 202 |
| GET | `/api/tasks/{id}` | 获取含日志、计量、测试结果的状态 |
| GET | `/api/tasks/{id}/events` | 运行事件与检索记录（轮询接口） |
| GET | `/api/tasks/{id}/diff` | 当前统一 Diff、摘要和一致性检查 |
| POST | `/api/tasks/{id}/approve` | 提交 `{"diff_digest":"..."}` 批准当前变更 |
| POST | `/api/tasks/{id}/reject` | 同上，拒绝当前变更 |
| POST | `/api/tasks/{id}/resume` | 继续 queued/running/blocked；中断点使用审批接口 |
| POST | `/api/tasks/{id}/pr` | 批准后显式请求草稿 PR，同样要求当前 Diff 摘要 |

每任务通过文件锁防止并发修改。错误返回 400/404/409；自动失败保留在状态和事件中。后台调度采用本地 FastAPI BackgroundTasks，不是分布式队列。进程重启后手动 resume，不自动扫描重启任务。

## MCP

```powershell
python -m app.mcp_server.server
```

客户端配置示例（修改路径为自己的安装位置）：

```json
{
  "mcpServers": {
    "repopilot": {
      "command": "E:/multi-agent/.venv/Scripts/python.exe",
      "args": ["-m", "app.mcp_server.server"],
      "cwd": "E:/multi-agent",
      "env": {"REPOPILOT_REPOSITORY_ROOT": "E:/multi-agent/demo_repository"}
    }
  }
}
```

工具：`list_files`、`search_code`、`read_file`、`find_symbol`、`inspect_dependencies`、`git_diff`。内部 Graph 直接复用同一工具实现，不依赖 MCP 传输才能运行。Git 工具仅处理带本地 `.git` 目录的仓库，不支持 Git linked worktree；输出 tracked diff。任务副本的完整新增文件 diff 由独立 baseline 比较提供。

## 评测与验证

```powershell
python -m app.evaluation.runner --repeats 3
# Docker 就绪且镜像构建后，验证 Bug 修复前失败、修复后独立验收通过：
$env:REPOPILOT_RUN_DOCKER_TESTS = '1'
python -m pytest tests/e2e -q
```

三种模式使用相同数据、模型配置、上下文预算、测试镜像与重试预算。Single 将定位后的推理与编码合并为一次模型请求，无独立 Planner/Reviewer；Multi 无审核模式保留规划与测试反馈；完整模式增加 Reviewer 反馈。检索器和测试器在三模式中相同。

验收测试保存在 `app/evaluation/acceptance`，不进入修复副本或 Prompt；验收容器只运行评测端注入的测试。当前数据集只有一个已知 Bug，适合验证管线，不足以推断系统修复泛化能力。

报告记录任务 ID、模式、耗时、调用、Token、重试及实际容器结果。成功率以已实际执行的独立验收为分母，同时单独报告已评测数和阻塞数；无测试证据显示 `null`。完成率指到达可人工审核状态的比例，不等同于修复成功率。Mock 模式的零调用/零 Token 是确定性规则的真实计量，不是模型性能数据。

本次已通过真实 Docker 修复前/后验收、Streamlit→API→Docker→人工拒绝链路，以及 MCP stdio 握手和工具调用。三种模式各执行 3 次确定性修复与独立验收，9 次均通过；这是一个样例的流程验证，不能推断 LLM 能力或 Multi-Agent 性能提升。详见 [验证记录](docs/validation.md) 和 [原始评测报告](docs/evaluation/report.md)。路由测试的替身明确标记 `evidence=test_double`，不能通过服务层批准操作。未配置真实模型 Key，因此 LLM 联网、LangSmith 上传和 GitHub 实际建 PR 尚未验证。

## 可选 GitHub Issue 与草稿 PR

配置 `REPOPILOT_GITHUB_REPOSITORY=owner/repository` 和 `GITHUB_TOKEN`（可写 Contents 与 Pull requests）。Issue 读取可使用公开仓库匿名读取；私有仓库需要凭据。界面填写 Issue URL，或使用 CLI：

```powershell
python -m app.cli --repo <本地仓库根目录> --issue-url https://github.com/owner/repository/issues/123
```

创建任务时只提供 `issue_description` 或 `github_issue_url` 之一。只接受匹配配置仓库的 GitHub Issue URL，不访问任意外部网址。任务通过真实测试并获人工批准后，界面另有显式创建草稿 PR 按钮。模块检查每个修改文件与远端默认分支基线一致，再创建新 tree/commit/branch 和草稿 PR；不会直接修改默认分支。重复成功调用返回同一 URL；网络失败后的不确定写入禁止自动重试，需人工检查远端。

本地目标必须对应远端仓库根目录。内置 `demo_repository` 是本项目的子目录，不能直接以它为基线向本项目根目录发 PR，远端一致性检查会拒绝。当前 GitHub 模块通过 HTTP 合约测试，未对真实仓库创建测试 PR。

## 故障排查与边界

- `Docker daemon or sandbox image unavailable`：启动 Docker Desktop，执行 `docker info`，构建 sandbox 镜像后 resume 原任务。不会降级到宿主机测试。
- `Repository is outside configured ...`：修改受控根目录配置并重启 API；不要把任意磁盘根目录设为允许范围。
- `Mock only accepts...`：Mock 只演示内置 Bug；其他任务用 live 模式。
- `Edit precondition...` / 输出解析失败：检查日志与选中上下文；失败任务保留副本，可调整描述后新建任务。
- `Diff has changed`：审批后置校验检测到外部修改。不要直接改运行中的 workspace；创建新任务重新验证。
- SQLite/临时目录权限：设置可写的 `REPOPILOT_DATA_DIR`。测试临时目录默认放在 `.repopilot/test-temp`，规避部分 Windows 系统临时目录 ACL 问题。
- MCP 客户端的工具 deadline 为 15 秒；底层 Git 另有 10 秒超时。线程超时停止等待，不会强杀 Python 线程；文件扫描有数量/大小上限。
- Docker 提供基础隔离，不等于面对内核漏洞的强多租户边界。源码及镜像依赖须符合你的运行策略；可写目录仅为临时测试结果目录。日志采用文件缓冲和返回截断；恶意大输出仍可能耗用磁盘，生产版需增加输出配额。
- checkpoint 可恢复已完成节点、人工审批和 Docker 阻塞；文件编辑与 checkpoint 不是跨文件原子事务。编辑中途被强制杀进程可能需要新建任务，不承诺 exactly-once 文件写入。

## 后续规划

PostgreSQL checkpointer、持久任务队列、更多真实 Bug 数据集、补丁事务日志、输出配额、OS 级文件竞态强化与生产认证。GitHub 扩展的真实外部写入验收仍需在明确授权的测试仓库进行。向量数据库不属于当前必需依赖。

参阅 [架构](docs/architecture.md)、[简历草稿](docs/resume.md)、[开发约定](AGENTS.md)。
