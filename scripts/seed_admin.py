"""Cria o administrador inicial do microsserviço Identidade."""

from __future__ import annotations

import argparse
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from contracts.eventos import Perfil
from identidade.contas import repositorio
from identidade.contas.dominio import Email, StatusUsuario, Usuario
from identidade.contas.seguranca import gerar_hash_senha
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "apps" / "identidade" / "migrations"


def criar_admin(
    *,
    nome: str,
    email_str: str,
    senha_plana: str,
    data_dir: str | Path = "data",
) -> tuple[Usuario, bool]:
    """Cria o ADMIN inicial sem duplicar registros existentes."""
    if not nome.strip():
        raise ValueError("O nome do administrador é obrigatório")

    if len(senha_plana) < 12:
        raise ValueError("A senha do administrador deve ter ao menos 12 caracteres")

    email = Email(email_str)

    migrate("identidade", MIGRATIONS_DIR, data_dir)
    install_messaging_schema("identidade", data_dir)

    def operacao(conn: sqlite3.Connection) -> tuple[Usuario, bool]:
        existente = repositorio.buscar_usuario_por_email(conn, email.valor)

        if existente is not None:
            if existente.perfil != Perfil.ADMIN:
                raise ValueError("O e-mail informado já pertence a um usuário que não é ADMIN")

            return existente, False

        agora = datetime.now(UTC)

        administrador = Usuario(
            id=str(uuid.uuid4()),
            nome=nome.strip(),
            email=email,
            senha_hash=gerar_hash_senha(senha_plana),
            perfil=Perfil.ADMIN,
            status=StatusUsuario.ATIVO,
            criado_em=agora,
            atualizado_em=agora,
        )

        repositorio.salvar_usuario(conn, administrador)

        return administrador, True

    return transaction(operacao, "identidade", data_dir)


def main() -> None:
    """Executa o seed usando variáveis de ambiente."""
    parser = argparse.ArgumentParser(description="Cria o administrador inicial da plataforma.")
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Diretório dos bancos SQLite.",
    )
    args = parser.parse_args()

    nome = os.getenv("ADMIN_NOME", "").strip()
    email = os.getenv("ADMIN_EMAIL", "").strip()
    senha = os.getenv("ADMIN_SENHA", "")

    if not nome or not email or not senha:
        parser.error("Defina ADMIN_NOME, ADMIN_EMAIL e ADMIN_SENHA antes de executar o seed.")

    try:
        administrador, criado = criar_admin(
            nome=nome,
            email_str=email,
            senha_plana=senha,
            data_dir=args.data_dir,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if criado:
        print("Administrador criado com sucesso.")
    else:
        print("Administrador já existente. Nenhum registro foi duplicado.")

    print(f"ID: {administrador.id}")
    print(f"E-mail: {administrador.email.valor}")
    print(f"Perfil: {administrador.perfil.value}")
    print(f"Status: {administrador.status.value}")


if __name__ == "__main__":
    main()
