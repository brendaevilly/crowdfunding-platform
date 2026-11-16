"""Contratos versionados: eventos e endpoints síncronos tipados.

Todo serviço importa os schemas daqui; nenhum app define payload por conta própria.
"""

from contracts import topicos
from contracts.campanhas_api import (
    CAMPANHA_STATUS_PATH,
    CampanhaStatusResponse,
    StatusCampanha,
    caminho_status_campanha,
)
from contracts.catalogo import (
    CATALOGO,
    ContratoInvalido,
    EventoSpec,
    chave_idempotencia,
    criar_envelope,
    ler_envelope,
)
from contracts.envelope import SCHEMA_VERSION_ATUAL, Envelope
from contracts.eventos import (
    AporteConfirmado,
    CampanhaLiquidada,
    CampanhaPublicada,
    IdentidadeVerificada,
    Perfil,
    ResultadoCampanha,
    ResultadoFinal,
    RetornoDistribuido,
    StatusUsuario,
    TotalArrecadadoAtualizado,
    UsuarioCadastrado,
    UsuarioStatusAlterado,
)

__all__ = [
    "CAMPANHA_STATUS_PATH",
    "CATALOGO",
    "SCHEMA_VERSION_ATUAL",
    "AporteConfirmado",
    "CampanhaLiquidada",
    "CampanhaPublicada",
    "CampanhaStatusResponse",
    "ContratoInvalido",
    "Envelope",
    "EventoSpec",
    "IdentidadeVerificada",
    "Perfil",
    "ResultadoCampanha",
    "ResultadoFinal",
    "RetornoDistribuido",
    "StatusCampanha",
    "StatusUsuario",
    "TotalArrecadadoAtualizado",
    "UsuarioCadastrado",
    "UsuarioStatusAlterado",
    "caminho_status_campanha",
    "chave_idempotencia",
    "criar_envelope",
    "ler_envelope",
    "topicos",
]
