from typing import Any

from aws_msk_iam_sasl_signer import MSKAuthTokenProvider
from confluent_kafka import Consumer, Producer

from s23.settings import Settings


def kafka_config(brokers: str, mode: str, region: str) -> dict[str, Any]:
    config: dict[str, Any] = {"bootstrap.servers": brokers}
    if mode == "aws":

        def token(_: str) -> tuple[str, float]:
            value, expires_ms = MSKAuthTokenProvider.generate_auth_token(region)
            return value, expires_ms / 1000

        config.update(
            {
                "security.protocol": "SASL_SSL",
                "sasl.mechanisms": "OAUTHBEARER",
                "oauth_cb": token,
            }
        )
    return config


class KafkaBus:
    def __init__(self, producer: Any, config: dict[str, Any] | None = None):
        self.producer = producer
        self.config = config or {}

    @classmethod
    def from_settings(cls, settings: Settings) -> "KafkaBus":
        config = kafka_config(settings.brokers, settings.mode, settings.region)
        producer = Producer(
            {
                **config,
                "enable.idempotence": True,
                "delivery.timeout.ms": 15000,
            }
        )
        return cls(producer, config)

    def publish(self, topic: str, value: str, key: str) -> None:
        errors: list[str] = []

        def completed(error: Any, _: Any) -> None:
            if error is not None:
                errors.append(str(error))

        self.producer.produce(topic=topic, value=value, key=key, on_delivery=completed)
        if self.producer.flush(15):
            raise TimeoutError(f"Kafka delivery did not finish for topic {topic}")
        if errors:
            raise RuntimeError(f"Kafka delivery failed: {errors[0]}")

    def consumer(self, group: str, topic: str) -> Any:
        consumer = Consumer(
            {
                **self.config,
                "group.id": group,
                "auto.offset.reset": "earliest",
                "enable.auto.commit": False,
                "enable.auto.offset.store": False,
            }
        )
        consumer.subscribe([topic])
        return consumer
