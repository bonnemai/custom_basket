#!/usr/bin/env bash

NAME=custom_basket

if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    source .env
    set +a
fi

docker stop "$NAME" || true
docker rm -f "$NAME" || true
docker build -t "$NAME" . && \
    docker run -e EODHD_API_TOKEN="$EODHD_API_TOKEN" \
    --rm -p 8000:8000 --name "$NAME" "$NAME"
