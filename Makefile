.PHONY: unit-tests run

unit-tests:
	uv run pytest

invoke-local:
	docker build -t custom-basket . && \
		docker run --rm -p 9000:8080 custom-basket
