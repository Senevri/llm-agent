FROM python:3.15-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    curl \
    jq \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -s /bin/bash sandboxuser

WORKDIR /workspace
RUN chown sandboxuser:sandboxuser /workspace

USER sandboxuser

RUN pip install --upgrade pip
RUN pip install --no-cache-dir requests pydantic openai python-dotenv

CMD ["/bin/bash"]