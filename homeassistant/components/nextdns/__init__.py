"""The NextDNS component."""

import asyncio
from dataclasses import dataclass
import logging
from types import MappingProxyType

from aiohttp.client_exceptions import ClientConnectorError
from nextdns import (
    AnalyticsDnssec,
    AnalyticsEncryption,
    AnalyticsIpVersions,
    AnalyticsProtocols,
    AnalyticsStatus,
    ApiError,
    ConnectionStatus,
    InvalidApiKeyError,
    NextDns,
    Settings,
)
from tenacity import RetryError

from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import CONF_API_KEY, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    ATTR_CONNECTION,
    ATTR_DNSSEC,
    ATTR_ENCRYPTION,
    ATTR_IP_VERSIONS,
    ATTR_PROTOCOLS,
    ATTR_SETTINGS,
    ATTR_STATUS,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    DOMAIN,
    SUBENTRY_TYPE_PROFILE,
)
from .coordinator import (
    NextDnsConnectionUpdateCoordinator,
    NextDnsDnssecUpdateCoordinator,
    NextDnsEncryptionUpdateCoordinator,
    NextDnsIpVersionsUpdateCoordinator,
    NextDnsProtocolsUpdateCoordinator,
    NextDnsSettingsUpdateCoordinator,
    NextDnsStatusUpdateCoordinator,
    NextDnsUpdateCoordinator,
)

_LOGGER = logging.getLogger(__name__)

type NextDnsConfigEntry = ConfigEntry[NextDnsData]


@dataclass
class NextDnsCoordinators:
    """Coordinators for a NextDNS profile."""

    connection: NextDnsUpdateCoordinator[ConnectionStatus]
    dnssec: NextDnsUpdateCoordinator[AnalyticsDnssec]
    encryption: NextDnsUpdateCoordinator[AnalyticsEncryption]
    ip_versions: NextDnsUpdateCoordinator[AnalyticsIpVersions]
    protocols: NextDnsUpdateCoordinator[AnalyticsProtocols]
    settings: NextDnsUpdateCoordinator[Settings]
    status: NextDnsUpdateCoordinator[AnalyticsStatus]


@dataclass
class NextDnsData:
    """Runtime data for the NextDNS integration."""

    client: NextDns
    profiles: dict[str, NextDnsCoordinators]


PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.SENSOR, Platform.SWITCH]
COORDINATORS: list[tuple[str, type[NextDnsUpdateCoordinator]]] = [
    (ATTR_CONNECTION, NextDnsConnectionUpdateCoordinator),
    (ATTR_DNSSEC, NextDnsDnssecUpdateCoordinator),
    (ATTR_ENCRYPTION, NextDnsEncryptionUpdateCoordinator),
    (ATTR_IP_VERSIONS, NextDnsIpVersionsUpdateCoordinator),
    (ATTR_PROTOCOLS, NextDnsProtocolsUpdateCoordinator),
    (ATTR_SETTINGS, NextDnsSettingsUpdateCoordinator),
    (ATTR_STATUS, NextDnsStatusUpdateCoordinator),
]


async def async_setup_entry(hass: HomeAssistant, entry: NextDnsConfigEntry) -> bool:
    """Set up NextDNS as config entry."""
    api_key = entry.data[CONF_API_KEY]

    websession = async_get_clientsession(hass)
    try:
        nextdns = await NextDns.create(websession, api_key)
    except (ApiError, ClientConnectorError, RetryError, TimeoutError) as err:
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="cannot_connect",
            translation_placeholders={
                "entry": entry.title,
                "error": repr(err),
            },
        ) from err
    except InvalidApiKeyError as err:
        raise ConfigEntryAuthFailed(
            translation_domain=DOMAIN,
            translation_key="auth_error",
            translation_placeholders={"entry": entry.title},
        ) from err

    profiles: dict[str, NextDnsCoordinators] = {}

    for subentry_id, subentry in entry.subentries.items():
        if subentry.subentry_type != SUBENTRY_TYPE_PROFILE:
            continue

        profile_id = subentry.data[CONF_PROFILE_ID]
        tasks = []
        coordinators = {}

        # Independent DataUpdateCoordinator is used for each API endpoint to avoid
        # unnecessary requests when entities using this endpoint are disabled.
        for coordinator_name, coordinator_class in COORDINATORS:
            coordinator = coordinator_class(
                hass, entry, nextdns, profile_id, subentry_id
            )
            tasks.append(coordinator.async_config_entry_first_refresh())
            coordinators[coordinator_name] = coordinator

        await asyncio.gather(*tasks)

        profiles[subentry_id] = NextDnsCoordinators(**coordinators)

    entry.runtime_data = NextDnsData(client=nextdns, profiles=profiles)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: NextDnsConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: NextDnsConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating NextDNS config entry from version %s",
        entry.version,
    )

    if entry.version == 1:
        profile_id = entry.data[CONF_PROFILE_ID]
        profile_name = entry.title

        # Create new data without profile_id
        new_data = {CONF_API_KEY: entry.data[CONF_API_KEY]}

        hass.config_entries.async_update_entry(
            entry,
            data=new_data,
            title="NextDNS",
            version=2,
        )

        hass.config_entries.async_add_subentry(
            entry,
            ConfigSubentry(
                data=MappingProxyType(
                    {CONF_PROFILE_ID: profile_id, CONF_PROFILE_NAME: profile_name}
                ),
                subentry_type=SUBENTRY_TYPE_PROFILE,
                title=profile_name,
                unique_id=profile_id,
            ),
        )

        _LOGGER.debug(
            "Migration to version %s successful",
            entry.version,
        )

    return True
