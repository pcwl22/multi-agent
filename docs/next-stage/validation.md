# 后续五阶段交付与本地验收

日期：2026-10-16（Asia/Shanghai）。用户选择 PR #2 保持草稿、继续本地验证；本轮未推送、合并、新建远端 PR 或发布版本。

## 1. PR #2 审查

审查版本 `edb60e0a180efeed9a18fb5086cb1daea121ad17`，未发现阻断问题。审批摘要、远端基线预校验、既有测试不可变、输出预算及有限重试均保留。复验 78 passed / 1 skipped，原 PR 的 Python 3.11、3.13 和 Docker CI 均通过。

[审查与摘要](pr2-review.md)，[结构化记录](pr2-review.json)。这是范围明确的正确性审查，不是完整安全审计。

## 2. 十案例真实模型评测

独立语料包含状态码、分页、折扣、时区、CSV、跨文件结算、库存重复预留、TTL、Unicode 和递归配置合并；每个仓库另有检索干扰模块。所有案例的旧测试在修复前通过，独立验收在修复前失败，参考修复能通过两组测试。原有三案例语料保持原样。

模型由用户指定兼容服务返回为 `deepseek-v4.1-flash`。10 案例 × 3 模式 × 3 次重复 = 90 次任务，温度 0、上下文 24000 字符、共享重试预算 2；修复副本和隐藏验收均在 Docker 执行。执行代码基于本地提交 `d003bd4`。

首轮：**23/90** 通过，**67 次服务错误**，服务返回“5 分钟最多 50 次请求”。67 次任务缺少完整 usage，没有填成零；原始记录和补丁完整保留。该轮结果主要受限流影响，不能据此比较模型修复能力。

等待窗口恢复后，以新目录复跑，请求间隔 7.5 秒，同一进程最多并行 3 个案例：**90/90** 通过独立验收；模型逻辑请求 **183** 次，服务报告 Token **250708**，usage 未知任务 **0** 个，服务错误 **0** 次。SDK 内部 HTTP 重试不另算一次逻辑请求。

| 模式 | 独立验收通过 / 总数 | 平均模型调用 | 平均 Token | 平均重试 |
|---|---:|---:|---:|---:|
| single | 30 / 30 | 1.00 | 1302.80 | 0.00 |
| multi_no_review | 30 / 30 | 2.10 | 2774.57 | 0.10 |
| multi_full | 30 / 30 | 3.00 | 4279.57 | 0.00 |

这是合成语料，重复运行不等于来自独立真实项目的样本；不能宣称泛化修复率或 Multi-Agent 的因果收益。并行、服务端负载和请求间隔均影响耗时，因此不以该轮耗时比较算法固有速度。报告的测试通过率基于每次任务最后一次 pytest；早期失败另见逐次证据。

[首轮完整数据](../evaluation/expanded-rate-limited-20261016/report.md)，[复跑完整数据](../evaluation/expanded-paced-20261016/report.md)，[审计汇总](evaluation-summary.json)。两轮各保留 90 条 JSONL、补丁和自然反馈证据。

[跨平台语料清单](portable-corpus-manifest.json) 以 LF 规范化文本计算哈希；原始报告仍保留 Windows 实际执行字节的哈希。

### 补充契约后的当前结论：84 / 90

补充审计发现原分页验收遗漏题目已声明的 Python range 输入。新增验收文件，没有修改旧测试；对相同 90 个已保存补丁重新运行 Docker，得到 Single 27/30、Multi 无 Reviewer 30/30、完整 Multi 27/30。6 次失败均为 range 返回类型契约未满足。当前以 **84/90** 为较严格结论，保留原始 90/90；此次重放没有新增模型调用，也没有修改模型补丁。

[补充契约复验](../evaluation/expanded-strict-replay-20261016/report.md)。它是事后补充验收，不是预先注册的另一轮模型评测；不据此建立模式优劣的因果结论。后续建议使用 dataset.strict.json。

## 3. 真实反馈闭环

首轮自然恢复 2 次，复跑自然恢复 3 次。证据包含失败 pytest 的实际 stdout、补丁拒绝、后续修改、服务响应标识和最终独立验收；原有测试逐字节保持不变。

[首轮自然恢复轨迹](../evaluation/expanded-rate-limited-20261016/natural-feedback.json)，[复跑自然恢复轨迹](../evaluation/expanded-paced-20261016/natural-feedback.json)。

另行执行真实联网故障注入实验，显式替换模型候选为错误代码，不混入上述成功率。两项实验使用重试预算 1：

- 仅替换首个候选，之后保留模型真实修复：awaiting_approval，2 次尝试，4 次模型调用；预期结果验证通过。
- 每个候选都替换为错误代码，验证有限终止：failed，2 次尝试，3 次模型调用；预期结果验证通过。

[故障注入证据](feedback-experiments.json)。这些初始错误是人为注入，不能宣称来自模型的自然失败。

## 4. 实际浏览器本地流程

使用 Playwright 操作真实 Edge、Streamlit 和 HTTP API，调用真实模型并执行 Docker。任务 `b14fc4d1-90de-46b9-afbf-138a622dd7f0` 完成提交、进度、Diff、测试、审核和本地批准；Diff SHA-256 为 `6b780e3407737a74481a55d2e4b20f17817ca54994ff015c23100aad8f8a2b8f`。

根据用户本轮“保持草稿、继续本地验证”的选择，发布服务未配置写凭据。点击创建 PR 会在本地返回明确拒绝，发布表仍为空，没有向 GitHub 发送写请求（实际 HTTP 409，原因是缺少 GITHUB_TOKEN）。本地自动化点击批准只用于验证界面和状态流转，不构成对外发布授权。

既有 [真实模型修复 PR #1](https://github.com/pcwl22/multi-agent/pull/1) 的实际发布与 CI 证据仍保留；本轮未新建 PR。

[浏览器证据](browser/evidence.json)，[结果截图](browser/result-overview.png)，[实际录屏](browser/local-flow.webm)。凭据不进入浏览器、源码、截图或报告；验收进程关闭后销毁。

## 5. 发布候选准备

干净虚拟环境禁用系统 site-packages，安装固定依赖和 wheel，用隔离导入方式执行全量测试：**99 passed、1 skipped**；pip check 和 Ruff 通过。跳过为 Windows 符号链接权限；11 条警告来自既有 TestClient timeout 弃用提示。

[干净安装记录](clean-install.json)，[v0.1.0 启动与支持范围](../release-v0.1.0.md)，[发布包摘要](release-artifacts.json)。wheel 和源码包已准备；本轮未创建 tag、GitHub Release 或上传包。可用 `python scripts/start_demo.py --live` 隐藏输入密钥并启动本地演示，Ctrl+C 关闭两个子进程。

LangSmith 上传仍未验收；任意构建系统、联网仓库测试和公网多用户服务不在已验证范围。

本轮新增改动按用户选择仅在本地验收，尚未运行其远端 CI；前文 CI 结果仅对应所审查的 PR #2 固定版本。界面补充了后端拒绝原因展示；结果截图为无凭据历史任务回看，未新增模型调用。
