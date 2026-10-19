# 真实历史 Bug 评测方法（2026-10-19）

本阶段扩展为 4 个公开 Python 项目的历史缺陷。正式矩阵为 4 案例 × 3 模式 × 2 重复，共 24 次；不以成功进入验收的任务作为分母。冻结配置见 [preregistration.json](preregistration.json)，最终数值见 [report.md](report.md)。这项评测不批准补丁、不调用产品发布接口，也不写入 GitHub。

## 样本与隔离

登记文件 `app/evaluation/historical_cases/spec.json` 固定修复前提交和其直接子修复提交。宿主机仅通过 Git 读取对象；原始 Python 源码及已有测试逐字节导出。参考副本只覆盖登记的非测试源码，不引入上游修复提交中的测试变更。任务说明由评测方依据公开缺陷整理，明确源码位置和需保持的行为，并非原始 GitHub Issue 的未经加工原文；模型输入不包含参考修复补丁。

| 案例 | 上游实际修复 | 独立验收重点 |
|---|---|---|
| jsonpointer-large-index | [b8fbae3](https://github.com/stefankoegl/python-json-pointer/commit/b8fbae380c74795b42de3e5a569519ab2dc8e8a8) | 超长数组索引的异常类型、默认值、普通索引与对象键 |
| itsdangerous-date-overflow | [37f0997](https://github.com/pallets/itsdangerous/commit/37f09970fa32a330a6660ded3abdb264086531b5) | 非法签名时间戳溢出的异常契约和正常签名/过期行为 |
| dotenv-empty-comment | [f5485a6](https://github.com/theskumar/python-dotenv/commit/f5485a61eefa5e686d6d5bdc7aa9ad6b104b1e92) | 空值注释、字面量井号、引号、CRLF、覆盖行为 |
| slugify-uppercase-translations | [a243ccd](https://github.com/un33k/python-slugify/commit/a243ccdc6d2b650b83782e03893e8f117356aeff) | 所有原始翻译的大写扩展、去重及公开转换行为 |

`test.py` / `tests.py` 保留原文件，仅新增收集适配器。python-dotenv 的 4 个 Markdown 文档符号链接不在宿主机物化，Git 模式和对象 SHA 列在 lock 中；任何代码链接、子模块或其他链接均拒绝。全部原始 Python 文件必须通过工具的大小和路径边界，否则案例不准入。正常任务快照会省略非 Python 文档，其清单同样记录。

模型允许的根目录仅为 `corpus/sources`；参考修复及隐藏验收位于根目录之外。所有目标代码、已有测试、模型新测试和独立验收都在固定镜像的 Docker 容器中执行。隐藏验收只运行修复源码和评测方的测试，排除模型生成的测试，检查导入确实来自当前工作区。

## 先做对照，再冻结运行

每个案例先执行四个真实 Docker 对照：缺陷版本原始套件、缺陷版本隐藏验收、参考修复原始套件、参考修复隐藏验收。隐藏验收必须在缺陷版本出现测试失败而非收集错误；两个参考套件均须通过，并具有实际镜像 ID。参考修复只证明验收有效，不计入模型成功。

第一次环境对照发现 python-dotenv 缺少上游声明的 `dotenv` 控制台入口，12 项原始 CLI 测试因此失败。这批诊断保留于本地 `results-01`，未用于正式评测。最终镜像加入同一入口的轻量启动脚本，从挂载源码导入包；没有安装已修复的目标库。重新执行全部四案例对照后，`results-02` 全部准入。其原始 IPython 可选测试因依赖缺失按原有 importorskip 跳过，未修改或增加跳过条件。

正式运行使用已完整验证的 wheel，107 个包内文件与本机工作区源码及安装字节一致；Git 的行尾规范化可能使提交对象与 Windows 工作区行尾不同，不据此声称 wheel 和所有 Git blob 字节相同。冻结运行时代码提交、镜像 ID、语料/验收/对照摘要、模型参数和预算后才调用正式模型。预注册前的 1 次原生连接诊断成功，1685 个已观测 Token，独立排除于 24 次任务与正式调用统计。

## 三种模式、资源与主指标

模式为 `single`、`multi_no_review`、`multi_full`。重复内按模式顺序执行，第二次旋转顺序；案例最多两路并发。使用真实 LangGraph，模型经用户提供的 `https://muyuan.do/v1` 通道，请求及返回别名为 `deepseek-v4.1-flash`，温度 0，流式返回用量，模型间隔 7.5 秒，模型与测试超时各 120 秒。

每个任务新建独立数据目录，启用补丁事务和持久化预算：900 秒、8 次模型请求、100000 已观测 Token、6 次沙箱尝试、256 MiB 任务文件准入、8 MiB 结果目录。`max_retries=1`，重试候选从独立工作区建立。预算是准入与持久化记账规则，Token 可以被单次已发请求超出，并非费用硬上限；文件预算也不是整机磁盘配额。评测方的对照/隐藏验收使用独立 Docker 预算账本，不占修复任务额度，另行统计。

主成功必须同时满足：修复前隐藏验收确实失败；原有测试和收集适配器哈希不变；任务进入 `awaiting_approval`；当前候选任务测试通过；评测方隐藏验收通过。全部 24 次均留在分母；各模式固定为 8 次。仅隐藏验收通过但审查拒绝、超预算、提供方失败或任务未就绪的结果，不计为主成功。

正式运行开始后，不编辑提示词、运行时代码、语料、验收及配置；不补跑或替换失败单元。未知用量保持未知，失败照实保留。已有通用评测器产生的 `formal/report.json` 为辅助旧口径；本阶段 `results-02/report.json` 的 `ready_and_accepted` 为主口径。

## 复现步骤

使用 Python 3.11+ 和 Docker，先安装锁定依赖及构建出的 RepoPilot wheel。克隆上表四个仓库到 `UPSTREAM/jsonpointer`、`itsdangerous`、`dotenv`、`slugify`，无需检出或在宿主机执行目标代码。

```powershell
repopilot-eval-historical prepare --upstream UPSTREAM --corpus CORPUS
```

命令输出语料 lock SHA-256。按仓库现有 `sandbox/Dockerfile.pilots` 构建基础镜像 `repopilot-pilots:local`，为新镜像上下文下载 `click==8.1.8` 和 `text-unidecode==1.3` 的 wheel 到 `wheels/`，将 `sandbox/historical_dotenv.py` 复制为上下文的 `dotenv-cli`，使用 `sandbox/Dockerfile.historical` 离线构建。记录实际 `docker image inspect` ID。

设置 `REPOPILOT_SANDBOX_IMAGE` 为该 `sha256:...` ID、测试超时 120 秒，再执行：

```powershell
repopilot-eval-historical controls --corpus CORPUS --output EVIDENCE --lock LOCK_SHA256
```

确认四例全部准入后，将本轮设置写入自己的预注册记录。通过进程环境或外部安全输入提供模型密钥；不要把密钥加入预注册、命令历史或仓库。设置 repository_root 为 `CORPUS/sources`，data_dir 为全新独立目录，model_mode=live，以及预注册列出的模型、流式用量、补丁事务和预算字段，再执行：

```powershell
repopilot-eval-historical run --corpus CORPUS --output EVIDENCE --lock LOCK_SHA256 --repeats 2 --workers 2
```

完整环境示例见 [reproduction.env.example](reproduction.env.example)，已用 Settings 实际解析核对。Settings 支持的环境变量定义在 `app/config/settings.py`；预算通过单个 `REPOPILOT_BUDGET_LIMITS` JSON 变量输入，例如 `{"wall_seconds":900,"model_requests":8,"observed_tokens":100000,"sandbox_runs":6,"artifact_bytes":268435456,"result_bytes":8388608}`，不是按字段展开的变量。不要直接复用报告中的机器绝对路径。本轮冻结的证据 JSON 通过 Git 属性禁用行尾转换，保留记录字节。跨平台重新导出时 JSON/收集适配器行尾可能不同，需冻结本次新 lock 并重新执行对照，不能声称一定生成相同完整语料摘要。

## 解释边界

四个公开、小型、以 Python 为主的缺陷及相关重复，无法代表未见仓库、复杂依赖、非 Python、多模块重构或生产修复能力。模型训练数据交集未知；代理返回的模型别名不证明实际底层权重。两次重复相关，表格为描述性数据，不能把 24 次视作 24 个独立 Bug。不同模式调用数和上下文不同，运行时间还包含共享 Docker/提供方负载与限流等待。此前两案例试验关闭预算且重试配置不同，本轮不据此宣称优化的因果效果。

本阶段只验证本地真实模型与 Docker 修复链路。新增源码尚未获得该提交上的 GitHub CI 证据；发布新的固定提交须另行绑定人工批准摘要。
