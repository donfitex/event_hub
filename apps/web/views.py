from django.contrib import messages
from django.contrib.auth import login
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.contrib.auth.views import LoginView, redirect_to_login
from django.http import Http404
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import PasswordChangeView
from django.contrib.messages.views import SuccessMessageMixin
from django.urls import reverse, reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from rest_framework.authtoken.models import Token

from apps.events.validators import user_can_manage_event
from apps.registrations.constants import ACTIVE_STATUSES, RegistrationStatus
from apps.registrations.exceptions import RegistrationError
from apps.registrations.models import Registration
from apps.registrations.services import (
    cancel_registration,
    cancellation_deadline,
    get_waitlist_position,
    register_for_event,
)

from apps.events.availability import availability_state
from apps.events.constants import EventStatus
from apps.events.models import Category, Event


from .forms import LoginForm, RegisterForm, ProfileForm

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
    event = get_object_or_404(_with_counts(Event.objects.all()), slug=slug)
    can_manage = user_can_manage_event(request.user, event)
    if event.status == EventStatus.DRAFT and not can_manage:
        raise Http404  # drafts are visible only to the organizer and admins

    registration = None
    if request.user.is_authenticated:
        registration = (
            Registration.objects.active().filter(user=request.user, event=event).first()
        )

    registered = event.registered_count
    state_code, state_label = availability_state(
        event, registered, registration.status if registration else None
    )
    now = timezone.now()
    start, end = timezone.localtime(event.start_datetime), timezone.localtime(event.end_datetime)

    context = {
        "event": event,
        "state_code": state_code,
        "state_label": state_label,
        "available_seats": max(event.capacity - registered, 0),
        "fill_percent": min(100, round(registered * 100 / event.capacity)),
        "registration": registration,
        "waitlist_position": get_waitlist_position(registration) if registration else None,
        "registration_open": event.status == EventStatus.PUBLISHED and now <= event.registration_deadline,
        "multi_day": start.date() != end.date(),
        "can_manage": can_manage,
    }
    return render(request, "web/event_detail.html", context)

def _registration_stats(user):
    now = timezone.now()
    return Registration.objects.filter(user=user).aggregate(
        upcoming=Count("id", filter=Q(status=RegistrationStatus.REGISTERED, event__end_datetime__gt=now)),
        waitlisted=Count("id", filter=Q(status=RegistrationStatus.WAITLISTED, event__end_datetime__gt=now)),
        past=Count("id", filter=Q(status__in=ACTIVE_STATUSES, event__end_datetime__lte=now)),
        cancelled=Count("id", filter=Q(status=RegistrationStatus.CANCELLED)),
    )


def _decorate_registrations(registrations):
    now = timezone.now()
    items = list(registrations)
    for r in items:
        r.can_cancel = r.is_active and now < cancellation_deadline(r.event)
        r.waitlist_position = get_waitlist_position(r)
        r.event_ended = r.event.end_datetime <= now
    return items


def _user_registrations(user):
    return Registration.objects.filter(user=user).select_related(
        "event", "event__category", "event__organizer"
    )


@login_required
def dashboard(request):
    now = timezone.now()
    upcoming = (
        _user_registrations(request.user)
        .filter(status__in=ACTIVE_STATUSES, event__end_datetime__gt=now)
        .order_by("event__start_datetime")[:3]
    )
    context = {
        "stats": _registration_stats(request.user),
        "next_up": _decorate_registrations(upcoming),
    }
    return render(request, "web/dashboard.html", context)


@login_required
def my_registrations(request):
    now = timezone.now()
    tab = request.GET.get("tab", "upcoming")
    qs = _user_registrations(request.user)
    if tab == "past":
        qs = qs.filter(status__in=ACTIVE_STATUSES, event__end_datetime__lte=now).order_by("-event__start_datetime")
    elif tab == "cancelled":
        qs = qs.filter(status=RegistrationStatus.CANCELLED).order_by("-cancelled_at")
    else:
        tab = "upcoming"
        qs = qs.filter(status__in=ACTIVE_STATUSES, event__end_datetime__gt=now).order_by("event__start_datetime")

    page = Paginator(qs, 10).get_page(request.GET.get("page"))
    context = {
        "tab": tab,
        "page": page,
        "registrations": _decorate_registrations(page.object_list),
        "stats": _registration_stats(request.user),
        "querystring": f"tab={tab}",
    }
    return render(request, "web/my_registrations.html", context)


@login_required
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Your profile has been updated.")
        return redirect("web:profile")
    return render(request, "web/profile.html", {"form": form})


class SitePasswordChangeView(SuccessMessageMixin, PasswordChangeView):
    template_name = "web/password_change.html"
    success_url = reverse_lazy("web:profile")
    success_message = "Your password has been changed."

    def form_valid(self, form):
        # Same rule as the API: a new password invalidates old API tokens.
        Token.objects.filter(user=self.request.user).delete()
        return super().form_valid(form)


@require_POST
def event_register(request, slug):
    event = get_object_or_404(Event.objects.exclude(status=EventStatus.DRAFT), slug=slug)
    detail_url = reverse("web:event_detail", args=[slug])
    if not request.user.is_authenticated:
        return redirect_to_login(detail_url)

    try:
        registration = register_for_event(request.user, event)
    except RegistrationError as exc:
        messages.error(request, exc.message)
    else:
        if registration.status == RegistrationStatus.WAITLISTED:
            position = get_waitlist_position(registration)
            messages.info(request, f"This event is full. You are number {position} on the waitlist.")
        else:
            messages.success(request, "You're registered! See you there.")
    return redirect(detail_url)


@require_POST
def registration_cancel(request, pk):
    if not request.user.is_authenticated:
        return redirect_to_login(reverse("web:home"))
    registration = get_object_or_404(
        Registration.objects.select_related("event"), pk=pk, user=request.user
    )
    was_waitlisted = registration.status == RegistrationStatus.WAITLISTED
    try:
        cancel_registration(registration, request.user)
    except RegistrationError as exc:
        messages.error(request, exc.message)
    else:
        messages.success(
            request,
            "You have left the waitlist." if was_waitlisted else "Your registration has been cancelled.",
        )
    next_url = request.POST.get("next", "")
    if url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return redirect(next_url)
    return redirect("web:event_detail", slug=registration.event.slug)

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