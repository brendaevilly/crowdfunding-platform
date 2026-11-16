
"""Aplicação HTTP do broker local de mensagens."""

from broker.dlq import router as dlq_router
from broker.publish import router as publish_router
from broker.stats import router as stats_router
from broker.subscriptions import router as subscriptions_router
from shared.http.app import create_app

app = create_app("broker", version="0.1.0")

app.include_router(subscriptions_router)
app.include_router(publish_router)
app.include_router(dlq_router)
app.include_router(stats_router)
