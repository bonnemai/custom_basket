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
    --rm -p 9000:8080 --name "$NAME" "$NAME"

echo "Container started with the Lambda Runtime API exposed at http://localhost:9000"
echo "Invoke with:"
cat <<'EOF'
curl -X POST \
  "http://localhost:9000/2015-03-31/functions/function/invocations" \
  -H "Content-Type: application/json" \
  -d '{
        "resource": "/baskets",
        "path": "/baskets",
        "httpMethod": "GET",
        "headers": {"accept": "application/json"},
        "requestContext": {"http": {"path": "/baskets", "method": "GET"}},
        "isBase64Encoded": false
      }'
EOF
