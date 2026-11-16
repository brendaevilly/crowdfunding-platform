"""Aplicação HTTP do broker local de mensagens."""

from shared.http.app import create_app

app = create_app("broker", version="0.1.0")
