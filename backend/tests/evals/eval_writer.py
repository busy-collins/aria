"""
Evaluations for the Writer and Critic agents.
Tests real content quality — uses real OpenAI calls.
Run: python tests/evals/eval_writer.py
"""
import asyncio
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Fix path — point to backend root ─────────────────────
ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "shared"))

# ── Set required env vars before importing ────────────────
os.environ.setdefault("DEFAULT_AWS_REGION", "us-east-1")
os.environ.setdefault("AURORA_CLUSTER_ARN", "placeholder")
os.environ.setdefault("AURORA_SECRET_ARN",  "placeholder")
os.environ.setdefault("DATABASE_NAME",      "aria")
os.environ.setdefault("PROJECT_NAME",       "aria")

# ── Verify OpenAI key ─────────────────────────────────────
if not os.getenv("OPENAI_API_KEY"):
    print("❌ OPENAI_API_KEY not set — check your .env file")
    sys.exit(1)

print(f"✅ OpenAI key found: {os.getenv('OPENAI_API_KEY')[:8]}...")

from writer_handler import run_writer, _saved_content


SAMPLE_ANALYSIS = """
Brief ID: eval-test-001
Topics: NVIDIA AI chip market 2025

Key Findings:
- NVIDIA H100 GPU revenue reached $18.4B in Q3 2025, up 112% YoY
- Market share: NVIDIA 80%, AMD 12%, Intel 5%, Others 3%
- Blackwell B200 GPU launched Q1 2025, 30x faster than H100
- TSMC produces 92% of NVIDIA chips at 4nm process
- AI chip market projected to reach $500B by 2028

Confidence: 85% average across all findings
Sources: NVIDIA investor relations, Bloomberg, Reuters
"""


async def eval_writer_produces_real_content():
    """Eval: Writer must produce real briefing not confirmation message."""
    print("\nRunning writer eval...")
    print("(This makes real OpenAI API calls — takes 30-60 seconds)")

    briefing = await run_writer(
        brief_id = "eval-test-001",
        topics   = ["NVIDIA AI chip market 2025"],
        analysis = SAMPLE_ANALYSIS
    )

    results = {}

    # Check 1: Not a placeholder
    placeholders = [
        "has been successfully saved",
        "word count of",
        "briefing saved",
        "feel free to ask",
    ]
    results["no_placeholder"] = not any(
        p.lower() in briefing.lower() for p in placeholders
    )

    # Check 2: Minimum length
    word_count                = len(briefing.split())
    results["minimum_length"] = word_count >= 200
    results["word_count"]     = word_count

    # Check 3: Has required sections
    sections = ["executive summary", "key findings", "recommendations"]
    results["has_sections"] = all(
        s in briefing.lower() for s in sections
    )

    # Check 4: Contains specific data from analysis
    results["contains_data"] = all(
        d in briefing for d in ["NVIDIA", "2025", "GPU"]
    )

    # Check 5: No stale dates
    results["no_stale_dates"] = not any(
        y in briefing for y in ["2022", "2023"]
    )

    # ── Print results ─────────────────────────────────────
    print("\n" + "=" * 50)
    print("WRITER EVAL RESULTS")
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
        print("\n⚠️  Writer needs improvement")
        print(f"Preview:\n{briefing[:300]}")
    else:
        print("\n✅ Writer is performing well")

    return score


async def eval_critic_scores_honestly():
    """Eval: Critic must score honestly — not always 7."""
    from critic_handler import run_critic

    print("\nRunning critic eval...")

    test_cases = [
        {
            "name":         "High quality briefing with sources",
            "expected_min": 7.5,
            "content": """
## Executive Summary
NVIDIA reported record Q3 2025 revenue of $35.1B, up 94% YoY,
driven by data center AI chip demand. The H100 and new Blackwell
B200 GPUs dominate enterprise AI deployments globally.

## Key Findings
- Revenue: $35.1B Q3 2025 — Source: NVIDIA IR (Oct 2025)
- Data center: $30.8B, up 112% YoY — Source: Bloomberg (Nov 2025)
- Market share: 80% of AI accelerator market — Source: IDC 2025
- B200 GPU: 30x faster than H100 for inference workloads
- AMD MI300X gaining traction: 12% market share — Source: Reuters

## Market Analysis
NVIDIA dominance stems from its CUDA software ecosystem built
over 15 years. Competitors face 3-5 year gap to replicate.
Cloud providers AWS, Azure, GCP all signed multi-year supply deals.

## Data & Evidence
- $35.1B revenue Q3 2025 (Source: NVIDIA Investor Relations, Oct 2025)
- 80% AI chip market share (Source: IDC, November 2025)
- TSMC 4nm allocation: 92% dedicated to NVIDIA (Source: DigiTimes)

## Recommendations
1. Monitor AMD MI300X adoption in hyperscaler deployments
2. Track Blackwell B200 supply chain constraints at TSMC
3. Watch for Intel Gaudi 3 enterprise deals in H1 2026
            """,
        },
        {
            "name":         "Poor quality — vague with no data",
            "expected_max": 4.0,
            "content": (
                "NVIDIA is a good company. They make chips. "
                "The market is growing. People like AI. Things are going well."
            ),
        },
    ]

    print("\n" + "=" * 50)
    print("CRITIC EVAL RESULTS")
    print("=" * 50)

    all_passed = True

    for case in test_cases:
        result = await run_critic("eval-test", case["content"])
        score  = result["score"]

        if "expected_min" in case:
            passed = score >= case["expected_min"]
            print(f"\n  {case['name']}")
            print(f"    Score:    {score}/10")
            print(f"    Expected: >= {case['expected_min']}")
            print(f"    Result:   {'✅ PASS' if passed else '❌ FAIL'}")
            print(f"    Feedback: {result.get('feedback', '')[:100]}")
            if not passed:
                all_passed = False

        if "expected_max" in case:
            passed = score <= case["expected_max"]
            print(f"\n  {case['name']}")
            print(f"    Score:    {score}/10")
            print(f"    Expected: <= {case['expected_max']}")
            print(f"    Result:   {'✅ PASS' if passed else '❌ FAIL'}")
            if not passed:
                all_passed = False

    label = "✅ PASS — critic scoring honestly" if all_passed else "❌ FAIL — critic not differentiating quality"
    print(f"\nOverall: {label}")
    return all_passed


if __name__ == "__main__":
    async def main():
        print("=" * 50)
        print("ARIA WRITER + CRITIC EVALUATIONS")
        print("=" * 50)
        print("Warning: uses real OpenAI API — costs ~$0.10-0.20")

        writer_score = await eval_writer_produces_real_content()
        critic_pass  = await eval_critic_scores_honestly()

        print("\n" + "=" * 50)
        print("FINAL EVAL SUMMARY")
        print("=" * 50)
        print(f"  Writer score:  {writer_score:.1f}/10")
        print(f"  Critic honest: {'✅' if critic_pass else '❌'}")

        if writer_score >= 8 and critic_pass:
            print("\n✅ All evals passing — agents behaving correctly")
        else:
            print("\n⚠️  Some evals failing — review agent prompts")

    asyncio.run(main())