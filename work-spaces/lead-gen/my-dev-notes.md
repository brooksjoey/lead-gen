# Core Files Development Notes

## `config.py`

Additional settings for production-only concerns (TLS, external webhooks, provider keys).

Environment-specific validation or guards (e.g., disallowing placeholder secrets outside development).

Possibly structured sub-settings (API, DB, Redis) if surface area grows.

## `logging.py`

Environment-aware processors (request IDs, correlation IDs).

Optional sinks/handlers for external log aggregation.

Tighter control of log level overrides per subsystem.

## `db/session.py`

Lifecycle hooks (startup/shutdown disposal).

Optional read/write engine separation or pool tuning.

Instrumentation hooks (metrics, tracing) layered on top.
