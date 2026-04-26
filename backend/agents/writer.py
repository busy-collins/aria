"""
Aria Writer Agent — synthesises the final briefing
"""
import os
from agents import Agent, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from shared.context import writer_instructions
from shared.tools import save_briefing


def create_writer_agent() -> Agent:
    """Create the writer agent."""
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    return Agent(
        name         = "Aria Writer",
        instructions = writer_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o",
            openai_client = client
        ),
        tools = [save_briefing]
    )