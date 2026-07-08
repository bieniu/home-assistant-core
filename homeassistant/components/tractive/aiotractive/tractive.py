"""Entrypoint for the Tractive REST API."""

from __future__ import annotations

from collections.abc import AsyncIterator
from types import TracebackType
from typing import Any

from .api import API
from .channel import Channel
from .trackable_object import TrackableObject
from .tracker import Tracker


class Tractive:
    """Asynchronous Python client for the Tractive REST API."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize the client."""
        self._api = API(*args, **kwargs)

    async def authenticate(self) -> dict[str, Any] | None:
        """Authenticate the client."""
        return await self._api.authenticate()

    async def trackers(self) -> list[Tracker]:
        """Get all trackers for the authenticated user."""
        trackers: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackers"
        )
        return [Tracker(self._api, t) for t in trackers]

    def tracker(self, tracker_id: str) -> Tracker:
        """Get tracker by ID."""
        return Tracker(self._api, {"_id": tracker_id, "_type": "tracker"})

    def trackable_object(self, trackable_id: str) -> TrackableObject:
        """Get trackable object by ID."""
        return TrackableObject(self._api, {"_id": trackable_id, "_type": "pet"})

    async def trackable_objects(self) -> list[TrackableObject]:
        """Get all trackable objects for the authenticated user."""
        trackable_objects: list[dict[str, Any]] = await self._api.request(
            f"user/{await self._api.user_id()}/trackable_objects"
        )
        return [TrackableObject(self._api, t) for t in trackable_objects]

    async def events(self) -> AsyncIterator[dict[str, Any]]:
        """Listen for real-time events from the Tractive API."""
        async for event in Channel(self._api).listen():
            yield event

    async def close(self) -> None:
        """Close open client session."""
        await self._api.close()

    async def __aenter__(self) -> Tractive:  # noqa: PYI034
        """Async enter."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Async exit."""
        await self.close()
