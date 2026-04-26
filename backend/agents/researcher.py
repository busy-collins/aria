"""
Aria Researcher Agent — web browsing via Playwright MCP
"""
import os
from agents import Agent, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from shared.context import researcher_instructions
from shared.tools import ingest_research_document
from shared.mcp_servers import create_playwright_mcp_server


def create_researcher_agent() -> Agent:
    """Create the researcher agent."""
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    return Agent(
        name         = "Aria Researcher",
        instructions = researcher_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o",
            openai_client = client
        ),
        tools = [ingest_research_document],
    )