FROM base-research:latest
USER root
WORKDIR /workspace

RUN apt-get update && apt-get install -y \
    git curl ripgrep \
    nano vim \
    less \
    procps \
    ca-certificates \
    sudo \
    git curl python3 python3-pip python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code



ENV IS_SANDBOX=1
RUN mkdir -p /root/.claude && \
    echo '{"permissions":{"defaultMode":"bypassPermissions"}}' > /root/.claude/settings.json