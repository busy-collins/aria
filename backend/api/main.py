"""
Aria API — FastAPI backend
"""
import os
import json
import logging
import boto3
import httpx
import jwt
import re
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from mangum import Mangum
from dotenv import load_dotenv

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Aria API")

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)

# ── AWS clients ───────────────────────────────────────────
rds = boto3.client(
    "rds-data",
    region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
)
sqs = boto3.client(
    "sqs",
    region_name=os.getenv("DEFAULT_AWS_REGION", "us-east-1")
)

CLUSTER_ARN    = os.getenv("AURORA_CLUSTER_ARN")
SECRET_ARN     = os.getenv("AURORA_SECRET_ARN")
DATABASE       = os.getenv("DATABASE_NAME", "aria")
SQS_QUEUE_URL  = os.getenv("SQS_QUEUE_URL")
CLERK_JWKS_URL = os.getenv("CLERK_JWKS_URL")


def execute_sql(sql: str, parameters: list = None) -> dict:
    kwargs = {
        "resourceArn": CLUSTER_ARN,
        "secretArn":   SECRET_ARN,
        "database":    DATABASE,
        "sql":         sql,
    }
    if parameters:
        kwargs["parameters"] = parameters
    return rds.execute_statement(**kwargs)


# ── Auth ──────────────────────────────────────────────────
security      = HTTPBearer()
_jwks_cache: dict = {}


def get_jwks() -> dict:
    global _jwks_cache
    if _jwks_cache:
        return _jwks_cache
    response    = httpx.get(CLERK_JWKS_URL, timeout=10)
    response.raise_for_status()
    _jwks_cache = response.json()
    return _jwks_cache


