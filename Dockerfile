FROM python:3.14.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app \
    --shell /usr/sbin/nologin app

COPY pyproject.toml ./
COPY src ./src
COPY config ./config

RUN python -m pip install --upgrade pip && \
    python -m pip install .

USER 10001:10001

CMD ["python", "-m", "sein_zum_tode.main"]
