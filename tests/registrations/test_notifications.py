import logging

import pytest
from django.core import mail
from django.core.mail import EmailMultiAlternatives

from apps.events.constants import EventStatus
from apps.events.services import change_event_status
from apps.registrations.models import Registration
from apps.registrations.services import cancel_registration, register_for_event
from tests.factories import EventFactory, RegistrationFactory, UserFactory
from tests.helpers import expect_error

pytestmark = pytest.mark.django_db


def subjects():
    return [m.subject for m in mail.outbox]


def recipients():
    return {address for m in mail.outbox for address in m.to}


class TestRegistrationEmails:
    def test_confirmation_email(self, django_capture_on_commit_callbacks):
        user, event = UserFactory(), EventFactory(title="Django Summit", venue="Eko Hotel")

        with django_capture_on_commit_callbacks(execute=True):
            register_for_event(user, event)

        assert len(mail.outbox) == 1
        message = mail.outbox[0]
        assert message.to == [user.email]
        assert message.subject == "You're registered: Django Summit"
        assert "Eko Hotel" in message.body
        assert f"http://testserver/events/{event.slug}/" in message.body
        assert message.alternatives  # an HTML version is attached too

    def test_waitlist_email_mentions_the_position(self, django_capture_on_commit_callbacks):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        user = UserFactory()

        with django_capture_on_commit_callbacks(execute=True):
            register_for_event(user, event)

        assert subjects() == [f"You're on the waitlist: {event.title}"]
        assert "position 1" in mail.outbox[0].body

    def test_special_characters_are_escaped_in_html_but_not_in_text(self, django_capture_on_commit_callbacks):
        event = EventFactory(title="Q&A <b>Night</b>")

        with django_capture_on_commit_callbacks(execute=True):
            register_for_event(UserFactory(), event)

        message = mail.outbox[0]
        html = message.alternatives[0][0]
        assert "Q&A <b>Night</b>" in message.body
        assert "Q&amp;A &lt;b&gt;Night&lt;/b&gt;" in html
        assert "<b>Night</b>" not in html

    def test_nothing_is_sent_until_the_transaction_commits(self):
        register_for_event(UserFactory(), EventFactory())
        assert mail.outbox == []

    def test_a_rejected_registration_sends_nothing(self, django_capture_on_commit_callbacks):
        event = EventFactory(closed=True)
        with django_capture_on_commit_callbacks(execute=True):
            with expect_error("REGISTRATION_CLOSED"):
                register_for_event(UserFactory(), event)
        assert mail.outbox == []


class TestCancellationEmails:
    def test_self_cancellation_email(self, django_capture_on_commit_callbacks):
        user = UserFactory()
        registration = RegistrationFactory(user=user)

        with django_capture_on_commit_callbacks(execute=True):
            cancel_registration(registration, user)

        assert len(mail.outbox) == 1
        assert mail.outbox[0].subject.startswith("Registration cancelled")
        assert "as requested" in mail.outbox[0].body

    def test_cancellation_by_the_organizer_says_so(self, django_capture_on_commit_callbacks):
        registration = RegistrationFactory()

        with django_capture_on_commit_callbacks(execute=True):
            cancel_registration(registration, registration.event.organizer)

        assert "by the organizer" in mail.outbox[0].body

    def test_a_freed_seat_emails_the_cancelled_user_and_the_promoted_one(self, django_capture_on_commit_callbacks):
        event = EventFactory(capacity=1)
        holder = RegistrationFactory(event=event)
        waiting = RegistrationFactory(event=event, waitlisted=True)

        with django_capture_on_commit_callbacks(execute=True):
            cancel_registration(holder, holder.user)

        assert recipients() == {holder.user.email, waiting.user.email}
        promoted_mail = next(m for m in mail.outbox if m.to == [waiting.user.email])
        assert promoted_mail.subject.startswith("You're in!")

    def test_leaving_the_waitlist_promotes_and_emails_nobody_else(self, django_capture_on_commit_callbacks):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        leaving = RegistrationFactory(event=event, waitlisted=True)
        RegistrationFactory(event=event, waitlisted=True)

        with django_capture_on_commit_callbacks(execute=True):
            cancel_registration(leaving, leaving.user)

        assert recipients() == {leaving.user.email}


class TestEventCancellationEmails:
    def test_every_active_registrant_is_emailed_once(self, django_capture_on_commit_callbacks):
        event = EventFactory(capacity=1)
        registered = RegistrationFactory(event=event)
        waitlisted = RegistrationFactory(event=event, waitlisted=True)
        RegistrationFactory(event=event, cancelled=True)  # already cancelled: no email

        with django_capture_on_commit_callbacks(execute=True):
            change_event_status(event, EventStatus.CANCELLED, event.organizer)

        assert sorted(m.to[0] for m in mail.outbox) == sorted(
            [registered.user.email, waitlisted.user.email]
        )
        assert all(m.subject == f"Event cancelled: {event.title}" for m in mail.outbox)


class TestEmailFailures:
    def test_a_broken_mail_server_never_breaks_the_registration(
        self, monkeypatch, caplog, django_capture_on_commit_callbacks
    ):
        def boom(self, *args, **kwargs):
            raise RuntimeError("SMTP is down")

        monkeypatch.setattr(EmailMultiAlternatives, "send", boom)
        user, event = UserFactory(), EventFactory()

        with caplog.at_level(logging.ERROR):
            with django_capture_on_commit_callbacks(execute=True):
                registration = register_for_event(user, event)

        assert Registration.objects.filter(pk=registration.pk).exists()
        assert "Failed to send email" in caplog.text