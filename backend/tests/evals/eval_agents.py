"""
Evaluations for Researcher and Analyst agents.
Run: python tests/evals/eval_agents.py
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "shared"))

os.environ.setdefault("DEFAULT_AWS_REGION", "us-east-1")
os.environ.setdefault("AURORA_CLUSTER_ARN", "placeholder")
os.environ.setdefault("AURORA_SECRET_ARN",  "placeholder")
os.environ.setdefault("DATABASE_NAME",      "aria")
os.environ.setdefault("PROJECT_NAME",       "aria")

if not os.getenv("OPENAI_API_KEY"):
    print("❌ OPENAI_API_KEY not set — check your .env file")
    sys.exit(1)

print(f"✅ OpenAI key: {os.getenv('OPENAI_API_KEY')[:8]}...")


MOCK_RESEARCH_NVIDIA = """
Source: https://investor.nvidia.com/news/2025-q3-results
Date: November 2025
Content: NVIDIA reported revenue of $35.1 billion for Q3 2025, up 94% from Q3 2024.
Data center revenue reached $30.8 billion, up 112% year-on-year.

Source: https://www.bloomberg.com/nvidia-market-share-2025
Date: November 2025
Content: NVIDIA holds approximately 80% of the AI accelerator market.
AMD MI300X holds 12%, Intel Gaudi 3 holds 5%, others 3%.

Source: https://www.reuters.com/technology/nvidia-blackwell-2025
Date: January 2025
Content: NVIDIA launched Blackwell B200 GPU in Q1 2025. It is 30x
faster than H100 for AI inference. TSMC manufacturing at 4nm.

Source: https://www.idc.com/ai-chip-market-2025
Date: October 2025
Content: Global AI chip market projected to reach $500B by 2028.
CAGR of 38% expected from 2025-2028.
"""

MOCK_RESEARCH_TESLA = """
Source: https://ir.tesla.com/annual-reports/2025
Date: February 2025
Content: Tesla reported $97.7B revenue for FY2024. Vehicle deliveries
reached 1.79M units, up 3% YoY.

Source: https://www.reuters.com/tesla-china-2025
Date: March 2025
Content: Tesla faces competition from BYD. Chinese market share
declined from 14% to 9% in 2024.

