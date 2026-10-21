# RepoPilot

基于 **LangGraph + MCP** 的本地代码定位、修复与验证系统。输入 Bug 描述，系统在任务副本中检索代码、生成受控修改、运行 Docker 测试，提供 Diff、执行轨迹和人工审批。

这是一个可开发、可测试的 Python 开源项目原型。当前交付不是生产级托管服务；实际验证范围见下文，不宣称未经评测的性能提升。

## 快速开始

本地优化阶段增加两项 P0 能力：生产发布需要对包含目标仓库、基分支/提交、目录映射、标题/正文和文件内容的完整请求单独审批；可选补丁事务可在进程中断后按日志摘要显式恢复，保留候选和模型响应。使用与边界见 [发布与事务优化](docs/optimization-p0-20261019/validation.md)。该阶段尚未更新远端 PR。

本轮完整版本已将 CI 故障输入隔离到固定 fixture，并提供正式流式、usage 和工作区路径范围配置。源码及新 wheel 的发布前验证各为 **167 passed、1 skipped**；Python 3.11/3.13 和 Docker 的实际 GitHub CI 已通过，见 [CI 隔离验收](docs/ci-isolation-stage-20261018/validation.md)。以下各轮数字和“测试未改动”说明是对应历史版本记录；后来 20 项样本引用/UI 输入调整经过单独批准，既有断言保留。

完整差异审查后的本地修复：嵌套构造输入按最外层表达式检查，CLI 在任务副本创建失败时返回非零状态。`app.evaluation.feedback` 是单独的故障注入诊断，固定使用 `preserve` 工作区策略，并在报告中记录有效策略与传入配置；它不作为独立副本策略对比试验。见 [审查后验证](docs/pr5-review-20261018/validation.md)。

此前第四轮版本补充结构化 Docker 失败反馈、重复候选识别、Reviewer 基线回归证据及 Windows 创建失败恢复。本地完整回归 **159 passed、1 skipped**，原有 52 个测试文件未改动。默认继续使用 `preserve`；独立副本保持可选。见 [第四轮验收](docs/iteration4/validation.md) 和 [实现与恢复边界](docs/iteration4/implementation.md)。

上一轮增加可选的独立尝试副本：每轮从原始基线生成完整候选，旧错误测试和补丁保留在原目录；审批同时绑定候选身份与 Diff 摘要。默认沿用原策略，旧任务保持兼容。本地完整回归 **143 passed、1 skipped**，原有测试不改动。见 [本轮阶段验收](docs/iteration3/validation.md) 和 [独立尝试使用说明](docs/iteration3/isolated-attempts.md)。

此前的字面输入契约检查、真实历史仓库试点与 129 项回归记录保留在 [第二轮验收](docs/iteration2/validation.md)；历史仓库复现见 [说明](docs/iteration2/pilots/README.md)。

此前十个隔离合成案例 × 三模式 × 三次重复，初始冻结验收 90/90；补充 `range` 输入契约后，同一批修复 **84/90** 通过。该历史批次有 183 次逻辑请求、250708 Token；失败与补丁均保留，不将合成案例解释为真实项目泛化能力。真实反馈、浏览器视频及历史 99 项回归见 [前轮验收](docs/next-stage/validation.md)。按用户决定，PR #2 保持草稿，本轮未推送、合并或新建远端 PR。

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

默认 `mock` 模式无需 API Key，支持内置的过期 Token、分页偏移和折扣百分比三个示例。它使用显式规则生成补丁，**测试仍由 Docker 真实执行**。不支持或同时涉及多个示例的问题会报错。默认不会执行任意宿主机仓库测试；Docker 不可用时任务停在 `blocked`，CLI 退出码为 2，保留实际补丁和任务 ID：

```powershell
python -m app.cli --resume <task_id>
```

启动演示的两个终端：

```powershell
python -m uvicorn app.api.main:app --host 127.0.0.1 --port 8000 --workers 1
python -m streamlit run frontend/demo.py --server.address 127.0.0.1
```

访问 Streamlit 显示的本地地址，提交描述后点击“刷新执行进度”。可输入旧任务 ID 加载状态。API 文档位于 `http://127.0.0.1:8000/docs`；POST 由本地 CLI/Streamlit 服务端调用，浏览器 Origin 写请求被拒绝，因此 Swagger 的浏览器写入操作可能受限。服务仅用于本地开发，不要开放公网或使用共享可写的任务目录。

