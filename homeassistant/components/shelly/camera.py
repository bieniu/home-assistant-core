"""Support for Shelly cameras."""

import aiohttp

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import ShellyConfigEntry, ShellyRpcCoordinator
from .entity import ShellyRpcEntity
from .utils import get_rpc_key_instances

PARALLEL_UPDATES = 0


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ShellyConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Shelly camera entities."""
    if not config_entry.runtime_data.rpc:
        return
    coordinator = config_entry.runtime_data.rpc
    async_add_entities(
        ShellyCameraEntity(coordinator, key)
        for key in get_rpc_key_instances(coordinator.device.status, "camera")
    )


class ShellyCameraEntity(ShellyRpcEntity, Camera):
    """Shelly camera entity for RPC-based Gen2/Gen3 devices."""

    _attr_name = None
    _attr_supported_features = CameraEntityFeature.ON_OFF | CameraEntityFeature.STREAM

    def __init__(self, coordinator: ShellyRpcCoordinator, key: str) -> None:
        """Initialize Shelly camera entity."""
        ShellyRpcEntity.__init__(self, coordinator, key)
        Camera.__init__(self)
        self._camera_id: int = int(key.split(":")[1])

    @property
    def is_on(self) -> bool:
        """Return True if the camera is on (privacy mode disabled)."""
        return not self.coordinator.device.config[self.key]["privacy"]

    @property
    def is_recording(self) -> bool:
        """Return True if the camera is currently recording."""
        return bool(self.status.get("recordings"))

    @property
    def is_streaming(self) -> bool:
        """Return True if the camera is currently streaming."""
        return self.status["streams"] > 0

    @property
    def motion_detection_enabled(self) -> bool:
        """Return True if camera is armed (motion detection active)."""
        return self.coordinator.device.config[self.key]["arm"]

    @property
    def use_stream_for_stills(self) -> bool:
        """Use direct HTTP snapshot instead of stream for still images."""
        return False

    async def stream_source(self) -> str | None:
        """Return the WHEP stream source URL for go2rtc."""
        return f"webrtc:{self.coordinator.configuration_url}/camera/{self._camera_id}/whep/0"

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return a still image from the camera's HTTP snapshot endpoint."""
        session = async_get_clientsession(self.hass)
        url = f"{self.coordinator.configuration_url}/camera/{self._camera_id}/snapshot"
        try:
            async with session.get(
                url, timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
        except aiohttp.ClientError, TimeoutError:
            return None
        return None

    async def async_turn_on(self) -> None:
        """Turn the camera on by disabling privacy mode."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"privacy": False}},
        )

    async def async_turn_off(self) -> None:
        """Turn the camera off by enabling privacy mode."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"privacy": True}},
        )

    async def async_enable_motion_detection(self) -> None:
        """Enable motion detection by arming the camera."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"arm": True}},
        )

    async def async_disable_motion_detection(self) -> None:
        """Disable motion detection by disarming the camera."""
        await self.call_rpc(
            "Camera.SetConfig",
            {"id": self._camera_id, "config": {"arm": False}},
        )
