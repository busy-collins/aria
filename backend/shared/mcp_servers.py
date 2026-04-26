"""
MCP server configuration for Aria agents.
"""
from agents.mcp import MCPServerStdio
from contextlib import asynccontextmanager


@asynccontextmanager
async def create_playwright_mcp_server(timeout_seconds: int = 60):
    """
    Create a Playwright MCP server for web browsing.
    Used by the Researcher agent to browse the web.
    """
    server = MCPServerStdio(
        params = {
            "command": "npx",
            "args": [
                "@playwright/mcp",
                "--headless",
                "--no-sandbox",
            ]
        },
        cache_tools_list = True,
        client_session_timeout_seconds = 120
    )
    async with server:
        yield server