Source: https://electrek.co/tesla-fsd-2025
Date: January 2025
Content: Tesla Full Self-Driving v13 deployed to 700,000 vehicles.
"""


async def eval_researcher_health():
    """Check Researcher App Runner is up and configured."""
    import httpx

    researcher_url = os.getenv("RESEARCHER_URL", "").rstrip("/")

    if not researcher_url:
        print("❌ RESEARCHER_URL not set — skipping")
        return False

    print("\nChecking researcher health...")

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(f"{researcher_url}/health")

        if response.status_code != 200:
            print(f"❌ Health check failed: {response.status_code}")
            return False

        data    = response.json()
        healthy = (
            data.get("status") == "healthy" and
            data.get("openai_configured") is True
        )

        print(f"  Status:            {data.get('status')}")
        print(f"  OpenAI configured: {data.get('openai_configured')}")
        print(f"  {'✅ Healthy' if healthy else '❌ Unhealthy'}")
        return healthy

    except Exception as e:
        print(f"❌ Health check error: {e}")
        return False


async def eval_researcher_finds_current_data():
    """Researcher must return 2024-2026 sources."""
    import httpx

    researcher_url = os.getenv("RESEARCHER_URL", "").rstrip("/")

    if not researcher_url:
        print("❌ RESEARCHER_URL not set — skipping researcher content eval")
        return None

    print("\nRunning researcher content eval...")
    print("  (Calls real App Runner — takes 2-5 minutes)")

    try:
        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{researcher_url}/research",
                json = {
                    "brief_id": "eval-researcher-001",
                    "topic":    "NVIDIA AI chip revenue market share 2025",
                }
            )

        if response.status_code != 200:
            print(f"❌ Researcher returned {response.status_code}")
            return 0

        data    = response.json()
        content = data.get("content") or data.get("result") or str(data)

        results = {}
        results["not_empty"]       = len(content) > 100
        results["has_2025_data"]   = "2025" in content or "2026" in content
        results["no_errors"]       = not any(
            p in content.lower() for p in ["error", "failed", "unable to"]
        )

        keywords = ["nvidia", "chip", "gpu", "market", "revenue"]
        matches  = sum(1 for k in keywords if k in content.lower())
        results["topic_relevant"]  = matches >= 3
        results["keyword_matches"] = matches

        results["no_stale_dates"]  = not any(
            y in content for y in ["2021", "2022"]
        )
        results["has_sources"]     = any(
            s in content.lower() for s in ["http", "source", "according", "reuters", "bloomberg"]
        )

    except Exception as e:
        print(f"❌ Researcher error: {e}")
        return 0

    print("\n" + "=" * 50)
    print("RESEARCHER EVAL RESULTS")
    print("=" * 50)

    passed = 0
    for check, result in results.items():
        if check == "keyword_matches":
            print(f"  Keyword matches: {result}/5")
            continue
        status = "✅" if result else "❌"
        print(f"  {status} {check}")
        if isinstance(result, bool) and result:
            passed += 1

    total = sum(1 for v in results.values() if isinstance(v, bool))
    score = (passed / total) * 10
    print(f"\nEval score: {score:.1f}/10  ({passed}/{total} checks passed)")

    if score < 7:
        print("\n⚠️  Researcher needs improvement")
    else:
        print("\n✅ Researcher performing well")

    return score


async def eval_analyst_produces_structured_analysis():
    """Analyst must produce structured analysis from research data."""
    from openai import AsyncOpenAI
    from agents import Agent, Runner, OpenAIChatCompletionsModel

    print("\nRunning analyst structure eval...")
    print("  (Uses real OpenAI — takes 30-60 seconds)")

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
        from context import analyst_instructions
        instructions = analyst_instructions()
    except ImportError:
        instructions = (
            "You are Aria's Analyst. Synthesise research into structured analysis. "
            "Focus on 2024-2026 data only. Include confidence scores."
        )

    analyst = Agent(
        name         = "Aria Analyst Eval",
        instructions = instructions,
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o",
            openai_client = client,
        ),
    )

    result = await Runner.run(
        analyst,
        input = f"""
Brief ID: eval-analyst-001
Topics: NVIDIA AI chip market 2025

Research findings:
{MOCK_RESEARCH_NVIDIA}

Analyse these findings and produce structured analysis with:
1. Key themes (minimum 3)
2. Confidence scores for each finding
3. Data gaps or limitations
4. Overall market assessment
""",
        max_turns = 5,
    )

    analysis = result.final_output
    results  = {}

    word_count                  = len(analysis.split())
    results["minimum_length"]   = word_count >= 150
    results["word_count"]       = word_count

    results["has_confidence"]   = any(
        c in analysis.lower() for c in
        ["confidence", "%", "high", "medium", "low", "likely", "approximately"]
    )

    data_checks                 = ["35", "80%", "2025", "NVIDIA", "revenue"]
    matches                     = sum(1 for d in data_checks if d in analysis)
    results["references_data"]  = matches >= 3
    results["data_matches"]     = matches

    results["no_stale_dates"]   = not any(y in analysis for y in ["2021", "2022"])

    structure_keywords          = ["finding", "theme", "analysis", "market",
                                   "revenue", "growth", "competition"]
    results["is_structured"]    = sum(
        1 for s in structure_keywords if s in analysis.lower()
    ) >= 4

    results["no_refusal"]       = not any(
        r in analysis.lower() for r in ["i cannot", "i'm unable", "as an ai"]
    )

    print("\n" + "=" * 50)
    print("ANALYST EVAL RESULTS — STRUCTURE")
    print("=" * 50)

    passed = 0
    for check, result in results.items():
        if check in ("word_count", "data_matches"):
            label = "Word count" if check == "word_count" else "Data matches"
            print(f"  {label}: {result}")
            continue
        status = "✅" if result else "❌"
        print(f"  {status} {check}")
        if isinstance(result, bool) and result:
            passed += 1

    total = sum(1 for v in results.values() if isinstance(v, bool))
    score = (passed / total) * 10
    print(f"\nEval score: {score:.1f}/10  ({passed}/{total} checks passed)")

    if score < 7:
        print("\n⚠️  Analyst needs improvement")
        print(f"Preview:\n{analysis[:400]}")
    else:
        print("\n✅ Analyst performing well")
        print(f"Preview:\n{analysis[:200]}...")

    return score


async def eval_analyst_handles_multiple_topics():
    """Analyst must cover ALL topics not just the first one."""
    from openai import AsyncOpenAI
    from agents import Agent, Runner, OpenAIChatCompletionsModel

    print("\nRunning multi-topic analyst eval...")

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
        from context import analyst_instructions
        instructions = analyst_instructions()
    except ImportError:
        instructions = "You are Aria's Analyst. Analyse all research findings."

    analyst = Agent(
        name         = "Aria Analyst Multi-Topic Eval",
        instructions = instructions,
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o-mini",
            openai_client = client,
        ),
    )

    combined = f"""
