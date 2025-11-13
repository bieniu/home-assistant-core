"""Tests for Shelly services."""

from unittest.mock import AsyncMock, Mock

from aioshelly.exceptions import DeviceConnectionError, RpcCallError
import pytest

from homeassistant.components.shelly.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr

from . import init_integration


async def test_service_get_kvs(
    hass: HomeAssistant, mock_rpc_device: Mock, device_registry: dr.DeviceRegistry
) -> None:
    """Test get_kvs service."""
    await init_integration(hass, 2)
    
    # Get the device
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_NETWORK_MAC, "123456789ABC")}
    )
    assert device
    
    # Mock the RPC call
    mock_rpc_device.call_rpc = AsyncMock(return_value={"value": "test_value"})
    
    # Call the service
    response = await hass.services.async_call(
        DOMAIN,
        "get_kvs",
        {"device_id": device.id, "key": "my_key"},
        blocking=True,
        return_response=True,
    )
    
    # Verify the response
    assert response == {"value": "test_value"}
    
    # Verify the RPC call was made with correct parameters
    mock_rpc_device.call_rpc.assert_called_once_with("KVS.Get", {"key": "my_key"})


async def test_service_get_kvs_multiple_devices(
    hass: HomeAssistant, mock_rpc_device: Mock, device_registry: dr.DeviceRegistry
) -> None:
    """Test get_kvs service with multiple device IDs (should use first)."""
    await init_integration(hass, 2)
    
    # Get the device
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_NETWORK_MAC, "123456789ABC")}
    )
    assert device
    
    # Mock the RPC call
    mock_rpc_device.call_rpc = AsyncMock(return_value={"value": "test_value"})
    
    # Call the service with multiple device IDs (pass as list)
    response = await hass.services.async_call(
        DOMAIN,
        "get_kvs",
        {"device_id": [device.id, "fake_device_id"], "key": "my_key"},
        blocking=True,
        return_response=True,
    )
    
    # Verify the response uses first device
    assert response == {"value": "test_value"}
    mock_rpc_device.call_rpc.assert_called_once_with("KVS.Get", {"key": "my_key"})


async def test_service_get_kvs_no_device(hass: HomeAssistant) -> None:
    """Test get_kvs service with no device selected."""
    await init_integration(hass, 2)
    
    # Call the service without device_id
    with pytest.raises(ServiceValidationError, match="No device selected"):
        await hass.services.async_call(
            DOMAIN,
            "get_kvs",
            {"key": "my_key"},
            blocking=True,
            return_response=True,
        )


async def test_service_get_kvs_invalid_device(hass: HomeAssistant) -> None:
    """Test get_kvs service with invalid device ID."""
    await init_integration(hass, 2)
    
    # Call the service with invalid device_id
    with pytest.raises(ServiceValidationError, match="Device not found"):
        await hass.services.async_call(
            DOMAIN,
            "get_kvs",
            {"device_id": "invalid_device_id", "key": "my_key"},
            blocking=True,
            return_response=True,
        )


async def test_service_get_kvs_block_device(
    hass: HomeAssistant, mock_block_device: Mock, device_registry: dr.DeviceRegistry
) -> None:
    """Test get_kvs service with non-RPC (Gen1) device."""
    await init_integration(hass, 1)
    
    # Get the device
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_NETWORK_MAC, "123456789ABC")}
    )
    assert device
    
    # Call the service with Gen1 device
    with pytest.raises(ServiceValidationError, match="not an RPC"):
        await hass.services.async_call(
            DOMAIN,
            "get_kvs",
            {"device_id": device.id, "key": "my_key"},
            blocking=True,
            return_response=True,
        )


async def test_service_get_kvs_rpc_call_error(
    hass: HomeAssistant, mock_rpc_device: Mock, device_registry: dr.DeviceRegistry
) -> None:
    """Test get_kvs service with RPC call error."""
    await init_integration(hass, 2)
    
    # Get the device
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_NETWORK_MAC, "123456789ABC")}
    )
    assert device
    
    # Mock the RPC call to raise an error
    mock_rpc_device.call_rpc = AsyncMock(
        side_effect=RpcCallError("Key not found", -105, "KVS.Get")
    )
    
    # Call the service
    with pytest.raises(HomeAssistantError, match="RPC call error"):
        await hass.services.async_call(
            DOMAIN,
            "get_kvs",
            {"device_id": device.id, "key": "nonexistent_key"},
            blocking=True,
            return_response=True,
        )


async def test_service_get_kvs_connection_error(
    hass: HomeAssistant, mock_rpc_device: Mock, device_registry: dr.DeviceRegistry
) -> None:
    """Test get_kvs service with device connection error."""
    await init_integration(hass, 2)
    
    # Get the device
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_NETWORK_MAC, "123456789ABC")}
    )
    assert device
    
    # Mock the RPC call to raise a connection error
    mock_rpc_device.call_rpc = AsyncMock(side_effect=DeviceConnectionError)
    
    # Call the service
    with pytest.raises(HomeAssistantError, match="connection error"):
        await hass.services.async_call(
            DOMAIN,
            "get_kvs",
            {"device_id": device.id, "key": "my_key"},
            blocking=True,
            return_response=True,
        )


async def test_service_get_kvs_different_key_values(
    hass: HomeAssistant, mock_rpc_device: Mock, device_registry: dr.DeviceRegistry
) -> None:
    """Test get_kvs service with different key values."""
    await init_integration(hass, 2)
    
    # Get the device
    device = device_registry.async_get_device(
        connections={(dr.CONNECTION_NETWORK_MAC, "123456789ABC")}
    )
    assert device
    
    test_cases = [
        ("key1", "value1"),
        ("key2", "value2"),
        ("some_long_key_name", "some_long_value"),
        ("numeric_key", "12345"),
    ]
    
    for key, value in test_cases:
        # Mock the RPC call
        mock_rpc_device.call_rpc = AsyncMock(return_value={"value": value})
        
        # Call the service
        response = await hass.services.async_call(
            DOMAIN,
            "get_kvs",
            {"device_id": device.id, "key": key},
            blocking=True,
            return_response=True,
        )
        
        # Verify the response
        assert response == {"value": value}
        
        # Verify the RPC call was made with correct parameters
        mock_rpc_device.call_rpc.assert_called_with("KVS.Get", {"key": key})
