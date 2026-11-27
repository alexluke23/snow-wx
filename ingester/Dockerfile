# Build from the ingester folder (compose sets context: .). The image contains only the ingester: its code, its settings,
# its point lists and its environment. Nothing else from the repository is needed.
#   docker build -t snow-wx-ingester ingester
FROM docker.io/mambaorg/micromamba:2.3.2

USER root
WORKDIR /app

COPY environment.yml ./environment.yml
RUN micromamba create -y -n ingester -f environment.yml && micromamba clean --all --yes

# the package (code, settings, point lists); secrets, tests and compose files are excluded by .dockerignore
COPY src ./src
COPY config ./config
COPY data ./data
COPY entrypoint.sh ./entrypoint.sh

RUN chmod +x /app/entrypoint.sh

ENV MAMBA_DOCKERFILE_ACTIVATE=1
ENV PYTHONUNBUFFERED=1
# the package lives in /app/src/ingester; settings and point lists are found from /app (REPO_ROOT = /app)
ENV PYTHONPATH=/app/src
# the folder the user launched compose from is mounted here; relative --output paths resolve against it
ENV INGEST_LAUNCH_DIR=/launch

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["ingest", "run", "--all"]
