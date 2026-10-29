FROM python:3.15-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/bun/bin:/home/sandboxuser/.local/bin:${PATH}" \
    LANG=C.UTF-8 \
    BUN_INSTALL=/opt/bun

COPY scripts/entrypoint.sh /entrypoint.sh

# Disable APT sandbox so it doesn't try to drop privileges to the _apt user
RUN echo 'APT::Sandbox::User "root";' > /etc/apt/apt.conf.d/10sandbox

# Tier 1: system packages
RUN apt-get update && apt-get install -y --no-install-recommends \
ast-grep \
bat \
build-essential \
ca-certificates \
curl \
fd-find \
fzf \
file \
git \
iproute2 \
iputils-ping \
jq \
just \
less \
mlr \
pkg-config \
procps \
python3 \
python3-pip \
python3-venv \
ripgrep \
rsync \
sd \
tmux \
hyperfine \
tree \
unzip \
vim \
w3m \
wget \
xz-utils \
    && ln -sf /usr/bin/fdfind /usr/local/bin/fd \
    && ln -sf /usr/bin/batcat /usr/local/bin/bat \
    && rm -rf /var/lib/apt/lists/*

# TODO: install the following
# rg fd fzf jq sd hyperfine delta btop watchexec just procs ncdu mlr

# NOTE: vi-tiny is noncompatible trash

# Create non-root user early
RUN useradd -m -s /bin/bash sandboxuser

# Install Bun system-wide so non-root users can use it
RUN curl -fsSL https://bun.sh/install | bash

# Now install omp; the binary will also go into /opt/bun/bin
RUN bun install -g @oh-my-pi/pi-coding-agent \
&& /opt/bun/bin/bun --version

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

# Add user local bin directory to PATH
ENV PATH="/home/sandboxuser/.local/bin:${PATH}"

CMD ["/bin/bash"]