也可用 `python scripts/start_demo.py` 同时启动两个进程，Ctrl+C 一起关闭。真实模型演示用 `python scripts/start_demo.py --live`，密钥通过隐藏输入进入 API 子进程，UI 不接收密钥。完整干净环境步骤与发布包说明见 [v0.1.0 发布准备](docs/release-v0.1.0.md)。

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

兼容服务已通过真实 DeepSeek 联网验收：本轮请求与响应模型标识为 `deepseek-v4.1-flash`，基地址为 `https://muyuan.do/v1`。可将上述模型名和基地址改为服务实际提供的值。密钥无需写入文件，PowerShell 可用 `$env:OPENAI_API_KEY = Read-Host 'API key' -MaskInput` 在当前环境临时配置。详见 [真实联网与 PR 验收](docs/live-validation.md)。

可选 LangSmith：显式设置 `LANGSMITH_TRACING=true` 和 `LANGSMITH_API_KEY`。默认关闭，事件与状态始终保存在本地；LangSmith 上传仍未验收。

有限流的服务可设置 `REPOPILOT_MODEL_MIN_INTERVAL=7.5`。同一进程、同一端点的模型实例共享请求间隔；不同进程不会自动协调。

兼容服务在等待完整响应时发生网关超时，可显式设置 REPOPILOT_MODEL_STREAMING=true，由正式 LiveModel 聚合流式结构化输出。默认仍为非流式。REPOPILOT_MODEL_STREAM_USAGE=true 请求流中的 usage；不支持该参数的服务可设为 false，未返回 usage 时仍标记统计不完整。流式传输不能保证消除上游故障；SDK 网络超时约束读写等待，并非整次生成的绝对耗时上限。

默认 REPOPILOT_MODEL_PATH_SCOPE=true，工作流向 Planner、Coder、Reviewer 提供最多 80 个受控工作区相对路径，以及配置的远端子目录映射；清单过长会标明截断。模型仍需自行返回正确的 Edit.path，系统不剥离前缀、不重写补丁，也不放宽精确编辑或原有测试保护。设为 false 可禁用这项附加上下文。

CI 的故障样本固定在 test_fixtures/repair_repository，其字节摘要见 test_fixtures/manifest.json。演示目录被实际修复后，测试仍使用独立缺陷输入。已有测试仅按人工批准调整样本引用及一项 UI 输入，断言和收集规则不变。显式重放内置故障评测时，应同时把 REPOPILOT_REPOSITORY_ROOT 和评测 --repo 指向该 fixture；对已修复的普通仓库仍执行原有失败基线检查，不把已通过样本计为修复成功。


模型限流、超时和临时连接/服务错误会保留为 `retryable`，冷却后由操作者明确重试失败节点；凭据错误、无效请求和预算耗尽直接终止。进程中断后可继续已保存节点；未记录的文件写入会阻止重放并保留现场。详见 [恢复行为与验证范围](docs/iteration2/recovery.md)。

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
demo_repository/   带 Token、分页、折扣三个 Bug 的 FastAPI 示例
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

新增十案例语料推荐使用补充契约版：

```powershell
$env:REPOPILOT_REPOSITORY_ROOT = 'app/evaluation/expanded/repos'
$env:REPOPILOT_MODEL_MIN_INTERVAL = '7.5'
python -m app.evaluation.runner --dataset app/evaluation/expanded/dataset.strict.json --repeats 3 --workers 3
```

上面的命令需要先按“真实模型模式”配置进程凭据和模型。原始十案例冻结版本 `dataset.json` 保留用于复现；较严格的 84/90 来自对已保存补丁的事后 Docker 复验，没有重新调用模型或修改补丁。明细见 [补充契约复验](docs/evaluation/expanded-strict-replay-20261016/report.md)。以下三案例命令和历史数字继续保留。

```powershell
python -m app.evaluation.runner --repeats 3
# Docker 就绪且镜像构建后，验证 Bug 修复前失败、修复后独立验收通过：
$env:REPOPILOT_RUN_DOCKER_TESTS = '1'
python -m pytest tests/e2e -q
```

三种模式使用相同数据、模型配置、上下文预算、测试镜像与重试预算。Single 将定位后的推理与编码合并为一次模型请求，无独立 Planner/Reviewer；Multi 无审核模式保留规划与测试反馈；完整模式增加 Reviewer 反馈。检索器和测试器在三模式中相同。

