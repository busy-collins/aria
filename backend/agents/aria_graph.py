"""
Aria Research Pipeline — LangGraph Orchestrator
Replaces the analyst → writer → critic Lambda chain
with a proper graph that has central control and retry logic.
"""
import os
import json
import httpx
import boto3
from typing import TypedDict
from concurrent.futures import ThreadPoolExecutor, as_completed
from langgraph.graph import StateGraph, END
from langchain_openai import ChatOpenAI


# ── Shared state — flows through every node ───────────────
class AriaState(TypedDict):
    brief_id:         str
    topics:           list
    research_results: list
    research_summary: str
    analysis:         str
    briefing:         str
    rewrite_count:    int
    critic_score:     float
    critic_feedback:  str
    approved:         bool
    status:           str
    pipeline_log:     list


# ── AWS helpers ───────────────────────────────────────────
def get_rds():
    return boto3.client(
        "rds-data",
        region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
    )


def update_status(brief_id: str, status: str):
    try:
        get_rds().execute_statement(
            resourceArn = os.getenv("AURORA_CLUSTER_ARN"),
            secretArn   = os.getenv("AURORA_SECRET_ARN"),
            database    = os.getenv("DATABASE_NAME", "aria"),
            sql         = "UPDATE briefs SET status=:s, updated_at=NOW() WHERE id=:id::uuid",
            parameters  = [
                {"name": "s",  "value": {"stringValue": status}},
                {"name": "id", "value": {"stringValue": brief_id}}
            ]
        )
        print(f"  status -> {status}")
    except Exception as e:
        print(f"  Warning: status update failed: {e}")


# ════════════════════════════════════════════════════════
# NODE 1 — RESEARCH
# Researches all topics in parallel
# ════════════════════════════════════════════════════════
def research_one_topic(brief_id: str, topic: str) -> dict:
    """Research a single topic — retries on 500 (cold start)."""
    researcher_url = os.getenv("RESEARCHER_URL", "")
    max_retries    = 3

    for attempt in range(1, max_retries + 1):
        try:
            print(f"  [RESEARCH] Attempt {attempt}/{max_retries}: {topic}")
            response = httpx.post(
                f"{researcher_url}/research",
                json    = {"brief_id": brief_id, "topic": topic},
                timeout = 300
            )
            if response.status_code == 200:
                content = response.json().get("content", "")
                print(f"  [OK] {topic}: {len(content)} chars")
                return {"topic": topic, "content": content, "success": True}

            print(f"  [FAIL] {topic}: HTTP {response.status_code}")

            if response.status_code == 500 and attempt < max_retries:
                import time
                wait = attempt * 15
            print(f"  [RETRY] Waiting {wait}s before retry (cold start)...")
            time.sleep(wait)
            continue

            return {"topic": topic, "content": "", "success": False}

        except httpx.TimeoutException:
            print(f"  [TIMEOUT] {topic} on attempt {attempt}")
            if attempt < max_retries:
                import time
                time.sleep(10)
                continue
            return {"topic": topic, "content": "", "success": False}

        except Exception as e:
            print(f"  [ERR] {topic}: {e}")
            return {"topic": topic, "content": "", "success": False}

    return {"topic": topic, "content": "", "success": False}


def research_node(state: AriaState) -> dict:
    """
    Researches ALL topics simultaneously using a thread pool.
    Partial failures are tolerated — pipeline continues
    as long as at least one topic succeeded.
    """
    print(f"\n[RESEARCH] Starting {len(state['topics'])} topics in parallel")
    update_status(state["brief_id"], "researching")

    # Fire all research requests simultaneously
    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(research_one_topic, state["brief_id"], topic): topic
            for topic in state["topics"]
        }
        for future in as_completed(futures):
            results.append(future.result(timeout=300))

    # Build combined summary for analyst
    summary = "\n\n".join(
        f"=== {r['topic']} ===\n{r['content']}"
        for r in results
    )

    succeeded = sum(1 for r in results if r["success"])
    log       = f"Research: {succeeded}/{len(results)} topics succeeded"
    print(f"[RESEARCH] {log}")

    return {
        "research_results": results,
        "research_summary": summary,
        "pipeline_log":     state.get("pipeline_log", []) + [log]
    }