=== Topic 1: NVIDIA AI chip market 2025 ===
{MOCK_RESEARCH_NVIDIA}

=== Topic 2: Tesla shares outlook 2025 ===
{MOCK_RESEARCH_TESLA}
"""

    result = await Runner.run(
        analyst,
        input = f"""
Brief ID: eval-analyst-002
Topics: NVIDIA AI chip market 2025, Tesla shares outlook 2025

Research findings:
{combined}

Analyse BOTH topics. Cover each one.
""",
        max_turns = 5,
    )

    analysis = result.final_output
    results  = {}

    results["covers_nvidia"]       = "nvidia" in analysis.lower()
    results["covers_tesla"]        = "tesla" in analysis.lower()
    results["covers_both"]         = results["covers_nvidia"] and results["covers_tesla"]

    word_count                     = len(analysis.split())
    results["sufficient_length"]   = word_count >= 200
    results["word_count"]          = word_count

    results["has_current_data"]    = "2025" in analysis

    print("\n" + "=" * 50)
    print("ANALYST EVAL RESULTS — MULTI-TOPIC")
    print("=" * 50)

    passed = 0
    for check, result in results.items():
        if check == "word_count":
            print(f"  Word count: {result}")
            continue
        status = "✅" if result else "❌"
        print(f"  {status} {check}")
        if isinstance(result, bool) and result:
            passed += 1

    total = sum(1 for v in results.values() if isinstance(v, bool))
    score = (passed / total) * 10
    print(f"\nEval score: {score:.1f}/10  ({passed}/{total} checks passed)")

    if score < 8:
        print("\n⚠️  Analyst not covering all topics")
    else:
        print("\n✅ Analyst covering all topics correctly")

    return score


async def eval_analyst_rejects_stale_data():
    """Analyst must ignore pre-2024 sources."""
    from openai import AsyncOpenAI
    from agents import Agent, Runner, OpenAIChatCompletionsModel

    print("\nRunning stale data rejection eval...")

    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    stale_research = """
Source: https://old-report.com/nvidia-2022
Date: March 2022
Content: NVIDIA revenue was $8.2B in Q3 2022. RTX 3090 is the flagship GPU.

Source: https://ancient-news.com/ai-chips-2021
Date: June 2021
Content: AI chip market worth $6B in 2021. NVIDIA A100 just launched.

