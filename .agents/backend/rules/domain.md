# Domain layer

Apply when changing entities, value objects, domain events, errors, or invariants under `modules/<module>/domain/`.

## Purpose

Domain holds business meaning and deterministic rules. It depends on Python standard library, validation library, and shared domain types only. Never import framework, ORM, HTTP, cache, queue, filesystem, clock, random, or provider SDK code.

## Rules

- Prefer immutable `pydantic.BaseModel` (`frozen=True`) or `@dataclass(frozen=True)` objects.
- Validate invariants at construction or in named transition methods. Invalid state must not be constructible.
- Pass IDs, timestamps, randomness, and external facts into methods. Do not call `now()`, generate IDs, query, log, or send inside domain code.
- Use value objects for meaningful concepts such as money, email, period, quantity, status, and identifier. Avoid untyped `dict[str, Any]` for stable business data.
- Define total, explicit state-transition maps. Reject unsupported transitions with a domain error.
- Domain errors describe business failures, carry safe identifiers, and never contain HTTP/framework details.
- Domain events are immutable, past tense, and contain identifiers plus facts needed by consumers; consumers re-read details through ports.

## Example

```python
class InvalidStatusTransition(DomainError): ...

def transition_to(self, target: Status, at: datetime) -> "Order":
    if target not in ALLOWED_TRANSITIONS[self.status]:
        raise InvalidStatusTransition(self.id, self.status, target)
    return self.model_copy(update={"status": target, "updated_at": at})
```

## Tests

Unit-test every invariant and allowed/rejected transition without database, network, wall clock, or mocks.

## Worked example

```python
# Good: deterministic rule with an explicit fact from caller.
def rename(self, name: Name, at: datetime) -> "Project":
    return self.model_copy(update={"name": name, "updated_at": at})

# Bad: domain reaches into infrastructure and becomes untestable.
def rename(self, name: str) -> None:
    self.updated_at = datetime.now()
    session.commit()
```

## Never

- ORM models as domain entities.
- `HTTPException`, `Request`, `Session`, provider types, or infrastructure imports.
- Mutable setters or validation methods callers must remember to invoke.
- Business rules duplicated in handlers, repositories, or workers.
