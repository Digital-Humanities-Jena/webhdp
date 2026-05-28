FROM mcr.microsoft.com/devcontainers/python:3.11-bookworm

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        make \
        pkg-config \
        sqlite3 \
        libxml2-dev \
        libxslt1-dev \
        zlib1g-dev \
    && python -m pip install --no-cache-dir --upgrade pip uv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

USER vscode

RUN mkdir -p /home/vscode/.cache/uv /home/vscode/.npm \
    && echo 'export PATH="$HOME/.local/bin:$PATH"' >> /home/vscode/.bashrc
