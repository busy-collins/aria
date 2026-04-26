"""
Shared function tools for all Aria agents.
"""
import os
import json
import httpx
import boto3
from datetime import datetime, UTC
from agents import function_tool

# ── Config ────────────────────────────────────────────────
ARIA_API_ENDPOINT = os.getenv("ARIA_API_ENDPOINT")
ARIA_API_KEY      = os.getenv("ARIA_API_KEY")
VECTOR_BUCKET     = os.getenv("VECTOR_BUCKET")
VECTOR_INDEX      = os.getenv("VECTOR_INDEX_NAME", "research-briefs")
AWS_REGION        = os.getenv("DEFAULT_AWS_REGION", "us-east-1")

# ── AWS clients (lazy init) ───────────────────────────────
_sagemaker = None
_s3vectors  = None

def get_sagemaker():
    global _sagemaker
    if _sagemaker is None:
        _sagemaker = boto3.client(
            "sagemaker-runtime",
            region_name=AWS_REGION
        )
    return _sagemaker

def get_s3vectors():
    global _s3vectors
    if _s3vectors is None:
        _s3vectors = boto3.client(
            "s3vectors",
            region_name=AWS_REGION
        )
    return _s3vectors


# ── Researcher tools ──────────────────────────────────────

@function_tool
def ingest_research_document(
    topic:    str,
    content:  str,
    source:   str = "web",
    brief_id: str = ""
) -> dict:
    """
    Store a research finding in the Aria knowledge base.

    Args:
        topic:    Topic or subject of the research
        content:  Research content to embed and store
        source:   URL or description of the source
        brief_id: ID of the brief that triggered this research
    """
    if not ARIA_API_ENDPOINT or not ARIA_API_KEY:
        return {
            "success": False,
            "error":   "ARIA_API_ENDPOINT or ARIA_API_KEY not configured"
        }

    document = {
        "text": content,
        "metadata": {
            "topic":     topic,
            "source":    source,
            "brief_id":  brief_id,
            "agent":     "researcher",
            "timestamp": datetime.now(UTC).isoformat()
        }
    }

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                ARIA_API_ENDPOINT,
                json    = document,
                headers = {"x-api-key": ARIA_API_KEY}
            )
            response.raise_for_status()
            result = response.json()

        return {
            "success":     True,
            "document_id": result.get("document_id"),
            "message":     f"Stored research for: {topic}"
        }

    except Exception as e:
        return {"success": False, "error": str(e)}


# ── Analyst tools ─────────────────────────────────────────

def _embed(text: str) -> list[float]:
    """Generate embedding via SageMaker."""
    endpoint = os.getenv("SAGEMAKER_ENDPOINT", "aria-embedding-endpoint")
    response = get_sagemaker().invoke_endpoint(
        EndpointName = endpoint,
        ContentType  = "application/json",
        Body         = json.dumps({"inputs": text})
    )
    result = json.loads(response["Body"].read().decode())
    if isinstance(result, list) and isinstance(result[0], list):
        if isinstance(result[0][0], list):
            return result[0][0]
        return result[0]
    return result


@function_tool
def search_knowledge_base(
    query:    str,
    top_k:    int = 5,
    brief_id: str = ""
) -> list:
    """
    Search the Aria knowledge base using semantic search.

    Args:
        query:    Natural language search query
        top_k:    Number of results to return (default 5)
        brief_id: Filter results by brief ID (optional)
    """
    try:
        vector = _embed(query)

        response = get_s3vectors().query_vectors(
            vectorBucketName = VECTOR_BUCKET,
            indexName        = VECTOR_INDEX,
            queryVector      = {"float32": vector},
            topK             = top_k,
            returnMetadata   = True
        )

        results = []
        for match in response.get("vectors", []):
            metadata = match.get("metadata", {})

            # Filter by brief_id if provided
            if brief_id and metadata.get("brief_id") != brief_id:
                continue

            results.append({
                "score":    match.get("score", 0),
                "topic":    metadata.get("topic", ""),
                "content":  metadata.get("text", ""),
                "source":   metadata.get("source", ""),
                "brief_id": metadata.get("brief_id", "")
            })

        return results

    except Exception as e:
        return [{"error": str(e)}]


@function_tool
def score_confidence(
    claim:    str,
    evidence: list[str]
) -> dict:
    """
    Score the confidence of a claim given supporting evidence.

    Args:
        claim:    The claim to evaluate
        evidence: List of evidence strings supporting the claim
    """
    # Simple heuristic — more evidence = higher confidence
    # In production this would use a separate LLM call
    base_score  = 0.3
    per_source  = 0.15
    score = min(base_score + (len(evidence) * per_source), 0.95)

    return {
        "claim":      claim,
        "confidence": round(score, 2),
        "evidence_count": len(evidence),
        "assessment": (
            "high"   if score >= 0.7 else
            "medium" if score >= 0.4 else
            "low"
        )
    }


# ── Writer tools ──────────────────────────────────────────

@function_tool
def save_briefing(
    brief_id: str,
    content:  str,
    topic:    str
) -> dict:
    """
    Save a completed briefing to the database.
    Only call this after writing the COMPLETE briefing content.

    Args:
        brief_id: ID of the research brief
        content:  The FULL written briefing (minimum 300 words)
        topic:    Main topic of the briefing
    """
    # Validate content is substantial before saving
    word_count = len(content.split())

    if word_count < 100:
        return {
            "success": False,
            "error":   f"Briefing too short ({word_count} words). Write the complete briefing first, then save it.",
            "hint":    "Your content must include Executive Summary, Key Findings, Analysis, and Recommendations sections."
        }

    print(f"\n{'='*60}")
    print(f"BRIEFING SAVED — {word_count} words")
    print(f"Topic: {topic}")
    print(f"Brief ID: {brief_id}")
    print(f"{'='*60}")
    print(content)
    print(f"{'='*60}\n")

    return {
        "success":    True,
        "brief_id":   brief_id,
        "topic":      topic,
        "word_count": word_count,
        "message":    f"Briefing saved successfully — {word_count} words"
    }


# ── Critic tools ──────────────────────────────────────────

@function_tool
def score_briefing(
    brief_id: str,
    content:  str
) -> dict:
    """
    Score a briefing for quality. Returns score and approval decision.

    Args:
        brief_id: ID of the briefing to score
        content:  Full briefing content to evaluate
    """
    # Heuristic scoring — replaced by LLM judge in production
    score = 7    # default — agent overrides with its own judgment

    return {
        "brief_id": brief_id,
        "score":    score,
        "approved": score >= 7,
        "message":  "Score based on critic agent evaluation"
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
    print(f"[HUMAN REVIEW REQUIRED] Brief {brief_id} — Score: {score} — {reason}")

    return {
        "brief_id": brief_id,
        "flagged":  True,
        "reason":   reason,
        "score":    score,
        "message":  "Briefing flagged for human review"
    }