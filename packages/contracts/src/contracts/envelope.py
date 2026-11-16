"""Envelope versionado que acompanha todo evento no broker."""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from contracts.base import Contrato, Id

SCHEMA_VERSION_ATUAL = 1


class Envelope[P: Contrato](Contrato):
    """{eventId, topic, schemaVersion, occurredAt, correlationId, payload}.

    `schemaVersion` muda quando o payload ganha uma mudança incompatível; o consumidor
    rejeita (ou migra) versões que não conhece.
    """

    event_id: Id
    topic: str = Field(min_length=1)
    schema_version: int = Field(default=SCHEMA_VERSION_ATUAL, ge=1)
    occurred_at: AwareDatetime
    correlation_id: Id
    payload: P
