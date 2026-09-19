FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
# `src` alone is enough: the JSON Schemas and the demo CSV live inside the
# package and are installed with it. They used to sit at the repository root
# and be found by walking up from __file__, which worked from a checkout and
# failed the moment the package was pip-installed here.
COPY src ./src
# Constraints keep an upstream release from breaking a build that worked
# yesterday; see constraints.txt for why each pin exists.
COPY constraints.txt ./
RUN pip install --no-cache-dir -c constraints.txt .

COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

# The app only ever sits behind a TLS gateway (Caddy, ADR 0012) that sets
# X-Forwarded-Proto; without trusting it, request.base_url is http:// and every
# OAuth discovery URL and `resource` the server advertises is wrong (ADR 0014).
# Port 8000 is published for that gateway, not the internet, so "*" is safe;
# nothing in the app keys on the client IP anyway.
CMD ["sh", "-c", "alembic upgrade head && uvicorn fuel_predictor.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
