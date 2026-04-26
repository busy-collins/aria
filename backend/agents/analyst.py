"""
Aria Analyst Agent — RAG retrieval + fact checking
"""
import os
from agents import Agent, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from shared.context import analyst_instructions
from shared.tools import search_knowledge_base, score_confidence


def create_analyst_agent() -> Agent:
    """Create the analyst agent."""
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    return Agent(
        name         = "Aria Analyst",
        instructions = analyst_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o",
            openai_client = client
        ),
        tools = [
            search_knowledge_base,
            score_confidence
        ]
    )