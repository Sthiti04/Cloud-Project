from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError
from google.protobuf import struct_pb2, wrappers_pb2
from kazoo.protocol.states import KazooState

from s23.adapters import HttpClient, SqsQueue
from s23.broker import KafkaBus, kafka_config
from s23.coordination import Election
from s23.domain import DeliveryRequest
from s23.registry import DeviceClient


def test_sqs_and_archive_use_real_sdk_with_in_memory_aws(aws, archive):
    sqs = aws.client("sqs")
    url = sqs.create_queue(QueueName="notifications")["QueueUrl"]
    queue = SqsQueue(sqs, url)
    request = DeliveryRequest(alert_id="a", version=1)
    queue.send(request)
    message = queue.receive()[0]
    assert DeliveryRequest.model_validate_json(message["Body"]) == request
    queue.delete(message["ReceiptHandle"])
    assert queue.receive() == []
    archive.put("event-1", '{"synthetic":true}')
    assert archive.client.get_object(
        Bucket="synthetic-readings",
        Key="readings/event-1.json",
    )["Body"].read()


def test_archive_retries_identical_readings_but_rejects_conflicting_reuse(archive):
    archive.put("event-1", '{"synthetic":true}')
    archive.put("event-1", '{"synthetic":true}')
    with pytest.raises(ValueError, match="reused"):
        archive.put("event-1", '{"synthetic":false}')
    assert (
        archive.client.get_object(
            Bucket="synthetic-readings",
            Key="readings/event-1.json",
        )["Body"].read()
        == b'{"synthetic":true}'
    )


def test_http_client_surfaces_errors_and_resolved_escalation_conflicts():
    session = Mock()
    response = session.request.return_value
    response.json.return_value = {"status": "ok"}
    client = HttpClient(session)
    assert client.call("GET", "http://service") == {"status": "ok"}
    session.request.assert_called_once()
    response.raise_for_status.assert_called_once()


def test_kafka_iam_config_uses_seconds_for_token_expiry():
    config = kafka_config("broker:9098", "aws", "ap-south-1")
    assert config["security.protocol"] == "SASL_SSL"
    with patch(
        "s23.broker.MSKAuthTokenProvider.generate_auth_token",
        return_value=("token", 1_800_000_000_000),
    ):
        assert config["oauth_cb"]("") == ("token", 1_800_000_000)
    assert kafka_config("kafka:9092", "local", "ap-south-1") == {
        "bootstrap.servers": "kafka:9092",
    }


def test_kafka_produce_waits_for_delivery_and_raises_on_failure():
    producer = Mock()
    producer.flush.return_value = 0

    def success(**kwargs):
        kwargs["on_delivery"](None, Mock())

    producer.produce.side_effect = success
    bus = KafkaBus(producer)
    bus.publish("topic", "{}", "key")
    producer.flush.assert_called_once_with(15)
    producer.produce.side_effect = lambda **kwargs: kwargs["on_delivery"]("offline", None)
    with pytest.raises(RuntimeError, match="offline"):
        bus.publish("topic", "{}", "key")
    producer.flush.return_value = 1
    with pytest.raises(TimeoutError):
        bus.publish("topic", "{}", "key")


def test_election_is_ordered_and_loses_authority_on_disconnect():
    client = Mock()
    client.state = KazooState.CONNECTED
    client.create.return_value = "/s23/escalation/worker-0000000007"
    client.get_children.return_value = ["worker-0000000008", "worker-0000000007"]
    election = Election(client)
    election.start()
    assert election.term() == 7
    client.get_children.return_value.insert(0, "worker-0000000006")
    assert election.term() is None
    client.state = KazooState.SUSPENDED
    election.on_state(KazooState.SUSPENDED)
    assert election.term() is None
    client.state = KazooState.CONNECTED
    election.on_state(KazooState.LOST)
    client.create.return_value = "/s23/escalation/worker-0000000011"
    client.get_children.return_value = ["worker-0000000011"]
    assert election.term() == 11
    election.close()
    client.stop.assert_called_once()
    client.close.assert_called_once()


def test_grpc_client_has_a_protobuf_contract_and_timeout():
    channel = Mock()
    result = struct_pb2.Struct()
    result.update({"device_id": "device-1", "patient_id": "patient-1", "active": True})
    channel.unary_unary.return_value.return_value = result
    client = DeviceClient(channel)
    assert client.get("device-1")["active"] is True
    args = channel.unary_unary.call_args
    assert args.args[0] == "/s23.DeviceRegistry/GetDevice"
    wire = args.kwargs["request_serializer"](wrappers_pb2.StringValue(value="device-1"))
    assert wrappers_pb2.StringValue.FromString(wire).value == "device-1"
    channel.unary_unary.return_value.assert_called_once()


def test_aws_permission_errors_are_not_reported_as_version_conflicts(table):
    from s23.store import DynamoStore

    error = ClientError({"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "Put")
    store = DynamoStore(table)
    with patch.object(store.client, "transact_write_items", side_effect=error):
        from s23.domain import Alert, Reading

        alert = Alert.from_reading(
            Reading(
                event_id="a",
                device_id="d",
                patient_id="p",
                heart_rate=145,
                observed_at=1_800_000_000_000,
            ),
            1_800_000_000_000,
        )
        with pytest.raises(ClientError):
            store.save(alert, None)
