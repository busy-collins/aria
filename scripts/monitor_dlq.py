# Create scripts/monitor_dlq.py
#!/usr/bin/env python3
"""
Monitor the dead letter queue for failed pipeline jobs.
Run periodically or add to GitHub Actions.
"""
import boto3
import json
import os
from dotenv import load_dotenv

load_dotenv()

sqs = boto3.client("sqs", region_name="us-east-1")

DLQ_URL = "https://sqs.us-east-1.amazonaws.com/975022060655/aria-jobs-dlq"

def check_dlq():
    response = sqs.get_queue_attributes(
        QueueUrl       = DLQ_URL,
        AttributeNames = ["ApproximateNumberOfMessages"]
    )

    count = int(response["Attributes"]["ApproximateNumberOfMessages"])

    if count > 0:
        print(f"⚠️  {count} failed jobs in DLQ")
        # Read messages to see what failed
        msgs = sqs.receive_message(
            QueueUrl            = DLQ_URL,
            MaxNumberOfMessages = 10
        )
        for msg in msgs.get("Messages", []):
            body = json.loads(msg["Body"])
            print(f"  Failed brief_id: {body.get('brief_id')}")
            print(f"  Topics: {body.get('topics')}")
    else:
        print("✅ DLQ is empty — no failed jobs")

if __name__ == "__main__":
    check_dlq()