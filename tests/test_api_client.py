"""Tests for the typed asynchronous GroupAlarm client."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from unittest.mock import AsyncMock, patch

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
from custom_components.groupalarm_ha_connect.api.client import (
    _non_negative_int,
    _parse_retry_after,
    _positive_int,
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


def test_scalar_validators_and_retry_after_edge_cases() -> None:
    """Wire scalars reject bools and Retry-After accepts both standard forms."""
    for value in (True, 0, -1, "1"):
        with pytest.raises(GroupAlarmResponseError, match="field"):
            _positive_int(value, "id")
    for value in (True, -1, "0"):
        with pytest.raises(GroupAlarmResponseError, match="field"):
            _non_negative_int(value, "count")

    assert _parse_retry_after(None) is None
    assert _parse_retry_after("invalid") is None
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT") == 0
    assert _parse_retry_after("Wed, 21 Oct 2015 07:28:00 -0000") == 0


async def test_empty_token_is_rejected(
    hass: HomeAssistant,
) -> None:
    """A client can never be constructed without authentication material."""
    with pytest.raises(ValueError, match="token"):
        GroupAlarmClient(async_get_clientsession(hass), "")


async def test_invalid_json_body_is_sanitized(
    client: GroupAlarmClient,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Malformed JSON never escapes parser or response-body details."""
    aioclient_mock.get(
        f"{BASE_URL}/user/",
        text="{secret invalid json",
        headers=JSON_HEADERS,
    )

    with pytest.raises(GroupAlarmResponseError, match="invalid JSON") as caught:
        await client.async_get_current_user()
    assert "secret" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [None],
        [{"id": 7, "name": "   "}],
    ],
)
async def test_organization_payload_boundaries(
    client: GroupAlarmClient,
    payload: object,
) -> None:
    """Organization responses require a list of valid reduced objects."""
    with patch.object(
        client,
        "_async_request",
        new=AsyncMock(return_value=payload),
    ):
        if payload == [{"id": 7, "name": "   "}]:
            assert (await client.async_get_organizations())[0].name == "7"
        else:
            with pytest.raises(GroupAlarmResponseError):
                await client.async_get_organizations()


@pytest.mark.parametrize(
    "payload",
    [
        {},
        [{"id": 91, "ownerID": 42, "active": True}],
        [{"id": 91, "ownerID": 41, "active": "yes"}],
        [
            {
                "id": 91,
                "ownerID": 41,
                "active": True,
                "isMainDevice": "yes",
            }
        ],
    ],
)
async def test_device_payload_boundaries(
    client: GroupAlarmClient,
    payload: object,
) -> None:
    """Device ownership and booleans are validated before reduction."""
    with (
        patch.object(
            client,
            "_async_request",
            new=AsyncMock(return_value=payload),
        ),
        pytest.raises(GroupAlarmResponseError),
    ):
        await client.async_get_app_devices(41)


async def test_device_input_and_fallback_name(
    client: GroupAlarmClient,
) -> None:
    """Device requests require a valid owner and tolerate an empty label."""
    with pytest.raises(ValueError, match="owner_id"):
        await client.async_get_app_devices(0)

    payload = [
        {
            "id": 91,
            "ownerID": 41,
            "active": False,
            "name": "",
        }
    ]
    with patch.object(
        client,
        "_async_request",
        new=AsyncMock(return_value=payload),
    ):
        device = (await client.async_get_app_devices(41))[0]
    assert device.name == "91"
    assert device.is_main_device is False


@pytest.mark.parametrize("response_timeout", [9, 86_401])
async def test_organization_timeout_input_and_wire_range(
    client: GroupAlarmClient,
    response_timeout: int,
) -> None:
    """Organization timeouts honor the documented 10..86400 range."""
    with pytest.raises(ValueError, match="organization_id"):
        await client.async_get_organization_timeout(0)

    with (
        patch.object(
            client,
            "_async_request",
            new=AsyncMock(return_value={"timeout": response_timeout}),
        ),
        pytest.raises(GroupAlarmResponseError, match="timeout"),
    ):
        await client.async_get_organization_timeout(7)


@pytest.mark.parametrize(
    ("organization_id", "limit", "offset", "message"),
    [
        (0, 10, 0, "organization_id"),
        (7, 0, 0, "limit"),
        (7, 51, 0, "limit"),
        (7, 10, -1, "offset"),
    ],
)
async def test_alarm_list_input_validation(
    client: GroupAlarmClient,
    organization_id: int,
    limit: int,
    offset: int,
    message: str,
) -> None:
    """Invalid pagination is rejected before any network request."""
    with pytest.raises(ValueError, match=message):
        await client.async_get_alarms(
            organization_id,
            limit=limit,
            offset=offset,
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"alarms": {}, "totalAlarms": 0},
        {
            "alarms": [{"id": 11, "organizationID": 12}],
            "totalAlarms": 1,
        },
        {
            "alarms": [{"id": 11, "organizationID": 7}],
            "totalAlarms": 0,
        },
    ],
)
async def test_alarm_list_response_validation(
    client: GroupAlarmClient,
    payload: object,
) -> None:
    """A page cannot cross organization boundaries or undercount its items."""
    with (
        patch.object(
            client,
            "_async_request",
            new=AsyncMock(return_value=payload),
        ),
        pytest.raises(GroupAlarmResponseError),
    ):
        await client.async_get_alarms(7)


async def test_alarm_without_organization_id_is_accepted(
    client: GroupAlarmClient,
) -> None:
    """The optional list organization field need not be synthesized."""
    payload = {"alarms": [{"id": 11}], "totalAlarms": 1}
    with patch.object(
        client,
        "_async_request",
        new=AsyncMock(return_value=payload),
    ):
        assert (await client.async_get_alarms(7)).alarms == ({"id": 11},)


async def test_alarm_detail_input_and_identity_validation(
    client: GroupAlarmClient,
) -> None:
    """A detail response must belong to the requested alarm."""
    with pytest.raises(ValueError, match="alarm_id"):
        await client.async_get_alarm(0)

    with (
        patch.object(
            client,
            "_async_request",
            new=AsyncMock(return_value={"id": 12}),
        ),
        pytest.raises(GroupAlarmResponseError, match="identity"),
    ):
        await client.async_get_alarm(11)


async def test_feedback_input_validation(
    client: GroupAlarmClient,
) -> None:
    """Feedback calls reject unsafe identifiers and arrival durations."""
    with pytest.raises(ValueError, match="identifiers"):
        await client.async_send_feedback(
            alarm_id=0,
            organization_id=7,
            user_id=41,
            response=True,
        )
    with pytest.raises(ValueError, match="identifiers"):
        await client.async_send_feedback_with_duration(
            alarm_id=11,
            device_id=0,
            duration=12,
        )
    for duration in (0, 181):
        with pytest.raises(ValueError, match="duration"):
            await client.async_send_feedback_with_duration(
                alarm_id=11,
                device_id=91,
                duration=duration,
            )
