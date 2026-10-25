from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.views import LoginView
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date

from apps.events.availability import availability_state
from apps.events.constants import EventStatus
from apps.events.models import Category, Event
from apps.registrations.constants import RegistrationStatus

from .forms import LoginForm, RegisterForm

PAGE_SIZE = 9
SORTS = {
    "soonest": "start_datetime",
    "latest": "-start_datetime",
    "newest": "-created_at",
    "title": "title",
}


def _with_counts(qs):
    return qs.select_related("category", "organizer").annotate(
        registered_count=Count(
            "registrations",
            filter=Q(registrations__status=RegistrationStatus.REGISTERED),
        )
    )


def public_events():
    """Published events that have not started yet."""
    return _with_counts(
        Event.objects.filter(status=EventStatus.PUBLISHED, start_datetime__gte=timezone.now())
    )


def decorate(events):
    """Attach seat counts and the availability badge to each event."""
    events = list(events)
    for event in events:
        registered = getattr(event, "registered_count", 0)
        event.available_seats = max(event.capacity - registered, 0)
        event.state_code, event.state_label = availability_state(event, registered)
    return events


def home(request):
    now = timezone.now()
    categories = Category.objects.filter(is_active=True).annotate(
        upcoming=Count(
            "events",
            filter=Q(events__status=EventStatus.PUBLISHED, events__start_datetime__gte=now),
        )
    )
    featured = decorate(public_events().order_by("start_datetime")[:6])
    return render(request, "web/home.html", {"categories": categories, "events": featured})


def event_list(request):
    qs = public_events()
    params = request.GET

    term = params.get("q", "").strip()
    if term:
        qs = qs.filter(
            Q(title__icontains=term)
            | Q(description__icontains=term)
            | Q(venue__icontains=term)
            | Q(location__icontains=term)
            | Q(category__name__icontains=term)
        )
    category = params.get("category", "")
    if category:
        qs = qs.filter(category__slug=category)
    location = params.get("location", "").strip()
    if location:
        qs = qs.filter(location__icontains=location)
    date_from = parse_date(params.get("from", ""))
    if date_from:
        qs = qs.filter(start_datetime__date__gte=date_from)

    sort = params.get("sort", "soonest")
    qs = qs.order_by(SORTS.get(sort, SORTS["soonest"]), "id")

    page = Paginator(qs, PAGE_SIZE).get_page(params.get("page"))
    query = params.copy()
    query.pop("page", None)

    context = {
        "page": page,
        "events": decorate(page.object_list),
        "categories": Category.objects.filter(is_active=True),
        "filters": {"q": term, "category": category, "location": location,
                    "from": params.get("from", ""), "sort": sort},
        "querystring": query.urlencode(),
    }
    return render(request, "web/event_list.html", context)


def event_detail(request, slug):
    """Minimal page for now; Commit 21 builds the full experience."""
    event = get_object_or_404(_with_counts(Event.objects.exclude(status=EventStatus.DRAFT)), slug=slug)
    event = decorate([event])[0]
    return render(request, "web/event_detail.html", {"event": event})


def register(request):
    if request.user.is_authenticated:
        return redirect("web:home")
    form = RegisterForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, f"Welcome to EventHub, {user.first_name}!")
        return redirect("web:event_list")
    return render(request, "web/register.html", {"form": form})


class SiteLoginView(LoginView):
    template_name = "web/login.html"
    authentication_form = LoginForm
    redirect_authenticated_user = True