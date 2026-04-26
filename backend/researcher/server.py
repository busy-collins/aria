"""Aria Researcher Service."""
import os
import logging
from datetime import datetime, UTC
from typing import Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from dotenv import load_dotenv
from agents import Agent, Runner, trace, OpenAIChatCompletionsModel
from openai import AsyncOpenAI

logging.getLogger("LiteLLM").setLevel(logging.CRITICAL)

# ── Import from shared package ────────────────────────────
from shared.context import researcher_instructions
from shared.mcp_servers import create_playwright_mcp_server
from shared.tools import ingest_research_document

load_dotenv(override=True)

app = FastAPI(title="Aria Researcher Service")


class ResearchRequest(BaseModel):
    topic:    Optional[str] = None
    brief_id: Optional[str] = None


async def run_research_agent(
    topic:    str = None,
    brief_id: str = None
) -> str:
    query = (
        f"Research this topic thoroughly: {topic}"
        if topic else researcher_instructions()
    )

    openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    model = OpenAIChatCompletionsModel(
        model         = "gpt-4o",
        openai_client = openai_client,
    )

    with trace("Aria Researcher"):
        async with create_playwright_mcp_server(timeout_seconds=60) as mcp:
            agent = Agent(
                name         = "Aria Research Agent",
                instructions = researcher_instructions(),
                model        = model,
                tools        = [ingest_research_document],
                mcp_servers  = [mcp],
            )
            result = await Runner.run(
                agent,
                input     = query,
                max_turns = 20
            )

    return result.final_output


@app.get("/")
async def root():
    return {"service": "Aria Researcher", "status": "healthy"}


@app.post("/research")
async def research(request: ResearchRequest) -> str:
    try:
        return await run_research_agent(
            topic    = request.topic,
            brief_id = request.brief_id
        )
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/research/auto")
async def research_auto():
    try:
        response = await run_research_agent(topic=None)
        return {
            "status":    "success",
            "timestamp": datetime.now(UTC).isoformat(),
            "preview":   response[:200] + "..." if len(response) > 200 else response,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/health")
async def health():
    return {
        "service":             "Aria Researcher",
        "status":              "healthy",
        "aria_api_configured": bool(
            os.getenv("ARIA_API_ENDPOINT") and os.getenv("ARIA_API_KEY")
        ),
        "openai_configured":   bool(os.getenv("OPENAI_API_KEY")),
        "timestamp":           datetime.now(UTC).isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)