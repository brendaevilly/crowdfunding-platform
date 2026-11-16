"""Base dos contratos: imutáveis, sem campos extras, JSON em camelCase."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from pydantic.alias_generators import to_camel

Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]
"""Identificador opaco de agregado/evento (ex.: UUID)."""

Centavos = Annotated[int, Field(ge=0)]
"""Valor monetário em centavos (inteiro, nunca float)."""

CentavosPositivos = Annotated[int, Field(gt=0)]


class Contrato(BaseModel):
    """Todo schema publicado herda daqui.

    Em Python os campos são snake_case; no JSON (published language) são camelCase.
    Use `model_dump(by_alias=True)` / `model_dump_json(by_alias=True)` ou `para_json()`.
    """

    model_config = ConfigDict(
        frozen=True,
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
    )

    def para_json(self) -> str:
        return self.model_dump_json(by_alias=True)

    def para_dict(self) -> dict[str, object]:
        return self.model_dump(mode="json", by_alias=True)
