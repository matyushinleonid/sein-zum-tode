# sein-zum-tode chart

The chart deploys one Telegram polling ingress, a configurable pool of Temporal workers, and an optional migration Job. PostgreSQL, Redis, and Temporal are external dependencies.

## Required configuration

Provide a Telegram token, Redis password, and PostgreSQL password in Kubernetes Secrets. Every `*SecretRef.name` is independent; an empty name falls back to `secrets.defaultName`, then to `<release>-secrets`.

```yaml
telegram:
  tokenSecretRef:
    name: telegram-credentials
    key: token
redis:
  passwordSecretRef:
    name: redis-credentials
    key: password
postgres:
  passwordSecretRef:
    name: postgres-credentials
    key: password
```

`externalSecret.enabled` is an optional convenience integration. Its `data` field accepts the native External Secrets data mappings and may populate the same default Secret or any independently referenced Secrets managed outside this chart.

## Telegram SOCKS5 proxy

Set `telegram.socks5Proxy.enabled: true` to route Telegram Bot API requests from both the ingress and worker through the shared `socks5Proxy` endpoint. Both workloads then require its host, port, username, and password Secret reference. Worker-side OpenAI integrations use the same endpoint independently of this Telegram flag.

## TLS

- PostgreSQL supports `disable`, `require`, `verify-ca`, and `verify-full`.
- Redis supports TLS with optional certificate verification and ACL usernames.
- Temporal supports server verification, a custom server name, a custom CA, and mTLS.

Set the relevant `tls.secretRef` keys to mount CA or client identity files. A client certificate and private key must always be configured together.

## Application content

With `applicationConfig.create: true`, `botContent`, `deathPrediction.config`, and `notificationSchedule.config` are rendered into a ConfigMap. Set `applicationConfig.create: false` and `applicationConfig.existingConfigMap` to provide the three YAML files from an existing ConfigMap.

## Availability and placement

Ingress is restricted to one steady-state replica because Telegram long polling has a single offset owner. Enable `ingress.coordination` and use `RollingUpdate` with `maxSurge: 1` and `maxUnavailable: 0` to serialize polling turns through a Kubernetes Lease while old and new pods overlap during a rollout. The chart creates a dedicated ServiceAccount, Role, and RoleBinding by default. If NetworkPolicy is enabled, its ingress egress rules must permit access to the Kubernetes API server.

Workers support replica count, rolling-update strategy, PodDisruptionBudget, affinity, tolerations, node selectors, and topology spread constraints independently.

## Monitoring and network policy

Metrics Services require no CRDs and are enabled by default. ServiceMonitor and PrometheusRule are disabled by default and can be enabled when Prometheus Operator CRDs are installed. Alert thresholds and additional rule groups are configurable.

NetworkPolicy is disabled by default. When enabled, the `ingress`, `worker`, and `migration` values are copied into their respective policy specs. Explicitly allow DNS and each external dependency; empty egress lists deny all egress.
