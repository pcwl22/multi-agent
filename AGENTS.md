# RepoPilot 开发约定

- Windows 命令使用 PowerShell 7 (`pwsh`)，保持 UTF-8。
- Python 3.11+；模块采用类型注解和 Pydantic 边界模型。
- 工作流使用真实 LangGraph；模型、文件工具和沙箱依赖可注入。
- 不可信仓库代码只能在 Docker 内执行；禁止宿主机回退和模型 Shell。
- 文件访问必须经过仓库路径检查；不得删除或修改已有测试。
- 修改在任务独立副本内进行，保留原始仓库与审批前后 diff。
- 外部写入必须绑定人工批准的内容摘要；不自动推送或建 PR。
- Mock 仅支持明确标注的示例修复，不伪装通用模型或真实测试。
- 每个阶段先实现再验证，文档写明未验证能力。
- 验证：`python -m pytest -q`；`python -m ruff check .`。
