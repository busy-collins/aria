"""
Local SQS worker — polls SQS and runs LangGraph pipeline.
Simulates what the analyst Lambda does in production.
Run alongside uvicorn for full local development.
"""
import os
import sys
import json
import time
import boto3
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "agents"))
sys.path.insert(0, str(ROOT / "shared"))

from shared.secrets import get_openai_api_key, get_langsmith_api_key

# ── Setup ─────────────────────────────────────────────────
os.environ["OPENAI_API_KEY"]    = get_openai_api_key()
os.environ["LANGSMITH_API_KEY"] = get_langsmith_api_key()
os.environ["LANGSMITH_TRACING"] = "true"
os.environ["LANGSMITH_PROJECT"] = "aria-production"

SQS_QUEUE_URL = os.getenv("SQS_QUEUE_URL")
sqs           = boto3.client("sqs", region_name="us-east-1")

print("="*50)
print("ARIA PIPELINE WORKER — LOCAL")
print("="*50)
print(f"Queue: {SQS_QUEUE_URL}")
print("Waiting for briefs...")
print()


def process_message(body: dict):
    """Run the full LangGraph pipeline for one brief."""
    brief_id = body.get("brief_id")
    topics   = body.get("topics", [])

    print(f"\nProcessing brief: {brief_id}")
    print(f"Topics: {topics}")

    from aria_graph import build_aria_graph

    graph = build_aria_graph()

    final = graph.invoke({
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
        "pipeline_log":     [f"Local worker started"]
    })

    print(f"\nComplete — status={final['status']} score={final['critic_score']}/10")


# ── Poll loop ─────────────────────────────────────────────
while True:
    try:
        response = sqs.receive_message(
            QueueUrl            = SQS_QUEUE_URL,
            MaxNumberOfMessages = 1,
            WaitTimeSeconds     = 10    # long polling
        )

        messages = response.get("Messages", [])

        if not messages:
            print(".", end="", flush=True)
            continue

        for message in messages:
            body = json.loads(message["Body"])
            print(f"\nMessage received: {body.get('brief_id')}")

            try:
                process_message(body)

                # Delete from queue on success
                sqs.delete_message(
                    QueueUrl      = SQS_QUEUE_URL,
                    ReceiptHandle = message["ReceiptHandle"]
                )
                print("Message deleted from queue ✅")

            except Exception as e:
                print(f"Pipeline error: {e}")
                import traceback
                traceback.print_exc()
                # Leave in queue — will retry or go to DLQ

    except KeyboardInterrupt:
        print("\nWorker stopped")
        break
    except Exception as e:
        print(f"Worker error: {e}")
        time.sleep(5)