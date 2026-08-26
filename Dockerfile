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
RUN pip install --no-cache-dir .

COPY alembic.ini ./
COPY alembic ./alembic

EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && uvicorn fuel_predictor.main:app --host 0.0.0.0 --port 8000"]
