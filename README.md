python3 -c "
content = open('README.md').read()

old_arch = '''## Architecture Overview

    User
     |
     v
CloudFront CDN
     |
     +-- S3 (Next.js static files)
     |
     +-- API Gateway --> Lambda (FastAPI + Mangum)
                              |
                             SQS
                              |
                       Analyst Lambda
                              |
                    App Runner (Researcher)
                    Playwright MCP + Real Browsing
                    S3 Vectors + SageMaker RAG
                              |
                       Writer Lambda
                              |
                       Critic Lambda
                              |
                    Aurora PostgreSQL Serverless'''

new_arch = '''## Architecture Overview

\`\`\`mermaid
flowchart TD
    User([User Browser]) --> CF[CloudFront CDN]

    CF --> S3[S3 Bucket\\nNext.js Static Files]
    CF --> AG[API Gateway\\nHTTP API]

    AG --> API[Lambda: API\\nFastAPI + Mangum\\nClerk JWT Auth]

    API --> SQS[SQS Queue\\naria-research-jobs]
    API --> Aurora[(Aurora PostgreSQL\\nServerless v2)]

    SQS --> Analyst[Lambda: Analyst\\nOpenAI Agents SDK]

    Analyst --> Researcher[App Runner\\nResearcher Service\\nPlaywright MCP\\nReal Web Browsing]

    Researcher --> Ingest[API Gateway\\nIngest Endpoint]
    Ingest --> IngestLambda[Lambda: Ingest]
    IngestLambda --> SM[SageMaker\\nall-MiniLM-L6-v2\\nEmbeddings]
    SM --> S3V[(S3 Vectors\\nresearch-briefs index)]

    Analyst --> S3V
    Analyst --> Writer[Lambda: Writer\\nGPT-4o\\nCapture Pattern]

    Writer --> Critic[Lambda: Critic\\nGPT-4o-mini\\nLLM-as-judge]

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
\`\`\`'''

print('Found old arch:', old_arch[:50] in content)
new_content = content.replace(old_arch, new_arch)
open('README.md', 'w').write(new_content)
print('Done')
"