#!/bin/bash
set -e

if [ -n "$S3_NOTEBOOK_PATH" ]; then
    mkdir -p /home/jovyan/work
    aws s3 cp "$S3_NOTEBOOK_PATH" /home/jovyan/work/notebook.ipynb
fi

exec jupyter notebook --ip=0.0.0.0 --port=8888 --allow-root --NotebookApp.token="${JUPYTER_TOKEN}" --NotebookApp.password=''
