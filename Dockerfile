# ── Stage 1: Base image with heavy deps (rarely changes) ──────────────
FROM python:3.11-slim AS base

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI (orchestrator needs it to launch runner containers)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
       https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 (for MCP servers, Pi, frontend build)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Pi coding agent (npm global)
RUN npm install -g @mariozechner/pi-coding-agent

# Claude Code CLI (npm global)
RUN npm install -g @anthropic-ai/claude-code

# Cursor agent (installed via official installer)
RUN curl -fsSL https://www.cursor.com/install-agent | bash || true

# Playwright + Chromium (headless browser for runner containers)
RUN pip install --no-cache-dir playwright \
    && playwright install --with-deps chromium


# ── Stage 2: App layer (rebuilds fast on source changes) ─────────────
FROM base AS app

# Copy dependency files first (cache npm install / pip install separately)
COPY tools/package.json /opt/llmflows/tools/package.json
RUN cd /opt/llmflows/tools && npm install

COPY llmflows/ui/frontend/package.json llmflows/ui/frontend/package-lock.json* /opt/llmflows/llmflows/ui/frontend/
RUN cd /opt/llmflows/llmflows/ui/frontend && npm install

COPY pyproject.toml README.md /opt/llmflows/
COPY llmflows/ /opt/llmflows/llmflows/
COPY scripts/ /opt/llmflows/scripts/
COPY tools/ /opt/llmflows/tools/

WORKDIR /opt/llmflows

# Build frontend
RUN cd llmflows/ui/frontend && npm run build

# Install llmflows Python package
RUN pip install --no-cache-dir -e "."

# Create system directory
RUN mkdir -p /root/.llmflows

ENV LLMFLOWS_HOME=/root/.llmflows

WORKDIR /workspace
ENTRYPOINT ["llmflows"]
CMD ["ui", "--host", "0.0.0.0"]
