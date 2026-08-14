# Deployable red-teaming app image. Builds ONLY this package — no braintools, no
# vitruvio, no brain. The app crosses the brain boundary through mounted data volumes
# (REDTEAM_KNOWLEDGE_PATH in, REDTEAM_FINDINGS_PATH out).
#
# Build from the repo root so the workspace lockfile is available:
#   docker build -f packages/redteam/Dockerfile -t alquimia-redteam .

FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Only the app package. (Add gaussia[roastme] here once `roast` is implemented.)
COPY packages/redteam/ ./

# Install into a project-local venv without dev deps.
RUN uv sync --no-dev

ENV PATH="/app/.venv/bin:${PATH}"
ENV REDTEAM_KNOWLEDGE_PATH=/data/knowledge.json
ENV REDTEAM_FINDINGS_PATH=/data/findings.json

ENTRYPOINT ["redteam"]
CMD ["--help"]
