FROM python:3.15-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/home/sandboxuser/.local/bin:${PATH}"

# Disable APT sandbox so it doesn't try to drop privileges to the _apt user
RUN echo 'APT::Sandbox::User "root";' > /etc/apt/apt.conf.d/10sandbox

# Tier 1: system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    curl \
    ddgr \
    wget \
    w3m \
    jq \
    less \
    procps \
    iproute2 \
    iputils-ping \
    vim-tiny \
    tree \
    tmux \
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

# Create non-root user early
RUN useradd -m -s /bin/bash sandboxuser

# Install Astral uv installer globally
RUN curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# Set up workspace ownership
WORKDIR /workspace
RUN chown sandboxuser:sandboxuser /workspace

# Python deps as root (globally visible), utilizing uv for speed
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir \
        requests pydantic openai python-dotenv \
        pytest ipython ddgs rich json-repair

# Switch to non-root user for runtime and final preparations
USER sandboxuser

# Create user local bin directory for user-space binaries
RUN mkdir -p /home/sandboxuser/.local/bin

CMD ["/bin/bash"]