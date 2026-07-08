"""Base class for Tractive data objects."""

from __future__ import annotations

from typing import Any

from .api import API


class DataObject:
    """Base class for Tractive data objects."""

    def __init__(self, api: API, data: dict[str, Any]) -> None:
        """Initialize the data object."""
        self._api = api
        self._id: str = data["_id"]
        self.type: str = data["_type"]

    def __repr__(self) -> str:
        """Return string representation of the data object."""
        return f"<{self.__class__.__name__} id={self._id} type={self.type}>"
