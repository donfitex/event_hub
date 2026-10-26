from datetime import timedelta

import pytest
from django.utils import timezone

from apps.events.models import Event
from apps.registrations.constants import RegistrationStatus as S
from apps.registrations.models import Registration
from apps.registrations.services import (
    cancel_all_registrations,
    cancel_registration,
    cancellation_deadline,
    get_waitlist_position,
    promote_waitlisted,
    register_for_event,
)
from tests.factories import (
    AdminFactory,
    EventFactory,
    OrganizerFactory,
    RegistrationFactory,
    UserFactory,
)
from tests.helpers import expect_error

pytestmark = pytest.mark.django_db


class TestRegisterForEvent:
    def test_registers_when_a_seat_is_free(self):
        user, event = UserFactory(), EventFactory(capacity=2)
        registration = register_for_event(user, event)
        registration.refresh_from_db()
        assert registration.status == S.REGISTERED
        assert (registration.user, registration.event) == (user, event)

    def test_seats_fill_up_and_then_the_waitlist_starts(self):
        event = EventFactory(capacity=2)
        statuses = [register_for_event(UserFactory(), event).status for _ in range(4)]
        assert statuses == [S.REGISTERED, S.REGISTERED, S.WAITLISTED, S.WAITLISTED]
        assert Registration.objects.registered().filter(event=event).count() == 2

    def test_the_waitlist_is_first_in_first_out(self):
        event = EventFactory(capacity=1)
        first = register_for_event(UserFactory(), event)
        second = register_for_event(UserFactory(), event)
        third = register_for_event(UserFactory(), event)
        assert [get_waitlist_position(r) for r in (first, second, third)] == [None, 1, 2]

    def test_duplicate_registration_is_rejected(self):
        user, event = UserFactory(), EventFactory()
        register_for_event(user, event)
        with expect_error("ALREADY_REGISTERED"):
            register_for_event(user, event)
        assert Registration.objects.filter(user=user, event=event).count() == 1

    def test_joining_the_waitlist_twice_is_rejected(self):
        event = EventFactory(capacity=1)
        register_for_event(UserFactory(), event)
        user = UserFactory()
        register_for_event(user, event)
        with expect_error("ALREADY_WAITLISTED"):
            register_for_event(user, event)
        assert Registration.objects.filter(user=user, event=event).count() == 1

    def test_a_user_can_register_again_after_cancelling(self):
        user, event = UserFactory(), EventFactory()
        first = register_for_event(user, event)
        cancel_registration(first, user)
        second = register_for_event(user, event)
        assert second.status == S.REGISTERED
        assert Registration.objects.filter(user=user, event=event).count() == 2

    @pytest.mark.parametrize(
        "traits, code",
        [
            ({"draft": True}, "EVENT_NOT_PUBLISHED"),
            ({"cancelled": True}, "EVENT_CANCELLED"),
            ({"completed": True}, "EVENT_COMPLETED"),
            ({"closed": True}, "REGISTRATION_CLOSED"),
        ],
    )
    def test_the_event_must_be_open(self, traits, code):
        event = EventFactory(**traits)
        with expect_error(code):
            register_for_event(UserFactory(), event)
        assert not Registration.objects.exists()

    def test_deadline_boundary(self):
        now = timezone.now()
        open_event = EventFactory(registration_deadline=now + timedelta(minutes=5))
        assert register_for_event(UserFactory(), open_event).status == S.REGISTERED
        expired = EventFactory(registration_deadline=now - timedelta(seconds=1))
        with expect_error("REGISTRATION_CLOSED"):
            register_for_event(UserFactory(), expired)

    def test_a_deleted_event_is_reported_as_not_found(self):
        event = EventFactory()
        stale = Event.objects.get(pk=event.pk)
        event.delete()
        with expect_error("EVENT_NOT_FOUND", status=404):
            register_for_event(UserFactory(), stale)

    def test_capacity_is_read_from_the_database_not_from_the_passed_object(self):
        event = EventFactory(capacity=10)  # this in-memory copy says 10 seats
        Event.objects.filter(pk=event.pk).update(capacity=1)
        RegistrationFactory(event=event)
        assert register_for_event(UserFactory(), event).status == S.WAITLISTED

    def test_the_deadline_is_read_from_the_database_too(self):
        event = EventFactory()
        Event.objects.filter(pk=event.pk).update(
            registration_deadline=timezone.now() - timedelta(minutes=1)
        )
        with expect_error("REGISTRATION_CLOSED"):
            register_for_event(UserFactory(), event)

    def test_a_newcomer_never_jumps_ahead_of_someone_waiting(self):
        event = EventFactory(capacity=1)
        holder = register_for_event(UserFactory(), event)
        waiting = register_for_event(UserFactory(), event)
        # The seat is freed behind our back, with no promotion having run:
        Registration.objects.filter(pk=holder.pk).update(
            status=S.CANCELLED, cancelled_at=timezone.now()
        )
        newcomer = register_for_event(UserFactory(), event)
        waiting.refresh_from_db()
        assert waiting.status == S.REGISTERED
        assert newcomer.status == S.WAITLISTED


