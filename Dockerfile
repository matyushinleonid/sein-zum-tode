FROM python:3.14.6-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --home-dir /app app

COPY pyproject.toml ./
COPY src ./src

RUN python -m pip install --upgrade pip && \
    python -m pip install .

USER app

CMD ["python", "-m", "sein_zum_tode.main"]

