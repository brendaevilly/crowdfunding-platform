"""Ponto de entrada para execução do microsserviço Notificação."""

from notificacao.app import app
from shared.http.runner import run


def main() -> None:
    """Inicia o servidor HTTP do serviço Notificação."""
    run(app, "notificacao")


if __name__ == "__main__":
    main()
