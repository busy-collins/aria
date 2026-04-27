# Read current README
content = open('README.md').read()

# Find architecture section boundaries
arch_start = content.find('## Architecture Overview

```mermaid
flowchart TD
    User([User Browser]) --> CF[CloudFront CDN]
    CF --> S3[S3 Bucket - Next.js Static Files]
    CF --> AG[API Gateway - HTTP API]
    AG --> API[Lambda: API - FastAPI + Mangum - Clerk JWT Auth]
    API --> SQS[SQS Queue - aria-research-jobs]
    API --> Aurora[(Aurora PostgreSQL Serverless v2)]
    SQS --> Analyst[Lambda: Analyst - OpenAI Agents SDK]
    Analyst --> Researcher[App Runner - Playwright MCP - Real Web Browsing]
    Researcher --> Ingest[Lambda: Ingest]
    Ingest --> SM[SageMaker - all-MiniLM-L6-v2 Embeddings]
    SM --> S3V[(S3 Vectors - research-briefs)]
    Analyst --> S3V
    Analyst --> Writer[Lambda: Writer - GPT-4o - Capture Pattern]
    Writer --> Critic[Lambda: Critic - GPT-4o-mini - LLM-as-judge]
    Critic --> Aurora

    style User fill:#4F46E5,color:#fff
    style CF fill:#FF9900,color:#fff
    style API fill:#FF9900,color:#fff
    style SQS fill:#FF9900,color:#fff
    style Analyst fill:#7C3AED,color:#fff
    style Writer fill:#7C3AED,color:#fff
    style Critic fill:#7C3AED,color:#fff
    style Researcher fill:#059669,color:#fff
    style Aurora fill:#2563EB,color:#fff
    style S3V fill:#2563EB,color:#fff
    style SM fill:#DC2626,color:#fff
```

)