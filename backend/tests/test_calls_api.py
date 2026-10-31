"""The call log as the dashboard reads it: filters, pagination, stats and who may see what."""

from datetime import UTC, datetime
from typing import Any

import pytest
from httpx import AsyncClient

from tests.booking_helpers import salon
from tests.helpers import World, build_world
from tests.retell_helpers import call_object, webhook

pytestmark = pytest.mark.usefixtures("retell_key")

DOWNTOWN_LINE = "+922100000001"
UPTOWN_LINE = "+922100000002"


def ms(day: str, hour: int, minute: int = 0) -> int:
    """UTC instant on `day` (YYYY-MM-DD) as unix milliseconds."""
    moment = datetime.fromisoformat(f"{day}T{hour:02d}:{minute:02d}:00").replace(tzinfo=UTC)
    return int(moment.timestamp() * 1000)


async def log_call(
    client: AsyncClient,
    call_id: str,
    started: int,
    *,
    to: str,
    outcome: str = "info_only",
    spoke: bool = True,
) -> None:
    reason = "error_dial_failed" if outcome == "failed" else "user_hangup"
    turns = [{"role": "agent", "content": "Hello"}]
    if spoke and outcome != "abandoned":
        turns.append({"role": "user", "content": "Hi"})
    call = call_object(
        call_id,
        to=to,
        start_timestamp=started,
        end_timestamp=started + 60_000,
        disconnection_reason=reason,
        transcript_object=turns,
    )
    assert (await webhook(client, "call_ended", call)).status_code == 200


async def two_locations(client: AsyncClient) -> World:
    w = await build_world(client)
    for number, location in ((DOWNTOWN_LINE, w.downtown), (UPTOWN_LINE, w.uptown)):
        await client.patch(
            f"/locations/{location['id']}", json={"phone": number}, headers=w.owner_a.headers
        )
    return w


async def ids(client: AsyncClient, who: Any, **params: Any) -> list[str]:
    response = await client.get("/calls", params=params, headers=who.headers)
    assert response.status_code == 200, response.text
    return [c["retell_call_id"] for c in response.json()["items"]]


async def test_calls_are_listed_newest_first_and_filterable(client: AsyncClient) -> None:
    w = await two_locations(client)
    await log_call(client, "c1", ms("2030-01-07", 5), to=DOWNTOWN_LINE)
    await log_call(client, "c2", ms("2030-01-07", 6), to=DOWNTOWN_LINE, outcome="failed")
    await log_call(client, "c3", ms("2030-01-08", 6), to=UPTOWN_LINE, outcome="abandoned")

    assert await ids(client, w.owner_a) == ["c3", "c2", "c1"]
    assert await ids(client, w.owner_a, outcome="failed") == ["c2"]
    assert await ids(client, w.owner_a, location_id=w.uptown["id"]) == ["c3"]
    assert await ids(client, w.owner_a, location_id=w.downtown["id"], outcome="abandoned") == []
    assert await ids(client, w.owner_a, **{"from": "2030-01-08"}) == ["c3"]
    assert await ids(client, w.owner_a, to="2030-01-07") == ["c2", "c1"]
    assert await ids(client, w.owner_a, **{"from": "2030-01-07", "to": "2030-01-07"}) == [
        "c2",
        "c1",
    ]


async def test_dates_are_the_salons_local_days(client: AsyncClient) -> None:
    """19:30 UTC on the 7th is 00:30 on the 8th in Karachi."""
    w = await two_locations(client)
    await log_call(client, "late", ms("2030-01-07", 19, 30), to=DOWNTOWN_LINE)
    assert await ids(client, w.owner_a, **{"from": "2030-01-08", "to": "2030-01-08"}) == ["late"]
    assert await ids(client, w.owner_a, **{"from": "2030-01-07", "to": "2030-01-07"}) == []


