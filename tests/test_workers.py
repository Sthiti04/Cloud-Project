from unittest.mock import Mock

import pytest

from s23.domain import Reading
from s23.workers import results, rules, schedule

NOW = 1_800_000_000_000


def test_rule_worker_commits_only_after_successful_alert_creation():
    resources = Mock()
    consumer = resources.broker.consumer.return_value
    message = consumer.poll.return_value
    message.error.return_value = None
    message.value.return_value = (
        Reading(event_id="r", device_id="d", patient_id="p", heart_rate=145, observed_at=NOW)
        .model_dump_json()
        .encode()
    )
    stop = Mock()
    stop.is_set.side_effect = [False, True]
    rules(resources, stop)
    resources.http.call.assert_called_once()
    consumer.commit.assert_called_once_with(message=message, asynchronous=False)
    consumer.close.assert_called_once()


def test_rule_worker_does_not_commit_failed_work():
    resources = Mock()
    consumer = resources.broker.consumer.return_value
    message = consumer.poll.return_value
    message.error.return_value = None
    message.value.return_value = Reading(
        event_id="r", device_id="d", patient_id="p", heart_rate=145, observed_at=NOW
    ).model_dump_json()
    resources.http.call.side_effect = RuntimeError("outage")
    stop = Mock()
    stop.is_set.return_value = False
    with pytest.raises(RuntimeError, match="outage"):
        rules(resources, stop)
    consumer.commit.assert_not_called()
    consumer.close.assert_called_once()


def test_results_worker_stores_before_commit():
    resources = Mock()
    consumer = resources.broker.consumer.return_value
    message = consumer.poll.return_value
    message.error.return_value = None
    message.value.return_value = '{"device_id":"d","window_end":1800000000000}'
    stop = Mock()
    stop.is_set.side_effect = [False, True]
    results(resources, stop)
    resources.store.put_result.assert_called_once()
    consumer.commit.assert_called_once()


def test_election_worker_closes_and_exposes_leadership():
    resources = Mock()
    resources.election.term.return_value = 7
    resources.scheduler.tick.return_value = 1
    stop = Mock()
    stop.is_set.side_effect = [False, True]
    schedule(resources, stop)
    resources.election.start.assert_called_once()
    resources.election.close.assert_called_once()
    resources.metrics.leader.labels.return_value.set.assert_called_with(1)
