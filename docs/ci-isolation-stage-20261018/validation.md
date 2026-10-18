# CI 隔离与模型配置验证（2026-10-18）

在独立管理工作区 codex/ci-fixture-model-config 实施；原 E:/multi-agent 工作区和远端 PR #2、#4 未修改。

## 已实现

- 将 CI 故障输入固定为 test_fixtures/repair_repository，6 个文件与原始 Git blob 字节一致，manifest 校验其完整性。
- 人工批准仅修改列出的 20 个旧测试中的样本引用，以及一项 UI 测试的路径输入。所有既有断言、名称、参数化、标记及跳过条件不变；其他旧测试字节未变。
- 正式 Settings 支持 model_streaming（默认 false）、model_stream_usage（默认 true）和 model_path_scope（默认 true）。
- LiveModel 正式使用这些流式设置，并在实际调用历史记录 streaming 状态；usage 缺失仍标为不完整。
- 工作流向各模型角色提供最多 80 个受控相对路径和远端子目录映射，不发送绝对路径或重写返回的编辑路径，原有路径及测试保护继续执行。
- 新增 8 项测试，涵盖 SSE 分片、usage 有无、默认/可选配置、范围限额与保密、角色传播及 fixture 完整性。

## 已完成验证

在单独的完整验证副本中，先将 demo_repository/auth.py 的过期状态码修复为 401，再启用全部 Docker 测试运行完整 pytest：**167 passed、1 skipped**。这直接验证测试不再要求可编辑演示代码保留该故障。运行应用来自独立 editable 安装，父子进程统一来源，原始工作区和开发副本的 demo 未被覆盖。Ruff 与 diff whitespace 检查通过。

使用既有真实 Issue #3、正式 TaskService/LiveModel 和标准 Settings 进行实际 DeepSeek 联网验证：任务 0d0355af-6df7-42ab-a0c2-998521e4fdd4，3 次模型调用，输入 8273、输出 2726 tokens，usage 完整。默认路径范围打开、显式流式打开，没有注入自定义模型包装器。候选 Docker 7 passed；独立验收从原始代码 4 passed/1 failed 到候选 5 passed；同一新增回归在原始代码失败、在候选通过，状态 demonstrated。LLM 复审通过；任务停在 awaiting_approval，没有批准或发布此演示补丁。

## 审批与证据

旧测试引用例外请求 SHA-256 为 063ae4b29202894296679fccc294b45115f41ed181cd8b74a247398819a1be17，用户明确批准“批准这些引用和 UI 输入调整，保持全部断言”。见 test-change-request.json 与 human-test-reference-approval.json。该批准仅为本地调整，不允许 GitHub 写入。

见 immutability-audit.json、fixed-demo-verification.json、source-tests.json 及 live-run/。完整测试 XML 在 E:/multi-agent/.repopilot/ci-isolation-suite.xml。

## 尚未宣称的能力

流式不能保证消除网关故障；网络读写超时不是完整生成的绝对耗时上限。模型仍可能返回无效路径，系统会拒绝。源代码检查在 Windows Python 3.13 执行；本阶段的新提交尚未运行 GitHub Python 3.11/3.13 CI，也没有更新 PR #2 或 #4。下一阶段仅在新的完整发布摘要获批后写入远端；不自动合并。

## 新构建 wheel 与源码包验证

运行时代码冻结于 9c8f535bb8b94690876278fe5eb798811b517f2f。新 wheel 安装替换了 editable 应用，确认所有应用导入来自独立 venv 的 site-packages；父子进程来源一致。在同一已修复 demo 的验证副本中再执行全部 pytest（Docker 开启）：**167 passed、1 skipped**，无失败。

wheel SHA-256 为 956bb42d139f7ccda0ee969a13dc8cfcd3afb5076821ffb319e54d195f07f8ec，源码包 SHA-256 为 b05e034ae4c3baab1b60ee3700d0146cfa8ac2312551fcf58d44e2e631da7fb4。包位于 E:/multi-agent/.repopilot/ci-stage-dist/。运行时模块字节与 wheel 一致，源码包包含全部 6 个 fixture 文件且逐项匹配 manifest。

完整 wheel 测试 XML 为 E:/multi-agent/.repopilot/ci-isolation-wheel-suite.xml；汇总见 wheel-tests.json。release-artifacts.json 是排除在自身源码包之外的伴随摘要；最终验证文档晚于打包，不能将最终文档提交误当作新的未测试运行时代码。
