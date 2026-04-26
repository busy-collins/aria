"""
Writer Lambda Handler
"""
import os
import sys
import json
import boto3
import asyncio

sys.path.insert(0, "/var/task")

from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel, function_tool
from langsmith import traceable
from langsmith.wrappers import wrap_openai
from shared.context import writer_instructions
from shared.secrets import get_openai_api_key, get_langsmith_api_key

# ── DO NOT import save_briefing from shared.tools ─────────
# The local @function_tool below captures the real content
# from shared.tools import save_briefing  ← REMOVED

# ── AWS clients ───────────────────────────────────────────
rds = boto3.client(
    "rds-data",
    region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
)

CLUSTER_ARN  = os.getenv("AURORA_CLUSTER_ARN")
SECRET_ARN   = os.getenv("AURORA_SECRET_ARN")
DATABASE     = os.getenv("DATABASE_NAME", "aria")
PROJECT_NAME = os.getenv("PROJECT_NAME", "aria")

# ── Module-level capture dict ─────────────────────────────
_saved_content: dict = {}


def setup_observability():
    try:
        openai_key    = get_openai_api_key()
        langsmith_key = get_langsmith_api_key()
        os.environ["OPENAI_API_KEY"]    = openai_key
        os.environ["LANGSMITH_API_KEY"] = langsmith_key
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = os.getenv(
            "LANGSMITH_PROJECT", "aria-production"
        )
        print("Observability configured ✅")
    except Exception as e:
        print(f"Observability setup failed: {e}")


def update_brief_failed(brief_id: str, error: str):
    try:
        rds.execute_statement(
            resourceArn = CLUSTER_ARN,
            secretArn   = SECRET_ARN,
            database    = DATABASE,
            sql         = """
                UPDATE briefs
                SET status     = 'failed',
                    updated_at = NOW()
                WHERE id = :id::uuid
            """,
            parameters  = [
                {"name": "id", "value": {"stringValue": brief_id}}
            ]
        )
    except Exception as e:
        print(f"Warning: Could not mark brief as failed: {e}")


# ── Local save_briefing — captures real content ───────────
@function_tool
def save_briefing(
    brief_id: str,
    content:  str,
    topic:    str
) -> dict:
    """
    Save the completed briefing after writing all sections.

    Args:
        brief_id: ID of the research brief
        content:  The FULL written briefing — minimum 300 words
        topic:    Main topic of the briefing
    """
    global _saved_content

    word_count = len(content.split())

    if word_count < 150:
        return {
            "success": False,
            "error":   f"Too short ({word_count} words). Write all sections first then save.",
        }

    # ── THIS is the capture ───────────────────────────────
    _saved_content[brief_id] = content

    print(f"Briefing captured ✅ — {word_count} words — brief_id: {brief_id}")
    print(f"Preview: {content[:100]}...")

    return {
        "success":    True,
        "brief_id":   brief_id,
        "word_count": word_count,
        "message":    f"Saved {word_count} words. Your work is complete."
    }


@traceable(name="writer-lambda")
async def run_writer(
    brief_id: str,
    topics:   list,
    analysis: str
) -> str:
    global _saved_content
    _saved_content = {}    # reset for each run

    raw_client     = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    wrapped_client = wrap_openai(raw_client)

    writer = Agent(
        name         = "Aria Writer",
        instructions = writer_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o",
            openai_client = wrapped_client
        ),
        tools = [save_briefing]    # ← local version, not shared
    )

    result = await Runner.run(
        writer,
        input     = f"""
Brief ID: {brief_id}
Topics: {', '.join(topics)}

Analysis:
{analysis}

INSTRUCTIONS:
1. Write the COMPLETE briefing with ALL sections
2. Minimum 400 words of actual content
3. After writing EVERYTHING call save_briefing with:
   - brief_id: {brief_id}
   - content: the complete text you just wrote
   - topic: the main topic

Required sections:
## Executive Summary
## Key Findings
## Market Analysis
## Data & Evidence
## Recommendations
""",
        max_turns = 10
    )

    # ── Return captured content, not agent's last message ─
    real_content = _saved_content.get(brief_id)

    if real_content:
        print(f"Returning real content ✅ — {len(real_content)} chars")
        return real_content

    print(f"Warning: save_briefing not called — using final_output ({len(result.final_output)} chars)")
    return result.final_output


def handler(event, context):
    setup_observability()

    brief_id = event.get("brief_id")
    topics   = event.get("topics", [])
    analysis = event.get("analysis", "")

    print(f"Writer Lambda triggered — brief_id: {brief_id}")
    print(f"Topics:   {topics}")
    print(f"Analysis: {len(analysis)} chars")

    try:
        briefing = asyncio.run(run_writer(brief_id, topics, analysis))

        print(f"Briefing ready — {len(briefing)} chars")

        boto3.client(
            "lambda",
            region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
        ).invoke(
            FunctionName   = f"{PROJECT_NAME}-critic",
            InvocationType = "Event",
            Payload        = json.dumps({
                "brief_id": brief_id,
                "briefing": briefing,
                "topics":   topics
            })
        )

        print(f"Critic Lambda invoked ✅")

        return {"statusCode": 200, "brief_id": brief_id}

    except Exception as e:
        print(f"Error in writer: {e}")
        import traceback
        traceback.print_exc()
        if brief_id:
            update_brief_failed(brief_id, str(e))
        raise