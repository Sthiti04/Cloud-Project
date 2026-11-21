import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from s23 import dispatcher, loadtest
from s23.services import TransientDeliveryError


def test_partial_batch_failures_do_not_retry_successful_records():
    runtime = Mock()
    runtime.dispatcher.deliver.side_effect = [TransientDeliveryError("test"), "delivered"]
    records = [
        {
            "messageId": str(i),
            "body": json.dumps({"alert_id": str(i), "version": 1}),
            "attributes": {"ApproximateReceiveCount": "1"},
        }
        for i in range(2)
    ]
    assert dispatcher.handle_batch({"Records": records}, runtime) == {
        "batchItemFailures": [{"itemIdentifier": "0"}],
    }
    with pytest.raises(ValueError):
        dispatcher.handle_batch({}, runtime)


def test_lambda_emits_failed_record_metrics_without_secrets(caplog):
    caplog.set_level("INFO", logger="s23")
    runtime = Mock()
    runtime.clock.return_value = 1_800_000_000_000
    runtime.dispatcher.deliver.return_value = "delivered"
    event = {"Records": [{"messageId": "a", "body": '{"alert_id":"a","version":1}'}]}
    with patch("s23.dispatcher.resources", return_value=runtime):
        assert dispatcher.handler(event, SimpleNamespace(function_name="demo")) == {
            "batchItemFailures": [],
        }
    metrics = [json.loads(r.message) for r in caplog.records if "_aws" in r.message][0]
    assert metrics["FailedRecords"] == 0
    assert metrics["FunctionName"] == "demo"


def test_local_dispatcher_deletes_only_successful_messages():
    for failed in (False, True):
        runtime = Mock()
        runtime.queue.receive.side_effect = [
            [
                {
                    "MessageId": "a",
                    "Body": '{"alert_id":"a","version":1}',
                    "ReceiptHandle": "receipt",
                }
            ],
            RuntimeError("stop-local-loop"),
        ]
        with (
            patch("s23.dispatcher.resources", return_value=runtime),
            patch(
                "s23.dispatcher.handle_batch",
                return_value={
                    "batchItemFailures": [{"itemIdentifier": "a"}] if failed else [],
                },
            ),
        ):
            with pytest.raises(RuntimeError, match="stop-local-loop"):
                dispatcher.local_run()
        assert runtime.queue.delete.call_count == (not failed)


def test_lambda_resources_cache_and_load_test_hides_key_in_environment(local_settings):
    dispatcher.resources.cache_clear()
    with (
        patch("s23.dispatcher.Settings.from_env", return_value=local_settings),
        patch("s23.dispatcher.Resources", return_value=Mock()) as factory,
    ):
        assert dispatcher.resources() is dispatcher.resources()
        factory.assert_called_once()
    dispatcher.resources.cache_clear()
    runtime = Mock()
    runtime.api_key.get.return_value = "synthetic-private-test-key"
    runtime.settings.ingestion_url = "http://vital-ingestion:8080"
    with (
        patch("s23.loadtest.Resources", return_value=runtime),
        patch("s23.loadtest.Settings.from_env", return_value=local_settings),
        patch("s23.loadtest.subprocess.run") as run,
    ):
        loadtest.main()
        assert run.call_args.kwargs["env"]["API_KEY"] == "synthetic-private-test-key"
        assert "synthetic-private-test-key" not in run.call_args.args[0]
