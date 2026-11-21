from functools import cached_property
from time import time

import boto3
import grpc
from kazoo.client import KazooClient

from s23.adapters import ApiKey, Archive, HttpAcknowledger, HttpClient, SqsQueue
from s23.broker import KafkaBus
from s23.coordination import Election
from s23.observability import Metrics
from s23.registry import DeviceClient, Registry
from s23.services import AlertService, Dispatcher, Scheduler
from s23.settings import Settings
from s23.store import DynamoStore


class Resources:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.session = boto3.Session(region_name=settings.region)
        self.metrics = Metrics(settings.service)

    def clock(self) -> int:
        return int(time() * 1000)

    @cached_property
    def store(self) -> DynamoStore:
        table = self.session.resource("dynamodb", endpoint_url=self.settings.aws_endpoint).Table(
            self.settings.table
        )
        return DynamoStore(table)

    @cached_property
    def queue(self) -> SqsQueue:
        return SqsQueue(
            self.session.client("sqs", endpoint_url=self.settings.aws_endpoint),
            self.settings.queue_url,
        )

    @cached_property
    def archive(self) -> Archive:
        return Archive(
            self.session.client("s3", endpoint_url=self.settings.aws_endpoint), self.settings.bucket
        )

    @cached_property
    def api_key(self) -> ApiKey:
        return ApiKey(
            self.session.client("secretsmanager", endpoint_url=self.settings.aws_endpoint),
            self.settings.api_secret_arn,
            self.settings.api_key,
        )

    @cached_property
    def broker(self) -> KafkaBus:
        return KafkaBus.from_settings(self.settings)

    @cached_property
    def registry(self) -> Registry:
        return Registry(self.settings)

    @cached_property
    def device_client(self) -> DeviceClient:
        return DeviceClient(
            grpc.insecure_channel(
                self.settings.registry_grpc,
                options=[("grpc.lb_policy_name", "round_robin")],
            )
        )

    @cached_property
    def http(self) -> HttpClient:
        return HttpClient()

    @cached_property
    def alerts(self) -> AlertService:
        return AlertService(self.store, self.clock)

    @cached_property
    def dispatcher(self) -> Dispatcher:
        return Dispatcher(
            self.store,
            self.clock,
            self.settings.ack_timeout_ms,
            self.settings.fail_first_delivery,
        )

    @cached_property
    def election(self) -> Election:
        return Election(KazooClient(hosts=self.settings.zk_hosts, timeout=10))

    @cached_property
    def scheduler(self) -> Scheduler:
        return Scheduler(
            self.store,
            self.broker,
            self.queue,
            HttpAcknowledger(self.http, self.settings.acknowledgement_url),
            self.clock,
            self.settings.dispatch_lease_ms,
            self.settings.max_dispatches,
        )
