"""Ponto de entrada para execução do broker local de mensagens."""

from broker.app import app
from shared.http.runner import run


def main() -> None:
    """Inicia o servidor HTTP do broker local."""
    run(app, "broker")


if __name__ == "__main__":
    main()
