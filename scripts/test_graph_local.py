"""
Local LangGraph test — runs the full pipeline locally.
    Real OpenAI calls
    Real Researcher App Runner
    Mocked Aurora (prints SQL instead of executing)

Run: python scripts/test_graph_local.py
"""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

# ── Setup paths ───────────────────────────────────────────
# scripts/ is at project root — .env is also at project root
PROJECT_ROOT = Path(__file__).parent.parent
BACKEND_ROOT = PROJECT_ROOT / "backend"

sys.path.insert(0, str(BACKEND_ROOT))
sys.path.insert(0, str(BACKEND_ROOT / "agents"))
sys.path.insert(0, str(BACKEND_ROOT / "shared"))

# .env is at project root alongside scripts/
load_dotenv(PROJECT_ROOT / ".env")
ROOT = BACKEND_ROOT

# ── Verify required env vars ──────────────────────────────
def check_env():
    required = {
        "OPENAI_API_KEY":  "OpenAI API key",
        "RESEARCHER_URL":  "Researcher App Runner URL",
    }
    missing = []
    for key, label in required.items():
        if not os.getenv(key):
            missing.append(f"  {key} — {label}")

    if missing:
        print("Missing environment variables:")
        for m in missing:
            print(m)
        print("\nMake sure your .env file is in the project root")
        sys.exit(1)

    # Set observability
    try:
        from shared.secrets import get_openai_api_key, get_langsmith_api_key
        os.environ["OPENAI_API_KEY"]    = get_openai_api_key()
        os.environ["LANGSMITH_API_KEY"] = get_langsmith_api_key()
        os.environ["LANGSMITH_TRACING"] = "true"
        os.environ["LANGSMITH_PROJECT"] = "aria-local-test"
        print("✅ Secrets loaded from AWS Secrets Manager")
    except Exception:
        # Fall back to .env values
        print("✅ Using API keys from .env file")

check_env()

print(f"  OpenAI:     {os.getenv('OPENAI_API_KEY')[:12]}...")
print(f"  Researcher: {os.getenv('RESEARCHER_URL')}")


# ════════════════════════════════════════════════════════
# MOCK AURORA
# Prints SQL statements instead of executing them
# so we don't write test data to production DB
# ════════════════════════════════════════════════════════

class MockRDSClient:
    """
    Drop-in replacement for boto3 rds-data client.
    Prints SQL instead of executing against Aurora.
    """
    def execute_statement(self, **kwargs):
        sql    = kwargs.get("sql", "").strip()
        params = kwargs.get("parameters", [])

        # Pretty print the SQL
        print(f"\n  [AURORA MOCK] {sql[:70]}")
        for p in params:
            name  = p.get("name")
            value = p.get("value", {})
            val   = (
                value.get("stringValue")  or
                value.get("doubleValue")  or
                value.get("booleanValue") or
                "null"
            )
            if name in ("content", "analysis", "briefing"):
                val = f"{str(val)[:50]}..." if len(str(val)) > 50 else val
            print(f"    :{name} = {val}")

        return {"records": [], "numberOfRecordsUpdated": 1}


def mock_get_rds():
    return MockRDSClient()


# ════════════════════════════════════════════════════════
# RUN THE GRAPH
# ════════════════════════════════════════════════════════

def run_local_graph(
    topics:   list[str],
    brief_id: str = "local-test-001"
) -> dict:
    """
    Run the full LangGraph pipeline locally.
    Aurora is mocked — everything else is real.
    """
    from aria_graph import build_aria_graph

    print("\n" + "="*60)
    print("ARIA LANGGRAPH — LOCAL TEST")
    print("="*60)
    print(f"Brief ID: {brief_id}")
    print(f"Topics:   {topics}")
    print(f"Time:     {time.strftime('%H:%M:%S')}")
    print("="*60)

    start = time.time()

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
        "pipeline_log":     [f"Local test — {len(topics)} topic(s)"]
    }

    # Run with mocked Aurora
    with patch("aria_graph.get_rds", mock_get_rds):
        final = graph.invoke(initial_state)

    elapsed = time.time() - start

    # ── Print results ─────────────────────────────────────
    print("\n" + "="*60)
    print("PIPELINE COMPLETE")
    print("="*60)
    print(f"  Status:        {final['status']}")
    print(f"  Critic score:  {final['critic_score']}/10")
    print(f"  Approved:      {final['approved']}")
    print(f"  Rewrites:      {max(0, final['rewrite_count'] - 1)}")
    print(f"  Total time:    {elapsed:.0f}s")

    # ── Pipeline log ──────────────────────────────────────
    print("\nPipeline log:")
    for entry in final.get("pipeline_log", []):
        print(f"  → {entry}")

    # ── Research results ──────────────────────────────────
    print("\nResearch results:")
    for r in final.get("research_results", []):
        icon    = "✅" if r["success"] else "❌"
        content = r.get("content", "")
        print(f"  {icon} {r['topic']}: {len(content)} chars")

    # ── Briefing preview ──────────────────────────────────
    briefing = final.get("briefing", "")
    if briefing:
        word_count = len(briefing.split())
        print(f"\nBriefing: {word_count} words")
        print("-"*60)
        print(briefing[:800])
        if len(briefing) > 800:
            print(f"\n... ({word_count - len(briefing[:800].split())} more words)")
    else:
        print("\nNo briefing produced")

    # ── Quality checks ────────────────────────────────────
    print("\n" + "="*60)
    print("QUALITY CHECKS")
    print("="*60)

    checks = {
        "pipeline_complete":  final["status"] in ("complete", "failed"),
        "pipeline_succeeded": final["status"] == "complete",
        "has_briefing":       len(briefing) > 100,
        "no_placeholder":     not any(
            p in briefing.lower() for p in [
                "has been successfully saved",
                "word count of",
                "feel free to ask"
            ]
        ),
        "minimum_words":      len(briefing.split()) >= 300,
        "has_sections":       all(
            s in briefing.lower() for s in [
                "executive summary", "key findings", "recommendations"
            ]
        ),
        "real_score":         1.0 <= final["critic_score"] <= 10.0,
        "has_2025_data":      "2025" in briefing or "2026" in briefing,
    }

    passed = 0
    for check, result in checks.items():
        icon = "✅" if result else "❌"
        print(f"  {icon} {check}")
        if result:
            passed += 1

    total = len(checks)
    print(f"\n  {passed}/{total} checks passed")

    if passed == total:
        print("\n✅ All checks passed — LangGraph working correctly")
    elif passed >= total * 0.7:
        print("\n⚠️  Most checks passed — review failures above")
    else:
        print("\n❌ Multiple checks failing — review pipeline logs")

    return final


# ════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test LangGraph pipeline locally")
    parser.add_argument(
        "--topics",
        nargs   = "+",
        default = ["NVIDIA AI chip market 2025"],
        help    = "Topics to research (default: NVIDIA AI chip market 2025)"
    )
    parser.add_argument(
        "--brief-id",
        default = f"local-test-{int(time.time())}",
        help    = "Brief ID to use (default: local-test-{timestamp})"
    )
    args = parser.parse_args()

    result = run_local_graph(
        topics   = args.topics,
        brief_id = args.brief_id
    )

    sys.exit(0 if result["status"] == "complete" else 1)