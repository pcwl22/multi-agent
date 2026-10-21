# 真实 LLM 联网与实际 PR 验收

日期：2026-10-16（Asia/Shanghai）。本记录全部基于实际网络调用与 Docker 执行；没有使用 Mock 替代模型结果。

## 模型与凭据

通过用户提供的兼容端点 `https://muyuan.do/v1` 查询模型目录，选择实际返回的 `deepseek-v4.1-flash`。复跑的模型响应标识也为 `deepseek-v4.1-flash`；原始记录保留请求标识、响应标识与 provider response ID。这里报告的是该兼容服务返回的模型标识。

凭据通过隐藏标准输入进入短期进程，仅保存在进程内存中。没有写入 `.env`、源码、报告或 Git 提交；验收后进程已关闭。GitHub 使用本机已登录账号的凭据，同样不落盘到项目文件。LangSmith 上传未开启，也未验收。

## 实际模型修复 PR

[PR #1：demo: DeepSeek repairs expired-token HTTP status](https://github.com/pcwl22/multi-agent/pull/1)

- 从远端 main 读取原始示例，按字节确认基线，执行 Planner→Locator→Coder→Docker Test→LLM Reviewer。
- 模型调用 3 次；服务报告输入 3250、输出 999 Token；一次补丁即通过。
- 模型只将过期 Token 的状态码 500 改为 401，并新增 `test_profile_expired_token.py`，覆盖过期、有效和缺失 Token。既有测试保持原样。
- 工作副本 pytest：5 passed。未提供给模型的独立验收：修复前 1 failed / 2 passed，修复后 3 passed。
- 发布经用户在聊天中明确授权。服务审批绑定 Diff 摘要，重新校验文件内容及远端基线，通过真实 GitHub tree/commit/ref/PR API 创建草稿。
- PR 目标为独立验证分支 `validation/expired-token-e4536db1`，文件位于 `validation_repository`，保留 main 中标准 Bug 数据集以供后续重复评测。该分支由 main 派生，额外建立原始 Bug 副本和针对该 PR 的 Docker 契约检查。
- 首次 PR CI 发现模型新增测试的导入排序不符合 Ruff。后续仅对新文件执行导入格式化，没有改动断言、原有测试或业务修复；再次执行 5 项回归和 3 项独立验收通过。最新 PR CI 的 Python 3.11、3.13、Docker 端到端和专用契约检查均通过。
- PR 保持 draft，未合并。

初始模型 Diff SHA-256：`fd787b6de49e1f1ea2baa4bf9640f7a6fce0cf7d980b75e7d4a6bed93124601e`。

导入格式化后的最终 Diff SHA-256：`63eec098495696bdb1e8479315e021e7dfeaf8ec31c6c7a88eac79252d102439`。

证据：[发布记录](live-validation/publication.json)、[独立验收](live-validation/independent.json)、[脱敏批准轨迹](live-validation/approved-trace.json)、[原始模型补丁](live-validation/repair.patch)、[最终补丁](live-validation/final-repair.patch)、[格式化后复验](live-validation/format-followup.json)。原始任务轨迹对应首次发布内容，最终补丁的格式化提交和新摘要另行记录，没有覆盖原始证据。

## 三模式真实评测

同一模型、温度 0、3 个 Bug、每模式每 Bug 1 次。测试采用相同 Docker 镜像，上下文预算 24000 字符，共享最多 2 次修复重试。所有案例都先用独立测试证明确实存在 Bug。

| 模式 | 首轮成功 / 总数 | 修正后复跑成功 / 总数 | 复跑平均调用 | 复跑平均 Token | 复跑平均秒数 |
|---|---:|---:|---:|---:|---:|
| Single | 1 / 3 | 3 / 3 | 1 | 1545 | 11.21 |
| Multi，无 Reviewer | 2 / 3 | 3 / 3 | 2 | 2552.33 | 15.15 |
| Multi，完整反馈 | 3 / 3 | 3 / 3 | 3 | 4240.33 | 18.54 |

首轮共 6/9 成功，另外 3 次因模型尝试修改既有测试被工具拒绝，失败保留在成功率分母中。真实运行由此暴露出原先补丁校验拒绝后直接终止的问题。现在拒绝原因会反馈给 Coder，校验拒绝、pytest 失败与 Reviewer 拒绝共用有限重试预算；非法补丁不落盘、不执行其测试。

复跑共 9/9 成功，18 次模型调用，服务报告共 25013 Token。复跑未触发补丁重试，因此不能声称该次运行已自然验证拒绝后恢复；该边界由新增的确定性集成测试覆盖。两轮提示词和实现存在变化，且模型有随机性、每格只有一个样本，不能据此建立因果结论或宣称 Multi-Agent 的成功率提升。

原始资料均保留：

- 首轮：[report.json](evaluation/live-deepseek-initial-20261016/report.json)、[runs.jsonl](evaluation/live-deepseek-initial-20261016/runs.jsonl)。
- 复跑：[report.json](evaluation/live-deepseek-feedback-20261016/report.json)、[runs.jsonl](evaluation/live-deepseek-feedback-20261016/runs.jsonl)。

每次完整任务状态和补丁另存本机 `.repopilot/evaluations/live-deepseek*/tasks`。Token 取自兼容服务的 usage，缺失时保持未知；没有用字符数估算。

## 接入中修复的问题

1. Settings 的环境变量别名曾导致程序按字段名传入的 SecretStr 被忽略。已允许字段名赋值，并保留 `.env` / 环境变量别名，新增回归测试。
2. 真实 Planner 常返回自然语言检索策略。Locator 现在提取有界关键词，并优先检索结构化 suspected_modules，避免全靠小仓库回退。
3. 补丁预校验失败现在反馈给 Coder，而非直接终止；既有测试不可变约束未放宽。
4. GitHub 发布支持受校验的仓库子目录映射和指定基准分支，继续对映射后的每个文件做远端内容一致性检查。
5. 模型事件增加请求/响应模型标识与 provider response ID，方便核查真实调用来源。

本地全量回归：设置 Docker 开关后 **78 passed，1 skipped**；Ruff 通过。跳过仍为 Windows 符号链接权限。所有此前已有测试未修改。

工程 PR 的首次 Linux CI 还发现测试夹具的权限差异：pytest 临时目录默认 `0700`，直接挂载后容器的 uid 65534 无法读取。已在 Linux 容器复现，并仅为端到端测试的新建临时目录补充 `0755` 权限；既有测试断言、生产仓库权限和非 root / 只读沙箱约束不变。

## 重现命令

PowerShell 7，API Key 在输入时隐藏且只进入当前进程环境；不要把真实值写入命令历史：

```powershell
$env:OPENAI_API_KEY = Read-Host 'Provider API key' -MaskInput
$env:REPOPILOT_MODEL_MODE = 'live'
$env:REPOPILOT_MODEL_BASE_URL = 'https://muyuan.do/v1'
$env:REPOPILOT_MODEL_NAME = 'deepseek-v4.1-flash'
$env:REPOPILOT_MODEL_TIMEOUT = '120'
python -m app.evaluation.runner --repeats 1
Remove-Item Env:OPENAI_API_KEY
```

模型目录可能变化，请使用服务实际提供的标识。GitHub 发布还需配置固定仓库、可选子目录和基准分支，在任务通过测试并获批准后单独调用 PR 接口；不会自动合并。
