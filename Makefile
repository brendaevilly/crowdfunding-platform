.PHONY: install lint typecheck format test e2e check dev seed contratos

install:            ## dependências + git hooks (rode uma vez após clonar)
	uv sync --all-packages
	git config core.hooksPath .githooks

lint:               ## o mesmo que o CI roda (ruff + mypy)
	uv run ruff check .
	uv run ruff format --check .
	uv run python -m mypy

typecheck:          ## só os tipos (mypy)
	uv run python -m mypy

test:               ## testes unitários e de integração (sem e2e)
	uv run python -m pytest -m "not e2e"

e2e:                ## sobe todos os serviços e roda os testes ponta a ponta
	@if [ -d e2e ]; then uv run python -m pytest e2e -m e2e; else echo "e2e/ ainda não existe"; fi

check: lint test    ## rode antes de abrir o PR

dev:                ## sobe todos os microsserviços (issue F07)
	uv run python scripts/dev.py up

seed:               ## popula o sistema com dados de demonstração (requer make dev no ar)
	uv run python scripts/seed_demo.py

format:             ## formata e corrige estilo com ruff
	uv run ruff format .
	uv run ruff check --fix .

contratos:          ## regenera docs/contratos a partir de packages/contracts
	uv run python scripts/gen_contratos_doc.py