Source: https://nvidia-2025.com/quarterly-results
Date: October 2025
Content: NVIDIA Q3 2025 revenue hit $35.1B, driven by Blackwell B200 demand.
"""

    try:
        from context import analyst_instructions
        instructions = analyst_instructions()
    except ImportError:
        instructions = (
            "You are Aria's Analyst. ONLY use data from 2024-2026. "
            "Explicitly discard any sources older than 2024."
        )

    analyst = Agent(
        name         = "Aria Analyst Stale-Data Eval",
        instructions = instructions,
        model        = OpenAIChatCompletionsModel(
            model         = "gpt-4o-mini",
            openai_client = client,
        ),
    )

    result = await Runner.run(
        analyst,
        input = f"""
Brief ID: eval-stale-001
Topics: NVIDIA AI chip market

Research (mix of old and new data):
{stale_research}

Analyse findings. ONLY use 2024-2026 data. Discard anything older.
""",
        max_turns = 3,
    )

    analysis = result.final_output
    results  = {}

    results["ignores_2021"]          = "2021" not in analysis and "$6B" not in analysis
    results["ignores_2022"]          = "8.2B" not in analysis
    results["uses_2025_data"]        = "35.1" in analysis or "2025" in analysis
    results["acknowledges_recency"]  = any(
        p in analysis.lower() for p in
        ["limited", "only", "recent", "current", "2025", "latest"]
    )

    print("\n" + "=" * 50)
    print("ANALYST EVAL RESULTS — STALE DATA REJECTION")
    print("=" * 50)

    passed = 0
    for check, result in results.items():
        status = "✅" if result else "❌"
        print(f"  {status} {check}")
        if isinstance(result, bool) and result:
            passed += 1

    total = sum(1 for v in results.values() if isinstance(v, bool))
    score = (passed / total) * 10
    print(f"\nEval score: {score:.1f}/10  ({passed}/{total} checks passed)")

    if score < 7:
        print("\n⚠️  Analyst using stale data — update analyst_instructions()")
    else:
        print("\n✅ Analyst correctly rejecting stale data")

    return score


if __name__ == "__main__":
    async def main():
        print("=" * 50)
        print("ARIA RESEARCHER + ANALYST EVALUATIONS")
        print("=" * 50)
        print("Warning: uses real OpenAI API — costs ~$0.20-0.50")

        scores = {}

        # ── Researcher ────────────────────────────────────
        print("\n" + "─" * 50)
        print("SECTION 1: RESEARCHER")
        print("─" * 50)

        healthy = await eval_researcher_health()
        scores["researcher_health"] = 10.0 if healthy else 0.0

        if healthy:
            scores["researcher_content"] = await eval_researcher_finds_current_data() or 0.0
        else:
            print("⚠️  Skipping content eval — researcher unhealthy")
            scores["researcher_content"] = None

        # ── Analyst ───────────────────────────────────────
        print("\n" + "─" * 50)
        print("SECTION 2: ANALYST")
        print("─" * 50)

        scores["analyst_structure"]   = await eval_analyst_produces_structured_analysis()
        scores["analyst_multi_topic"] = await eval_analyst_handles_multiple_topics()
        scores["analyst_recency"]     = await eval_analyst_rejects_stale_data()

        # ── Summary ───────────────────────────────────────
        print("\n" + "=" * 50)
        print("FINAL EVAL SUMMARY")
        print("=" * 50)

        valid   = [v for v in scores.values() if v is not None]
        overall = sum(valid) / len(valid) if valid else 0.0

        for name, score in scores.items():
            if score is None:
                print(f"  {'—':2s} {name:30s}: SKIPPED")
            else:
                bar    = "█" * int(score) + "░" * (10 - int(score))
                status = "✅" if score >= 7 else "⚠️ "
                print(f"  {status} {name:28s}: {score:4.1f}/10  {bar}")

        print(f"\n  Overall agent quality: {overall:.1f}/10")

        if overall >= 8:
            print("\n✅ All agents performing well — ready for production")
        elif overall >= 6:
            print("\n⚠️  Agents acceptable — review failing evals")
        else:
            print("\n❌ Agents need improvement — check prompts in context.py")

    asyncio.run(main())