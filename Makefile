.PHONY: unit-tests run

unit-tests:
	uv run pytest

run:
	uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
