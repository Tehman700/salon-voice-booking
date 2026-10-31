"""Booking emails: queued with the change, sent once, retried, never for a failed change."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.db.session import get_sessionmaker
from app.models.notification import NotificationOutbox, OutboxStatus
from app.services import notifications
from app.services.notifications import MAX_ATTEMPTS, SesSender, deliver_due, run_sender
from tests.booking_helpers import MONDAY, TUESDAY, Salon, at, key, salon
from tests.retell_helpers import call_object, tool

SALON_INBOX = "frontdesk@glow.example.com"
CUSTOMER = "ayesha@example.com"
LATER = datetime(2031, 1, 1, tzinfo=UTC)  # after every test booking, so everything is due


class FakeSender:
    def __init__(self, fail_times: int = 0) -> None:
        self.sent: list[dict[str, str]] = []
        self.fail_times = fail_times

    async def send(self, *, to: str, subject: str, text: str, html: str) -> None:
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("SES is having a bad day")
        self.sent.append({"to": to, "subject": subject, "text": text, "html": html})


async def outbox(db: AsyncSession) -> list[NotificationOutbox]:
    db.expire_all()
    rows = await db.scalars(select(NotificationOutbox).order_by(NotificationOutbox.created_at))
    return list(rows)


def by_kind(rows: list[NotificationOutbox]) -> dict[str, NotificationOutbox]:
    return {r.kind: r for r in rows if r.status == OutboxStatus.pending}


async def with_alerts(client: AsyncClient) -> Salon:
    s = await salon(client)
    response = await client.patch(
        "/business", json={"notification_email": SALON_INBOX}, headers=s.owner.headers
    )
    assert response.status_code == 200 and response.json()["notification_email"] == SALON_INBOX
    return s


async def create(
    client: AsyncClient, s: Salon, start: str, *, email: str | None = CUSTOMER, **customer: Any
) -> dict[str, Any]:
    response = await client.post(
        "/bookings",
        json={
            "location_id": s.location_id,
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "starts_at": start,
            "customer": {
                "full_name": "Ayesha Khan",
                "phone": "+923001234567",
                "email": email,
                **customer,
            },
        },
        headers={**s.owner.headers, "Idempotency-Key": key()},
    )
    assert response.status_code in (201, 409), response.text
    return dict(response.json())


async def deliver(sender: FakeSender, now: datetime = LATER) -> int:
    async with get_sessionmaker()() as session:
        return await deliver_due(session, sender, now=now)


# --- The salon's notification address ---


async def test_the_salon_can_set_and_clear_its_notification_address(client: AsyncClient) -> None:
    s = await with_alerts(client)
    assert (await client.get("/business", headers=s.owner.headers)).json()[
        "notification_email"
    ] == SALON_INBOX
    unchanged = await client.patch("/business", json={"name": "Glow"}, headers=s.owner.headers)
    assert unchanged.json()["notification_email"] == SALON_INBOX
    cleared = await client.patch(
        "/business", json={"notification_email": ""}, headers=s.owner.headers
    )
    assert cleared.json()["notification_email"] is None
    bad = await client.patch(
        "/business", json={"notification_email": "not-an-email"}, headers=s.owner.headers
    )
    assert bad.status_code == 422


# --- What gets queued ---


async def test_a_booking_queues_confirmation_reminder_and_salon_alert(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await with_alerts(client)
    booking = await create(client, s, at(MONDAY, 10))
    rows = by_kind(await outbox(db))
    assert set(rows) == {"booking_created", "booking_reminder", "booking_created_salon"}

    confirmation = rows["booking_created"]
    assert confirmation.to_email == CUSTOMER
    assert confirmation.subject == "Booking confirmed: Haircut on Monday 7 January 2030 at 10:00 AM"
    assert booking["reference"] in confirmation.body_text
    assert "Hi Ayesha," in confirmation.body_text and "Sana" in confirmation.body_text
    assert "call +923001234567" in confirmation.body_text  # the salon's own number
    assert confirmation.send_after <= datetime.now(UTC)

    reminder = rows["booking_reminder"]
    assert reminder.send_after == datetime.fromisoformat(at(MONDAY, 10)) - timedelta(hours=24)
    assert reminder.subject.startswith("Reminder: Haircut tomorrow")

    alert = rows["booking_created_salon"]
    assert alert.to_email == SALON_INBOX
    assert (
        "from the dashboard" in alert.body_text and "Ayesha Khan (+923001234567)" in alert.body_text
    )
    assert {r.appointment_id for r in rows.values()} == {__import__("uuid").UUID(booking["id"])}


async def test_nothing_is_queued_without_any_address(client: AsyncClient, db: AsyncSession) -> None:
    s = await salon(client)
    await create(client, s, at(MONDAY, 10), email=None)
    assert await outbox(db) == []


@pytest.mark.usefixtures("retell_key")
async def test_a_phone_booking_alerts_the_salon(client: AsyncClient, db: AsyncSession) -> None:
    s = await with_alerts(client)
    result = await tool(
        client,
        "create_booking",
        {
            "service_id": s.service["id"],
            "staff_id": s.staff["id"],
            "date": MONDAY,
            "time": "10:00",
            "customer_name": "Bilal Ahmed",
        },
        call=call_object(),
    )
    assert result["success"] is True
    [alert] = await outbox(db)  # no customer email from a phone call
    assert alert.kind == "booking_created_salon"
    assert "by phone (voice agent)" in alert.body_text and result["reference"] in alert.body_text


async def test_a_refused_booking_queues_nothing(client: AsyncClient, db: AsyncSession) -> None:
    s = await with_alerts(client)
    await create(client, s, at(MONDAY, 10))
    before = len(await outbox(db))
    taken = await create(
        client, s, at(MONDAY, 10), email="other@example.com", phone="+923009999999"
    )
    assert taken["error"]["code"] == "slot_unavailable"
    assert len(await outbox(db)) == before


async def test_moving_a_booking_replaces_its_reminder(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await with_alerts(client)
    booking = await create(client, s, at(MONDAY, 10))
    moved = await client.patch(
        f"/bookings/{booking['id']}", json={"starts_at": at(TUESDAY, 14)}, headers=s.owner.headers
    )
    assert moved.status_code == 200
    rows = await outbox(db)
    reminders = [r for r in rows if r.kind == "booking_reminder"]
    assert [r.status for r in reminders] == [OutboxStatus.skipped, OutboxStatus.pending]
    assert reminders[1].send_after == datetime.fromisoformat(at(TUESDAY, 14)) - timedelta(hours=24)
    pending = by_kind(rows)
    assert pending["booking_rescheduled"].subject.startswith(
        "Booking moved: Haircut is now on Tuesday"
    )
    assert "booking_rescheduled_salon" in pending
    # Editing notes alone sends nothing.
    count = len(rows)
    await client.patch(f"/bookings/{booking['id']}", json={"notes": "x"}, headers=s.owner.headers)
    assert len(await outbox(db)) == count


async def test_cancelling_drops_the_reminder_and_says_so(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await with_alerts(client)
    booking = await create(client, s, at(MONDAY, 10))
    await client.delete(f"/bookings/{booking['id']}", headers=s.owner.headers)
    rows = await outbox(db)
    assert [r.status for r in rows if r.kind == "booking_reminder"] == [OutboxStatus.skipped]
    pending = by_kind(rows)
    assert {"booking_cancelled", "booking_cancelled_salon"} <= set(pending)
    assert "booking_reminder" not in pending


async def test_reminders_are_sensible_for_bookings_made_at_short_notice(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    now = datetime(2030, 1, 7, 3, 30, tzinfo=UTC)  # 08:30 in Karachi on the Monday
    async with get_sessionmaker()() as session:
        from app.models.booking import Appointment

        await create(client, s, at(MONDAY, 10))
        appointment = (await session.scalars(select(Appointment))).one()
        for row in list(await session.scalars(select(NotificationOutbox))):
            await session.delete(row)
        await session.flush()
        # 1.5 hours ahead: too late for a reminder.
        await notifications.on_booking(
            session, appointment, notifications.BookingChange.created, now=now
        )
        await session.flush()
        kinds = [r.kind for r in await session.scalars(select(NotificationOutbox))]
        assert kinds == ["booking_created"]
        # 6 hours ahead: inside the 24 hours, so the reminder goes out right away.
        for row in list(await session.scalars(select(NotificationOutbox))):
            await session.delete(row)
        earlier = now - timedelta(hours=4, minutes=30)
        await notifications.on_booking(
            session, appointment, notifications.BookingChange.created, now=earlier
        )
        await session.flush()
        rows = {r.kind: r for r in await session.scalars(select(NotificationOutbox))}
        assert rows["booking_reminder"].send_after == earlier
        await session.rollback()


async def test_names_cannot_inject_html(client: AsyncClient, db: AsyncSession) -> None:
    s = await salon(client)
    await create(client, s, at(MONDAY, 10), full_name="<script>alert(1)</script> Khan")
    row = by_kind(await outbox(db))["booking_created"]
    assert "<script>" not in row.body_html and "&lt;script&gt;" in row.body_html


# --- Delivery ---


async def test_due_emails_are_sent_once_and_future_ones_wait(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await with_alerts(client)
    await create(client, s, at(MONDAY, 10))
    sender = FakeSender()
    now = datetime.now(UTC)
    assert await deliver(sender, now) == 2  # confirmation + salon alert; the reminder is in 2030
    assert sorted(m["to"] for m in sender.sent) == [CUSTOMER, SALON_INBOX]
    assert await deliver(sender, now) == 0  # nothing twice
    assert await deliver(sender, LATER) == 1  # the reminder, once its time comes
    rows = await outbox(db)
    assert all(r.status == OutboxStatus.sent and r.sent_at is not None for r in rows)
    assert all(r.attempts == 1 for r in rows)


async def test_a_failed_send_is_retried_with_backoff_then_given_up(
    client: AsyncClient, db: AsyncSession
) -> None:
    s = await salon(client)
    await create(client, s, at(MONDAY, 10))
    sender = FakeSender(fail_times=1)
    now = datetime.now(UTC)
    assert await deliver(sender, now) == 0
    row = by_kind(await outbox(db))["booking_created"]
    assert row.attempts == 1 and "bad day" in (row.last_error or "")
    assert row.send_after == now + timedelta(minutes=1)
    assert await deliver(sender, now) == 0  # not yet: backing off
    assert await deliver(sender, now + timedelta(minutes=1)) == 1
    assert "booking_created" not in by_kind(await outbox(db))  # sent now

    always = FakeSender(fail_times=99)
    await create(client, s, at(TUESDAY, 10), email="b@example.com", phone="+923001112222")
    moment = now
    for _ in range(MAX_ATTEMPTS):
        moment += timedelta(hours=1)
        await deliver(always, moment)
    gave_up = [
        r for r in await outbox(db) if r.to_email == "b@example.com" and r.kind == "booking_created"
    ]
    assert gave_up[0].status == OutboxStatus.failed and gave_up[0].attempts == MAX_ATTEMPTS


async def test_two_senders_never_send_the_same_email(client: AsyncClient) -> None:
    s = await with_alerts(client)
    for hour in (10, 12, 14):
        await create(
            client, s, at(MONDAY, hour), email=f"c{hour}@example.com", phone=f"+9230012300{hour}"
        )
    sender = FakeSender()
    await asyncio.gather(*(deliver(sender) for _ in range(4)))
    subjects = [(m["to"], m["subject"]) for m in sender.sent]
    assert len(subjects) == len(set(subjects)) == 9  # 3 bookings x (confirmation, reminder, alert)


async def test_the_background_sender_runs_until_stopped(client: AsyncClient) -> None:
    s = await salon(client)
    await create(client, s, at(MONDAY, 10))
    sender = FakeSender()
    stop = asyncio.Event()
    task = asyncio.create_task(run_sender(get_sessionmaker(), sender, stop, interval=0.05))
    for _ in range(100):
        if sender.sent:
            break
        await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert [m["to"] for m in sender.sent] == [CUSTOMER]


async def test_a_crashing_pass_does_not_stop_the_sender() -> None:
    calls = 0

    def broken_sessionmaker() -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("database is down")

    stop = asyncio.Event()
    task = asyncio.create_task(run_sender(broken_sessionmaker, FakeSender(), stop, interval=0.01))
    await asyncio.sleep(0.1)
    stop.set()
    await asyncio.wait_for(task, timeout=5)
    assert calls >= 2


# --- SES and configuration ---


def test_ses_request_has_the_right_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test")
    sender = SesSender("Glow <hello@example.com>", "ap-south-1")
    captured: dict[str, Any] = {}

    class FakeClient:
        def send_email(self, **kwargs: Any) -> None:
            captured.update(kwargs)

    sender.client = FakeClient()
    asyncio.run(sender.send(to="a@example.com", subject="Hi", text="Hello", html="<p>Hello</p>"))
    assert captured["FromEmailAddress"] == "Glow <hello@example.com>"
    assert captured["Destination"] == {"ToAddresses": ["a@example.com"]}
    body = captured["Content"]["Simple"]
    assert body["Subject"]["Data"] == "Hi" and body["Body"]["Html"]["Data"] == "<p>Hello</p>"


def test_no_sender_is_configured_without_an_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMAIL_FROM", "  ")
    assert Settings().email_from is None
    assert notifications.configured_sender() is None
    monkeypatch.setenv("EMAIL_FROM", "hello@example.com")
    monkeypatch.setenv("EMAIL_FROM_NAME", "Glow Salon")
    assert Settings().email_from_header == "Glow Salon <hello@example.com>"
