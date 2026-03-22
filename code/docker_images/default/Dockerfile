FROM --platform=linux/amd64 jupyter/base-notebook:x86_64-ubuntu-22.04

USER root
RUN apt-get update && apt-get install -y awscli curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir papermill uv jupyterlab-lsp jedi-language-server

COPY pyproject.toml /opt/default-venv-config/pyproject.toml
RUN uv venv /opt/default-venv \
    && uv pip install --python /opt/default-venv/bin/python -r /opt/default-venv-config/pyproject.toml \
    && /opt/default-venv/bin/python -m ipykernel install --name default --display-name "Python (default)" --prefix=/opt/conda
