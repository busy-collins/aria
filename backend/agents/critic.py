"""
Aria Critic Agent — evaluates briefing quality (LLM-as-judge)
"""
import os
from agents import Agent, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from shared.context import critic_instructions
from tools import score_briefing, flag_for_human_review


def create_critic_agent() -> Agent:
    """Create the critic agent."""
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    return Agent(
        name         = "Aria Critic",
        instructions = critic_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o-mini",    # cheaper for scoring
            openai_client = client
        ),
        tools = [
            score_briefing,
            flag_for_human_review
        ]
    )