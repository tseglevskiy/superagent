"""EventBus — typed pub/sub with three priority tiers.

Tier 1 (instant):    Utility scores, counters. No LLM. Runs synchronously.
Tier 2 (fast):       Domain detection, between turns. Queued, async.
Tier 3 (background): Consolidation, idle-time work. Queued, async.

For Day 1 only the instant tier fires.  The queue infrastructure exists
so that later days can add fast/background handlers without touching this file.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class EventBus:
    """Simple sync + async event bus."""

    _sync_handlers: dict[str, list[Callable]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _async_handlers: dict[str, list[Callable]] = field(
        default_factory=lambda: defaultdict(list)
    )
    _bg_queue: asyncio.Queue | None = field(default=None, repr=False)

    # ---- registration ----

    def on(self, event: str, handler: Callable) -> None:
        """Register a synchronous (instant-tier) handler."""
        self._sync_handlers[event].append(handler)

    def on_async(self, event: str, handler: Callable) -> None:
        """Register an async (fast/background-tier) handler."""
        self._async_handlers[event].append(handler)

    # ---- emission ----

    def emit(self, event: str, data: Any = None) -> None:
        """Fire instant-tier handlers synchronously, queue async ones."""
        for handler in self._sync_handlers.get(event, []):
            try:
                handler(data)
            except Exception:
                log.exception("instant handler failed for %s", event)

        for handler in self._async_handlers.get(event, []):
            if self._bg_queue is not None:
                self._bg_queue.put_nowait((handler, data))
            else:
                log.debug("async handler for %s dropped (no queue)", event)

    # ---- background runner ----

    async def run_background(self) -> None:
        """Process queued async handlers.  Call as a long-lived task."""
        self._bg_queue = asyncio.Queue()
        while True:
            handler, data = await self._bg_queue.get()
            try:
                await handler(data)
            except Exception:
                log.exception("background handler failed")
            self._bg_queue.task_done()
