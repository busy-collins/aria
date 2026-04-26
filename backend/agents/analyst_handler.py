"""
Analyst Lambda Handler
Triggered by SQS — orchestrates the full research pipeline:
    1. Calls Researcher App Runner for each topic (web browsing)
    2. Runs Analyst agent on combined research (RAG + fact checking)
    3. Invokes Writer Lambda with analysis results
"""
import os
import sys
import json
import boto3
import asyncio
import httpx

sys.path.insert(0, "/var/task")

from openai import AsyncOpenAI
from agents import Agent, Runner, OpenAIChatCompletionsModel
from langsmith import traceable
from langsmith.wrappers import wrap_openai
from shared.context import analyst_instructions
from shared.tools import search_knowledge_base, score_confidence
from shared.secrets import get_openai_api_key, get_langsmith_api_key

# ── AWS clients ───────────────────────────────────────────
rds = boto3.client(
    "rds-data",
    region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
)

CLUSTER_ARN    = os.getenv("AURORA_CLUSTER_ARN")
SECRET_ARN     = os.getenv("AURORA_SECRET_ARN")
DATABASE       = os.getenv("DATABASE_NAME", "aria")
RESEARCHER_URL = os.getenv("RESEARCHER_URL", "").rstrip("/")
PROJECT_NAME   = os.getenv("PROJECT_NAME", "aria")


# ── Observability ─────────────────────────────────────────
def setup_observability():
    """Configure LangSmith and OpenAI — call before anything else."""
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


# ── Researcher ────────────────────────────────────────────
def call_researcher(topic: str, brief_id: str) -> str:
    """
    Call the Researcher App Runner service.
    Researcher browses the web via Playwright MCP
    and ingests findings into S3 Vectors tagged with brief_id.
    Returns a summary of what was researched.
    """
    if not RESEARCHER_URL:
        print("Warning: RESEARCHER_URL not set — skipping web research")
        return f"No research available for topic: {topic}"

    print(f"  Calling researcher for: {topic}")

    try:
        with httpx.Client(timeout=300.0) as client:
            response = client.post(
                f"{RESEARCHER_URL}/research",
                json = {
                    "topic":    topic,
                    "brief_id": brief_id
                }
            )
            response.raise_for_status()
            result = response.text
            print(f"  Research complete for: {topic} ({len(result)} chars)")
            return result

    except httpx.TimeoutException:
        print(f"  Warning: Researcher timed out for topic: {topic}")
        return f"Research timed out for topic: {topic}"

    except Exception as e:
        print(f"  Warning: Researcher failed for topic: {topic} — {e}")
        return f"Research failed for topic: {topic}"


def research_all_topics(topics: list[str], brief_id: str) -> str:
    """
    Call Researcher for each topic and combine results.
    Topics are researched sequentially to avoid overwhelming
    the App Runner service.
    """
    print(f"Starting research for {len(topics)} topics...")

    summaries = []
    for topic in topics:
        summary = call_researcher(topic, brief_id)
        summaries.append(f"## Topic: {topic}\n{summary}")

    combined = "\n\n---\n\n".join(summaries)
    print(f"All research complete — {len(combined)} chars total")
    return combined


# ── Database helpers ──────────────────────────────────────
def update_brief_status(brief_id: str, status: str):
    """Update brief status in Aurora — non-fatal."""
    try:
        rds.execute_statement(
            resourceArn = CLUSTER_ARN,
            secretArn   = SECRET_ARN,
            database    = DATABASE,
            sql         = """
                UPDATE briefs
                SET status     = :status,
                    updated_at = NOW()
                WHERE id = :id::uuid
            """,
            parameters  = [
                {"name": "status", "value": {"stringValue": status}},
                {"name": "id",     "value": {"stringValue": brief_id}}
            ]
        )
    except Exception as e:
        print(f"Warning: Could not update brief status: {e}")


