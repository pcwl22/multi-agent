# P0 顺序优化验收（2026-10-19）

本阶段按建议先交付两项 P0：完整发布请求审批，以及补丁事务与崩溃恢复。基线为 PR #5 的 `27d960f301eb363e4649f95aec23fdc57a32b085`，在独立工作区本地分支 `codex/publication-journal` 实现；尚未推送或合并。

## 1. 完整发布请求绑定

生产 TaskService/API 将修复批准与发布批准分开：

1. 现有流程完成 Docker 验证并人工批准当前 diff/候选。
2. `POST /api/tasks/{id}/publication/preview`，JSON `{}` 或指定 `title`、`body`。仅以 GET 读取 GitHub 基线，本地保存规范请求。
3. 人工检查完整请求；`POST /api/tasks/{id}/publication/approve`，提交 `request_digest`。
4. `POST /api/tasks/{id}/pr`，提交原 `diff_digest`、需要时的 `candidate_id`，以及单独批准的 `publication_digest`。

完整规范请求绑定：任务/候选、diff、基线与工作区清单摘要、目标 owner/repository、配置与解析后的基分支、远端父提交和 tree、子目录映射、新分支、标题、正文、draft=true、每个文件的路径/模式/完整内容及原内容摘要。请求不包含凭据。

执行前重新构造并比较请求；仓库、目录、配置、远端默认/基分支提交、代码或正文变化后旧摘要均不能执行。刷新预览清除先前的发布批准。写入中若基线移动，不创建分支或 PR；已生成的孤立 tree/commit 需要人工检查，既有不确定结果不自动重放。

新任务携带 `publication_contract_version=1`，不能退回 diff-only 的低层发布路径。生产 API 对旧任务也要求新的完整请求批准。旧版受信嵌入式适配器与显式注入测试接口保留兼容；它们是操作者代码边界，不应被当成面向不可信调用者的完整审批 API。旧任务若缺少可绑定的 Docker/diff 证据，会被拒绝，不静默升级旧批准。

界面依次展示目标、父提交、PR 正文和完整请求摘要，再提供批准与执行两个按钮。`GET /api/tasks/{id}/publication` 可读取持久请求；UI 缓存不是授权，服务端始终重新验证。

## 2. 可选补丁事务

新任务可以设置：

```powershell
$env:REPOPILOT_PATCH_TRANSACTIONS = "true"
```

默认 false，保留旧任务对未记录写入的拒绝契约；开关只决定新任务是否启用，既有任务保存自己的策略，重启后不会随配置切换。

事务流程：完整校验模型补丁 → 持久化 prepared 意图 → 各文件写临时文件、fsync、原子替换 → written 日志 → LangGraph durable checkpoint → acknowledged。日志在任务目录 `patch-journal/`，不进入目标工作区或模型检索范围。准备阶段预留最终 diff 的存储预算，单日志最多 8 MB。

未 checkpoint 的日志会阻止普通 resume，也不会再次调用编码模型。恢复步骤：

1. `GET /api/tasks/{id}/recovery/patch` 检查候选、文件前后摘要、日志摘要及冲突原因。
2. 人工确认后 `POST /api/tasks/{id}/recovery/patch`，提交 `journal_digest`。
3. 对未写/部分写/已写内容完成同一事务，用缓存响应更新 coder checkpoint，然后正常 resume 进入 Docker 验证。

恢复前重新检查原始基线、候选、既有测试、全部受控工作区文件、计数器和日志摘要。只接受原字节或意图中的目标字节；额外修改会被保留并阻断，不自动覆盖。若 checkpoint 已记录补丁，只对账日志，不重写文件、追加补丁或再调用模型。

恢复 API 和界面不绕过 Docker 测试、现有 diff 审批或独立发布审批。默认模式及所有既有测试契约保留。

## 验证结果

- 全部源码套件：**216 passed、1 skipped、11 warnings，292.21 秒**；Docker 已启用，独立验证副本的 demo 已先修为 401，父子进程加载相同 editable 应用。跳过项为 Windows 符号链接权限条件。
- 新 wheel 安装验证：**41 passed，79.74 秒**，覆盖全部新增用例，包含真实进程硬退出与 Docker；97 个 app 文件逐项匹配源码。没有重跑新 wheel 的完整 217 项，也未重建源码包。
- Ruff、diff whitespace 检查通过；66 个基线测试/辅助文件内容不变，新增 6 个测试/辅助文件、41 个用例。
- 真实硬退出覆盖 preserve/isolated 两种策略，各自在 prepared、临时文件已 fsync、首文件已替换、written、checkpoint 已持久化等边界中断；保留候选身份和单次编码响应，恢复后获得真实 Docker 与 fail-to-pass 回归证据。
- 发布契约测试覆盖目标/正文/内容/候选变化、默认/基线移动、迟到的基线变化、重复执行和重启后配置变化。使用明确标注的 HTTP/元数据替身，没有真实 GitHub 写入。
- 单元恢复测试使用明确标注的非执行 runner 与合成非零用量，验证不重复计数；它们不冒充真实 LLM 或 Docker 观测。真实 Docker 证据来自 E2E 测试。
- 本轮没有真实 LLM 调用、新 GitHub CI、PR 更新或 Release 上传。旧 PR #5 CI 全绿不代表新提交已过远端 CI。

本地 wheel：`E:/multi-agent/.repopilot/optimization-dist/repopilot-0.1.0-py3-none-any.whl`，SHA-256 `761c1ccd2791b695f22620adc775bde0d229ff2c23d8dd4440569077512c0c25`。版本名仍为 0.1.0，按路径与摘要区分旧包。

原工作区伴随证据在 `E:/multi-agent/docs/optimization-p0-20261019/`，JUnit 在 `.repopilot/optimization-{publication,journal,focused,full,wheel}.xml`。首次真实进程子集为 optimization-process.xml；扩展的全部 10 个退出场景已经包含于源码完整套件与新 wheel 验证。

## 边界与后续顺序

日志和 SQLite checkpoint 不共享存储事务；验证的是进程丢失及受控写入错误，不保证任意断电、磁盘损坏、恶意本地竞态或被篡改私有数据库后的自动修复。原型依赖可信操作者及私有任务目录，没有增加生产身份认证。发布使用固定 GitHub API 主机；凭据和账户身份不进入请求摘要。

暂未用新发布流程真实写入 GitHub，未重新运行真实模型，也没有对新提交做独立安全全扫描。上述能力不能从 HTTP 替身或旧报告推断为已验证。

后续按原顺序推进：任务总时限/调用与结果目录预算 → 更多真实历史 Bug 和分类型指标 → 任务进度、候选对比与恢复体验。本阶段未把这三项宣称为完成。