async def test_pagination_visits_every_call_once(client: AsyncClient) -> None:
    w = await two_locations(client)
    for i in range(5):
        await log_call(client, f"c{i}", ms("2030-01-07", 1 + i), to=DOWNTOWN_LINE)
    seen: list[str] = []
    cursor = None
    while True:
        params: dict[str, Any] = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        page = (await client.get("/calls", params=params, headers=w.owner_a.headers)).json()
        seen += [c["retell_call_id"] for c in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == ["c4", "c3", "c2", "c1", "c0"]


@pytest.mark.parametrize(
    "params",
    [
        {"cursor": "junk"},
        {"limit": 0},
        {"limit": 201},
        {"outcome": "weird"},
        {"from": "tomorrow"},
        {"from": "2030-01-09", "to": "2030-01-08"},
    ],
)
async def test_bad_parameters_are_validation_errors(
    client: AsyncClient, params: dict[str, Any]
) -> None:
    owner = await salon(client)
    response = await client.get("/calls", params=params, headers=owner.owner.headers)
    assert response.status_code == 422


async def test_one_call_has_its_transcript(client: AsyncClient) -> None:
    w = await two_locations(client)
    await log_call(client, "c1", ms("2030-01-07", 5), to=DOWNTOWN_LINE)
    [listed] = (await client.get("/calls", headers=w.owner_a.headers)).json()["items"]
    one = (await client.get(f"/calls/{listed['id']}", headers=w.owner_a.headers)).json()
    assert one["transcript"] == [
        {"role": "agent", "text": "Hello"},
        {"role": "user", "text": "Hi"},
    ]
    assert one["retell_call_id"] == "c1" and one["duration_seconds"] == 60
    assert (
        await client.get("/calls/00000000-0000-0000-0000-000000000000", headers=w.owner_a.headers)
    ).status_code == 404


async def test_stats_count_outcomes_and_local_days(client: AsyncClient) -> None:
    w = await two_locations(client)
    await log_call(client, "c1", ms("2030-01-07", 5), to=DOWNTOWN_LINE)
    await log_call(client, "c2", ms("2030-01-07", 6), to=DOWNTOWN_LINE, outcome="failed")
    await log_call(client, "c3", ms("2030-01-07", 19, 30), to=UPTOWN_LINE, outcome="abandoned")
    stats = (await client.get("/calls/stats", headers=w.owner_a.headers)).json()
    assert stats["total"] == 3
    assert stats["by_outcome"] == {
        "booked": 0,
        "rescheduled": 0,
        "cancelled": 0,
        "info_only": 1,
        "failed": 1,
        "abandoned": 1,
    }
    assert stats["per_day"] == [
        {"date": "2030-01-07", "count": 2},
        {"date": "2030-01-08", "count": 1},  # 19:30 UTC is already the 8th in Karachi
    ]
    only_up = (
        await client.get(
            "/calls/stats", params={"location_id": w.uptown["id"]}, headers=w.owner_a.headers
        )
    ).json()
    assert only_up["total"] == 1
    empty = await client.get("/calls/stats", params={"to": "2029-12-31"}, headers=w.owner_a.headers)
    assert empty.json()["total"] == 0 and empty.json()["per_day"] == []


async def test_managers_see_only_their_location_and_staff_see_nothing(client: AsyncClient) -> None:
    w = await two_locations(client)
    await log_call(client, "down", ms("2030-01-07", 5), to=DOWNTOWN_LINE)
    await log_call(client, "up", ms("2030-01-07", 6), to=UPTOWN_LINE)
    assert await ids(client, w.manager_a) == ["down"]
    assert await ids(client, w.manager_a_uptown) == ["up"]
    assert (await client.get("/calls/stats", headers=w.manager_a.headers)).json()["total"] == 1
    assert await ids(client, w.manager_a, location_id=w.uptown["id"]) == []

    up_call = (await client.get("/calls", headers=w.manager_a_uptown.headers)).json()["items"][0]
    assert (
        await client.get(f"/calls/{up_call['id']}", headers=w.manager_a.headers)
    ).status_code == 404
    for path in ("/calls", "/calls/stats", f"/calls/{up_call['id']}"):
        assert (await client.get(path, headers=w.staff_a.headers)).status_code == 403
        assert (await client.get(path)).status_code == 401


async def test_another_business_sees_none_of_it(client: AsyncClient) -> None:
    w = await two_locations(client)
    await log_call(client, "mine", ms("2030-01-07", 5), to=DOWNTOWN_LINE)
    [log] = (await client.get("/calls", headers=w.owner_a.headers)).json()["items"]
    assert await ids(client, w.owner_b) == []
    assert (await client.get("/calls/stats", headers=w.owner_b.headers)).json()["total"] == 0
    assert (await client.get(f"/calls/{log['id']}", headers=w.owner_b.headers)).status_code == 404
