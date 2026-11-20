"""Ponto de entrada para execução do microsserviço Campanhas."""

from campanhas.app import app
from shared.http.runner import run


def main() -> None:
    """Inicia o servidor HTTP do serviço Campanhas."""
    run(app, "campanhas")


if __name__ == "__main__":
    main()
