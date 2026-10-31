# The official Playwright image: Chromium, the system libraries and the fonts are already in it,
# and it is exactly the revision that `playwright==1.56.0` in pyproject.toml expects. They change
# TOGETHER, otherwise level 2 fails at `launch`. The digest locks the image: same Dockerfile,
# same bytes. `BASE_IMAGE` exists only for networks with a TLS-intercepting proxy (own CA).
ARG BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.56.0-noble@sha256:a7f6cf3ae520c9d670ad956572c13747ed5abdbba5123a01526f873ed1662528
FROM ${BASE_IMAGE}

# HOME=/tmp and no caches (pytest, ruff): the code stays read-only, also for `--user $(id -u)` on Linux.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTEST_ADDOPTS="-p no:cacheprovider" \
    RUFF_NO_CACHE=true \
    HOME=/tmp

WORKDIR /app

# Dependencies before the rest of the repository: a change to a test or to the docs does not
# reinstall the packages.
COPY pyproject.toml README.md ./
COPY sitetriage/ sitetriage/
RUN pip install -e '.[dev]'

COPY . .

# The tool reads other people's sites; there is no reason to do that as root.
USER pwuser

CMD ["sitetriage", "--help"]
