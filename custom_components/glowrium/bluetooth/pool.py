"""Bound the number of Glowrium GATT sessions across local devices."""

from __future__ import annotations

import asyncio
from typing import Protocol


class Session(Protocol):
    @property
    def last_used(self) -> float: ...

    @property
    def busy(self) -> bool: ...

    @property
    def online(self) -> bool: ...

    async def evict(self) -> None: ...


class BleConnectionPool:
    """Evict an idle session before opening another connection.

    This is an integration-wide budget, not a claim about a proxy's actual slots.
    A busy session is never interrupted. Home Assistant still chooses the adapter.
    """

    def __init__(self, max_connections: int = 2) -> None:
        self.max_connections = max_connections
        self._sessions: set[Session] = set()
        self._lock = asyncio.Lock()

    async def reserve(self, session: Session) -> None:
        async with self._lock:
            if session in self._sessions:
                return
            if len(self._sessions) < self.max_connections:
                self._sessions.add(session)
                return
            candidates = [
                other
                for other in self._sessions
                if other is not session and not other.busy
            ]
            if not candidates:
                raise ConnectionError("All Glowrium Bluetooth sessions are busy")
            victim = min(candidates, key=lambda other: other.last_used)
            self._sessions.remove(victim)
            self._sessions.add(session)
        # Do not hold the budget lock while waiting for the other device's GATT
        # lock. A disconnecting session might itself need to reserve again.
        try:
            await victim.evict()
        except BaseException:
            async with self._lock:
                self._sessions.discard(session)
                if victim.online and len(self._sessions) < self.max_connections:
                    self._sessions.add(victim)
            raise

    def release(self, session: Session) -> None:
        self._sessions.discard(session)
