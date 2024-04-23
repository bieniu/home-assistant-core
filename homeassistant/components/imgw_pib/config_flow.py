"""Config flow for IMGW-PIB integration."""

from __future__ import annotations

import logging
from typing import Any

from imgw_pib import ImgwPib
from imgw_pib.exceptions import ApiError
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import CONF_STATION_ID, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect."""
    client_session = async_get_clientsession(hass)

    station_id = data[CONF_STATION_ID]

    imgwpib = await ImgwPib.create(client_session, hydrological_station_id=station_id)

    hydrological_data = await imgwpib.get_hydrological_data()

    return {"title": f"{hydrological_data.station} ({hydrological_data.river})"}


class ImgwPibFlowHandler(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for IMGW-PIB."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            await self.async_set_unique_id(
                user_input[CONF_STATION_ID], raise_on_progress=False
            )
            self._abort_if_unique_id_configured()
            try:
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except ApiError:
                errors["base"] = "api_error"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title=info["title"], data=user_input)

        client_session = async_get_clientsession(self.hass)

        imgwpib = await ImgwPib.create(client_session)
        await imgwpib.update_hydrological_stations()

        options: list[SelectOptionDict] = [
            SelectOptionDict(value=station_id, label=station_name)
            for station_id, station_name in imgwpib.hydrological_stations.items()
        ]

        schema: vol.Schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        multiple=False,
                        sort=True,
                        mode=SelectSelectorMode.LIST,
                    ),
                )
            }
        )

        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""
