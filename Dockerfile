FROM python:3.12-slim

RUN pip install --no-cache-dir uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY pgdelta ./pgdelta
RUN uv sync --frozen --no-dev

ENTRYPOINT ["uv", "run", "pgdelta"]
