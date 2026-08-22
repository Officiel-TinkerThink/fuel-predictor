# Framework layer

Apply when changing application factory, settings, dependency wiring, workers, logging, or error mapping.

## Rules

- Read environment in one typed settings object; validate at startup; use secret types; forbid unknown/mistyped config. No scattered `getenv`.
- Create engines, clients, pools, and worker resources in lifespan/startup, not import time. Dispose cleanly on shutdown.
- One dependency provider per use case. Tests override providers or inject fakes.
- Map domain errors to HTTP responses in one framework location. Log unexpected errors with correlation ID; return no internal details.
- Use structured logs with correlation ID and safe actor/resource identifiers. Never log secrets, credentials, tokens, raw sensitive payloads, or full provider responses.
- Worker shares domain/use cases with API. Claim jobs atomically, heartbeat/lease them, handle shutdown, retry bounded transient failures, and mark terminal outcomes visibly.
- Use transactional outbox or equivalent for state-change events that must reach external systems.

## Never

- Business rules in `main.py`, dependency providers, middleware, or worker loop.
- Global mutable clients/sessions initialized at import time.

## Worked example

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.engine = create_engine(settings.database_url.get_secret_value())
    try:
        yield
    finally:
        app.state.engine.dispose()

# Bad: `engine = create_engine(...)` at module import time.
```
