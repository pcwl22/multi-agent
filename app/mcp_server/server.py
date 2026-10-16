import asyncio
import json
import logging
import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

from app.config.settings import Settings
from app.tools.repository import Repository

logger = logging.getLogger("repopilot.mcp")


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    error: str | None = None


def create_server(root) -> FastMCP:
    repo = Repository(root)
    server = FastMCP("RepoPilot", instructions="Read-only scoped repository tools")

    async def invoke(tool: str, fn, *args) -> ToolResult:
        started = time.monotonic()
        try:
            value = await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=15)
            result = ToolResult(ok=True, data=value)
        except (ValueError, OSError, TimeoutError) as exc:
            result = ToolResult(ok=False, error=str(exc)[:500])
        logger.info(
            json.dumps({"tool": tool, "ok": result.ok, "seconds": time.monotonic() - started})
        )
        return result

    @server.tool()
    async def list_files() -> ToolResult:
        """List bounded text files inside the configured repository."""
        return await invoke("list_files", repo.list_files)

    @server.tool()
    async def search_code(keyword: str, limit: int = 30) -> ToolResult:
        """Search a literal keyword, returning relative paths and line numbers."""
        return await invoke("search_code", repo.search_code, keyword, limit)

    @server.tool()
    async def read_file(path: str, max_chars: int = 16000) -> ToolResult:
        """Read a UTF-8 file with traversal, link and secret-path restrictions."""
        return await invoke("read_file", repo.read_file, path, max_chars)

    @server.tool()
    async def find_symbol(symbol: str) -> ToolResult:
        """Find Python function/class definitions without importing code."""
        return await invoke("find_symbol", repo.find_symbol, symbol)

    @server.tool()
    async def inspect_dependencies() -> ToolResult:
        """Read known dependency manifests without running package managers."""
        return await invoke("inspect_dependencies", repo.inspect_dependencies)

    @server.tool()
    async def git_diff() -> ToolResult:
        """Read tracked-file Git diff; external drivers and textconv are disabled."""
        return await invoke("git_diff", repo.git_diff)

    return server


def main():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    create_server(Settings().repository_root).run(transport="stdio")


if __name__ == "__main__":
    main()