# ════════════════════════════════════════════════════════
# NODE 2 — ANALYST
# Synthesises research into structured analysis
# ════════════════════════════════════════════════════════
def analyst_node(state: AriaState) -> dict:
    print(f"\n[ANALYST] Analysing research for {len(state['topics'])} topics")
    update_status(state["brief_id"], "analysing")

    llm    = ChatOpenAI(model="gpt-4o", temperature=0.3)
    prompt = (
        f"Brief ID: {state['brief_id']}\n"
        f"Topics: {', '.join(state['topics'])}\n\n"
        f"Research findings:\n{state['research_summary']}\n\n"
        "Produce structured analysis:\n"
        "- Key findings per topic (2024-2026 data only)\n"
        "- Confidence score for each finding (0-100%)\n"
        "- Market trends and patterns\n"
        "- Note any data gaps"
    )

    response = llm.invoke(prompt)
    analysis = response.content
    log      = f"Analyst: {len(analysis.split())} words produced"
    print(f"[ANALYST] {log}")

    return {
        "analysis":     analysis,
        "pipeline_log": state.get("pipeline_log", []) + [log]
    }


# ════════════════════════════════════════════════════════
# NODE 3 — WRITER
# Writes the briefing — called again if critic rejects it
# ════════════════════════════════════════════════════════
def writer_node(state: AriaState) -> dict:
    rewrite = state.get("rewrite_count", 0)
    label   = f"rewrite {rewrite}" if rewrite > 0 else "first draft"
    print(f"\n[WRITER] Writing briefing ({label})")
    update_status(state["brief_id"], "writing")

    llm = ChatOpenAI(model="gpt-4o", temperature=0.4)

    # On rewrites include critic feedback so writer improves
    feedback = ""
    if rewrite > 0 and state.get("critic_feedback"):
        feedback = (
            f"\nPREVIOUS SCORE: {state['critic_score']}/10"
            f"\nCRITIC FEEDBACK: {state['critic_feedback']}"
            f"\nAddress this feedback in your revision.\n"
        )

    prompt = (
        f"Brief ID: {state['brief_id']}\n"
        f"Topics: {', '.join(state['topics'])}\n"
        f"{feedback}\n"
        f"Analysis to convert into briefing:\n{state['analysis']}\n\n"
        "Write the COMPLETE briefing — minimum 400 words.\n"
        "Include specific data points, dates, and percentages.\n\n"
        "## Executive Summary\n"
        "## Key Findings\n"
        "## Market Analysis\n"
        "## Data and Evidence\n"
        "## Recommendations"
    )

    response = llm.invoke(prompt)
    briefing = response.content
    log      = f"Writer: {len(briefing.split())} words ({label})"
    print(f"[WRITER] {log}")

    return {
        "briefing":      briefing,
        "rewrite_count": rewrite + 1,
        "pipeline_log":  state.get("pipeline_log", []) + [log]
    }


