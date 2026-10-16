# RepoPilot 第二轮阶段验收

按用户指定顺序完成契约改进与复测、真实历史仓库试点、异常恢复验证和本地发布候选整理。所有目标代码只在 Docker 中执行；PR #2 继续保持草稿，本轮无远端写入。

实际请求 `https://muyuan.do/v1` 兼容接口，成功响应报告的模型标识均为 `deepseek-v4.1-flash`；
这记录的是服务提供的标识，不独立证明上游权重身份。本轮含诊断迭代共 165 个真实模型任务、
384 次逻辑请求、1026101 个已报告 Token，另有一个任务 usage 未知；各轮成功率分别计算。

## 结果与口径

| 轮次 | 独立验收通过 | 进入人工审批 | 同时满足两项 | 逻辑模型调用 | 已知 Token | usage 缺失任务 |
|---|---:|---:|---:|---:|---:|---:|
| [仅提示与 Reviewer 上下文](prompt-only/report.md) | 84/90 | 85/90 | 82/90 | 204 | 496885 | 1 |
| [含误拦截的检查诊断轮](guard-initial/report.md) | 29/30 | 29/30 | 29/30 | 66 | 160959 | 0 |
| [修正后的最终完整语料](strict-final/report.md) | 28/30 | 28/30 | 28/30 | 71 | 176519 | 0 |
| [最终分页定向重复](pagination-target/report.md) | 9/9 | 9/9 | 9/9 | 28 | 77112 | 0 |
| [真实历史仓库试点](historical-pilots/report.md) | 5/6 | 5/6 | 5/6 | 15 | 114626 | 0 |

失败始终留在分母中；空 usage 表示未知，不是零。调用为逻辑结构化请求，SDK 内部 HTTP 重试不另计。修复源码通过独立验收与整个任务进入人工审批是两个指标，Reviewer 拒绝也会终止任务。

前轮同一批 90 个已保存补丁，在新增 range 契约下事后复验为 84/90。本轮仅提示改进也为 84/90，不能宣称总成功率提高。最终完整语料为十案例、三模式、一次重复，与九次分页定向验证分别报告；样本量和重复次数不同，不能据此证明统计显著性或模式优劣。十案例仍是合成语料，真实试点也只有两个历史 Bug。

## 第一阶段：契约检查与真实复测

根因：Coder 会把需求中的 range 输入转换为 list，再声称覆盖原例；旧 Reviewer 只有 diff 和测试摘要，未独立核对完整相关源码。改进包括角色契约要求、结构化核对证据、Reviewer 源码上下文，以及对明确字面构造表达式的静态覆盖检查。没有读取或泄露独立验收给修复模型。

仅提示轮的六次独立验收未通过：三次分页输入类型遗漏、两次新增错误测试导致终止，一次服务错误（usage 未返回）。另有两次 Reviewer 终止，但其源码已经通过独立验收；原始记录保留这些差异。

静态检查的首轮实际评测发现误拦截：上次尝试已加入正确测试，随后仅修源码却被要求再加测试。该诊断轮完整保留为 29/30。修正后检查同时读取现存测试，并向 Coder 提供现存路径和新增文件上下文；保留失败测试，仅修源码的两次真实 Docker 回归和十项独立验收均通过。

最终完整语料的两次失败分别为：分页模型测试把仍有最后一项的页误判为空页；折扣模型测试擅自要求 int 返回类型。两项任务均在预算内终止，没有删除或修正已保存的测试。随后对完全相同的源码补丁执行独立 Docker 诊断均通过；这些事后诊断不改变评测失败或任务审批状态，见 [源码诊断](failed-source-diagnostics.json)。

| 最终完整语料模式 | 独立验收成功率 | 任务完成率 | 平均调用 | 平均 Token | 自然恢复任务 |
|---|---:|---:|---:|---:|---:|
| single | 100.0% | 100.0% | 1.20 | 2227.6 | 1 |
| multi_no_review | 90.0% | 90.0% | 2.50 | 5696.8 | 2 |
| multi_full | 90.0% | 90.0% | 3.40 | 9727.5 | 2 |

分页定向最终为 **9/9**，其中 9 个任务经真实反馈和有限重试后通过。使用原来的严格验收文件、原始 issue 和源码；没有修改验收或已有模型补丁来获得通过。

静态检查只处理短字面构造表达式和简单变量绑定，不解释目标代码，也不是一般语义证明。清单可被模型遗漏或误判；增加证据和源码上下文也增加 Token 成本，本轮不声称效率优势。

## 第二阶段：真实历史仓库

使用固定上游历史提交，不是人为注入 Bug，也不是宣称当前上游版本仍有问题。参考修复与验收均在受控仓库根目录之外，未发给模型。原始 Python 测试逐字节保留，jsonpointer 新增收集适配器，itsdangerous 使用原始 src 布局及锁定的 freezegun 测试依赖。