def verify_token(token: str) -> dict:
    try:
        jwks       = get_jwks()
        header     = jwt.get_unverified_header(token)
        kid        = header.get("kid")
        public_key = None

        for key in jwks.get("keys", []):
            if key.get("kid") == kid:
                public_key = jwt.algorithms.RSAAlgorithm.from_jwk(
                    json.dumps(key)
                )
                break

        if not public_key:
            raise HTTPException(status_code=401, detail="Public key not found")

        payload = jwt.decode(
            token,
            public_key,
            algorithms = ["RS256"],
            options    = {"verify_exp": True}
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
    except Exception as e:
        logger.error(f"Token verification error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")


async def get_user_id(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> str:
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="No user ID in token")
    return user_id


# ── Helpers ───────────────────────────────────────────────
def parse_topics(row_value: dict) -> list[str]:
    """Parse Aurora Data API text[] — handles arrayValue and stringValue."""
    if not row_value or row_value.get("isNull"):
        return []

    # arrayValue format (newer Aurora Data API)
    if "arrayValue" in row_value:
        values = row_value["arrayValue"].get("stringValues", [])
        return [t.strip() for t in values if t.strip()]

    # stringValue format
    topics_str = row_value.get("stringValue", "")
    if not topics_str or topics_str in ("{}", "NULL", "null"):
        return []

    cleaned   = topics_str.strip("{}")
    if not cleaned:
        return []

    topics    = []
    current   = ""
    in_quotes = False

    for char in cleaned:
        if char == '"':
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            topic = current.strip().strip('"')
            if topic:
                topics.append(topic)
            current = ""
        else:
            current += char

    last = current.strip().strip('"')
    if last:
        topics.append(last)

    return [t for t in topics if t.strip()]


# ── Guardrails ────────────────────────────────────────────
class TopicValidator:
    MAX_TOPIC_LENGTH = 200
    MIN_TOPIC_LENGTH = 5
    MAX_TOPICS       = 5

    BLOCKED_PATTERNS = [
        r"ignore (previous|above|all) instructions",
        r"you are now",
        r"system prompt",
        r"jailbreak",
        r"<script>",
        r"javascript:",
        r"eval\(",
    ]

    BLOCKED_TOPICS = [
        "how to make", "weapons", "explosives",
        "hack into", "steal", "illegal"
    ]

    @classmethod
    def validate(cls, topics: list[str]) -> tuple[bool, str]:
        if not topics:
            return False, "At least one topic is required"
        if len(topics) > cls.MAX_TOPICS:
            return False, f"Maximum {cls.MAX_TOPICS} topics allowed"

        for topic in topics:
            topic = topic.strip()
            if len(topic) < cls.MIN_TOPIC_LENGTH:
                return False, f"Topic too short: '{topic}'"
            if len(topic) > cls.MAX_TOPIC_LENGTH:
                return False, f"Topic too long (max {cls.MAX_TOPIC_LENGTH} chars)"

            topic_lower = topic.lower()
            for pattern in cls.BLOCKED_PATTERNS:
                if re.search(pattern, topic_lower):
                    return False, "Invalid topic — please describe a research subject"
            for blocked in cls.BLOCKED_TOPICS:
                if blocked in topic_lower:
                    return False, "Topic not permitted for research"

        return True, ""


# ── Request models ────────────────────────────────────────
class BriefRequest(BaseModel):
    topics: list[str]


# ── Routes ────────────────────────────────────────────────
@app.get("/health")
@app.get("/api/health")
async def health():
    return {
        "status":    "healthy",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.post("/api/user")
async def get_or_create_user(
    request: Request,
    user_id: str = Depends(get_user_id)
):
    try:
        result = execute_sql(
            "SELECT id, clerk_user_id, display_name FROM users WHERE clerk_user_id = :id",
            [{"name": "id", "value": {"stringValue": user_id}}]
        )

        if result["records"]:
            row = result["records"][0]
            return {
                "id":            row[0]["stringValue"],
                "clerk_user_id": row[1]["stringValue"],
                "display_name":  row[2].get("stringValue", ""),
                "created":       False
            }

        result = execute_sql(
            """
            INSERT INTO users (clerk_user_id, display_name)
            VALUES (:id, :name)
            RETURNING id, clerk_user_id, display_name
            """,
            [
                {"name": "id",   "value": {"stringValue": user_id}},
                {"name": "name", "value": {"stringValue": "Aria User"}}
            ]
        )

        row = result["records"][0]
        return {
            "id":            row[0]["stringValue"],
            "clerk_user_id": row[1]["stringValue"],
            "display_name":  row[2].get("stringValue", ""),
            "created":       True
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_or_create_user: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/briefs")
async def submit_brief(
    brief:   BriefRequest,
    user_id: str = Depends(get_user_id)
):
    is_valid, error = TopicValidator.validate(brief.topics)
    if not is_valid:
        raise HTTPException(status_code=400, detail=error)

    try:
        result = execute_sql(
            "SELECT id FROM users WHERE clerk_user_id = :id",
            [{"name": "id", "value": {"stringValue": user_id}}]
        )

        if not result["records"]:
            raise HTTPException(status_code=404, detail="User not found")

        internal_user_id = result["records"][0][0]["stringValue"]

        topics_literal = "{" + ",".join(
            '"' + t.replace('"', '\\"') + '"'
            for t in brief.topics
        ) + "}"

        result = execute_sql(
            """
            INSERT INTO briefs (user_id, topics, status)
            VALUES (:user_id::uuid, :topics::text[], 'pending')
            RETURNING id, topics::text
            """,
            [
                {"name": "user_id", "value": {"stringValue": internal_user_id}},
                {"name": "topics",  "value": {"stringValue": topics_literal}}
            ]
        )

        brief_id    = result["records"][0][0]["stringValue"]
        topics_back = result["records"][0][1].get("stringValue", "")
        logger.info(f"Brief {brief_id} created — topics stored as: {topics_back}")

        sqs.send_message(
            QueueUrl    = SQS_QUEUE_URL,
            MessageBody = json.dumps({
                "brief_id": brief_id,
                "topics":   brief.topics
            })
        )

        return {
            "brief_id": brief_id,
            "status":   "pending",
            "topics":   brief.topics,
            "message":  "Brief submitted — research in progress"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting brief: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/briefs")
async def list_briefs(user_id: str = Depends(get_user_id)):
    try:
        result = execute_sql(
            """
            SELECT
                b.id,
                b.topics,
                b.status,
                b.created_at,
                b.updated_at,
                LEFT(br.content, 300) as content_preview,
                br.critic_score
            FROM briefs b
            JOIN users u ON u.id = b.user_id
            LEFT JOIN briefings br ON br.brief_id = b.id
            WHERE u.clerk_user_id = :user_id
            ORDER BY b.created_at DESC
            LIMIT 20
            """,
            [{"name": "user_id", "value": {"stringValue": user_id}}]
        )

        briefs = []
        for row in result["records"]:
            topics  = parse_topics(row[1])
            preview = row[5].get("stringValue") if not row[5].get("isNull") else None
            score   = row[6].get("doubleValue")  if not row[6].get("isNull") else None

            briefs.append({
                "id":              row[0]["stringValue"],
                "topics":          topics,
                "status":          row[2]["stringValue"],
                "created_at":      row[3].get("stringValue", ""),
                "updated_at":      row[4].get("stringValue", ""),
                "content_preview": preview,
                "critic_score":    score,
            })

        return {"briefs": briefs}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing briefs: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/briefs/{brief_id}")
async def get_brief(
    brief_id: str,
    user_id:  str = Depends(get_user_id)
):
    try:
        result = execute_sql(
            """
            SELECT b.id, b.topics, b.status, b.created_at,
                   br.content, br.critic_score, br.approved
            FROM briefs b
            JOIN users u ON u.id = b.user_id
            LEFT JOIN briefings br ON br.brief_id = b.id
            WHERE b.id = :brief_id::uuid
              AND u.clerk_user_id = :user_id
            ORDER BY br.created_at DESC
            LIMIT 1
            """,
            [
                {"name": "brief_id", "value": {"stringValue": brief_id}},
                {"name": "user_id",  "value": {"stringValue": user_id}}
            ]
        )

        if not result["records"]:
            raise HTTPException(status_code=404, detail="Brief not found")

        row    = result["records"][0]
        topics = parse_topics(row[1])
        logger.info(f"Brief {brief_id} topics raw: {row[1]} parsed: {topics}")

        return {
            "id":           row[0]["stringValue"],
            "topics":       topics,
            "status":       row[2]["stringValue"],
            "created_at":   row[3].get("stringValue", ""),
            "content":      row[4].get("stringValue") if not row[4].get("isNull") else None,
            "critic_score": row[5].get("doubleValue")  if not row[5].get("isNull") else None,
            "approved":     row[6].get("booleanValue") if not row[6].get("isNull") else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting brief: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Lambda handler ────────────────────────────────────────
handler = Mangum(app)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)