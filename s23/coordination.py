from typing import Any

from kazoo.exceptions import NoNodeError
from kazoo.protocol.states import KazooState

from s23.observability import log

ELECTION_PATH = "/s23/escalation"


class Election:
    def __init__(self, client: Any):
        self.client = client
        self.node: str | None = None
        self.client.add_listener(self.on_state)

    def on_state(self, state: str) -> None:
        log("zookeeper_session", state=state)
        if state == KazooState.LOST:
            self.node = None

    def start(self) -> None:
        self.client.start(timeout=15)
        self.client.ensure_path(ELECTION_PATH)
        self._join()

    def _join(self) -> None:
        self.node = self.client.create(
            f"{ELECTION_PATH}/worker-",
            b"s23-alert-queue-manager",
            ephemeral=True,
            sequence=True,
        )
        log("election_joined", node=self.node)

    def term(self) -> int | None:
        if self.client.state != KazooState.CONNECTED:
            return None
        if self.node is None:
            self.client.ensure_path(ELECTION_PATH)
            self._join()
        children = sorted(self.client.get_children(ELECTION_PATH))
        name = str(self.node).rsplit("/", 1)[-1]
        if name not in children:
            log("election_node_expired", node=self.node)
            self.node = None
            return None
        if name != children[0]:
            return None
        return int(name.removeprefix("worker-"))

    def close(self) -> None:
        if self.node is not None and self.client.state == KazooState.CONNECTED:
            try:
                self.client.delete(self.node)
            except NoNodeError:
                log("election_node_already_expired", node=self.node)
        self.client.stop()
        self.client.close()
