# 提供方参数兼容优化与真实验证（2026-10-21）

运行时固定提交 `610136f4c9faa5005ef7cf7298c633e9866bf507`，模型 `deepseek-4.1-flash-background`，通道 `https://gw.lunaroute.com/v1`。

新增显式 opt-in Token 参数方言与关闭思考开关；默认仍使用 max_completion_tokens 和 provider_default，不根据别名推断支持，不增加自动回退。预算约束、length 拒绝、原测试保护、严格 fail-to-pass 见证和人工发布审批保持。新增响应形态只记录 SDK 可见字符/工具调用计数及有效 reasoning 用量，不记录正文、工具参数或推理正文；缺失不补零。

完整安装包回归 **411 passed、2 skipped**，显式启用 Docker；22 项新增受控 SDK/HTTP/SSE 用例。92 个既有测试/辅助文件未改，120 个包内应用文件逐字节匹配源码与安装。Ruff 和补丁格式检查通过。受控测试不冒充真实模型证据。

## 冻结的真实参数对照

同一公开历史 Issue 的 Plan 输入，三组均保持工具 schema、named tool 选择、parallel_tool_calls=False 和 2048 输出上限；每组独立非流式/流式各一次。A=默认参数；B=仅 max_tokens；C=max_tokens + thinking.disabled。只有 A/B 均未通过双模式完整输出时才执行 C。选择通过双模式的最小改动配置；发生连接/提供方错误、用量未知或中断即停止，不回退替换。

| 单元 | 结果 | 实际 HTTP 参数 | 实际思考请求 | 结束原因 | 解析 | 已知 Token | Reasoning 用量 |
|---|---|---|---|---|---|---:|---|
| A-nonstream | failed | max_completion_tokens | provider_default | length | missing | 3144 | 2048 |
| A-stream | failed | max_completion_tokens | provider_default | length | missing | 3144 | 2048 |
| B-nonstream | failed | max_tokens | provider_default | length | missing | 3144 | 2048 |
| B-stream | failed | max_tokens | provider_default | length | missing | 3144 | 2048 |
| C-nonstream | failed | max_tokens | disabled | length | missing | 3144 | 2048 |
| C-stream | failed | max_tokens | disabled | length | missing | 3144 | 2048 |

选择结果：`None`；停止原因：`no_profile_passed_both_complete_output_modes`。真实诊断共 6 次请求、18864 已观测 Token。

HTTP 观测来自实际 SDK 请求钩子，只保存允许列表字段，不读取 Authorization 或保存原始请求正文。它能证明客户端发出的参数，不能证明代理最终转发或提供方确实遵守了思考开关。响应计数仅限通用 SDK 保留的字段，不能把正文为空、缺失 reasoning 统计或工具参数未记录当成没有生成或零费用。

## 条件真实修复验证

预定 2 个全新 multi_full / legacy-policy 历史任务，实际完成 0 项，严格成功 0 项，0 次请求、0 已观测 Token。选中配置用于修复时显式设置 4096 输出上限。未选择通过的配置时，两个任务保持未执行，不算两次模型修复失败。

严格成功要求原始测试不变、固定失败基线成立、候选待人工审批、原始套件与隐藏验收通过，以及同一新增测试在原版失败、当前候选通过。目标代码只在固定 Docker 镜像执行；24 项控制复用同一语料/镜像已封存证据，不称为本轮重新运行。

每个诊断单元仅 1 次请求预留、75 秒边界预算、45 秒 SDK 超时、32768 已观测 Token 阈值；135 秒独立进程硬时限。诊断阶段最多 900 秒。每个修复任务最多 360 秒、8 请求预留、100000 已观测 Token、10 次任务 Docker；额外隐藏验收和回放各有独立单次 Docker 预算，工作进程硬时限 660 秒，修复阶段最多 1800 秒。这些阈值不是金额硬限，缺失用量保持未知，不退款或重发。

根私有 `.env` 未改，旧 16 份账本保持摘要；质量开关默认关闭，没有启动完整历史矩阵，没有批准候选或写 GitHub。小额探测和两项已知案例不证明持续稳定性、底层权重、修复质量改善或未见仓库泛化，所有失败/条件未执行保留。

参数与诊断依据见 [实现说明](implementation-notes.md)，其中链接 OpenAI 官方参数/Token 文档和 DeepSeek 接口说明；官方接口规范不是当前第三方通道符合规范的证明。
