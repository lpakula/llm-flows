# llmflows runner/orchestrator image.
# BUILD_FRONTEND=1 npm-builds the React UI; default 0 uses committed static output.

ARG BUILD_FRONTEND=0

FROM python:3.11-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates gnupg \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI (orchestrator spawns runner containers)
RUN install -m 0755 -d /etc/apt/keyrings \
    && curl -fsSL https://download.docker.com/linux/debian/gpg -o /etc/apt/keyrings/docker.asc \
    && chmod a+r /etc/apt/keyrings/docker.asc \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] \
       https://download.docker.com/linux/debian $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
       > /etc/apt/sources.list.d/docker.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# Node.js 22 (MCP servers, Pi, optional frontend build)
RUN curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @mariozechner/pi-coding-agent
RUN npm install -g @anthropic-ai/claude-code
RUN curl -fsSL https://www.cursor.com/install-agent | bash || true

RUN pip install --no-cache-dir uv playwright \
    && playwright install --with-deps chromium


FROM base AS app

ARG BUILD_FRONTEND=0

COPY tools/package.json /opt/llmflows/tools/package.json
RUN cd /opt/llmflows/tools && npm install

COPY pyproject.toml uv.lock README.md /opt/llmflows/
COPY scripts/ /opt/llmflows/scripts/
COPY llmflows/ /opt/llmflows/llmflows/

WORKDIR /opt/llmflows

RUN if [ "$BUILD_FRONTEND" = "1" ]; then \
      cd llmflows/ui/frontend && npm install && npm run build; \
    fi

RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements.txt \
    && uv pip install --system -r /tmp/requirements.txt \
    && uv pip install --system --no-deps .

RUN mkdir -p /root/.llmflows
ENV LLMFLOWS_HOME=/root/.llmflows

WORKDIR /workspace
ENTRYPOINT ["llmflows"]
CMD ["ui", "--host", "0.0.0.0"]