验收测试保存在 `app/evaluation/acceptance`，不进入修复副本或 Prompt；验收容器只运行评测端注入的测试。数据集包含 Token 状态码、分页偏移和折扣计算三个已知 Bug。先独立运行每个案例的失败基线，确认问题可复现，再执行修复。基线已通过或无法证明缺陷的案例记录为 invalid_case/blocked，不计作修复成功。此数据集适合验证管线，不足以推断系统修复泛化能力。

报告记录任务 ID、模式、耗时、调用、Token、重试、数据集 SHA-256、依赖版本与实际容器镜像 ID。成功率的分母包含已建立失败基线但修复失败的任务，避免只统计成功进入独立验收的样本；已评测数、独立验收数、阻塞数和无效案例数分别展示。无执行证据显示 `null`。完成率指到达可人工审核状态的比例，不等同于修复成功率。Mock 模式的零调用/零 Token 是确定性规则的真实计量，不是模型性能数据。每次完整状态与补丁另存于本机报告目录的 tasks 子目录。

项目按 Phase 1→4 顺序实施，确定性评测的 27 次修复与独立 Docker 验收通过；其 [阶段记录](docs/phases.md) 和 [报告](docs/evaluation/phased-20261016/report.md) 保留用于追溯。新增真实 DeepSeek 验收后，完整回归为 **78 passed、1 skipped**。

