FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    calibre \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

RUN mkdir -p /data/epubs

VOLUME ["/data"]
EXPOSE 8000

ENV DATABASE_URL=sqlite+aiosqlite:///data/kindledrop.db
ENV EPUB_DIR=/data/epubs

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
