# ARIA — Autonomous Research Intelligence Assistant

> A production multi-agent AI system that researches topics,
> synthesises findings, and delivers structured intelligence briefings.

[![Live Demo](https://img.shields.io/badge/Live-Demo-blue)](https://your-cloudfront-url.cloudfront.net)

## Architecture
User → CloudFront → API Gateway → Lambda (FastAPI)
↓
SQS
↓
Analyst Lambda
↓
Researcher (App Runner)
Playwright MCP + Web Browsing
↓
Writer Lambda
↓
Critic Lambda
↓
Aurora PostgreSQL
## Tech Stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Frontend | Next.js + CloudFront | Static export, global CDN |
| Auth | Clerk + PyJWT | Production auth, RS256 JWT |
| API | FastAPI + Lambda | Serverless, auto-scaling |
| Database | Aurora PostgreSQL Serverless | HTTP Data API, scale to zero |
| Queue | SQS | Decoupled pipeline, handles spikes |
| Agents | OpenAI Agents SDK + GPT-4o | Tool calling, agent loops |
| Research | Playwright MCP + App Runner | Real browser, persistent process |
| Vectors | S3 Vectors + SageMaker | RAG, semantic search |
| Observability | LangSmith | LLM tracing and debugging |
| IaC | Terraform | 7 modules, fully reproducible |
| Testing | pytest + moto + testcontainers | 55 tests across 3 layers |

## Project Structure
aria/
├── backend/
│   ├── agents/          # Lambda handlers + LangGraph orchestrator
│   │   ├── analyst_handler.py
│   │   ├── writer_handler.py
│   │   ├── critic_handler.py
│   │   └── aria_graph.py      # LangGraph (local testing)
│   ├── api/             # FastAPI application
│   │   └── main.py
│   ├── researcher/      # App Runner service
│   │   ├── server.py
│   │   └── Dockerfile
│   ├── shared/          # Shared utilities
│   │   ├── context.py   # Agent system prompts
│   │   ├── tools.py     # Agent tools
│   │   └── secrets.py   # AWS Secrets Manager
│   └── tests/
│       ├── unit/        # 25 pure logic tests
│       ├── integration/ # 23 moto + testcontainers tests
│       └── evals/       # LLM quality evaluations
├── frontend/            # Next.js application
├── scripts/             # Deployment and testing scripts
└── terraform/           # Infrastructure as Code
├── 1_iam/
├── 2_sagemaker/
├── 3_ingest/
├── 4_researcher/
├── 5_database/
├── 6_agents/
└── 7_frontend/

## Getting Started

### Prerequisites

- AWS account with appropriate permissions
- Python 3.12
- Node.js 18+
- Terraform 1.5+
- Docker Desktop
- OpenAI API key
- Clerk account

### Setup

1. Clone the repository
```bash
git clone https://github.com/busy-collins/aria.git
cd aria
```

2. Copy environment template
```bash
cp .env.example .env
# Fill in your values
```

3. Deploy infrastructure
```bash
# Each module builds on the previous
cd terraform/1_iam && terraform init && terraform apply
cd ../2_sagemaker  && terraform init && terraform apply
cd ../3_ingest     && terraform init && terraform apply
cd ../4_researcher && terraform init && terraform apply
cd ../5_database   && terraform init && terraform apply
cd ../6_agents     && terraform init && terraform apply
cd ../7_frontend   && terraform init && terraform apply
```

4. Run database migrations
```bash
cd backend/api
python run_migrations.py
```

5. Deploy researcher
```bash
cd backend/researcher
python deploy.py
```

6. Deploy frontend
```bash
export NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_test_...
python scripts/deploy_frontend.py
```

## Running Locally

```bash
# Terminal 1 — API
cd backend/api
uvicorn main:app --reload --port 8000

# Terminal 2 — Frontend
cd frontend
npm run dev
```

## Testing

```bash
cd backend

# Unit tests (no dependencies)
python -m pytest tests/unit/ -v

# Integration tests (moto — no real AWS)
python -m pytest tests/integration/test_pipeline.py -v

# Database tests (needs Docker)
python -m pytest tests/integration/test_database.py -v

# All tests
python -m pytest tests/ -v

# LLM quality evals (uses real OpenAI)
python tests/evals/eval_writer.py
python tests/evals/eval_agents.py
```

## Testing the Pipeline Locally

```bash
# Test LangGraph pipeline with mock Aurora
python scripts/test_graph_local.py --topics "NVIDIA AI chips 2025"

# Test without Researcher (mock research data)
python scripts/test_graph_offline.py

# Full E2E test against production
python scripts/test_e2e.py --token "your-jwt-token" --env prod
```

## Key Design Decisions

### Why separate Lambdas over LangGraph inline?
Each Lambda scales independently. The Analyst, Writer, and Critic
can each handle different concurrency levels. A single LangGraph
Lambda would eliminate this — a fundamental production requirement.

### Why Aurora Serverless Data API?
Lambda functions can't maintain persistent database connections.
The Data API is HTTP-based — stateless, no connection pools,
works seamlessly with serverless functions.

### Why App Runner for the Researcher?
Playwright requires a persistent browser process. Lambda's
ephemeral execution model and 15-minute timeout make it
unsuitable. App Runner provides always-on containers without
Kubernetes complexity.

### Why moto + testcontainers over real AWS?
Real AWS tests cost money and are slow. moto provides accurate
AWS service mocks in memory. testcontainers spins up real
PostgreSQL in Docker — validating actual SQL without touching
production data.

## Architecture Diagram
┌─────────────────────────────────────────────────────────┐
│                    CloudFront CDN                        │
│                  (dhjx5b.cloudfront.net)                 │
└──────────┬──────────────────────┬───────────────────────┘
│                      │
┌──────▼──────┐      ┌───────▼────────┐
│  S3 Bucket  │      │  API Gateway   │
│  (Next.js)  │      │  HTTP API      │
└─────────────┘      └───────┬────────┘
│
┌────────▼────────┐
│  Lambda: API    │
│  FastAPI+Mangum │
│  Clerk JWT Auth │
└────────┬────────┘
│
┌────────▼────────┐
│   SQS Queue     │
│  aria-research  │
└────────┬────────┘
│
┌────────────▼──────────────┐
│    Lambda: Analyst         │
│    OpenAI Agents SDK       │
│         │                  │
│    App Runner              │
│    Researcher              │
│    Playwright MCP          │
│    Real Web Browsing       │
└────────────┬──────────────┘
│
┌────────────▼──────────────┐
│    Lambda: Writer          │
│    GPT-4o                  │
│    Capture pattern         │
└────────────┬──────────────┘
│
┌────────────▼──────────────┐
│    Lambda: Critic          │
│    GPT-4o-mini             │
│    LLM-as-judge            │
└────────────┬──────────────┘
│
┌────────────▼──────────────┐
│    Aurora PostgreSQL       │
│    Serverless v2           │
│    Data API               │
└───────────────────────────┘

## Cost Estimate

| Service | Monthly Cost (low traffic) |
|---------|--------------------------|
| Lambda (API + Agents) | ~$7 |
| Aurora Serverless | ~$15 |
| App Runner | ~$25 |
| SageMaker Serverless | ~$3 |
| CloudFront + S3 | ~$2 |
| SQS + Secrets Manager | ~$3 |
| **Total** | **~$55/month** |

Cost per briefing: ~$0.18 (OpenAI + AWS compute)

## Author

**Nwaogugu Chibuike Collins**
## License

MIT