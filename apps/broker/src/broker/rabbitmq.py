"""Integração do broker com RabbitMQ via AMQP (pika)."""

from __future__ import annotations

import json
import logging
import os
from typing import Any

import pika

logger = logging.getLogger(__name__)

EXCHANGE_EVENTS = "crowdfunding.events"
EXCHANGE_DLX = "crowdfunding.dlx"
QUEUE_DLQ = "crowdfunding.dlq"


def get_rabbitmq_url() -> str:
    """Retorna a URL de conexão do RabbitMQ."""
    return os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")


def is_rabbitmq_enabled() -> bool:
    """Verifica se a integração externa com RabbitMQ está habilitada."""
    return os.getenv("RABBITMQ_ENABLED", "false").lower() in ("true", "1", "yes")


def is_rabbitmq_available() -> bool:
    """Verifica se o servidor RabbitMQ está acessível."""
    if not is_rabbitmq_enabled():
        return False
    try:
        params = pika.URLParameters(get_rabbitmq_url())
        params.socket_timeout = 1.0
        connection = pika.BlockingConnection(params)
        connection.close()
        return True
    except Exception:
        return False


def setup_rabbitmq_topology(channel: pika.adapters.blocking_connection.BlockingChannel) -> None:
    """Declara exchanges e a fila de DLQ no RabbitMQ."""
    # Exchange principal de eventos (topic para fan-out por tópico)
    channel.exchange_declare(
        exchange=EXCHANGE_EVENTS,
        exchange_type="topic",
        durable=True,
    )
    # Dead Letter Exchange e fila DLQ
    channel.exchange_declare(
        exchange=EXCHANGE_DLX,
        exchange_type="fanout",
        durable=True,
    )
    channel.queue_declare(
        queue=QUEUE_DLQ,
        durable=True,
    )
    channel.queue_bind(
        exchange=EXCHANGE_DLX,
        queue=QUEUE_DLQ,
    )


def publish_to_rabbitmq(
    topic: str,
    event_id: str,
    payload: dict[str, Any],
    correlation_id: str | None = None,
) -> bool:
    """Publica um evento no RabbitMQ usando routing key = topic."""
    if not is_rabbitmq_enabled():
        return False
    try:
        params = pika.URLParameters(get_rabbitmq_url())
        params.socket_timeout = 2.0
        with pika.BlockingConnection(params) as connection:
            channel = connection.channel()
            setup_rabbitmq_topology(channel)

            message_body = json.dumps(
                {
                    "eventId": event_id,
                    "topic": topic,
                    "payload": payload,
                    "correlationId": correlation_id,
                }
            ).encode("utf-8")

            properties = pika.BasicProperties(
                content_type="application/json",
                delivery_mode=pika.DeliveryMode.Persistent,
                message_id=event_id,
                correlation_id=correlation_id,
                headers={"topic": topic},
            )

            channel.basic_publish(
                exchange=EXCHANGE_EVENTS,
                routing_key=topic,
                body=message_body,
                properties=properties,
            )
            logger.info(
                "Evento %s publicado no RabbitMQ (exchange=%s, routing_key=%s)",
                event_id,
                EXCHANGE_EVENTS,
                topic,
            )
            return True
    except Exception as exc:
        logger.warning("RabbitMQ não disponível para publicação de %s: %s", event_id, exc)
        return False


def setup_rabbitmq_subscription(service: str, topic: str) -> bool:
    """Cria uma fila para o serviço no RabbitMQ e faz o bind com o tópico."""
    if not is_rabbitmq_enabled():
        return False
    try:
        params = pika.URLParameters(get_rabbitmq_url())
        params.socket_timeout = 2.0
        with pika.BlockingConnection(params) as connection:
            channel = connection.channel()
            setup_rabbitmq_topology(channel)

            queue_name = f"crowdfunding.{service}.{topic}"
            channel.queue_declare(
                queue=queue_name,
                durable=True,
                arguments={
                    "x-dead-letter-exchange": EXCHANGE_DLX,
                },
            )
            channel.queue_bind(
                exchange=EXCHANGE_EVENTS,
                queue=queue_name,
                routing_key=topic,
            )
            logger.info(
                "Fila RabbitMQ configurada: %s vinculada ao tópico %s",
                queue_name,
                topic,
            )
            return True
    except Exception as exc:
        logger.warning("RabbitMQ não disponível para assinatura %s/%s: %s", service, topic, exc)
        return False
