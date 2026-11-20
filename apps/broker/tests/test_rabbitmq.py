"""Testes da integração com RabbitMQ."""

from unittest.mock import MagicMock, patch

from broker.rabbitmq import (
    EXCHANGE_DLX,
    EXCHANGE_EVENTS,
    QUEUE_DLQ,
    get_rabbitmq_url,
    is_rabbitmq_available,
    publish_to_rabbitmq,
    setup_rabbitmq_subscription,
    setup_rabbitmq_topology,
)


def test_get_rabbitmq_url_padrao(monkeypatch):
    monkeypatch.delenv("RABBITMQ_URL", raising=False)
    assert get_rabbitmq_url() == "amqp://guest:guest@localhost:5672/"


def test_get_rabbitmq_url_customizada(monkeypatch):
    monkeypatch.setenv("RABBITMQ_URL", "amqp://user:pass@rabbitmq.local:5672/vhost")
    assert get_rabbitmq_url() == "amqp://user:pass@rabbitmq.local:5672/vhost"


def test_is_rabbitmq_available_falso_quando_indisponivel():
    with patch("pika.BlockingConnection", side_effect=Exception("Sem conexão")):
        assert is_rabbitmq_available() is False


def test_is_rabbitmq_available_verdadeiro_quando_conecta():
    mock_conn = MagicMock()
    with patch("pika.BlockingConnection", return_value=mock_conn):
        assert is_rabbitmq_available() is True
        mock_conn.close.assert_called_once()


def test_setup_rabbitmq_topology():
    mock_channel = MagicMock()
    setup_rabbitmq_topology(mock_channel)

    # Verifica declaração dos exchanges e fila DLQ
    mock_channel.exchange_declare.assert_any_call(
        exchange=EXCHANGE_EVENTS,
        exchange_type="topic",
        durable=True,
    )
    mock_channel.exchange_declare.assert_any_call(
        exchange=EXCHANGE_DLX,
        exchange_type="fanout",
        durable=True,
    )
    mock_channel.queue_declare.assert_called_once_with(
        queue=QUEUE_DLQ,
        durable=True,
    )
    mock_channel.queue_bind.assert_called_once_with(
        exchange=EXCHANGE_DLX,
        queue=QUEUE_DLQ,
    )


def test_publish_to_rabbitmq_sucesso():
    mock_conn = MagicMock()
    mock_channel = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.channel.return_value = mock_channel

    with patch("pika.BlockingConnection", return_value=mock_conn):
        sucesso = publish_to_rabbitmq(
            topic="AporteConfirmado",
            event_id="evt-123",
            payload={"aporteId": "apo-1"},
            correlation_id="cor-1",
        )

        assert sucesso is True
        mock_channel.basic_publish.assert_called_once()


def test_publish_to_rabbitmq_resiliente_com_falha():
    with patch("pika.BlockingConnection", side_effect=Exception("Falha de conexão")):
        sucesso = publish_to_rabbitmq(
            topic="AporteConfirmado",
            event_id="evt-123",
            payload={"aporteId": "apo-1"},
        )
        assert sucesso is False


def test_setup_rabbitmq_subscription_sucesso():
    mock_conn = MagicMock()
    mock_channel = MagicMock()
    mock_conn.__enter__.return_value = mock_conn
    mock_conn.channel.return_value = mock_channel

    with patch("pika.BlockingConnection", return_value=mock_conn):
        sucesso = setup_rabbitmq_subscription("campanhas", "AporteConfirmado")
        assert sucesso is True
        mock_channel.queue_declare.assert_called_with(
            queue="crowdfunding.campanhas.AporteConfirmado",
            durable=True,
            arguments={"x-dead-letter-exchange": EXCHANGE_DLX},
        )
        mock_channel.queue_bind.assert_called_with(
            exchange=EXCHANGE_EVENTS,
            queue="crowdfunding.campanhas.AporteConfirmado",
            routing_key="AporteConfirmado",
        )
