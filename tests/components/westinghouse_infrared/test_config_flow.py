"""Tests for the Westinghouse Infrared config flow."""

from unittest.mock import AsyncMock, patch

from homeassistant.components.westinghouse_infrared.const import (
    CONF_INFRARED_EMITTER_ENTITY_ID,
    DOMAIN,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from tests.common import MockConfigEntry
from tests.components.infrared import EMITTER_ENTITY_ID as MOCK_INFRARED_ENTITY_ID


async def test_user_flow_no_emitters(hass: HomeAssistant) -> None:
    """Test the flow aborts when no infrared emitters are available."""
    with patch(
        "homeassistant.components.westinghouse_infrared.config_flow.infrared.async_get_emitters",
        return_value=[],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_emitters"


async def test_user_flow_success(hass: HomeAssistant) -> None:
    """Test the user flow shows the form and creates an entry."""
    with (
        patch(
            "homeassistant.components.westinghouse_infrared.config_flow.infrared.async_get_emitters",
            return_value=[MOCK_INFRARED_ENTITY_ID],
        ),
        patch(
            "homeassistant.components.westinghouse_infrared.config_flow.er.async_get",
        ) as mock_er,
        patch(
            "homeassistant.components.westinghouse_infrared.async_setup_entry",
            return_value=True,
        ) as mock_setup_entry,
    ):
        mock_entry = AsyncMock()
        mock_entry.name = "Test IR emitter"
        mock_entry.original_name = None
        mock_er.return_value.async_get.return_value = mock_entry

        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "user"
        assert result["errors"] is None

        user_input = {
            CONF_INFRARED_EMITTER_ENTITY_ID: MOCK_INFRARED_ENTITY_ID,
        }

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input,
        )

    assert result2["type"] is FlowResultType.CREATE_ENTRY
    assert result2["title"] == "Westinghouse Fan via Test IR emitter"
    assert result2["data"] == user_input
    assert len(mock_setup_entry.mock_calls) == 1
    assert result2["result"].unique_id == f"fan_{MOCK_INFRARED_ENTITY_ID}"


async def test_user_flow_already_configured(hass: HomeAssistant) -> None:
    """Test the flow aborts when the emitter is already configured."""
    mock_entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_INFRARED_EMITTER_ENTITY_ID: MOCK_INFRARED_ENTITY_ID,
        },
        unique_id=f"fan_{MOCK_INFRARED_ENTITY_ID}",
    )
    mock_entry.add_to_hass(hass)

    with patch(
        "homeassistant.components.westinghouse_infrared.config_flow.infrared.async_get_emitters",
        return_value=[MOCK_INFRARED_ENTITY_ID],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}
        )

        user_input = {
            CONF_INFRARED_EMITTER_ENTITY_ID: MOCK_INFRARED_ENTITY_ID,
        }

        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            user_input,
        )

    assert result2["type"] is FlowResultType.ABORT
    assert result2["reason"] == "already_configured"
