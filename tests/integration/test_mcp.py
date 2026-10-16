import asyncio
from pathlib import Path

from app.mcp_server.server import create_server


def test_mcp_schemas_calls_and_scope():
    async def scenario():
        server = create_server(Path(__file__).parents[2] / "demo_repository")
        tools = await server.list_tools()
        assert {t.name for t in tools} == {
            "list_files",
            "search_code",
            "read_file",
            "git_diff",
            "find_symbol",
            "inspect_dependencies",
        }
        assert next(t for t in tools if t.name == "read_file").inputSchema["required"] == ["path"]
        _, result = await server.call_tool("read_file", {"path": "auth.py"})
        assert result["ok"] and "FastAPI" in result["data"]
        _, bad = await server.call_tool("read_file", {"path": "../secret.py"})
        assert bad["ok"] is False

    asyncio.run(scenario())


def test_mcp_stdio_transport():
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def scenario():
        root = Path(__file__).parents[2]
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server.server"],
            cwd=str(root),
            env={"REPOPILOT_REPOSITORY_ROOT": str(root / "demo_repository")},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert len(tools.tools) == 6
                result = await session.call_tool("search_code", {"keyword": "expired"})
                assert not result.isError
                assert result.structuredContent["ok"] is True
                assert result.structuredContent["data"][0]["path"] == "auth.py"

    asyncio.run(scenario())
