FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src
COPY alembic.ini ./alembic.ini
COPY migrations ./migrations

RUN pip install --no-cache-dir .

EXPOSE 8000

CMD ["uvicorn", "company_lens.main:app", "--host", "0.0.0.0", "--port", "8000"]

