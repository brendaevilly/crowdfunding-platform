"""Aplicação HTTP do broker local de mensagens."""

from shared.http.app import create_app

from broker.publish import router as publish_router
from broker.subscriptions import router as subscriptions_router

app = create_app("broker", version="0.1.0")

app.include_router(subscriptions_router)
app.include_router(publish_router)

