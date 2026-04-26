"""
Critic Lambda Handler
Invoked by Writer Lambda — scores briefing quality and saves to Aurora.
Uses local score_briefing tool to capture real score from agent.
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
from shared.context import critic_instructions
from shared.secrets import get_openai_api_key, get_langsmith_api_key

# ── DO NOT import score_briefing from shared.tools ────────
# The local @function_tool below captures the real score
# from shared.tools import score_briefing   ← REMOVED

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
_score_result: dict = {}


# ── Observability ─────────────────────────────────────────
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


# ── Database helpers ──────────────────────────────────────
def save_to_db(
    brief_id: str,
    content:  str,
    score:    float,
    approved: bool
):
    """Save briefing with critic score to Aurora."""
    try:
        rds.execute_statement(
            resourceArn = CLUSTER_ARN,
            secretArn   = SECRET_ARN,
            database    = DATABASE,
            sql         = """
                INSERT INTO briefings
                    (brief_id, content, critic_score, approved)
                VALUES
                    (:brief_id::uuid, :content, :score, :approved)
                ON CONFLICT DO NOTHING
            """,
            parameters  = [
                {"name": "brief_id",  "value": {"stringValue": brief_id}},
                {"name": "content",   "value": {"stringValue": content}},
                {"name": "score",     "value": {"doubleValue": score}},
                {"name": "approved",  "value": {"booleanValue": approved}}
            ]
        )
        print(f"Briefing saved to Aurora ✅")
    except Exception as e:
        print(f"Error saving briefing: {e}")
        raise


def update_brief_complete(brief_id: str):
    try:
        rds.execute_statement(
            resourceArn = CLUSTER_ARN,
            secretArn   = SECRET_ARN,
            database    = DATABASE,
            sql         = """
                UPDATE briefs
                SET status     = 'complete',
                    updated_at = NOW()
                WHERE id = :id::uuid
            """,
            parameters  = [
                {"name": "id", "value": {"stringValue": brief_id}}
            ]
        )
        print(f"Brief marked complete ✅")
    except Exception as e:
        print(f"Warning: Could not mark complete: {e}")


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
        print(f"Warning: Could not mark failed: {e}")


# ── Local score_briefing — captures real score ────────────
@function_tool
def score_briefing(
    brief_id: str,
    score:    float,
    feedback: str,
    approved: bool
) -> dict:
    """
    Record your quality score after evaluating the briefing.
    Call this once after completing your full evaluation.

    Args:
        brief_id: ID of the briefing being scored
        score:    Your honest score from 1.0 to 10.0
                  1-3: Poor, missing key sections
                  4-6: Acceptable but lacks specifics
                  7-8: Good, well structured with evidence
                  9-10: Excellent, specific data and citations
        feedback: Specific actionable feedback (2-3 sentences)
        approved: True only if score >= 7
    """
    global _score_result

    # Validate score range
    score = max(1.0, min(10.0, float(score)))

    print(f"Score captured ✅ — {score}/10 — approved: {approved}")
    print(f"Feedback: {feedback[:100]}...")

    _score_result = {
        "score":    score,
        "approved": approved and score >= 7,
        "feedback": feedback
    }

    return {
        "success":  True,
        "brief_id": brief_id,
        "score":    score,
        "approved": approved and score >= 7,
        "message":  f"Score {score}/10 recorded."
    }


@function_tool
def flag_for_human_review(
    brief_id: str,
    reason:   str,
    score:    float
) -> dict:
    """
    Flag a briefing for human review when quality is insufficient.

    Args:
        brief_id: ID of the briefing
        reason:   Why it needs human review
        score:    The quality score that triggered the flag
    """
    print(f"[HUMAN REVIEW] Brief {brief_id} — Score: {score} — {reason}")
    return {
        "flagged":  True,
        "brief_id": brief_id,
        "reason":   reason,
        "score":    score
    }


# ── Critic agent ──────────────────────────────────────────
@traceable(name="critic-lambda")
async def run_critic(brief_id: str, briefing: str) -> dict:
    """
    Run the critic agent.
    Returns the REAL score captured from score_briefing tool call.
    """
    global _score_result
    _score_result = {}    # reset for each run

    raw_client     = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    wrapped_client = wrap_openai(raw_client)

    critic = Agent(
        name         = "Aria Critic",
        instructions = critic_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o-mini",
            openai_client = wrapped_client
        ),
        tools = [score_briefing, flag_for_human_review]
    )

    await Runner.run(
        critic,
        input     = f"""
You are a rigorous research briefing evaluator. Be honest — do not default to 7.

Evaluate this briefing for brief_id={brief_id}:

{briefing}

Score on EACH criterion (max 2 points each = 10 total):

1. ACCURACY (0-2): Are claims supported by evidence?
   - 0: No evidence, all vague claims
   - 1: Some evidence but inconsistent
   - 2: All major claims backed by sources

2. COMPLETENESS (0-2): Does it cover the topic fully?
   - 0: Missing major sections
   - 1: Covers basics but lacks depth
   - 2: Thorough coverage of all aspects

3. SPECIFICITY (0-2): Are there real numbers and data points?
   - 0: Only vague statements
   - 1: Some numbers but mostly generic
   - 2: Specific percentages, dates, company names

4. CITATIONS (0-2): Are sources cited?
   - 0: No citations at all
   - 1: Some sources mentioned
   - 2: Sources cited for all major claims

5. STRUCTURE (0-2): Is it well organised?
   - 0: No clear structure
   - 1: Basic structure present
   - 2: Clear professional structure throughout

Add up your score then call score_briefing with:
- brief_id: {brief_id}
- score: your total (1.0-10.0, be honest)
- feedback: 2-3 sentences of specific actionable feedback
- approved: true only if score >= 7

If score < 6 also call flag_for_human_review.
""",
        max_turns = 4
    )

    # Use real captured score
    if _score_result:
        print(f"Real score: {_score_result['score']}/10")
        return _score_result

    # Fallback — parse from final output if tool not called
    print("Warning: score_briefing not called — using fallback score 5")
    return {
        "score":    5.0,
        "approved": False,
        "feedback": "Could not evaluate properly — resubmit brief"
    }


# ── Handler ───────────────────────────────────────────────
def handler(event, context):
    """
    Critic Lambda handler.
    Invoked directly by Writer Lambda.
    """
    setup_observability()

    brief_id = event.get("brief_id")
    briefing = event.get("briefing", "")

    print(f"Critic Lambda triggered — brief_id: {brief_id}")
    print(f"Briefing length: {len(briefing)} chars")

    if not briefing or len(briefing) < 50:
        print("Warning: Briefing too short to evaluate")
        if brief_id:
            update_brief_failed(brief_id, "Briefing content too short")
        return {"statusCode": 400}

    try:
        result   = asyncio.run(run_critic(brief_id, briefing))
        score    = result["score"]
        approved = result["approved"]

        print(f"Final — score: {score}/10 approved: {approved}")

        save_to_db(
            brief_id = brief_id,
            content  = briefing,
            score    = score,
            approved = approved
        )

        update_brief_complete(brief_id)

        print(f"Pipeline complete ✅ — brief_id: {brief_id}")

        return {
            "statusCode": 200,
            "brief_id":   brief_id,
            "score":      score,
            "approved":   approved
        }

    except Exception as e:
        print(f"Error in critic: {e}")
        import traceback
        traceback.print_exc()
        if brief_id:
            update_brief_failed(brief_id, str(e))
        raise