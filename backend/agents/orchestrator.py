"""
Aria Orchestrator with LangSmith observability
"""
import os
import asyncio
import uuid
from agents import Agent, Runner, OpenAIChatCompletionsModel
from openai import AsyncOpenAI
from dotenv import load_dotenv
from langsmith import traceable
from langsmith.wrappers import wrap_openai

load_dotenv(override=True)

# ── Context imports — all prompts ─────────────────────────
from shared.context import (
    orchestrator_instructions,
    DEFAULT_RESEARCH_PROMPT,
    analyst_instructions,
    writer_instructions,
    critic_instructions
)
from shared.tools import (
    ingest_research_document,
    search_knowledge_base,
    score_confidence,
    save_briefing,
    score_briefing,
    flag_for_human_review
)
from shared.mcp_servers import create_playwright_mcp_server


async def run_aria(brief_id: str, topics: list[str]) -> dict:

    # ── Wrapped client sends ALL calls to LangSmith ───────
    raw_client     = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    wrapped_client = wrap_openai(raw_client)

    @traceable(name="research-step")
    async def run_research():
        async with create_playwright_mcp_server(timeout_seconds=120) as mcp:
            researcher = Agent(
                name         = "Aria Researcher",
                instructions = f"Research thoroughly. brief_id={brief_id}",
                model        = OpenAIChatCompletionsModel(
                    model         = "gpt-4o",
                    openai_client = wrapped_client    # ← wrapped
                ),
                mcp_servers = [mcp],
                tools       = [ingest_research_document]
            )
            tasks = [
                Runner.run(
                    researcher,
                    input     = f"Research: {topic}. brief_id={brief_id}",
                    max_turns = 15
                )
                for topic in topics
            ]
            return await asyncio.gather(*tasks)

    @traceable(name="analyst-step")
    async def run_analyst(combined: str):
        analyst = Agent(
            name         = "Aria Analyst",
            instructions = analyst_instructions(),
            model        = OpenAIChatCompletionsModel(
                model         = "gpt-4o",
                openai_client = wrapped_client    # ← wrapped
            ),
            tools = [search_knowledge_base, score_confidence]
        )
        return await Runner.run(
            analyst,
            input     = f"Brief ID: {brief_id}\n\nResearch:\n{combined}",
            max_turns = 10
        )

    @traceable(name="writer-step")
    async def run_writer(analysis: str):
        writer = Agent(
            name         = "Aria Writer",
            instructions = writer_instructions(),
            model        = OpenAIChatCompletionsModel(
                model         = "gpt-4o",
                openai_client = wrapped_client    # ← wrapped
            ),
            tools = [save_briefing]
        )
        return await Runner.run(
        writer,
        input     = f"""
Brief ID: {brief_id}
Topic: {', '.join(topics)}

Analysis to convert into briefing:
{analysis}

Instructions:
1. Write the complete briefing following the required structure
2. Use the analysis above as your source material
3. Be specific — include numbers and data points
4. Minimum 400 words
5. Call save_briefing with the COMPLETE text after writing
""",
        max_turns = 8    # ← increase from 5 to give writer more turns
    )

    @traceable(name="critic-step")
    async def run_critic(briefing: str):
        critic = Agent(
            name         = "Aria Critic",
            instructions = critic_instructions(),
            model        = OpenAIChatCompletionsModel(
                model         = "gpt-4o-mini",
                openai_client = wrapped_client    # ← wrapped
            ),
            tools = [score_briefing, flag_for_human_review]
        )
        return await Runner.run(
            critic,
            input     = f"Evaluate: {briefing}",
            max_turns = 3
        )

    # ── Run pipeline ──────────────────────────────────────
    print(f"Starting Aria pipeline — brief_id: {brief_id}")

    research_results = await run_research()
    print(f"Research complete — {len(research_results)} topics")

    combined = "\n\n---\n\n".join([
        f"Topic: {topics[i]}\n{r.final_output}"
        for i, r in enumerate(research_results)
    ])

    analysis = await run_analyst(combined)
    print(f"Analysis complete")

    briefing = await run_writer(analysis.final_output)
    print(f"Briefing complete")

    verdict  = await run_critic(briefing.final_output)
    print(f"Critic complete")

    return {
        "brief_id": brief_id,
        "briefing": briefing.final_output,
        "verdict":  verdict.final_output,
        "topics":   topics,
    }


if __name__ == "__main__":

    async def test():
        print("="*60)
        print("ARIA PIPELINE TEST")
        print("="*60)

        brief_id = str(uuid.uuid4())
        topics   = ["NVIDIA AI chip market 2026"]

        print(f"Brief ID: {brief_id}")
        print(f"Topics:   {topics}")
        print("="*60)

        result = await run_aria(
            brief_id = brief_id,
            topics   = topics
        )

        print("\n" + "="*60)
        print("PIPELINE COMPLETE")
        print("="*60)
        print(f"Brief ID: {result.get('brief_id')}")
        print("\nFINAL BRIEFING:")
        print("-"*60)
        print(result.get("briefing", "No briefing returned"))
        print("\nVERDICT:")
        print("-"*60)
        print(result.get("verdict", "No verdict returned"))
        print("="*60)

    asyncio.run(test())