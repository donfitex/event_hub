from datetime import timedelta
from io import StringIO

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.core.management import call_command
from django.utils import timezone

from tests.factories import EventFactory, RegistrationFactory

pytestmark = pytest.mark.django_db


def run(**options):
    out = StringIO()
    call_command("send_event_reminders", stdout=out, **options)
    return out.getvalue()


def soon_event(hours=5, **extra):
    return EventFactory(start_datetime=timezone.now() + timedelta(hours=hours), **extra)


def test_reminds_registered_attendees_only():
    event = soon_event()
    attendees = [RegistrationFactory(event=event) for _ in range(2)]
    RegistrationFactory(event=event, waitlisted=True)
    RegistrationFactory(event=event, cancelled=True)

    output = run()

    assert "Reminders sent: 2, failed: 0" in output
    assert sorted(m.to[0] for m in mail.outbox) == sorted(a.user.email for a in attendees)
    assert all(m.subject.startswith("Reminder:") for m in mail.outbox)
    for attendee in attendees:
        attendee.refresh_from_db()
        assert attendee.reminder_sent_at is not None


def test_running_twice_never_sends_a_second_reminder():
    RegistrationFactory(event=soon_event())
    run()
    assert "Reminders sent: 0" in run()
    assert len(mail.outbox) == 1


def test_events_outside_the_window_are_skipped_until_it_is_widened():
    RegistrationFactory(event=soon_event(hours=72))
    assert "Reminders sent: 0" in run()
    assert "Reminders sent: 1" in run(hours=96)


@pytest.mark.parametrize("trait", ["cancelled", "draft"])
def test_events_that_are_not_published_get_no_reminders(trait):
    RegistrationFactory(event=soon_event(**{trait: True}))
    assert "Reminders sent: 0" in run()


def test_events_that_already_started_get_no_reminders():
    now = timezone.now()
    event = EventFactory(
        start_datetime=now - timedelta(hours=1),
        end_datetime=now + timedelta(hours=3),
        registration_deadline=now - timedelta(days=1),
    )
    RegistrationFactory(event=event)
    assert "Reminders sent: 0" in run()


def test_a_failed_send_is_retried_on_the_next_run(monkeypatch):
    registration = RegistrationFactory(event=soon_event())

    def boom(self, *args, **kwargs):
        raise RuntimeError("SMTP is down")

    monkeypatch.setattr(EmailMultiAlternatives, "send", boom)
    assert "Reminders sent: 0, failed: 1" in run()
    registration.refresh_from_db()
    assert registration.reminder_sent_at is None  # released, so a later run can retry

    monkeypatch.undo()
    assert "Reminders sent: 1" in run()