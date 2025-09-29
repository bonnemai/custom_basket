# syntax=docker/dockerfile:1.4
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim AS base
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Copy project metadata first for better layer caching
COPY pyproject.toml README.md ./

# Install production dependencies together with package code
FROM base AS deps
COPY app ./app
RUN uv pip install --system --no-cache .

# Unit test target stage
FROM deps AS unit-tests
COPY tests ./tests
RUN uv pip install --system --no-cache .[dev]
RUN pytest

# Runtime image
FROM deps AS runtime
RUN groupadd --system app && useradd --system --create-home --gid app app \
    && chown -R app:app /app
USER app
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["uvicorn"]
CMD ["app.main:app", "--host", "0.0.0.0", "--port", "8000"]
