"""Test the IMGW-PIB config flow."""

from unittest.mock import AsyncMock, PropertyMock, patch

from aiohttp import ClientError
from imgw_pib.exceptions import ApiError
import pytest

from homeassistant import config_entries
from homeassistant.components.imgw_pib.const import CONF_STATION_ID, DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from . import HYDROLOGICAL_DATA, HYDROLOGICAL_STATIONS


async def test_form(hass: HomeAssistant, mock_setup_entry: AsyncMock) -> None:
    """Test we get the form."""
    with (
        patch("homeassistant.components.imgw_pib.ImgwPib.update_hydrological_stations"),
        patch(
            "homeassistant.components.imgw_pib.ImgwPib.hydrological_stations",
            new_callable=PropertyMock,
            return_value=HYDROLOGICAL_STATIONS,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {}

    with (
        patch("homeassistant.components.imgw_pib.ImgwPib.update_hydrological_stations"),
        patch("homeassistant.components.imgw_pib.ImgwPib._update_hydrological_details"),
        patch(
            "homeassistant.components.imgw_pib.ImgwPib.get_hydrological_data",
            return_value=HYDROLOGICAL_DATA,
        ),
        patch(
            "homeassistant.components.imgw_pib.ImgwPib.hydrological_stations",
            new_callable=PropertyMock,
            return_value=HYDROLOGICAL_STATIONS,
        ),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_STATION_ID: "123"},
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "River Name (Station Name)"
    assert result["data"] == {CONF_STATION_ID: "123"}
    assert len(mock_setup_entry.mock_calls) == 1


@pytest.mark.parametrize(
    "exception", [ApiError("API Error"), ClientError, TimeoutError]
)
async def test_form_no_station_list(hass: HomeAssistant, exception: Exception) -> None:
    """Test aborting the flow when we cannot get the list of hydrological stations."""
    with patch(
        "homeassistant.components.imgw_pib.ImgwPib.update_hydrological_stations",
        side_effect=exception,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_station_list"
