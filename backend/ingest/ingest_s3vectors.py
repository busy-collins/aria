"""
Lambda function for ingesting text into S3 Vectors with embeddings.
Aria Research Intelligence Assistant — Ingest Pipeline
"""

import json
import os
import boto3
import datetime
import uuid

# ── Environment variables ─────────────────────────────────
VECTOR_BUCKET      = os.environ.get("VECTOR_BUCKET", "aria-vectors")
SAGEMAKER_ENDPOINT = os.environ.get("SAGEMAKER_ENDPOINT")
INDEX_NAME         = os.environ.get("INDEX_NAME", "research-briefs")
PROJECT_NAME       = os.environ.get("PROJECT_NAME", "aria")

# ── AWS clients ───────────────────────────────────────────
sagemaker_runtime = boto3.client("sagemaker-runtime")
s3_vectors        = boto3.client("s3vectors")


def get_embedding(text: str) -> list[float]:
    """
    Get embedding vector from SageMaker endpoint.
    Handles all HuggingFace nesting formats:
        [[[embedding]]]  → extract result[0][0]
        [[embedding]]    → extract result[0]
        [embedding]      → return as-is
    """
    response = sagemaker_runtime.invoke_endpoint(
        EndpointName = SAGEMAKER_ENDPOINT,
        ContentType  = "application/json",
        Body         = json.dumps({"inputs": text})
    )

    result = json.loads(response["Body"].read().decode())

    if isinstance(result, list) and len(result) > 0:
        if isinstance(result[0], list) and len(result[0]) > 0:
            if isinstance(result[0][0], list):
                return result[0][0]   # [[[embedding]]]
            return result[0]          # [[embedding]]
    return result                     # [embedding]


def lambda_handler(event, context):
    """
    Main Lambda handler for Aria ingest pipeline.

    Expected request body:
    {
        "text": "Research content to embed and store",
        "metadata": {
            "topic":      "NVIDIA AI chips",
            "source":     "https://...",
            "agent":      "researcher",
            "brief_id":   "uuid-of-the-research-brief"
        }
    }

    Returns:
    {
        "document_id": "uuid",
        "message":     "Document indexed successfully"
    }
    """
    try:
        # ── Parse request body ────────────────────────────
        # API Gateway sends body as a JSON string
        # Direct Lambda invocation sends body as a dict
        if isinstance(event.get("body"), str):
            body = json.loads(event["body"])
        else:
            body = event.get("body", {})

        text     = body.get("text")
        metadata = body.get("metadata", {})

        # ── Validate input ────────────────────────────────
        if not text:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "Missing required field: text"})
            }

        if not SAGEMAKER_ENDPOINT:
            return {
                "statusCode": 500,
                "body": json.dumps({"error": "SAGEMAKER_ENDPOINT not configured"})
            }

        # ── Generate embedding ────────────────────────────
        print(f"Getting embedding for text ({len(text)} chars): {text[:100]}...")
        embedding = get_embedding(text)
        print(f"Embedding generated: {len(embedding)} dimensions")

        # ── Store in S3 Vectors ───────────────────────────
        vector_id = str(uuid.uuid4())

        print(f"Storing vector {vector_id} in bucket: {VECTOR_BUCKET}, index: {INDEX_NAME}")

        s3_vectors.put_vectors(
            vectorBucketName = VECTOR_BUCKET,
            indexName        = INDEX_NAME,
            vectors          = [{
                "key":  vector_id,
                "data": {"float32": embedding},
                "metadata": {
                    "text":      text,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "project":   PROJECT_NAME,
                    **metadata   # topic, source, agent, brief_id etc.
                }
            }]
        )

        print(f"Successfully stored vector: {vector_id}")

        return {
            "statusCode": 200,
            "headers":    {"Content-Type": "application/json"},
            "body": json.dumps({
                "message":     "Document indexed successfully",
                "document_id": vector_id
            })
        }

    except sagemaker_runtime.exceptions.ModelError as e:
        print(f"SageMaker model error: {e}")
        return {
            "statusCode": 502,
            "body": json.dumps({"error": f"Embedding model error: {str(e)}"})
        }

    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }