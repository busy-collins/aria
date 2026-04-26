"""
Test the graph without the Researcher App Runner.
Uses mock research data so you can test analyst/writer/critic
without needing App Runner running.
"""
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock
from dotenv import load_dotenv

load_dotenv()
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "shared"))


MOCK_RESEARCH = """
Source: https://investor.nvidia.com/2025-q3
Date: November 2025
NVIDIA Q3 2025 revenue: $35.1B, up 94% YoY.
Data center revenue: $30.8B, up 112%.
Market share: 80% of AI accelerator market.
Blackwell B200 GPU: 30x faster than H100.
TSMC producing at 4nm, 92% allocated to NVIDIA.
"""


class MockRDS:
    def execute_statement(self, **kwargs):
        print(f"  [DB] {kwargs.get('sql','')[:60].strip()}")
        return {"records": []}


def mock_research(brief_id, topic):
    print(f"  [MOCK RESEARCH] {topic}")
    return {"topic": topic, "content": MOCK_RESEARCH, "success": True}


if __name__ == "__main__":
    print("Testing graph with mock research (no App Runner needed)")
    print("="*60)

    with patch("aria_graph.get_rds", lambda: MockRDS()), \
         patch("aria_graph.research_one_topic", mock_research):

        from aria_graph import build_aria_graph

        graph = build_aria_graph()
        final = graph.invoke({
            "brief_id":         "offline-test-001",
            "topics":           ["NVIDIA AI chip market 2025"],
            "research_results": [],
            "research_summary": "",
            "analysis":         "",
            "briefing":         "",
            "rewrite_count":    0,
            "critic_score":     0.0,
            "critic_feedback":  "",
            "approved":         False,
            "status":           "researching",
            "pipeline_log":     ["Offline test started"]
        })

    print()
    print(f"Status: {final['status']}")
    print(f"Score:  {final['critic_score']}/10")
    print(f"Words:  {len(final['briefing'].split())}")
    print()
    print("Briefing preview:")
    print(final['briefing'][:400])
