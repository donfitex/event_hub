from django.core.management.base import BaseCommand

from apps.events.models import Category

CATEGORIES = [
    "Technology", "Business", "Education", "Conference", "Workshop",
    "Networking", "Entertainment", "Sports", "Career", "Community",
]


class Command(BaseCommand):
    help = "Create the default event categories (safe to run repeatedly)."

    def handle(self, *args, **options):
        created = 0
        for name in CATEGORIES:
            _, was_created = Category.objects.get_or_create(name=name)
            created += was_created
        self.stdout.write(self.style.SUCCESS(f"{created} created, {len(CATEGORIES) - created} already existed."))