FROM python:3.15-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/home/sandboxuser/.local/bin:${PATH}"

# Tier 1: system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    curl \
    wget \
    jq \
    less \
    procps \
    iproute2 \
    iputils-ping \
    vim-tiny \
    tree \
    ripgrep \
    fd-find \
    bat \
    file \
    unzip \
    xz-utils \
    rsync \
    build-essential \
    pkg-config \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash sandboxuser

WORKDIR /workspace
RUN chown sandboxuser:sandboxuser /workspace

RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Python deps as root, before switching user. System-wide, visible to sandboxuser.
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        requests pydantic openai python-dotenv \
        pytest ipython ddgs


USER sandboxuser

# The ENV above already adds ~/.local/bin to PATH; create it so pip --user works cleanly.
RUN mkdir -p /home/sandboxuser/.local/bin


CMD ["/bin/bash"]