# 简历项目介绍草稿

**RepoPilot：基于 LangGraph 与 MCP 的智能代码修复系统**

- 使用 LangGraph StateGraph 构建 Supervisor、Planner、Locator、Coder 与 Reviewer 工作流，串联代码检索、受控补丁、测试反馈、有限重试及人工审批。
- 设计 Pydantic 结构化输出、独立 task_id/thread_id 和 SQLite Checkpointer，支持节点状态追踪、审批中断与 Docker 阻塞后继续运行。
- 实现 MCP 标准只读工具服务与受控文件编辑器，约束路径、上下文大小、既有测试修改和模型 Shell；采用非 root、禁网络、限资源的 Docker 测试配置。
- 基于 FastAPI + Streamlit 提供 Diff、日志、测试与计量展示，设计 Single/Multi 消融评测与独立验收测试，指标从真实执行记录汇总。

已完成真实 Docker 验收：修复前独立测试失败，修复后契约通过；三模式各重复 3 次，共 9 次确定性修复与验收通过。面试时应说明这是一个已知 Bug 的流程验证，不代表泛化修复成功率。真实 LLM 联网、LangSmith 上传和 GitHub 外部建 PR 尚未验收，不声称 Multi-Agent 带来性能提升。
