# syntax=docker/dockerfile:1.4
ARG PYTHON_VERSION=3.11

FROM --platform=linux/arm64 python:${PYTHON_VERSION}-slim AS builder
WORKDIR /app
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --upgrade pip \
    && pip install --no-cache-dir . --target /opt/python

FROM builder AS unit-tests
COPY tests ./tests
RUN pip install --no-cache-dir \
    "pytest>=7.4.0,<9.0.0" \
    "pytest-cov>=4.1.0,<5.0.0"
ENV PYTHONPATH=/opt/python
RUN pytest

FROM --platform=linux/arm64 public.ecr.aws/lambda/python:${PYTHON_VERSION} AS runtime
COPY --from=builder /opt/python /opt/python
COPY app ./app

CMD ["app.main:lambda_handler"]
