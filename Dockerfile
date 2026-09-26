# Zvanična Playwright slika: Chromium, sistemske biblioteke i fontovi su već unutra, i to
# baš revizija koju traži `playwright==1.56.0` iz pyproject.toml. Menjaju se ZAJEDNO,
# inače nivo 2 puca na `launch`. Digest zaključava sliku: isti Dockerfile, isti bajtovi.
# `BASE_IMAGE` postoji samo za mreže sa proxy-jem koji menja TLS (sopstveni CA).
ARG BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.56.0-noble@sha256:a7f6cf3ae520c9d670ad956572c13747ed5abdbba5123a01526f873ed1662528
FROM ${BASE_IMAGE}

# HOME=/tmp i bez keševa (pytest, ruff): kod ostaje read-only i za `--user $(id -u)` na Linuxu.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTEST_ADDOPTS="-p no:cacheprovider" \
    RUFF_NO_CACHE=true \
    HOME=/tmp

WORKDIR /app

# Zavisnosti pre ostatka repoa: izmena testa ili dokumentacije ne reinstalira pakete.
COPY pyproject.toml README.md ./
COPY skener/ skener/
RUN pip install -e '.[dev]'

COPY . .

# Alat čita tuđe sajtove — nema razloga da to radi kao root.
USER pwuser

CMD ["skener", "--help"]
