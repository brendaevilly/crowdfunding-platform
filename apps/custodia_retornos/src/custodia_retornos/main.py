"""Ponto de entrada do microsserviço Custódia e Retornos."""

from custodia_retornos.app import app
from shared.http.runner import run


def main() -> None:
    """Inicia o servidor HTTP da Custódia."""
    run(app, "custodia_retornos")


if __name__ == "__main__":
    main()
