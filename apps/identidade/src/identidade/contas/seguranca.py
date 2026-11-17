"""Segurança e criptografia de senhas usando scrypt."""

from __future__ import annotations

import hashlib
import hmac
import secrets

N_SCRYPT = 16384
R_SCRYPT = 8
P_SCRYPT = 1


def gerar_hash_senha(senha: str) -> str:
    """Gera hash scrypt seguro com salt aleatório."""
    if len(senha) < 6:
        raise ValueError("A senha deve ter no mínimo 6 caracteres")

    salt = secrets.token_hex(16)
    chave = hashlib.scrypt(
        senha.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=N_SCRYPT,
        r=R_SCRYPT,
        p=P_SCRYPT,
    )
    return f"scrypt${salt}${chave.hex()}"


def verificar_senha(senha: str, hash_armazenado: str) -> bool:
    """Verifica se a senha confere com o hash scrypt em tempo constante."""
    partes = hash_armazenado.split("$")
    if len(partes) != 3 or partes[0] != "scrypt":
        return False

    salt = partes[1]
    chave_esperada = partes[2]

    chave_calculada = hashlib.scrypt(
        senha.encode("utf-8"),
        salt=salt.encode("utf-8"),
        n=N_SCRYPT,
        r=R_SCRYPT,
        p=P_SCRYPT,
    )
    return hmac.compare_digest(chave_esperada, chave_calculada.hex())
