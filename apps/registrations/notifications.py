import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.template.loader import render_to_string
from django.urls import reverse

logger = logging.getLogger(__name__)


def _url(name, *args):
    return f"{settings.SITE_URL}{reverse(name, args=args)}"


def _build(user, event, subject, heading, paragraphs, cta_label, cta_url):
    context = {
        "name": user.first_name or "there",
        "event": event,
        "heading": heading,
        "paragraphs": paragraphs,
        "cta_label": cta_label,
        "cta_url": cta_url,
    }
    message = EmailMultiAlternatives(
        subject=subject,
        body=render_to_string("emails/message.txt", context),
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(render_to_string("emails/message.html", context), "text/html")
    return message


def _deliver(messages):
    """Send over one connection. A failure is logged and never raised to the caller."""
    sent = 0
    try:
        with get_connection() as connection:
            for message in messages:
                try:
                    message.connection = connection
                    message.send()
                    sent += 1
                except Exception:
                    logger.exception("Failed to send email to %s", message.to)
    except Exception:
        logger.exception("Could not open the email connection")
    return sent


def send_registration_confirmed(registration):
    event = registration.event
    _deliver([_build(
        registration.user, event,
        subject=f"You're registered: {event.title}",
        heading="You're registered",
        paragraphs=[
            f"Your seat for {event.title} is confirmed.",
            "If your plans change, please cancel from your dashboard so someone on the "
            "waitlist can take your place.",
        ],
        cta_label="View event",
        cta_url=_url("web:event_detail", event.slug),
    )])


def send_waitlist_joined(registration, position):
    event = registration.event
    _deliver([_build(
        registration.user, event,
        subject=f"You're on the waitlist: {event.title}",
        heading="You're on the waitlist",
        paragraphs=[
            f"{event.title} is full right now, so you have been added to the waitlist "
            f"at position {position}.",
            "If a seat opens up you will be promoted automatically and we will email you.",
        ],
        cta_label="View event",
        cta_url=_url("web:event_detail", event.slug),
    )])


def send_registration_cancelled(registration, event, by_staff=False):
    who = "by the organizer" if by_staff else "as requested"
    _deliver([_build(
        registration.user, event,
        subject=f"Registration cancelled: {event.title}",
        heading="Registration cancelled",
        paragraphs=[f"Your registration for {event.title} has been cancelled {who}."],
        cta_label="Browse events",
        cta_url=_url("web:event_list"),
    )])


def send_event_cancelled(event, registrations):
    _deliver([
        _build(
            r.user, event,
            subject=f"Event cancelled: {event.title}",
            heading="This event has been cancelled",
            paragraphs=[
                f"We are sorry to tell you that {event.title} has been cancelled by the organizer.",
                "Your registration was cancelled automatically, so there is nothing more you need to do.",
            ],
            cta_label="Find other events",
            cta_url=_url("web:event_list"),
        )
        for r in registrations
    ])


def send_waitlist_promoted(event, registrations):
    _deliver([
        _build(
            r.user, event,
            subject=f"You're in! A seat opened up for {event.title}",
            heading="A seat opened up for you",
            paragraphs=[
                f"Good news: you have moved from the waitlist to registered for {event.title}.",
                "If you can no longer attend, please cancel so the next person can join.",
            ],
            cta_label="View event",
            cta_url=_url("web:event_detail", event.slug),
        )
        for r in registrations
    ])


def send_reminder(registration):
    """Returns True if the reminder was sent."""
    event = registration.event
    return _deliver([_build(
        registration.user, event,
        subject=f"Reminder: {event.title} is coming up",
        heading="Your event is coming up",
        paragraphs=[f"This is a friendly reminder that you are registered for {event.title}."],
        cta_label="View event",
        cta_url=_url("web:event_detail", event.slug),
    )]) == 1