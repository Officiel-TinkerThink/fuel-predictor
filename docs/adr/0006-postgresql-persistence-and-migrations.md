# ADR 0006: Use PostgreSQL with SQLAlchemy and Alembic

## Status

Accepted

## Context

Ticket 01 and Ticket 02 originally used hand-written SQLite repositories that created their
tables on demand. The local MVP now needs durable PostgreSQL persistence, a repeatable schema
history, and container startup that does not race the database.

## Decision

Keep the modular monolith and its framework-independent domain dataclasses. Use Pydantic for
HTTP contracts and runtime settings, SQLAlchemy 2 for PostgreSQL mapping and short-lived session
boundaries, and Alembic for the versioned database schema. The initial migration contains both
Daily Operations and the historical-import tables, including source provenance and correction
reports. PostgreSQL deployments run `alembic upgrade head`; the application does not create the
production schema itself.

Docker Compose waits for PostgreSQL's health check before the application applies migrations and
starts. SQLite schema creation remains only an explicit compatibility seam for existing isolated
tests that pass `database_path`; it is never selected by normal runtime configuration.

## Research and adaptation

DeepWiki was not installed in this Codex environment, so no external repository was treated as a
reference implementation. The design was instead checked against the primary package guidance:

- [SQLAlchemy](https://docs.sqlalchemy.org/en/20/orm/session_basics.html) recommends a configured
  `sessionmaker` and a local context-managed transaction. The repositories use one factory from
  application composition, with one short transaction per write; sessions and ORM rows do not
  enter the domain layer.
- [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html) documents a source-controlled
  migration environment and `alembic upgrade head`. The project includes an initial explicit
  revision rather than using `metadata.create_all` in production.
- [Docker Compose](https://docs.docker.com/compose/how-tos/startup-order/) documents
  `depends_on.condition: service_healthy` for databases that must be ready before a dependent
  service starts. The app waits for `pg_isready` before migrations run.

We intentionally do not adopt a separate frontend service, asynchronous ORM, a global scoped
session, or a distributed deployment pattern. The existing server-rendered Indonesian form and
FastAPI API remain two delivery adapters of one small application; none of those additions solve
a current product problem.

## Consequences

Future schema changes require a new reviewed Alembic revision. Local and Docker users must apply
migrations before running the app outside Compose. The domain remains easy to test without a
database or framework.
