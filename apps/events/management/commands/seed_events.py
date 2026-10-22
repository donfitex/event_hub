from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.events.models import Category, Event

CITIES = ["Lagos", "Abuja", "Ibadan", "Port Harcourt", "Ota"]
STATUSES = ["PUBLISHED"] * 5 + ["DRAFT", "CANCELLED", "COMPLETED"]


class Command(BaseCommand):
    help = "Create 25 sample events for development (run seed_categories first)."

    def handle(self, *args, **options):
        if Event.objects.filter(title__startswith="Sample Event").exists():
            self.stdout.write("Sample events already exist.")
            return
        organizer = get_user_model().objects.filter(role__in=["ORGANIZER", "ADMIN"]).first()
        categories = list(Category.objects.all())
        if not organizer or not categories:
            raise CommandError("Need an organizer/admin user and categories first.")

        now = timezone.now()
        for i in range(25):
            status = STATUSES[i % len(STATUSES)]
            offset = timedelta(days=-(i + 5)) if status == "COMPLETED" else timedelta(days=i + 3)
            start = now + offset
            category = categories[i % len(categories)]
            Event.objects.create(
                title=f"Sample Event {i + 1}: {category.name} Meetup",
                description=f"A sample {category.name.lower()} event for development and testing.",
                organizer=organizer,
                category=category,
                location=CITIES[i % len(CITIES)],
                venue=f"Venue {i + 1}",
                start_datetime=start,
                end_datetime=start + timedelta(hours=4),
                registration_deadline=start - timedelta(days=1),
                capacity=20 + i * 5,
                status=status,
            )
        self.stdout.write(self.style.SUCCESS("25 sample events created."))