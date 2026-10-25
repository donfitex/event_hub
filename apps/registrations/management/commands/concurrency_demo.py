# apps/registrations/management/commands/concurrency_demo.py
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from apps.events.models import Event
from apps.registrations.exceptions import RegistrationError
from apps.registrations.models import Registration
from apps.registrations.services import register_for_event


class Command(BaseCommand):
    help = "Fire simultaneous registrations at a nearly-full event (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--capacity", type=int, default=5)
        parser.add_argument("--users", type=int, default=20)

    def handle(self, *args, **opts):
        event = Event.objects.filter(status="PUBLISHED").first()
        if not event:
            raise CommandError("No published event. Run seed_events first.")

        Registration.objects.filter(event=event).delete()
        Event.objects.filter(pk=event.pk).update(
            capacity=opts["capacity"],
            registration_deadline=timezone.now() + timedelta(days=1),
        )
        event.refresh_from_db()

        User = get_user_model()
        users = []
        for i in range(opts["users"]):
            email = f"load{i}@example.com"
            users.append(
                User.objects.filter(email=email).first()
                or User.objects.create_user(email, "Pass#12345", first_name="Load", last_name=str(i))
            )

        def attempt(user):
            try:
                return register_for_event(user, event).status
            except RegistrationError as exc:
                return exc.code
            finally:
                connection.close()  # each thread owns its own connection

        with ThreadPoolExecutor(max_workers=len(users)) as pool:
            results = Counter(pool.map(attempt, users))

        registered = Registration.objects.registered().filter(event=event).count()
        waitlisted = Registration.objects.waitlisted().filter(event=event).count()
        self.stdout.write(f"Event {event.pk}, capacity {event.capacity}")
        self.stdout.write(f"Outcomes: {dict(results)}")
        self.stdout.write(f"Registered: {registered}, waitlisted: {waitlisted}")
        ok = registered == event.capacity and registered + waitlisted == len(users)
        style = self.style.SUCCESS if ok else self.style.ERROR
        self.stdout.write(style("PASS: no overbooking" if ok else "FAIL: capacity exceeded"))