def save_analysis_to_jobs(brief_id: str, analysis: str):
    """Save analysis result to jobs table for audit trail."""
    try:
        rds.execute_statement(
            resourceArn = CLUSTER_ARN,
            secretArn   = SECRET_ARN,
            database    = DATABASE,
            sql         = """
                INSERT INTO jobs
                    (user_id, brief_id, job_type, status, result)
                SELECT
                    u.id,
                    :brief_id::uuid,
                    'analysis',
                    'complete',
                    :result::jsonb
                FROM briefs b
                JOIN users u ON u.id = b.user_id
                WHERE b.id = :brief_id::uuid
            """,
            parameters  = [
                {"name": "brief_id", "value": {"stringValue": brief_id}},
                {"name": "result",   "value": {"stringValue": json.dumps({
                    "analysis_preview": analysis[:500],
                    "analysis_length":  len(analysis)
                })}}
            ]
        )
        print(f"Analysis saved to jobs table ✅")
    except Exception as e:
        print(f"Warning: Could not save to jobs: {e}")


def update_brief_failed(brief_id: str, error: str):
    """Mark brief as failed in Aurora."""
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


# ── Analyst agent ─────────────────────────────────────────
@traceable(name="analyst-lambda")
async def run_analyst(
    brief_id:          str,
    combined_research: str
) -> str:
    """
    Run the analyst agent on combined research findings.
    Searches S3 Vectors for context, fact-checks claims,
    scores confidence, and writes structured analysis.
    Traced in LangSmith.
    """
    raw_client     = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    wrapped_client = wrap_openai(raw_client)

    analyst = Agent(
        name         = "Aria Analyst",
        instructions = analyst_instructions(),
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o",
            openai_client = wrapped_client
        ),
        tools = [search_knowledge_base, score_confidence]
    )

    result = await Runner.run(
    analyst,
    input     = f"""
Brief ID: {brief_id}

Research findings from web browsing (focus on 2024-2026 data only):
{combined_research}

Your job:
1. Search the knowledge base for research tagged with brief_id={brief_id}
2. DISCARD any findings older than 2024
3. Identify key themes from CURRENT data only
4. Fact-check the most important 2025/2026 claims
5. Score confidence — recent data = high, old data = discard
6. Write detailed structured analysis using only current information

If research data seems outdated, note this clearly.
Today's date context: We are in 2025-2026.
""",
    max_turns = 10
)

    return result.final_output


# ── Main handler ──────────────────────────────────────────
def handler(event, context):
    """
    SQS Lambda handler — entry point for the pipeline.

    SQS message format:
    {
        "brief_id": "uuid",
        "topics":   ["topic 1", "topic 2", "topic 3"]
    }

    Pipeline:
        1. Call Researcher for each topic → web browsing → S3 Vectors
        2. Run Analyst agent → RAG retrieval → structured analysis
        3. Invoke Writer Lambda → briefing synthesis
    """
    setup_observability()

    print(f"Analyst Lambda triggered — {len(event['Records'])} records")

    for record in event["Records"]:
        brief_id = None

        try:
            # ── Parse SQS message ─────────────────────────
            body     = json.loads(record["body"])
            brief_id = body["brief_id"]
            topics   = body.get("topics", [])

            print(f"Brief ID: {brief_id}")
            print(f"Topics:   {topics}")

            # ── Mark brief as running ─────────────────────
            update_brief_status(brief_id, "running")

            # ── Step 1: Research each topic via App Runner ─
            # Researcher browses web and ingests to S3 Vectors
            combined_research = research_all_topics(topics, brief_id)

            # ── Step 2: Analyse combined research ─────────
            # Analyst retrieves from S3 Vectors + fact checks
            print("Running analyst agent...")
            analysis = asyncio.run(
                run_analyst(brief_id, combined_research)
            )

            print(f"Analysis complete — {len(analysis)} chars")

            # ── Step 3: Save to audit trail ───────────────
            save_analysis_to_jobs(brief_id, analysis)

            # ── Step 4: Invoke Writer Lambda ──────────────
            boto3.client(
                "lambda",
                region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
            ).invoke(
                FunctionName   = f"{PROJECT_NAME}-writer",
                InvocationType = "Event",    # async — do not wait
                Payload        = json.dumps({
                    "brief_id":  brief_id,
                    "topics":    topics,
                    "analysis":  analysis
                })
            )

            print(f"Writer Lambda invoked ✅")

        except Exception as e:
            print(f"Error processing brief {brief_id}: {e}")
            import traceback
            traceback.print_exc()
            if brief_id:
                update_brief_failed(brief_id, str(e))
            raise    # re-raise so SQS retries

    return {"statusCode": 200}