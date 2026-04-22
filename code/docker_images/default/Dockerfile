FROM --platform=linux/amd64 jupyter/base-notebook:x86_64-ubuntu-22.04

WORKDIR /home/user
USER root
RUN apt-get update && apt-get install -y awscli curl && apt install -y zsh && rm -rf /var/lib/apt/lists/*
RUN sh -c "$(wget -O- https://github.com/deluan/zsh-in-docker/releases/download/v1.2.1/zsh-in-docker.sh)"
RUN pip install --no-cache-dir papermill uv jupyterlab-lsp jedi-language-server
RUN curl -fsSL https://code-server.dev/install.sh | sh

COPY pyproject.toml /opt/default-venv-config/pyproject.toml
RUN uv venv /opt/default-venv \
    && uv pip install --python /opt/default-venv/bin/python -r /opt/default-venv-config/pyproject.toml \
    && /opt/default-venv/bin/python -m ipykernel install --name default --display-name "Python (default)" --prefix=/opt/conda
