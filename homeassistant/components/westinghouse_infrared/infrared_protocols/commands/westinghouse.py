"""Westinghouse infrared fan commands."""

from typing import override

from infrared_protocols.commands import Command

FRAME_GAP = 96000  # Space (µs) between repeated frames


class WestinghouseFanCommand(Command):
    """Westinghouse infrared fan command.

    A raw timing-based IR command for controlling a Westinghouse fan. The
    carrier frequency is fixed at 38 kHz.
    """

    def __init__(
        self,
        *,
        raw_timings: list[int],
        modulation: int = 38000,
        repeat_count: int = 0,
    ) -> None:
        """Initialize the Westinghouse fan command.

        Args:
            raw_timings: Raw IR timings in microseconds. Positive values are
                pulse (mark) durations, negative values are space durations.
            modulation: Carrier frequency in Hz.
            repeat_count: Number of times the frame is repeated when sent.
        """
        super().__init__(modulation=modulation, repeat_count=repeat_count)
        self._raw_timings = raw_timings

    @override
    def get_raw_timings(self) -> list[int]:
        """Return the raw timings for the command.

        The frame is repeated ``repeat_count`` times to support devices that
        require multiple transmissions per button press. A space gap is
        inserted between consecutive frames, matching the NEC frame gap.
        """
        if self.repeat_count <= 0:
            return list(self._raw_timings)

        timings: list[int] = list(self._raw_timings)
        for _ in range(self.repeat_count):
            timings.append(-FRAME_GAP)
            timings.extend(self._raw_timings)
        return timings
