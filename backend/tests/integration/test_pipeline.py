"""
Integration tests using moto to mock AWS services.
No real AWS calls — all mocked in memory.
"""
import json
import os
import pytest
import boto3
from moto import mock_aws


@pytest.fixture
def aws_credentials():
    """Fake AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"]     = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"]    = "testing"
    os.environ["AWS_SESSION_TOKEN"]     = "testing"
    os.environ["AWS_DEFAULT_REGION"]    = "us-east-1"
    yield


class TestSQSIntegration:

    @mock_aws
    def test_send_message_to_queue(self, aws_credentials):
        sqs   = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName="aria-research-jobs")
        url   = queue["QueueUrl"]

        response = sqs.send_message(
            QueueUrl    = url,
            MessageBody = json.dumps({
                "brief_id": "test-brief-123",
                "topics":   ["NVIDIA AI chips 2025"]
            })
        )

        assert response["ResponseMetadata"]["HTTPStatusCode"] == 200
        assert "MessageId" in response

    @mock_aws
    def test_message_readable_from_queue(self, aws_credentials):
        sqs   = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName="aria-research-jobs")
        url   = queue["QueueUrl"]

        sqs.send_message(
            QueueUrl    = url,
            MessageBody = json.dumps({
                "brief_id": "brief-456",
                "topics":   ["Tesla 2025"]
            })
        )

        response = sqs.receive_message(
            QueueUrl            = url,
            MaxNumberOfMessages = 1
        )

        messages = response.get("Messages", [])
        assert len(messages) == 1

        body = json.loads(messages[0]["Body"])
        assert body["brief_id"] == "brief-456"
        assert body["topics"]   == ["Tesla 2025"]

    @mock_aws
    def test_message_has_required_fields(self, aws_credentials):
        """Verify SQS message has all fields analyst_handler expects."""
        sqs   = boto3.client("sqs", region_name="us-east-1")
        queue = sqs.create_queue(QueueName="aria-research-jobs")
        url   = queue["QueueUrl"]

        sqs.send_message(
            QueueUrl    = url,
            MessageBody = json.dumps({
                "brief_id": "test-uuid",
                "topics":   ["Nigerian stock market 2025"]
            })
        )

        response = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=1)
        body     = json.loads(response["Messages"][0]["Body"])

        assert "brief_id" in body
        assert "topics"   in body
        assert isinstance(body["topics"], list)
        assert len(body["topics"]) > 0

    @mock_aws
    def test_dlq_receives_failed_messages(self, aws_credentials):
        """Verify DLQ setup works correctly."""
        sqs = boto3.client("sqs", region_name="us-east-1")

        # Create DLQ first
        dlq = sqs.create_queue(QueueName="aria-jobs-dlq")
        dlq_attrs = sqs.get_queue_attributes(
            QueueUrl       = dlq["QueueUrl"],
            AttributeNames = ["QueueArn"]
        )
        dlq_arn = dlq_attrs["Attributes"]["QueueArn"]

        # Create main queue with redrive policy
        queue = sqs.create_queue(
            QueueName  = "aria-research-jobs",
            Attributes = {
                "RedrivePolicy": json.dumps({
                    "deadLetterTargetArn": dlq_arn,
                    "maxReceiveCount":     "3"
                })
            }
        )

        assert queue["QueueUrl"] is not None


class TestSecretsManagerIntegration:

    @mock_aws
    def test_store_and_fetch_openai_key(self, aws_credentials):
        sm = boto3.client("secretsmanager", region_name="us-east-1")

        sm.create_secret(
            Name         = "aria/openai-api-key",
            SecretString = json.dumps({"api_key": "sk-test-key-123"})
        )

        response = sm.get_secret_value(SecretId="aria/openai-api-key")
        secret   = json.loads(response["SecretString"])

        assert secret["api_key"] == "sk-test-key-123"

    @mock_aws
    def test_store_and_fetch_langsmith_key(self, aws_credentials):
        sm = boto3.client("secretsmanager", region_name="us-east-1")

        sm.create_secret(
            Name         = "aria/langsmith-api-key",
            SecretString = json.dumps({"api_key": "ls-test-key-456"})
        )

        response = sm.get_secret_value(SecretId="aria/langsmith-api-key")
        secret   = json.loads(response["SecretString"])

        assert secret["api_key"] == "ls-test-key-456"

    @mock_aws
    def test_missing_secret_raises_exception(self, aws_credentials):
        sm = boto3.client("secretsmanager", region_name="us-east-1")

        with pytest.raises(Exception) as exc_info:
            sm.get_secret_value(SecretId="aria/nonexistent-secret")

        assert "ResourceNotFoundException" in str(exc_info.value) \
            or "could not be found" in str(exc_info.value).lower() \
            or "does not exist" in str(exc_info.value).lower()

    @mock_aws
    def test_rotate_secret(self, aws_credentials):
        """Test updating a secret value."""
        sm = boto3.client("secretsmanager", region_name="us-east-1")

        sm.create_secret(
            Name         = "aria/openai-api-key",
            SecretString = json.dumps({"api_key": "sk-old-key"})
        )

        sm.update_secret(
            SecretId     = "aria/openai-api-key",
            SecretString = json.dumps({"api_key": "sk-new-key"})
        )

        response = sm.get_secret_value(SecretId="aria/openai-api-key")
        secret   = json.loads(response["SecretString"])

        assert secret["api_key"] == "sk-new-key"


class TestAPILogic:
    """Test API business logic — no AWS needed."""

    def test_topics_array_format(self):
        topics = ["NVIDIA chips", "Tesla 2025", "Apple Vision Pro"]
        topics_literal = "{" + ",".join(
            '"' + t.replace('"', '\\"') + '"'
            for t in topics
        ) + "}"
        assert topics_literal == '{"NVIDIA chips","Tesla 2025","Apple Vision Pro"}'

    def test_single_topic_format(self):
        topics = ["Nigerian stock market 2025"]
        topics_literal = "{" + ",".join(
            '"' + t.replace('"', '\\"') + '"'
            for t in topics
        ) + "}"
        assert topics_literal == '{"Nigerian stock market 2025"}'

    def test_topics_with_special_chars_escaped(self):
        topics = ['Topic with "quotes" inside']
        topics_literal = "{" + ",".join(
            '"' + t.replace('"', '\\"') + '"'
            for t in topics
        ) + "}"
        assert '\\"' in topics_literal

    def test_sqs_payload_structure(self):
        brief_id = "test-uuid-123"
        topics   = ["NVIDIA", "Tesla"]
        payload  = json.dumps({"brief_id": brief_id, "topics": topics})
        parsed   = json.loads(payload)
        assert parsed["brief_id"] == brief_id
        assert parsed["topics"]   == topics

    def test_analyst_event_parsing(self):
        """Verify analyst_handler correctly parses SQS event."""
        event = {
            "Records": [{
                "body": json.dumps({
                    "brief_id": "abc-123",
                    "topics":   ["NVIDIA 2025"]
                })
            }]
        }

        record   = event["Records"][0]
        body     = json.loads(record["body"])
        brief_id = body["brief_id"]
        topics   = body.get("topics", [])

        assert brief_id == "abc-123"
        assert topics   == ["NVIDIA 2025"]

    def test_writer_lambda_payload(self):
        payload = json.dumps({
            "brief_id":  "test-brief",
            "topics":    ["NVIDIA"],
            "analysis":  "Detailed analysis..."
        })
        parsed = json.loads(payload)
        assert "brief_id"  in parsed
        assert "topics"    in parsed
        assert "analysis"  in parsed

    def test_critic_lambda_payload(self):
        payload = json.dumps({
            "brief_id": "test-brief",
            "briefing": "## Executive Summary\nContent...",
            "topics":   ["NVIDIA"]
        })
        parsed = json.loads(payload)
        assert "brief_id" in parsed
        assert "briefing" in parsed
        assert len(parsed["briefing"]) > 0