class TestCancelRegistration:
    def test_owner_cancels(self):
        user = UserFactory()
        registration = register_for_event(user, EventFactory())
        cancelled, promoted = cancel_registration(registration, user)
        assert cancelled.status == S.CANCELLED
        assert cancelled.cancelled_at is not None
        assert promoted == []

    def test_cancelling_frees_the_seat(self):
        event = EventFactory(capacity=1)
        user = UserFactory()
        registration = register_for_event(user, event)
        cancel_registration(registration, user)
        assert register_for_event(UserFactory(), event).status == S.REGISTERED

    def test_cancelling_promotes_the_earliest_waitlisted_user(self):
        event = EventFactory(capacity=1)
        holder = UserFactory()
        holder_reg = register_for_event(holder, event)
        first_waiting = register_for_event(UserFactory(), event)
        second_waiting = register_for_event(UserFactory(), event)

        _, promoted = cancel_registration(holder_reg, holder)

        assert promoted == [first_waiting]
        first_waiting.refresh_from_db()
        second_waiting.refresh_from_db()
        assert first_waiting.status == S.REGISTERED
        assert second_waiting.status == S.WAITLISTED
        assert get_waitlist_position(second_waiting) == 1

    def test_one_freed_seat_promotes_exactly_one_person(self):
        event = EventFactory(capacity=2)
        users = [UserFactory() for _ in range(2)]
        regs = [register_for_event(u, event) for u in users]
        waiting = [register_for_event(UserFactory(), event) for _ in range(3)]
        _, promoted = cancel_registration(regs[0], users[0])
        assert promoted == [waiting[0]]
        assert Registration.objects.registered().filter(event=event).count() == 2

    def test_cancelling_a_waitlisted_registration_promotes_nobody(self):
        event = EventFactory(capacity=1)
        register_for_event(UserFactory(), event)
        user = UserFactory()
        waiting = register_for_event(user, event)
        other_waiting = register_for_event(UserFactory(), event)

        _, promoted = cancel_registration(waiting, user)

        assert promoted == []
        other_waiting.refresh_from_db()
        assert other_waiting.status == S.WAITLISTED
        assert get_waitlist_position(other_waiting) == 1

    def test_cancelling_twice_is_rejected_even_with_a_stale_object(self):
        user = UserFactory()
        registration = register_for_event(user, EventFactory())
        stale = Registration.objects.get(pk=registration.pk)
        cancel_registration(registration, user)
        with expect_error("ALREADY_CANCELLED"):
            cancel_registration(stale, user)

    def test_a_stranger_cannot_cancel(self):
        registration = register_for_event(UserFactory(), EventFactory())
        with expect_error("FORBIDDEN", status=403):
            cancel_registration(registration, UserFactory())
        registration.refresh_from_db()
        assert registration.status == S.REGISTERED

    def test_the_events_organizer_can_cancel_an_attendee(self):
        event = EventFactory()
        registration = register_for_event(UserFactory(), event)
        cancelled, _ = cancel_registration(registration, event.organizer)
        assert cancelled.status == S.CANCELLED

    def test_an_admin_can_cancel_any_registration(self):
        registration = register_for_event(UserFactory(), EventFactory())
        cancelled, _ = cancel_registration(registration, AdminFactory())
        assert cancelled.status == S.CANCELLED

    def test_another_organizer_cannot_cancel(self):
        registration = register_for_event(UserFactory(), EventFactory())
        with expect_error("FORBIDDEN", status=403):
            cancel_registration(registration, OrganizerFactory())

    def test_cannot_cancel_after_the_event_has_started(self):
        now = timezone.now()
        event = EventFactory(
            start_datetime=now - timedelta(hours=1),
            end_datetime=now + timedelta(hours=3),
            registration_deadline=now - timedelta(days=1),
        )
        registration = RegistrationFactory(event=event)
        with expect_error("CANCELLATION_CLOSED"):
            cancel_registration(registration, registration.user)

    def test_the_notice_period_setting_blocks_late_cancellations(self, settings):
        event = EventFactory(start_datetime=timezone.now() + timedelta(hours=24))
        registration = RegistrationFactory(event=event)

        settings.REGISTRATION_CANCELLATION_CUTOFF_HOURS = 48
        with expect_error("CANCELLATION_CLOSED"):
            cancel_registration(registration, registration.user)

        settings.REGISTRATION_CANCELLATION_CUTOFF_HOURS = 12
        cancelled, _ = cancel_registration(registration, registration.user)
        assert cancelled.status == S.CANCELLED

    def test_cancellation_deadline_is_start_minus_the_notice_period(self, settings):
        event = EventFactory()
        settings.REGISTRATION_CANCELLATION_CUTOFF_HOURS = 24
        assert cancellation_deadline(event) == event.start_datetime - timedelta(hours=24)