真实 LLM 首轮三模式评测 **6/9 成功**，另 3 次因尝试修改已有测试被拒绝。补齐拒绝反馈并改进提示后，复跑 **9/9 通过独立验收**，18 次真实调用、25013 Token；原始失败记录没有删除。另一个针对远端原始基线的真实修复经独立验收后，已由系统创建 [草稿 PR #1](https://github.com/pcwl22/multi-agent/pull/1)，CI 通过。这些小样本数据不能推断泛化能力或模式间性能提升。详见 [完整联网与 PR 验收](docs/live-validation.md)。路由测试替身仍标记为 `evidence=test_double`，不能通过服务层批准操作。LangSmith 上传未验收。

也可分别体验两个新案例：

```powershell
python -m app.cli --repo demo_repository --issue "分页错误：第 2 页每页 2 条，应返回 [3,4]，请修复 pagination 并补充测试"
python -m app.cli --repo demo_repository --issue "折扣计算错误：100 元打 20% discount 后应为 80，请修复并补充测试"
```

## 可选 GitHub Issue 与草稿 PR

配置 `REPOPILOT_GITHUB_REPOSITORY=owner/repository` 和 `GITHUB_TOKEN`（可写 Contents 与 Pull requests）。Issue 读取可使用公开仓库匿名读取；私有仓库需要凭据。界面填写 Issue URL，或使用 CLI：

```powershell
python -m app.cli --repo <本地仓库根目录> --issue-url https://github.com/owner/repository/issues/123
```

创建任务时只提供 `issue_description` 或 `github_issue_url` 之一。只接受匹配配置仓库的 GitHub Issue URL，不访问任意外部网址。任务通过真实测试并获人工批准后，界面另有显式创建草稿 PR 按钮。模块检查每个修改文件与远端默认分支基线一致，再创建新 tree/commit/branch 和草稿 PR；不会直接修改默认分支。重复成功调用返回同一 URL；网络失败后的不确定写入禁止自动重试，需人工检查远端。

本地目标默认对应远端仓库根目录；若目标是子目录，配置 `REPOPILOT_GITHUB_REPOSITORY_SUBDIRECTORY`（例如 `demo_repository`）。可选 `REPOPILOT_GITHUB_BASE_BRANCH` 指定基准分支，缺省使用远端默认分支。映射后的每个文件仍需匹配远端原始内容，路径穿越和不规范路径在请求前拒绝。实际 [PR #1](https://github.com/pcwl22/multi-agent/pull/1) 使用独立验证分支和 `validation_repository` 子目录，验证了真实发布与 CI；标准 Bug 数据集保留在 main。

## 故障排查与边界

- `Docker daemon or sandbox image unavailable`：启动 Docker Desktop，执行 `docker info`，构建 sandbox 镜像后 resume 原任务。不会降级到宿主机测试。
- `Repository is outside configured ...`：修改受控根目录配置并重启 API；不要把任意磁盘根目录设为允许范围。
- `Mock only accepts...`：Mock 只演示内置 Bug；其他任务用 live 模式。
- `Edit precondition...` / 输出解析失败：检查日志与选中上下文；失败任务保留副本，可调整描述后新建任务。
- `Diff has changed`：审批后置校验检测到外部修改。不要直接改运行中的 workspace；创建新任务重新验证。
- SQLite/临时目录权限：设置可写的 `REPOPILOT_DATA_DIR`。测试临时目录默认放在 `.repopilot/test-temp`，规避部分 Windows 系统临时目录 ACL 问题。
- MCP 客户端的工具 deadline 为 15 秒；底层 Git 另有 10 秒超时。线程超时停止等待，不会强杀 Python 线程；文件扫描有数量/大小上限。
- Docker 提供基础隔离，不等于面对内核漏洞的强多租户边界。源码及镜像依赖须符合你的运行策略；可写目录仅为临时测试结果目录。stdout/stderr 使用管道持续排空，各保留前 20000 字节并标记截断，Docker 日志驱动关闭。测试结果目录目前没有独立的宿主磁盘配额，生产版仍需限制结果写入量。
- checkpoint 可恢复已完成节点、人工审批和 Docker 阻塞。新任务可设置 `REPOPILOT_PATCH_TRANSACTIONS=true`：先保存意图、逐文件原子替换，中断后检查并确认日志摘要再恢复；不会重新调用编码模型。默认关闭以保留旧任务的拒绝恢复契约。日志与 checkpoint 仍不是同一存储事务，不保证任意断电、文件系统损坏或恶意本地并发下的恢复。

## 后续规划

PostgreSQL checkpointer、持久任务队列、更多真实 Bug 数据集与更大规模 Live 评测、补丁事务日志、发布前可配置的 lint 检查、结果目录磁盘配额、OS 级文件竞态强化与生产认证。向量数据库不属于当前必需依赖。

参阅 [架构](docs/architecture.md)、[简历草稿](docs/resume.md)、[开发约定](AGENTS.md)。


### 任务资源与时间预算（可选）

设置 `REPOPILOT_TASK_BUDGETS=true` 后，仅新任务启用冻结并持久化的预算；已有任务不受进程默认值变化影响。`REPOPILOT_BUDGET_LIMITS` 为服务端 JSON，默认：总截止时间 900 秒、模型请求 20 次、已观测 Token 200000、Docker 执行 10 次、任务现场文件准入 256 MiB、每个容器结果目录 8 MiB。普通 API 请求不能提高额度。

模型与沙箱执行前先写入独立 SQLite 额度账本，进程退出不会退还占用。存在未完成调用或未知 Token 用量时拒绝自动重放。额度耗尽进入 `budget_exhausted`，保留 Diff、日志和候选，普通恢复接口拒绝继续执行；查看 `GET /api/tasks/{id}/budget` 或 UI 的预算面板。预算账本丢失/变更也拒绝恢复，不自动重建额度。

总截止时间从创建开始，包括排队、冷却和离线等待；完成修复后的人工作出批准/拒绝及已批准发布操作不受此执行预算阻拦。Docker 启动前按剩余时间缩短超时，容器内另有固定 pytest 看门狗，即使宿主执行进程退出也会结束测试。清理容器另最多等待 10 秒。预算模式的 `/results` 使用内核限额 tmpfs，容器不再获得可写宿主结果目录；仅最多 2 MB 的 JUnit 经限长通道读回，缺失/超大报告会停止任务。CPU、内存、进程、网络及只读目录限制继续生效。

Token 是供应商返回用量的累计准入阈值，单次响应的输入开销可能使其越过阈值；它不是计费硬上限。输出请求上限按剩余额度收紧，且预算模式关闭 SDK 隐藏重试。自定义受信模型按一次 `generate` 计一次额度，内部行为由适配器负责。网络超时是传输超时，节点截止时间为协作检查，不保证强制中断任意注入模型或每个持续 SSE 流；Docker 有独立进程超时。任务文件准入在节点边界检查，不能替代整个数据目录、共享 checkpoint/SQLite 或磁盘的硬配额。新增验证均明确区分受控 HTTP/模型替身和真实 Docker，没有新增真实 LLM 调用。
