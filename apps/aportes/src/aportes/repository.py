"""Persistência do agregado Aporte em SQLite."""

import sqlite3
from pathlib import Path

from aportes.domain import Aporte, StatusAporte, Valor
from shared.db import migrate, transaction
from shared.messaging_schema import install_messaging_schema

SERVICE = "aportes"
MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "migrations"


def inicializar_banco(data_dir: str | Path = "data") -> None:
    """Instala as migrations de domínio e mensageria."""
    migrate(SERVICE, MIGRATIONS_DIR, data_dir)
    install_messaging_schema(SERVICE, data_dir)


class AporteRepository:
    """Repositório de aportes no banco exclusivo do serviço."""

    def __init__(self, data_dir: str | Path = "data") -> None:
        self.data_dir = data_dir

    def salvar(self, aporte: Aporte) -> None:
        """Insere ou atualiza um aporte respeitando as regras do agregado."""

        def operacao(conn: sqlite3.Connection) -> None:
            existente = conn.execute(
                """
                SELECT campanha_id, investidor_id, valor, status
                FROM aporte
                WHERE id = ?
                """,
                (aporte.id,),
            ).fetchone()

            if existente is None:
                conn.execute(
                    """
                    INSERT INTO aporte (
                        id, campanha_id, investidor_id, valor, status
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        aporte.id,
                        aporte.campanha_id,
                        aporte.investidor_id,
                        aporte.valor.centavos,
                        aporte.status.value,
                    ),
                )
                return

            campanha_id, investidor_id, valor_atual, status_atual = existente

            # Os identificadores não podem ser modificados.
            if campanha_id != aporte.campanha_id or investidor_id != aporte.investidor_id:
                raise ValueError("Não é possível alterar os identificadores do aporte")

            # Um aporte confirmado ou rejeitado não pode ser modificado.
            if status_atual != StatusAporte.PENDENTE:
                if valor_atual != aporte.valor.centavos or status_atual != aporte.status.value:
                    raise ValueError("Não é possível alterar um aporte finalizado")

                # Salvar novamente o mesmo estado é permitido.
                return

            # Um aporte pendente pode continuar pendente,
            # ser confirmado ou ser rejeitado.
            if aporte.status not in (
                StatusAporte.PENDENTE,
                StatusAporte.CONFIRMADO,
                StatusAporte.REJEITADO,
            ):
                raise ValueError("Transição de status inválida")

            conn.execute(
                """
                UPDATE aporte
                SET valor = ?, status = ?
                WHERE id = ?
                """,
                (
                    aporte.valor.centavos,
                    aporte.status.value,
                    aporte.id,
                ),
            )

        transaction(operacao, SERVICE, self.data_dir)

    def buscar_por_id(self, aporte_id: str) -> Aporte | None:
        """Busca um aporte pelo identificador."""

        def operacao(conn: sqlite3.Connection) -> Aporte | None:
            row = conn.execute(
                """
                SELECT id, campanha_id, investidor_id, valor, status
                FROM aporte
                WHERE id = ?
                """,
                (aporte_id,),
            ).fetchone()

            if row is None:
                return None

            return Aporte(
                id=row[0],
                campanha_id=row[1],
                investidor_id=row[2],
                valor=Valor(row[3]),
                status=StatusAporte(row[4]),
            )

        return transaction(operacao, SERVICE, self.data_dir)
