"""
AWS Secrets Manager helper — fetch secrets at runtime.
Cached per Lambda execution context for performance.
"""
import os
import json
import boto3
from functools import lru_cache

_client = None

def get_client():
    global _client
    if _client is None:
        _client = boto3.client(
            "secretsmanager",
            region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
        )
    return _client


@lru_cache(maxsize=10)
def get_secret(secret_name: str) -> dict:
    """
    Fetch a secret from AWS Secrets Manager.
    Cached with lru_cache — only fetches once per Lambda instance.
    """
    response = get_client().get_secret_value(SecretId=secret_name)
    return json.loads(response["SecretString"])


def get_openai_api_key() -> str:
    """Get OpenAI API key from Secrets Manager."""
    secret_name = os.getenv("OPENAI_SECRET_NAME", "aria/openai-api-key")
    return get_secret(secret_name)["api_key"]


def get_langsmith_api_key() -> str:
    """Get LangSmith API key from Secrets Manager."""
    secret_name = os.getenv("LANGSMITH_SECRET_NAME", "aria/langsmith-api-key")
    return get_secret(secret_name)["api_key"]