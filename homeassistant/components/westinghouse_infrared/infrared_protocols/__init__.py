"""Westinghouse infrared protocol support."""

from .codes.westinghouse.fan import WestinghouseFanCode
from .commands import WestinghouseFanCommand

__all__ = ["WestinghouseFanCode", "WestinghouseFanCommand"]
