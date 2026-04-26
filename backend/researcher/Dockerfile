FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    nodejs npm curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy pyproject.toml + shared package and install
COPY pyproject.toml .
COPY shared/ ./shared/
RUN pip install --no-cache-dir -e .

# Install researcher dependencies
COPY researcher/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright MCP
RUN npm install -g @playwright/mcp
RUN npx playwright install chromium
RUN npx playwright install-deps chromium

# Copy researcher service entry point
COPY researcher/server.py ./server.py

# Verify imports at build time
RUN python -c 'from shared.context import researcher_instructions; from shared.tools import ingest_research_document; from shared.mcp_servers import create_playwright_mcp_server; print("All imports OK")'

EXPOSE 8000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]