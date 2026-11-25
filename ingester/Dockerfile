# Build from the REPOSITORY ROOT (compose sets context: ..), because the image needs pipeline/, config/, data/ and web/:
#   docker build -f ingester/Dockerfile -t snow-wx-ingester .
FROM docker.io/mambaorg/micromamba:2.3.2

USER root
WORKDIR /app

COPY environment.yml ./environment.yml
RUN micromamba create -y -n snow-wx -f environment.yml && micromamba clean --all --yes

COPY pipeline ./pipeline
# only the package's source and the entry script: tests, the secrets folder and compose files are never copied
COPY ingester/src/ingester ./src/ingester
COPY ingester/entrypoint.sh ./entrypoint.sh
COPY config ./config
COPY data ./data
COPY web ./web
COPY tools ./tools

RUN chmod +x /app/entrypoint.sh

ENV MAMBA_DOCKERFILE_ACTIVATE=1
ENV PYTHONUNBUFFERED=1
# the package lives in /app/src/ingester; pipeline/ is found from the working directory /app
ENV PYTHONPATH=/app/src

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["ingest", "run", "--all", "--stage", "/output/stage", "--local-root", "/output/store"]