class TestPromoteWaitlisted:
    def test_promotes_only_into_free_seats(self):
        event = EventFactory(capacity=3)
        RegistrationFactory(event=event)
        waiting = [RegistrationFactory(event=event, waitlisted=True) for _ in range(4)]
        assert promote_waitlisted(event) == waiting[:2]
        assert Registration.objects.registered().filter(event=event).count() == 3

    def test_order_follows_the_join_time_not_the_row_id(self):
        event = EventFactory(capacity=1)
        now = timezone.now()
        created_first = RegistrationFactory(event=event, waitlisted=True)
        created_second = RegistrationFactory(event=event, waitlisted=True)
        Registration.objects.filter(pk=created_first.pk).update(registered_at=now)
        Registration.objects.filter(pk=created_second.pk).update(
            registered_at=now - timedelta(hours=1)
        )
        assert promote_waitlisted(event) == [created_second]

    def test_identical_join_times_fall_back_to_the_row_id(self):
        event = EventFactory(capacity=1)
        same = timezone.now()
        a = RegistrationFactory(event=event, waitlisted=True)
        b = RegistrationFactory(event=event, waitlisted=True)
        Registration.objects.filter(pk__in=[a.pk, b.pk]).update(registered_at=same)
        assert promote_waitlisted(event) == [a]

    def test_nothing_happens_when_the_event_is_full(self):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        waiting = RegistrationFactory(event=event, waitlisted=True)
        assert promote_waitlisted(event) == []
        waiting.refresh_from_db()
        assert waiting.status == S.WAITLISTED

    @pytest.mark.parametrize("trait", ["draft", "cancelled", "completed"])
    def test_events_that_are_not_published_never_promote(self, trait):
        event = EventFactory(capacity=2, **{trait: True})
        waiting = RegistrationFactory(event=event, waitlisted=True)
        assert promote_waitlisted(event) == []
        waiting.refresh_from_db()
        assert waiting.status == S.WAITLISTED

    def test_a_capacity_increase_lets_waiting_people_in(self):
        event = EventFactory(capacity=1)
        RegistrationFactory(event=event)
        waiting = [RegistrationFactory(event=event, waitlisted=True) for _ in range(3)]
        Event.objects.filter(pk=event.pk).update(capacity=3)
        event.refresh_from_db()
        assert promote_waitlisted(event) == waiting[:2]


class TestWaitlistPosition:
    def test_only_waitlisted_registrations_have_a_position(self):
        assert get_waitlist_position(RegistrationFactory()) is None
        assert get_waitlist_position(RegistrationFactory(cancelled=True)) is None

    def test_positions_are_per_event(self):
        a, b = EventFactory(), EventFactory()
        RegistrationFactory(event=a, waitlisted=True)
        in_b = RegistrationFactory(event=b, waitlisted=True)
        assert get_waitlist_position(in_b) == 1


class TestCancelAllRegistrations:
    def test_cancels_every_active_registration_and_nothing_else(self):
        event, other_event = EventFactory(), EventFactory()
        registered = RegistrationFactory(event=event)
        waitlisted = RegistrationFactory(event=event, waitlisted=True)
        earlier = RegistrationFactory(event=event, cancelled=True)
        earlier_timestamp = earlier.cancelled_at
        untouched = RegistrationFactory(event=other_event)

        affected = cancel_all_registrations(event)

        assert set(affected) == {registered, waitlisted}
        for registration in (registered, waitlisted):
            registration.refresh_from_db()
            assert registration.status == S.CANCELLED
            assert registration.cancelled_at is not None
        earlier.refresh_from_db()
        assert earlier.cancelled_at == earlier_timestamp
        untouched.refresh_from_db()
        assert untouched.status == S.REGISTERED