# 简历项目介绍草稿

**RepoPilot：基于 LangGraph 与 MCP 的智能代码修复系统**

- 使用 LangGraph StateGraph 构建 Supervisor、Planner、Locator、Coder 与 Reviewer 工作流，串联代码检索、受控补丁、测试反馈、有限重试及人工审批。
- 设计 Pydantic 结构化输出、独立 task_id/thread_id 和 SQLite Checkpointer，支持节点状态追踪、审批中断与 Docker 阻塞后继续运行。
- 实现 MCP 标准只读工具服务与受控文件编辑器，约束路径、上下文大小、既有测试修改和模型 Shell；采用非 root、禁网络、限资源的 Docker 测试配置。
- 基于 FastAPI + Streamlit 提供 Diff、日志、测试与计量展示，设计 Single/Multi 消融评测与独立验收测试，指标从真实执行记录汇总。

已完成真实 Docker 验收与 DeepSeek 联网：3 类 Bug 的独立测试在修复前失败，修复后通过。真实模型三模式首轮 6/9 成功，改进拒绝反馈与提示后复跑 9/9 成功，保留失败记录；另一个真实模型补丁由系统创建草稿 PR 并通过 CI。最新回归 78 passed、1 skipped。面试时应说明样本只有 3 类已知 Bug，每模式每 Bug 1 次，不代表泛化修复率或因果收益；LangSmith 上传尚未验收。详见 [真实证据](live-validation.md)。

后续扩展：10 个隔离合成案例、三模式各重复 3 次。冻结验收 90/90；发现分页 range 契约漏测后，新增测试并对相同补丁复验为 84/90，完整保留原结果与失败。验证自然反馈恢复及故障注入下的真实模型恢复、有限终止；浏览器实测至本地批准和发布保护。最新回归 99 passed、1 skipped。合成小样本不能代表真实项目泛化成功率，详见 [后续验收](next-stage/validation.md)。