# ════════════════════════════════════════════════════════
# NODE 4 — CRITIC
# Scores the briefing — routes back to writer if poor
# ════════════════════════════════════════════════════════
def critic_node(state: AriaState) -> dict:
    print(f"\n[CRITIC] Evaluating briefing quality")
    update_status(state["brief_id"], "reviewing")

    llm    = ChatOpenAI(model="gpt-4o-mini", temperature=0.1)
    prompt = (
        "Score this research briefing on 5 criteria (0-2 points each, 10 total):\n"
        "1. Accuracy     - are claims backed by evidence?\n"
        "2. Completeness - does it cover the topic fully?\n"
        "3. Specificity  - are there real numbers and dates?\n"
        "4. Citations    - are sources referenced?\n"
        "5. Structure    - is it well organised?\n\n"
        f"Briefing to evaluate:\n{state['briefing']}\n\n"
        "Reply with JSON only — no markdown, no explanation:\n"
        "{\"score\": 8.5, \"approved\": true, \"feedback\": \"your feedback here\"}"
    )

    response = llm.invoke(prompt)

    # Parse the JSON response
    try:
        raw = response.content.strip()
        # Strip markdown fences if model added them
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        result   = json.loads(raw.strip())
        score    = float(result.get("score", 5.0))
        approved = bool(result.get("approved", score >= 7))
        feedback = str(result.get("feedback", ""))
    except Exception as e:
        print(f"[CRITIC] Parse error: {e} — defaulting to 5.0")
        score    = 5.0
        approved = False
        feedback = "Could not parse evaluation"

    verdict = "APPROVED" if approved else "NEEDS REWRITE"
    log     = f"Critic: {score}/10 - {verdict}"
    print(f"[CRITIC] {log} — {feedback[:80]}")

    return {
        "critic_score":    score,
        "critic_feedback": feedback,
        "approved":        approved,
        "pipeline_log":    state.get("pipeline_log", []) + [log]
    }


# ════════════════════════════════════════════════════════
# NODE 5 — SAVE
# Persists the final briefing to Aurora
# ════════════════════════════════════════════════════════
def save_node(state: AriaState) -> dict:
    print(f"\n[SAVE] Saving briefing to Aurora")

    rds = get_rds()
    arn = os.getenv("AURORA_CLUSTER_ARN")
    sec = os.getenv("AURORA_SECRET_ARN")
    db  = os.getenv("DATABASE_NAME", "aria")

    rds.execute_statement(
        resourceArn = arn,
        secretArn   = sec,
        database    = db,
        sql         = (
            "INSERT INTO briefings (brief_id, content, critic_score, approved) "
            "VALUES (:bid::uuid, :content, :score, :approved) "
            "ON CONFLICT DO NOTHING"
        ),
        parameters  = [
            {"name": "bid",      "value": {"stringValue":  state["brief_id"]}},
            {"name": "content",  "value": {"stringValue":  state["briefing"]}},
            {"name": "score",    "value": {"doubleValue":  state["critic_score"]}},
            {"name": "approved", "value": {"booleanValue": state["approved"]}}
        ]
    )

    rds.execute_statement(
        resourceArn = arn,
        secretArn   = sec,
        database    = db,
        sql         = (
            "UPDATE briefs SET status='complete', updated_at=NOW() "
            "WHERE id=:id::uuid"
        ),
        parameters  = [
            {"name": "id", "value": {"stringValue": state["brief_id"]}}
        ]
    )

    log = f"Saved: score={state['critic_score']}/10 approved={state['approved']}"
    print(f"[SAVE] {log}")

    return {
        "status":       "complete",
        "pipeline_log": state.get("pipeline_log", []) + [log]
    }


# ════════════════════════════════════════════════════════
# NODE 6 — ERROR
# Marks brief as failed when all research fails
# ════════════════════════════════════════════════════════
def error_node(state: AriaState) -> dict:
    print(f"\n[ERROR] Pipeline failed for brief {state['brief_id']}")
    update_status(state["brief_id"], "failed")
    return {
        "status":       "failed",
        "pipeline_log": state.get("pipeline_log", []) + ["Pipeline failed"]
    }


# ════════════════════════════════════════════════════════
# ROUTING — decides which node runs next
# ════════════════════════════════════════════════════════
def route_after_research(state: AriaState) -> str:
    """After research — continue if any topic succeeded, else error."""
    succeeded = sum(1 for r in state.get("research_results", []) if r["success"])
    if succeeded == 0:
        print("[ROUTER] All research failed -> error")
        return "error"
    print(f"[ROUTER] {succeeded} topics succeeded -> analyst")
    return "analyst"