| 历史 Bug | 原始测试 | 独立失败基线 | 上游参考修复独立验收 |
|---|---|---|---|
| jsonpointer-large-index | 26 passed / 0 failed | 2 passed / 5 failed | 7 passed |
| itsdangerous-date-overflow | 296 passed / 1 failed | 1 passed / 3 failed | 4 passed |

| 模型修复任务 | 模式 | 原有及新增测试 | 独立验收 | 任务状态 |
|---|---|---|---|---|
| jsonpointer-large-index | single | 26 passed / 0 failed | 7 passed / 0 failed | awaiting_approval |
| itsdangerous-date-overflow | single | 297 passed / 0 failed | 4 passed / 0 failed | awaiting_approval |
| jsonpointer-large-index | multi_no_review | 40 passed / 0 failed | 7 passed / 0 failed | awaiting_approval |
| jsonpointer-large-index | multi_full | 40 passed / 0 failed | 7 passed / 0 failed | awaiting_approval |
| itsdangerous-date-overflow | multi_no_review | 297 passed / 0 failed | 4 passed / 0 failed | awaiting_approval |
| itsdangerous-date-overflow | multi_full | 314 passed / 1 failed | 未进入 | failed |

真实历史试点最终为 **5/6**。itsdangerous 完整模式的新增测试试图用只接受无符号整数的编码函数编码负数，
在进入待修复分支前触发 `struct.error`；之后触及已有测试保护并耗尽预算。原有测试均通过，
但整个任务仍失败。对同一份源码另做独立诊断为 4 passed，不计入上述成功数。

[来源、许可证、固定提交及复现步骤](pilots/README.md)；[逐文件摘要](pilots/provenance.json)；[依赖 wheel 与镜像摘要](pilots/dependency-wheels.json)。任务审计确认所有原有测试未改动。这两个历史修复涉及相关公开 API/模块的契约验证，不代表任意构建系统、依赖动态安装或大仓库泛化能力。

## 第三阶段：异常与进程恢复

已实现暂时模型错误的冷却与明确手动恢复，永久错误和预算耗尽终止；恢复仅重跑失败节点。LangGraph 同步检查点与所有尝试的 diff 一致性检查保护进程恢复。旧历史任务仍可读取，原来 Digest 绑定的人工审批与发布保护保留。

验证分开记录：真实 SDK 配合受控 HTTP 传输覆盖 429/503/401/超时；服务重开、三种模型节点恢复、冷却/预算/API、界面提示与按钮均有测试。实际 os._exit 覆盖已保存补丁和未记录写入窗口，使用明确 Mock 修复规则及真实 Docker。这些受控故障不是实际服务可用率数据，不计入真实模型成功率。

根目录 tests.py 的不可变保护遗漏已修正，并统一到修复、上下文和独立验收路径识别；未修改项目原有 35 个测试文件。完整状态表和未验证边界见 [恢复说明](recovery.md)。

## 第四阶段：审阅与本地候选

最终源码与无系统包继承的干净 wheel 环境均为 **129 passed、1 skipped**，Ruff、pip check 和全量 diff 检查通过。Python 3.13.5；目标测试在 Linux Docker 中执行。跳过项是既有 Windows 链接权限限制；11 条既有 Starlette TestClient 弃用警告保留。隔离父进程及实际恢复子进程确认导入安装包，不从工作区冒充 wheel 验收。

实测 Shell 为当前工具提供的 pwsh 7.6.5；未单独以用户推荐的 7.6.3 复测，未使用 Windows PowerShell 5.1。

[干净安装证据与 wheel SHA-256](clean-install.json)；[功能审阅及限制](local-review.md)。新制品放在 dist/iteration2-final-7abd716，前轮与诊断制品均未覆盖。源码包含本轮原始记录、补丁、依赖准备和复现资料；不含密钥、运行数据库、虚拟环境或目标仓库副本。包摘要通过独立 SHA256SUMS 和 release-artifacts.json 交付，后者不打入自身所校验的源码包。

PR #2 只读核对仍为 OPEN 草稿，head 为 edb60e0a180efeed9a18fb5086cb1daea121ad17。本轮没有推送、合并、新建 PR、tag、release 或 LangSmith 上传。新代码没有远端 CI 覆盖；旧 PR 头部的全绿 CI 不作为本轮代码的验证证据。

## 审计入口

- [汇总及全部失败索引](summary.json)，各轮目录含 JSONL、报告、每个补丁和测试/契约审计。
- [最初预先范围](preregistered-validation.json)与[修正后运行前范围](preregistered-validation-v2.json)；诊断失败未丢弃。
- [跨平台严格语料指纹](portable-strict-corpus.json)。运行报告保存实际原始字节哈希；该文件另列 CRLF→LF 指纹用于平台比较。

仍需改进的重点是模型生成测试的可靠性。当前规则将保存后的测试视为不可变，错误断言会使任务有界失败；本轮明确保留这一限制，不把源码诊断通过等同于可批准或可发布。
