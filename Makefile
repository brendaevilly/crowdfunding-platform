.PHONY: install lint typecheck format test e2e check dev contratos

install:            ## dependências + git hooks (rode uma vez após clonar)
	uv sync --all-packages
	git config core.hooksPath .githooks

lint:
	uv run ruff check .
	uv run ruff format --check .
	uv run python -m mypy

typecheck:
	uv run python -m mypy

test:
	uv run python -m pytest -m "not e2e"

test:               ## testes unitários e de integração (sem e2e)
	uv run pytest -m "not e2e"

e2e:                ## sobe todos os serviços e roda os testes ponta a ponta
	@if [ -d e2e ]; then uv run pytest e2e -m e2e; else echo "e2e/ ainda não existe"; fi

check: lint test    ## rode antes de abrir o PR

dev:                ## sobe todos os microsserviços (issue F07)
	uv run python scripts/dev.py up

contratos:          ## regenera docs/contratos a partir de packages/contracts
	uv run python scripts/gen_contratos_doc.py
