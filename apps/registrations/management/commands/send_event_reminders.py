from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.registrations import notifications
from apps.registrations.models import Registration


class Command(BaseCommand):
    help = "Email reminders to registered attendees of events starting soon (safe to run repeatedly)."

    def add_arguments(self, parser):
        parser.add_argument("--hours", type=int, default=24, help="Remind this many hours ahead.")

    def handle(self, *args, **options):
        now = timezone.now()
        due = (
            Registration.objects.registered()
            .filter(
                reminder_sent_at__isnull=True,
                event__status="PUBLISHED",
                event__start_datetime__gt=now,
                event__start_datetime__lte=now + timedelta(hours=options["hours"]),
            )
            .select_related("user", "event")
        )
        sent = failed = 0
        for registration in due.iterator():
            # Claim the row first, so two overlapping runs can never email the same person twice.
            claimed = Registration.objects.filter(
                pk=registration.pk, reminder_sent_at__isnull=True
            ).update(reminder_sent_at=timezone.now())
            if not claimed:
                continue
            if notifications.send_reminder(registration):
                sent += 1
            else:
                Registration.objects.filter(pk=registration.pk).update(reminder_sent_at=None)
                failed += 1
        self.stdout.write(self.style.SUCCESS(f"Reminders sent: {sent}, failed: {failed}"))