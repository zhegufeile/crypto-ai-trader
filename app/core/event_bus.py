from collections import defaultdict
from collections.abc import Callable
from typing import Any


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, event_name: str, handler: Callable[[Any], None]) -> None:
        self._handlers[event_name].append(handler)

    def publish(self, event_name: str, payload: Any) -> None:
        for handler in self._handlers[event_name]:
            handler(payload)