def route_after_critic(state: AriaState) -> str:
    """
    After critic evaluation:
        score >= 7 OR already rewritten twice -> save
        score < 7 AND rewrites remaining      -> back to writer
    """
    score    = state.get("critic_score", 0)
    approved = state.get("approved", False)
    rewrites = state.get("rewrite_count", 0)
    max_rewrites = 2

    if approved or score >= 7:
        print(f"[ROUTER] Score {score}/10 approved -> save")
        return "save"

    if rewrites >= max_rewrites:
        print(f"[ROUTER] Score {score}/10 max rewrites reached -> save anyway")
        return "save"

    print(f"[ROUTER] Score {score}/10 -> rewrite ({rewrites}/{max_rewrites})")
    return "writer"


# ════════════════════════════════════════════════════════
# BUILD THE GRAPH
# ════════════════════════════════════════════════════════
def build_aria_graph():
    """
    Builds and compiles the Aria LangGraph pipeline.

    Graph structure:
        research -> analyst -> writer -> critic
                                         |
                              score < 7  |  score >= 7
                                 v               v
                              writer           save
    """
    graph = StateGraph(AriaState)

    # Register all nodes
    graph.add_node("research", research_node)
    graph.add_node("analyst",  analyst_node)
    graph.add_node("writer",   writer_node)
    graph.add_node("critic",   critic_node)
    graph.add_node("save",     save_node)
    graph.add_node("error",    error_node)

    # Entry point
    graph.set_entry_point("research")

    # Edges
    graph.add_conditional_edges(
        "research",
        route_after_research,
        {"analyst": "analyst", "error": "error"}
    )
    graph.add_edge("analyst", "writer")
    graph.add_edge("writer",  "critic")
    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {"save": "save", "writer": "writer"}
    )
    graph.add_edge("save",  END)
    graph.add_edge("error", END)

    return graph.compile()


# ════════════════════════════════════════════════════════
# LAMBDA HANDLER
# This replaces analyst_handler.py as the SQS entry point
# ════════════════════════════════════════════════════════
def handler(event, context):
    """
    Single Lambda entry point for the entire pipeline.
    Triggered by SQS. Runs the full LangGraph graph.
    """
    import sys
    sys.path.insert(0, "/var/task")
    from shared.secrets import get_openai_api_key, get_langsmith_api_key

    # Setup observability first
    try:
        os.environ["OPENAI_API_KEY"]    = get_openai_api_key()
        os.environ["LANGSMITH_API_KEY"] = get_langsmith_api_key()
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "aria-production")
        print("Observability configured")
    except Exception as e:
        print(f"Observability setup failed: {e}")

    # Parse SQS event
    record   = event["Records"][0]
    body     = json.loads(record["body"])
    brief_id = body.get("brief_id")
    topics   = body.get("topics", [])

    print(f"\nLangGraph pipeline starting")
    print(f"  brief_id: {brief_id}")
    print(f"  topics:   {topics}")

    # Build and run the graph
    graph = build_aria_graph()

    initial_state = {
        "brief_id":         brief_id,
        "topics":           topics,
        "research_results": [],
        "research_summary": "",
        "analysis":         "",
        "briefing":         "",
        "rewrite_count":    0,
        "critic_score":     0.0,
        "critic_feedback":  "",
        "approved":         False,
        "status":           "researching",
        "pipeline_log":     [f"Pipeline started — {len(topics)} topics"]
    }

    final_state = graph.invoke(initial_state)

    # Print audit trail
    print("\nPipeline complete. Log:")
    for entry in final_state.get("pipeline_log", []):
        print(f"  -> {entry}")

    return {
        "statusCode": 200,
        "brief_id":   brief_id,
        "status":     final_state["status"],
        "score":      final_state["critic_score"]
    }