"""Tests for the typed asynchronous GroupAlarm client."""

from __future__ import annotations

import asyncio
from http import HTTPStatus

import pytest
from aiohttp import ClientConnectionError
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
)

from custom_components.groupalarm_ha_connect.api import (
    GroupAlarmAuthenticationError,
    GroupAlarmClient,
    GroupAlarmPermissionError,
    GroupAlarmRateLimitError,
    GroupAlarmRequestError,
    GroupAlarmResponseError,
    GroupAlarmServerError,
    GroupAlarmTimeoutError,
    GroupAlarmTransportError,
)

BASE_URL = "https://example.test/api/v1"
JSON_HEADERS = {"Content-Type": "application/json"}


@pytest.fixture
def client(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> GroupAlarmClient:
    """Create a client using HA's shared mocked session."""
    return GroupAlarmClient(
        async_get_clientsession(hass),
        token="pat-test-secret",
        base_url=BASE_URL,
        request_timeout=0.1,
    )


async def test_current_user_path_header_and_reduction(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/user/",
        json={
            "id": 41,
            "name": "Sensitive Name",
            "email": "person@example.org",
            "token": "server-secret",
        },
        headers=JSON_HEADERS,
    )

    user = await client.async_get_current_user()

    assert user.id == 41
    method, url, _data, headers = aioclient_mock.mock_calls[0]
    assert method == "GET"
    assert str(url) == f"{BASE_URL}/user/"
    assert headers["Personal-Access-Token"] == "pat-test-secret"
    assert headers["Accept"] == "application/json"
    assert not hasattr(user, "name")
    assert not hasattr(user, "email")
    assert not hasattr(user, "token")


async def test_organizations_use_documented_path_and_shape(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/organizations",
        json=[
            {"id": 12, "name": "Zulu"},
            {"id": 7, "name": "Alpha"},
        ],
        headers=JSON_HEADERS,
    )

    organizations = await client.async_get_organizations()

    assert [(item.id, item.name) for item in organizations] == [
        (7, "Alpha"),
        (12, "Zulu"),
    ]
    assert str(aioclient_mock.mock_calls[0][1]) == f"{BASE_URL}/organizations"


async def test_devices_are_reduced_before_return(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/app/device?owner_id=41",
        json=[
            {
                "id": 91,
                "ownerID": 41,
                "name": "Phone",
                "active": True,
                "isMainDevice": True,
                "pushToken": "must-never-leave-client",
                "os": "secret-ish metadata",
            }
        ],
        headers=JSON_HEADERS,
    )

    devices = await client.async_get_app_devices(41)

    assert len(devices) == 1
    assert devices[0].id == 91
    assert devices[0].owner_id == 41
    assert devices[0].active is True
    assert devices[0].is_main_device is True
    assert not hasattr(devices[0], "push_token")
    assert "must-never-leave-client" not in repr(devices)


async def test_organization_timeout_validation(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/messaging/timeout/7",
        json={"timeout": 120},
        headers=JSON_HEADERS,
    )

    assert await client.async_get_organization_timeout(7) == 120


async def test_alarm_list_keeps_order_uninterpreted(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/alarms?organization=7&limit=2&offset=0",
        json={
            "alarms": [
                {"id": 50, "organizationID": 7},
                {"id": 49, "organizationID": 7},
            ],
            "totalAlarms": 8,
        },
        headers=JSON_HEADERS,
    )

    page = await client.async_get_alarms(7, limit=2)

    assert [alarm["id"] for alarm in page.alarms] == [50, 49]
    assert page.total_alarms == 8


async def test_alarm_detail_requests_user_specific_data(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/alarm/50?update_for_user=true",
        json={"id": 50, "organizationID": 7},
        headers=JSON_HEADERS,
    )

    alarm = await client.async_get_alarm(50)

    assert alarm["id"] == 50


async def test_feedback_request_bodies(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.post(f"{BASE_URL}/messaging/feedback")
    await client.async_send_feedback(
        alarm_id=50,
        organization_id=7,
        user_id=41,
        response=False,
    )

    aioclient_mock.post(f"{BASE_URL}/app/feedback")
    await client.async_send_feedback_with_duration(
        alarm_id=50,
        device_id=91,
        duration=12,
    )

    assert aioclient_mock.mock_calls[0][2] == {
        "alarmID": 50,
        "organizationID": 7,
        "response": False,
        "userID": 41,
    }
    assert aioclient_mock.mock_calls[1][2] == {
        "alarmID": 50,
        "deviceID": 91,
        "response": True,
        "answerData": {"duration": 12},
    }


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (HTTPStatus.UNAUTHORIZED, GroupAlarmAuthenticationError),
        (HTTPStatus.FORBIDDEN, GroupAlarmPermissionError),
        (HTTPStatus.NOT_FOUND, GroupAlarmRequestError),
        (HTTPStatus.UNPROCESSABLE_ENTITY, GroupAlarmRequestError),
        (HTTPStatus.INTERNAL_SERVER_ERROR, GroupAlarmServerError),
    ],
)
async def test_status_codes_map_to_safe_exceptions(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
    status: HTTPStatus,
    expected: type[Exception],
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/user/",
        status=status,
        text="sensitive response body with pat-test-secret",
    )

    with pytest.raises(expected) as caught:
        await client.async_get_current_user()

    assert "sensitive response body" not in str(caught.value)
    assert "pat-test-secret" not in str(caught.value)


async def test_rate_limit_exposes_only_retry_after(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/user/",
        status=HTTPStatus.TOO_MANY_REQUESTS,
        headers={"Retry-After": "17"},
    )

    with pytest.raises(GroupAlarmRateLimitError) as caught:
        await client.async_get_current_user()

    assert caught.value.retry_after == 17
    assert caught.value.status == 429


@pytest.mark.parametrize(
    ("exception", "expected"),
    [
        (TimeoutError(), GroupAlarmTimeoutError),
        (ClientConnectionError("secret transport detail"), GroupAlarmTransportError),
    ],
)
async def test_transport_failures_are_sanitized(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
    exception: BaseException,
    expected: type[Exception],
) -> None:
    aioclient_mock.get(f"{BASE_URL}/user/", exc=exception)

    with pytest.raises(expected) as caught:
        await client.async_get_current_user()

    assert "secret transport detail" not in str(caught.value)


@pytest.mark.parametrize(
    ("payload", "headers"),
    [
        ([], JSON_HEADERS),
        ({"id": 0}, JSON_HEADERS),
        ({"id": 41}, {"Content-Type": "text/plain"}),
    ],
)
async def test_unexpected_user_payload_is_rejected(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
    payload: object,
    headers: dict[str, str],
) -> None:
    aioclient_mock.get(
        f"{BASE_URL}/user/",
        json=payload,
        headers=headers,
    )

    with pytest.raises(GroupAlarmResponseError):
        await client.async_get_current_user()


async def test_real_asyncio_timeout_is_translated(
    hass: HomeAssistant,
) -> None:
    class SlowSession:
        def request(self, *args: object, **kwargs: object) -> object:
            class SlowContext:
                async def __aenter__(self) -> object:
                    await asyncio.sleep(0.02)
                    return self

                async def __aexit__(self, *args: object) -> None:
                    return None

            return SlowContext()

    client = GroupAlarmClient(
        SlowSession(),  # type: ignore[arg-type]
        token="token",
        base_url=BASE_URL,
        request_timeout=0.001,
    )

    with pytest.raises(GroupAlarmTimeoutError):
        await client.async_get_current_user()
