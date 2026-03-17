FROM --platform=linux/amd64 jupyter/base-notebook:x86_64-ubuntu-22.04

USER root
RUN apt-get update && apt-get install -y awscli && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir papermill

COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
