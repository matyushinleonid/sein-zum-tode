[![Hermeneutic phenomenology](.github/badges/hermeneutic-phenomenology.svg)](https://github.com/matyushinleonid/sein-zum-tode)
[![Being](.github/badges/being.svg)](https://github.com/matyushinleonid/sein-zum-tode)

[![CI](https://github.com/matyushinleonid/sein-zum-tode/actions/workflows/ci.yml/badge.svg)](https://github.com/matyushinleonid/sein-zum-tode/actions/workflows/ci.yml)
[![Codecov](https://codecov.io/gh/matyushinleonid/sein-zum-tode/branch/main/graph/badge.svg)](https://codecov.io/gh/matyushinleonid/sein-zum-tode)
[![Lines of Code](https://raw.githubusercontent.com/matyushinleonid/sein-zum-tode/badges/lines-of-code.svg)](https://github.com/matyushinleonid/sein-zum-tode/actions/workflows/ci.yml)
[![Hits of Code](https://hitsofcode.com/github/matyushinleonid/sein-zum-tode)](https://hitsofcode.com/github/matyushinleonid/sein-zum-tode/view)
[![Telegram](https://img.shields.io/badge/Telegram-@SeinZumTodeBot-26A5E4?logo=telegram)](https://t.me/SeinZumTodeBot)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![](https://img.shields.io/badge/coffee%20drunk-694%20L-6F4E37)](https://github.com/matyushinleonid/sein-zum-tode)

# Sein zum Tode

### ... or "being-towards-death"

![barbie](https://storage.yandexcloud.net/leonid.sh/sein-zum-tode/barbie.png?v=2)

---

The topic of death remains largely taboo in today’s society (as noted, for example, by Philippe Ariès). This project is designed to help users face the inevitability of death as a phenomenon that will (and indeed **is**) happen to them.

Users are invited to answer a series of questions about their lifestyle, after which a rough estimate of their remaining lifespan is calculated by an LLM-based model. Of course, the resulting number of days left is not meant to be precisely accurate. The real value lies in the daily countdown of remaining days that the bot will send to the user.

---

- The current Telegram implementation is available as [SeinZumTodeBot](https://t.me/SeinZumTodeBot)
- It runs in k8s.leonid.sh ([IaC repository](https://github.com/matyushinleonid/k8s.leonid.sh)). The ArgoCD application and related Kubernetes resources are available [here](https://github.com/matyushinleonid/k8s.leonid.sh/tree/main/argocd/sein-zum-tode).

## User interface

- `/begin` — start or restart the questionnaire.
- `/notifications` — configure notification schedule.
- `/localization` — choose Russian or English.
- `/help` — show usage instructions.
- `/about` — show project information and source code.

> **Note:** Questionnaire answers are never stored in PostgreSQL or in Temporal history. They exist only temporarily in Redis with a TTL, are used to generate a prediction, and are explicitly deleted upon completion or expiration for privacy reasons.

## High-level overview

```mermaid
flowchart LR
    user["Telegram user"] <--> telegram["Telegram Bot API"]

    subgraph service["Sein zum Tode"]
        ingress["Ingress / poller<br/>long polling and handoff"]
        worker["Bot worker<br/>workflows and activities"]
    end

    telegram -->|"updates"| ingress
    ingress -->|"payload with TTL"| redis[("Redis")]
    ingress -->|"Signal-With-Start"| temporal["Temporal"]
    temporal -->|"workflow and activity tasks"| worker
    worker <-->|"payload with TTL"| redis
    worker <-->|"Mortal profiles"| postgres[("PostgreSQL")]
    worker -->|"messages"| telegram
    worker <-->|"structured completion"| llm["LLM provider"]
```

- **Ingress** uses aiogram only as a lightweight Telegram Bot API transport/model wrapper, stores updates in Redis, and hands Redis keys to Temporal. The bot does not use aiogram dispatching or state machines.
- **Bot worker** runs Temporal Workflows and Activities, processes questionnaires, sends messages, and schedules notifications.
- **Redis** keeps sensitive payloads temporarily with TTL.
- **PostgreSQL** stores user profiles, preferences, death dates, and LLM quota.

The service is written in Python and uses aiogram, Temporal, Redis, PostgreSQL, SQLAlchemy, Alembic, Pydantic, OpenAI/Yandex AI Studio SDKs, Prometheus, Loki, Docker Compose, Helm, Kubernetes, and Argo CD.

Temporal is used instead of bot-specific state-machine frameworks because those frameworks do not provide Temporal’s durable execution, retries, recovery, and workflow-history guarantees.

## Local development

Docker Compose does not start Temporal. Forward an existing Temporal frontend first:

```shell
kubectl port-forward -n temporal svc/temporal-frontend 7233:7233
```

Containers reach the forwarded port at `host.docker.internal:7233`.

```shell
make install
make test       # run tests
make check      # run lint, type checking, and tests
make run
```

## Release

Run the **Release** workflow from the `main` branch and enter the application version without the `v` prefix. The version must match both `pyproject.toml` and the chart's `appVersion`. The workflow promotes the image already tested by main CI to the full and minor version tags, then creates the corresponding `v<version>` Git tag and GitHub Release.
