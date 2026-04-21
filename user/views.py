from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .models import (
    Booking,
    Payment,
    EventType,
    Review,
    ReviewReply,
    Notification,
    ContactMessage,
    BookingStatusHistory,
    LandingCarouselImage,
    HALL_INCLUDED_CAPACITY,
    HALL_SINGLE_HALL_LIMIT,
    HALL_EXCESS_PERSON_FEE,
)
from datetime import datetime, date as date_type, timedelta
from django.conf import settings
from .mailer import (
    send_verification_email, send_password_reset_email, send_email_change_verification,
    send_booking_confirmation_email, send_booking_status_email, send_guest_invitation_email,
    send_cancellation_email, send_payment_confirmed_email, send_html_email,
)
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError
import logging
import uuid
import json
import random
import string
import threading
import sys
from decimal import Decimal

logger = logging.getLogger(__name__)

User = get_user_model()

DECLINE_REASON_TEMPLATES = [
    {'key': 'slot_unavailable', 'label': 'Slot unavailable', 'text': 'The selected date or time slot is no longer available.'},
    {'key': 'capacity_limit', 'label': 'Capacity limit', 'text': 'The requested guest count exceeds the venue capacity for this event.'},
    {'key': 'incomplete_details', 'label': 'Incomplete details', 'text': 'The booking details submitted are incomplete and need clarification.'},
    {'key': 'payment_issue', 'label': 'Payment issue', 'text': 'We could not verify the payment requirement for this booking.'},
]

CANCEL_REASON_TEMPLATES = [
    {'key': 'change_of_plans', 'label': 'Change of plans', 'text': 'The client requested cancellation due to a change of plans.'},
    {'key': 'budget_constraints', 'label': 'Budget constraints', 'text': 'The booking was cancelled due to budget constraints.'},
    {'key': 'schedule_conflict', 'label': 'Schedule conflict', 'text': 'The booking was cancelled because of a schedule conflict.'},
    {'key': 'duplicate_request', 'label': 'Duplicate request', 'text': 'The booking was cancelled because a duplicate request already exists.'},
]

DEFAULT_HALL_BASE_PRICE = Decimal('5000')
MAX_SLOTS = 5


def _get_hall_base_price(event_type_obj):
    return Decimal(str(event_type_obj.price)) if event_type_obj else DEFAULT_HALL_BASE_PRICE


def _get_guest_count(value):
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _get_pricing_payload(event_type_obj, guest_count):
    base_price = _get_hall_base_price(event_type_obj)
    excess_guests = max(0, guest_count - HALL_INCLUDED_CAPACITY)
    excess_total = Decimal(excess_guests) * HALL_EXCESS_PERSON_FEE
    return {
        'base_price': float(base_price),
        'included_capacity': HALL_INCLUDED_CAPACITY,
        'max_capacity': HALL_SINGLE_HALL_LIMIT,
        'excess_person_fee': float(HALL_EXCESS_PERSON_FEE),
        'excess_guests': excess_guests,
        'excess_total': float(excess_total),
        'total_amount': float(base_price + excess_total),
        'single_hall_supported': guest_count <= HALL_SINGLE_HALL_LIMIT if guest_count > 0 else True,
    }


def _resolve_selected_halls(raw_selected_halls, fallback_event_type=''):
    if isinstance(raw_selected_halls, str):
        selected_halls = [item.strip() for item in raw_selected_halls.split(',') if item.strip()]
    elif isinstance(raw_selected_halls, list):
        selected_halls = [str(item).strip() for item in raw_selected_halls if str(item).strip()]
    else:
        selected_halls = []

    if not selected_halls and fallback_event_type:
        selected_halls = [fallback_event_type.strip()]

    seen = set()
    normalized = []
    for hall in selected_halls:
        key = hall.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(hall)
    return normalized


def _get_hall_combo_pricing(selected_hall_names, guest_count):
    hall_names = _resolve_selected_halls(selected_hall_names)
    hall_objects = list(EventType.objects.filter(event_type__in=hall_names, is_active=True).order_by('event_type'))
    hall_lookup = {hall.event_type: hall for hall in hall_objects}
    ordered_halls = [hall_lookup[name] for name in hall_names if name in hall_lookup]

    if not ordered_halls:
        return None

    base_price = sum(_get_hall_base_price(hall) for hall in ordered_halls)
    included_capacity = sum(
        hall.max_capacity if hall.max_capacity and hall.max_capacity > 0 else HALL_INCLUDED_CAPACITY
        for hall in ordered_halls
    )
    max_capacity = sum(
        hall.max_capacity if hall.max_capacity and hall.max_capacity > 0 else HALL_SINGLE_HALL_LIMIT
        for hall in ordered_halls
    )
    excess_person_fee = max(
        [HALL_EXCESS_PERSON_FEE] + [HALL_EXCESS_PERSON_FEE for _hall in ordered_halls]
    )
    excess_guests = max(0, guest_count - included_capacity)
    excess_total = Decimal(excess_guests) * excess_person_fee

    return {
        'base_price': float(base_price),
        'included_capacity': included_capacity,
        'max_capacity': max_capacity,
        'excess_person_fee': float(excess_person_fee),
        'excess_guests': excess_guests,
        'excess_total': float(excess_total),
        'total_amount': float(base_price + excess_total),
        'single_hall_supported': guest_count <= max_capacity if guest_count > 0 else True,
        'selected_halls': [hall.event_type for hall in ordered_halls],
        'display_name': ' + '.join(hall.event_type for hall in ordered_halls),
    }


def _build_combo_suggestions(selected_event_type_name, guest_count):
    if guest_count <= HALL_SINGLE_HALL_LIMIT:
        return []

    halls = list(EventType.objects.filter(is_active=True).order_by('event_type'))
    selected_hall = next((hall for hall in halls if hall.event_type == selected_event_type_name), None)
    other_halls = [hall for hall in halls if hall.event_type != selected_event_type_name]
    suggestions = []

    if selected_hall:
        for other_hall in other_halls:
            suggestions.append({
                'label': f'{selected_hall.event_type} + {other_hall.event_type}',
                'combined_capacity': HALL_SINGLE_HALL_LIMIT * 2,
                'base_price': float(_get_hall_base_price(selected_hall) + _get_hall_base_price(other_hall)),
                'halls': [selected_hall.event_type, other_hall.event_type],
            })

    if len(suggestions) < 3:
        for index, first_hall in enumerate(halls):
            for second_hall in halls[index + 1:]:
                label = f'{first_hall.event_type} + {second_hall.event_type}'
                if any(item['label'] == label for item in suggestions):
                    continue
                suggestions.append({
                    'label': label,
                    'combined_capacity': HALL_SINGLE_HALL_LIMIT * 2,
                    'base_price': float(_get_hall_base_price(first_hall) + _get_hall_base_price(second_hall)),
                    'halls': [first_hall.event_type, second_hall.event_type],
                })
                if len(suggestions) >= 4:
                    break
            if len(suggestions) >= 4:
                break

    return suggestions


def _serialize_status_history_entry(entry):
    return {
        'id': entry.id,
        'from_status': entry.from_status,
        'to_status': entry.to_status,
        'reason': entry.reason,
        'actor': entry.actor.email if entry.actor else None,
        'metadata': entry.metadata,
        'created_at': entry.created_at.isoformat(),
    }


def _booking_status_history(booking):
    return [_serialize_status_history_entry(entry) for entry in booking.status_history.all()]


def _record_booking_history(booking, to_status, actor=None, reason='', metadata=None, from_status=''):
    BookingStatusHistory.objects.create(
        booking=booking,
        from_status=from_status,
        to_status=to_status,
        actor=actor,
        reason=reason,
        metadata=metadata or {},
    )


def _template_reason(template_key, custom_reason, templates):
    custom_reason = (custom_reason or '').strip()
    if custom_reason:
        return custom_reason
    for template in templates:
        if template['key'] == template_key:
            return template['text']
    return ''


def _normalize_invited_emails(raw_value, owner_email):
    raw_value = raw_value or ''
    candidate_emails = [part.strip().lower() for part in raw_value.replace(';', ',').split(',') if part.strip()]
    normalized = []
    seen = set()
    invalid = []
    for email in candidate_emails:
        if email in seen:
            continue
        try:
            validate_email(email)
        except ValidationError:
            invalid.append(email)
            continue
        if email == owner_email.lower():
            invalid.append(email)
            continue
        seen.add(email)
        normalized.append(email)
    return normalized, invalid


def _active_booking_queryset():
    return Booking.objects.exclude(status__in=['declined', 'cancelled'])


def _duplicate_booking_queryset(user, booking_date, time_slot, booking_time=None, exclude_booking_id=None):
    queryset = _active_booking_queryset().filter(user=user, date=booking_date, time_slot=time_slot)
    if time_slot != 'whole_day' and booking_time:
        queryset = queryset.filter(time=booking_time)
    if exclude_booking_id:
        queryset = queryset.exclude(id=exclude_booking_id)
    return queryset


def _get_recent_acceptance_block(user):
    try:
        latest_confirmed_booking = (
            Booking.objects.filter(user=user, status='confirmed', accepted_at__isnull=False)
            .order_by('-accepted_at')
            .first()
        )
    except (ProgrammingError, OperationalError):
        return None

    if not latest_confirmed_booking:
        return None

    unlock_at = latest_confirmed_booking.accepted_at + timedelta(hours=24)
    if timezone.now() >= unlock_at:
        return None

    return {
        'booking': latest_confirmed_booking,
        'accepted_at': latest_confirmed_booking.accepted_at,
        'unlock_at': unlock_at,
        'remaining': unlock_at - timezone.now(),
    }


def _conflict_summary(booking_date, time_slot, booking_time=None, exclude_booking_id=None):
    active = _active_booking_queryset().filter(date=booking_date)
    if exclude_booking_id:
        active = active.exclude(id=exclude_booking_id)

    whole_day_booked = active.filter(time_slot='whole_day').count()
    morning_used = active.filter(time_slot='morning').count() + whole_day_booked
    afternoon_used = active.filter(time_slot='afternoon').count() + whole_day_booked
    warnings = []

    if whole_day_booked:
        warnings.append('A whole-day booking already exists on this date and reduces slot availability.')
    if morning_used >= 4:
        warnings.append('Morning slots are nearly full for this date.')
    if afternoon_used >= 4:
        warnings.append('Afternoon slots are nearly full for this date.')

    return {
        'morning_booked': morning_used,
        'afternoon_booked': afternoon_used,
        'whole_day_booked': whole_day_booked,
        'requested_slot': time_slot,
        'requested_time': str(booking_time) if booking_time else None,
        'warnings': warnings,
    }


def _throttle_email_action(scope, identifier, limit, window_seconds):
    from django.core.cache import cache

    key = f'throttle:{scope}:{identifier}'
    attempts = cache.get(key, 0)
    if attempts >= limit:
        return False
    cache.set(key, attempts + 1, timeout=window_seconds)
    return True


def send_mail_async(subject, message, recipient_list):
    """Send email in background thread so it never blocks the request."""
    def _send():
        try:
            send_html_email(subject=subject, html_body=message, recipient_list=recipient_list, plain_text=message)
        except Exception as e:
            logger.error('send_mail_async failed to %s: %s', recipient_list, e)
    threading.Thread(target=_send, daemon=True).start()


def send_ws_notification(user_id, message, notif_type='info'):
    """Push a real-time WebSocket notification to a specific user."""
    def _push():
        try:
            from channels.layers import get_channel_layer
            from asgiref.sync import async_to_sync
            channel_layer = get_channel_layer()
            async_to_sync(channel_layer.group_send)(
                f'notifications_{user_id}',
                {
                    'type': 'notification.message',
                    'data': {
                        'type': notif_type,
                        'message': message,
                    },
                }
            )
        except Exception as e:
            print(f'[WS notify error] {e}')
    threading.Thread(target=_push, daemon=True).start()


def _start_reminder_scheduler():
    """Background thread: checks every hour for upcoming bookings and sends reminders."""
    def _run():
        import time
        while True:
            try:
                _send_booking_reminders()
            except Exception as e:
                logger.exception('Reminder scheduler error: %s', e)
            time.sleep(3600)  # check every hour
    threading.Thread(target=_run, daemon=True).start()


def _send_booking_reminders():
    """Send WS + email reminders for bookings happening in 24h or 1h."""
    now = datetime.now()
    today = now.date()
    tomorrow = today + timedelta(days=1)

    # 24-hour reminder: bookings tomorrow that haven't been reminded yet
    upcoming_24h = Booking.objects.filter(
        date=tomorrow,
        status='confirmed',
        reminder_sent=False,
    ).select_related('user')

    for booking in upcoming_24h:
        msg = f'Reminder: Your {booking.event_type} event is tomorrow ({booking.date})!'
        Notification.objects.create(user=booking.user, message=msg)
        send_ws_notification(booking.user.id, msg, notif_type='reminder_24h')
        event_time_str = booking.time.strftime('%I:%M %p') if hasattr(booking.time, 'strftime') else (str(booking.time) if booking.time else 'Whole Day')
        send_html_email(
            subject='EventPro — Your Event is Tomorrow!',
            html_body=(
                f'<h1 style="color:#fff;font-size:22px;font-weight:900;margin:0 0 8px;">Your Event is Tomorrow! 🎉</h1>'
                f'<p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 16px;">Hi <strong style="color:#e2e8f0;">{booking.user.first_name}</strong>, just a reminder about your upcoming event.</p>'
                f'<table width="100%" style="background:rgba(255,255,255,0.04);border-radius:10px;padding:16px;margin:16px 0;">'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;width:100px;">Event</td><td style="color:#e2e8f0;font-size:13px;font-weight:600;">{booking.event_type}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;">Date</td><td style="color:#e2e8f0;font-size:13px;font-weight:600;">{booking.date}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;">Time</td><td style="color:#e2e8f0;font-size:13px;font-weight:600;">{event_time_str}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;">Venue</td><td style="color:#e2e8f0;font-size:13px;font-weight:600;">{booking.location}</td></tr>'
                f'</table>'
            ),
            recipient_list=[booking.user.email],
            plain_text=f'Hi {booking.user.first_name},\n\nReminder: Your {booking.event_type} is tomorrow ({booking.date}) at {event_time_str}.\nVenue: {booking.location}\n\n— EventPro Team',
        )
        booking.reminder_sent = True
        booking.save(update_fields=['reminder_sent'])

    # 1-hour reminder: bookings today where time is within the next 60 minutes
    todays_bookings = Booking.objects.filter(
        date=today,
        status='confirmed',
        whole_day=False,
        time__isnull=False,
    ).select_related('user')

    for booking in todays_bookings:
        if booking.time is None:
            continue
        event_dt = datetime.combine(today, booking.time)
        minutes_left = (event_dt - now).total_seconds() / 60
        if 0 < minutes_left <= 60:
            msg = f'Your {booking.event_type} event starts in about {int(minutes_left)} minutes!'
            Notification.objects.create(user=booking.user, message=msg)
            send_ws_notification(booking.user.id, msg, notif_type='reminder_1h')




# ── Payment deadline checker (runs every hour) ──────────────────────────────
def _start_deadline_checker():
    def _run():
        import time
        while True:
            try:
                _check_payment_deadlines()
            except Exception as e:
                logger.exception('Deadline checker error: %s', e)
            time.sleep(3600)
    threading.Thread(target=_run, daemon=True).start()


def _should_start_background_workers():
    management_commands_to_skip = {
        'migrate',
        'makemigrations',
        'showmigrations',
        'collectstatic',
        'shell',
        'dbshell',
        'test',
        'check',
    }
    return not any(command in sys.argv for command in management_commands_to_skip)

def _check_payment_deadlines():
    from django.utils import timezone
    now = timezone.now()
    try:
        overdue = Booking.objects.only(
            'id',
            'user',
            'event_type',
            'date',
            'status',
            'payment_status',
            'payment_deadline',
            'decline_reason',
        ).filter(
            status='pending',
            payment_status__in=['pending', 'rejected'],
            payment_deadline__lt=now,
        )
    except (ProgrammingError, OperationalError):
        return
    for booking in overdue:
        booking.status = 'declined'
        booking.decline_reason = 'Auto-declined: payment deadline passed (3 days).'
        booking.save(update_fields=['status', 'decline_reason'])
        msg = f'Your {booking.event_type} booking on {booking.date} was auto-declined because payment was not submitted within 3 days.'
        Notification.objects.create(user=booking.user, message=msg)
        send_ws_notification(booking.user.id, msg, notif_type='booking_declined')
        send_html_email(
            subject='EventPro — Booking Auto-Declined (Payment Deadline)',
            html_body=(
                f'<h1 style="color:#fff;font-size:22px;font-weight:900;margin:0 0 8px;">Booking Auto-Declined</h1>'
                f'<p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 16px;">Hi <strong style="color:#e2e8f0;">{booking.user.first_name}</strong>, your booking was automatically declined because payment was not submitted within 3 days.</p>'
                f'<table width="100%" style="background:rgba(255,255,255,0.04);border-radius:10px;padding:16px;margin:16px 0;">'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;width:100px;">Event</td><td style="color:#e2e8f0;font-size:13px;font-weight:600;">{booking.event_type}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;">Date</td><td style="color:#e2e8f0;font-size:13px;font-weight:600;">{booking.date}</td></tr>'
                f'<tr><td style="padding:6px 0;color:#64748b;font-size:13px;">Status</td><td style="color:#ef4444;font-size:13px;font-weight:700;">Auto-Declined</td></tr>'
                f'</table>'
                f'<p style="color:#94a3b8;font-size:14px;">Please create a new booking and complete payment promptly.</p>'
            ),
            recipient_list=[booking.user.email],
            plain_text=f'Hi {booking.user.first_name},\n\nYour {booking.event_type} booking on {booking.date} was auto-declined due to missed payment deadline.\n\n— EventPro Team',
        )

if _should_start_background_workers():
    _start_deadline_checker()


def _send_invitation_emails(booking, confirmed=False):
    """Send HTML invitation emails to all guests listed in invited_emails."""
    if not booking.invited_emails:
        return {'sent': [], 'failed': [], 'invalid': []}
    emails, invalid_emails = _normalize_invited_emails(booking.invited_emails, booking.user.email)
    if not emails:
        if invalid_emails:
            logger.warning('Skipping invalid guest invitation emails for booking %s: %s', booking.id, invalid_emails)
        return {'sent': [], 'failed': [], 'invalid': invalid_emails}
    host_name = f'{booking.user.first_name} {booking.user.last_name}'
    sent = []
    failed = []
    for email in emails:
        try:
            send_guest_invitation_email(email, host_name, booking, confirmed=confirmed)
            sent.append(email)
        except Exception as exc:
            logger.warning('Guest invitation email failed for %s on booking %s: %s', email, booking.id, exc)
            failed.append({'email': email, 'error': str(exc)})
    return {'sent': sent, 'failed': failed, 'invalid': invalid_emails}



@api_view(['GET'])
def get_event_types(request):
    event_types = EventType.objects.filter(is_active=True)
    data = []
    for et in event_types:
        image = None
        if et.image:
            try:
                image = request.build_absolute_uri(et.image.url)
            except Exception:
                image = None
        elif et.image_url:
            image = et.image_url
        data.append({
            'id': et.id,
            'event_type': et.event_type,
            'price': float(et.price),
            'included_capacity': HALL_INCLUDED_CAPACITY,
            'max_capacity': HALL_SINGLE_HALL_LIMIT,
            'max_invited_emails': et.max_invited_emails,
            'people_per_table': et.people_per_table,
            'excess_person_fee': float(HALL_EXCESS_PERSON_FEE),
            'description': et.description,
            'image': image,
        })
    return Response(data)


@api_view(['GET'])
def get_landing_carousel(request):
    carousel_images = LandingCarouselImage.objects.filter(is_active=True).order_by('display_order', 'id')
    data = []
    for item in carousel_images:
        image = None
        if item.image:
            try:
                image = request.build_absolute_uri(item.image.url)
            except Exception:
                image = None
        elif item.image_url:
            image = item.image_url

        if not image:
            continue

        data.append({
            'id': item.id,
            'title': item.title,
            'subtitle': item.subtitle,
            'image': image,
            'display_order': item.display_order,
        })
    return Response(data)


@api_view(['GET'])
def get_public_stats(request):
    total_bookings = Booking.objects.count()
    active_event_types = EventType.objects.filter(is_active=True).count()
    reviews = Review.objects.all()
    review_count = reviews.count()
    average_rating = round(sum(review.rating for review in reviews) / review_count, 1) if review_count > 0 else 0.0
    satisfaction_rate = round((average_rating / 5) * 100) if review_count > 0 else 0

    return Response({
        'events_hosted': total_bookings,
        'average_rating': average_rating,
        'event_types': active_event_types,
        'satisfaction_rate': satisfaction_rate,
    })

@api_view(['POST'])
def register(request):
    try:
        from django.core.cache import cache

        data = request.data
        email = data.get('email', '').strip().lower()
        password = data.get('password')
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()

        if User.objects.filter(email=email).exists():
            return Response({'message': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        if not email or not password or not first_name or not last_name:
            return Response({'message': 'First name, last name, email, and password are required.'}, status=status.HTTP_400_BAD_REQUEST)

        if not _throttle_email_action('register', email or request.META.get('REMOTE_ADDR', 'unknown'), 5, 900):
            return Response({'message': 'Too many registration attempts. Please wait 15 minutes.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

        code = ''.join(random.choices(string.digits, k=6))
        pending = {
            'email': email,
            'password': password,
            'first_name': first_name,
            'last_name': last_name,
            'date_of_birth': data.get('date_of_birth'),
            'address': data.get('address', '').strip(),
            'code': code,
        }
        cache.set(f'pending_reg_{email}', pending, timeout=900)

        try:
            send_verification_email(email, first_name, code)
        except Exception:
            cache.delete(f'pending_reg_{email}')
            raise

        return Response({
            'message': 'Verification code sent to your email.',
            'requires_verification': True,
            'email': email,
        }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.exception('register error: %s', e)
        return Response({'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def request_email_change(request):
    from django.core.cache import cache
    new_email = request.data.get('new_email', '').strip().lower()
    if not new_email:
        return Response({'message': 'New email is required'}, status=status.HTTP_400_BAD_REQUEST)
    if User.objects.filter(email=new_email).exists():
        return Response({'message': 'This email is already in use'}, status=status.HTTP_400_BAD_REQUEST)
    if not _throttle_email_action('email_change', str(request.user.id), 5, 600):
        return Response({'message': 'Too many email change requests. Please wait 10 minutes.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    code = ''.join(random.choices(string.digits, k=6))
    cache.set(f'email_change_{request.user.id}', {'new_email': new_email, 'code': code}, timeout=600)
    send_email_change_verification(request.user.email, request.user.first_name, new_email, code)
    return Response({'message': f'Verification code sent to your current email'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_email_change(request):
    from django.core.cache import cache
    code = request.data.get('code', '').strip()
    pending = cache.get(f'email_change_{request.user.id}')
    if not pending:
        return Response({'message': 'Verification expired. Please request again.'}, status=status.HTTP_400_BAD_REQUEST)
    if pending['code'] != code:
        return Response({'message': 'Invalid verification code'}, status=status.HTTP_400_BAD_REQUEST)
    new_email = pending['new_email']
    user = request.user
    user.email = new_email
    user.username = new_email
    user.save()
    cache.delete(f'email_change_{user.id}')
    return Response({'message': 'Email updated successfully', 'email': new_email})


@api_view(['POST'])
def forgot_password(request):
    email = (request.data.get('email') or '').strip().lower()
    if not _throttle_email_action('forgot_password', email or request.META.get('REMOTE_ADDR', 'unknown'), 5, 900):
        return Response({'message': 'Too many reset requests. Please wait 15 minutes.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    try:
        user = User.objects.get(email=email, is_active=True)
    except User.DoesNotExist:
        return Response({'message': 'This email does not exist.'}, status=status.HTTP_404_NOT_FOUND)

    code = ''.join(random.choices(string.digits, k=6))
    user.verification_code = code
    user.save()

    send_password_reset_email(user.email, user.first_name, code)
    return Response({'message': 'If that email exists, a reset code has been sent.'})


@api_view(['POST'])
def reset_password(request):
    email = request.data.get('email')
    code = request.data.get('code')
    new_password = request.data.get('new_password')

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'message': 'Invalid request'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.verification_code or user.verification_code != code:
        return Response({'message': 'Invalid or expired reset code'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        validate_password(new_password, user)
    except ValidationError as e:
        return Response({'message': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.verification_code = ''
    user.save()
    return Response({'message': 'Password reset successfully. You can now sign in.'})


@api_view(['POST'])
def get_verification_code_debug(request):
    """Temporary debug endpoint — returns verification code directly."""
    from django.core.cache import cache
    email = request.data.get('email', '').strip().lower()
    pending = cache.get(f'pending_reg_{email}')
    if not pending:
        return Response({'message': 'No pending registration found.'}, status=status.HTTP_404_NOT_FOUND)
    return Response({'code': pending['code'], 'email': email})


@api_view(['POST'])
def resend_verification_code(request):
    from django.core.cache import cache
    email = request.data.get('email', '').strip().lower()
    if not _throttle_email_action('resend_verification', email or request.META.get('REMOTE_ADDR', 'unknown'), 5, 900):
        return Response({'message': 'Too many resend attempts. Please wait 15 minutes.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)
    pending = cache.get(f'pending_reg_{email}')
    if not pending:
        return Response({'message': 'No pending verification found for this email.'}, status=status.HTTP_400_BAD_REQUEST)

    code = ''.join(random.choices(string.digits, k=6))
    pending['code'] = code
    cache.set(f'pending_reg_{email}', pending, timeout=900)

    try:
        send_verification_email(email, pending.get('first_name', ''), code)
    except Exception as mail_err:
        logger.exception('Resend verification email failed for %s: %s', email, mail_err)
        return Response(
            {'message': 'We could not resend the verification email. Please check the email service configuration and try again.'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
    return Response({'message': 'A new verification code has been sent to your email.'})


@api_view(['POST'])
def verify_reset_code(request):
    email = request.data.get('email')
    code = request.data.get('code')

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        return Response({'message': 'Invalid request'}, status=status.HTTP_400_BAD_REQUEST)

    if not user.verification_code or user.verification_code != code:
        return Response({'message': 'Invalid reset code. Please check your email and try again.'}, status=status.HTTP_400_BAD_REQUEST)

    return Response({'message': 'Code verified successfully.', 'valid': True})


@api_view(['POST'])
def verify_email(request):
    from django.core.cache import cache
    email = request.data.get('email', '').strip().lower()
    code = request.data.get('code', '').strip()

    pending = cache.get(f'pending_reg_{email}')
    if not pending:
        return Response({'message': 'Verification expired or not found. Please register again.'}, status=status.HTTP_400_BAD_REQUEST)

    if pending['code'] != code:
        return Response({'message': 'Invalid verification code'}, status=status.HTTP_400_BAD_REQUEST)

    if User.objects.filter(email=email).exists():
        return Response({'message': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)

    # Only now create the user in the database
    user = User.objects.create_user(
        username=email,
        email=email,
        password=pending['password'],
        first_name=pending['first_name'],
        last_name=pending['last_name'],
    )
    user.date_of_birth = pending.get('date_of_birth')
    user.address = pending.get('address', '')
    user.is_organizer = False
    user.email_verified = True
    user.is_active = True
    user.save()

    cache.delete(f'pending_reg_{email}')

    refresh = RefreshToken.for_user(user)
    return Response({
        'message': 'Email verified successfully!',
        'access': str(refresh.access_token),
        'refresh': str(refresh),
    })

@api_view(['POST'])
def login(request):
    from django.core.cache import cache
    email = request.data.get('email', '').strip().lower()
    password = request.data.get('password')

    # Rate limiting: max 5 attempts per 15 minutes per email
    cache_key = f'login_attempts_{email}'
    attempts = cache.get(cache_key, 0)
    if attempts >= 500:
        return Response({'message': 'Too many login attempts. Please wait 15 minutes.'}, status=status.HTTP_429_TOO_MANY_REQUESTS)

    try:
        user = User.objects.get(email=email)
    except User.DoesNotExist:
        cache.set(cache_key, attempts + 1, timeout=900)
        return Response({'message': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.is_active:
        return Response({'message': 'Account is not active'}, status=status.HTTP_401_UNAUTHORIZED)

    if not user.check_password(password):
        cache.set(cache_key, attempts + 1, timeout=900)
        return Response({'message': 'Invalid credentials'}, status=status.HTTP_401_UNAUTHORIZED)

    cache.delete(cache_key)  # reset on success
    refresh = RefreshToken.for_user(user)
    return Response({
        'access': str(refresh.access_token),
        'refresh': str(refresh),
        'is_organizer': user.is_organizer,
        'user_type': 'organizer' if user.is_organizer else 'client'
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_availability(request):
    date = request.GET.get('date')
    if not date:
        return Response({'error': 'Date is required'}, status=status.HTTP_400_BAD_REQUEST)
    event_type_name = request.GET.get('event_type', '').strip()
    guest_count = _get_guest_count(request.GET.get('guest_count'))
    selected_halls = _resolve_selected_halls(request.GET.getlist('selected_halls'), event_type_name)
    event_type_obj = EventType.objects.filter(event_type=event_type_name, is_active=True).first() if event_type_name else None

    requested_slot = request.GET.get('time_slot', 'morning')
    if requested_slot not in ['morning', 'afternoon', 'whole_day']:
        requested_slot = 'morning'

    active = _active_booking_queryset().filter(date=date)

    whole_day_count = active.filter(time_slot='whole_day').count()
    morning_count = active.filter(time_slot='morning').count() + whole_day_count
    afternoon_count = active.filter(time_slot='afternoon').count() + whole_day_count

    conflict_summary = _conflict_summary(date, requested_slot)
    duplicate_info = None
    if request.user and request.user.is_authenticated:
        duplicate = _duplicate_booking_queryset(request.user, date, requested_slot).order_by('-created_at').first()
        if duplicate:
            duplicate_info = {
                'booking_id': duplicate.id,
                'status': duplicate.status,
                'payment_status': duplicate.payment_status,
                'date': str(duplicate.date),
                'time': str(duplicate.time) if duplicate.time else None,
                'time_slot': duplicate.time_slot,
            }

    pricing_payload = (
        _get_hall_combo_pricing(selected_halls, guest_count)
        if len(selected_halls) > 1
        else _get_pricing_payload(event_type_obj, guest_count)
    )

    return Response({
        'total_slots': MAX_SLOTS,
        'morning': {
            'booked': morning_count,
            'available': max(0, MAX_SLOTS - morning_count),
        },
        'afternoon': {
            'booked': afternoon_count,
            'available': max(0, MAX_SLOTS - afternoon_count),
        },
        # legacy field kept for backward compat
        'available_rooms': max(0, MAX_SLOTS - active.count()),
        'booked_rooms': active.count(),
        'warnings': conflict_summary['warnings'],
        'conflicts': {
            'requested_slot': requested_slot,
            'whole_day_booked': whole_day_count,
            'morning_nearly_full': morning_count >= 4,
            'afternoon_nearly_full': afternoon_count >= 4,
        },
        'pricing': pricing_payload,
        'combo_suggestions': _build_combo_suggestions(event_type_name, guest_count),
        'duplicate_booking': duplicate_info,
    })

@api_view(['GET'])
def get_public_events(request):
    event_type = request.GET.get('type', None)
    
    if event_type:
        bookings = Booking.objects.filter(event_type=event_type, status='confirmed')
    else:
        bookings = Booking.objects.filter(status='confirmed')
    
    data = [{
        'id': b.id,
        'user': f"{b.user.first_name} {b.user.last_name}",
        'event_type': b.event_type,
        'description': b.description,
        'capacity': b.capacity,
        'date': b.date,
        'time': b.time,
        'location': b.location,
        'status': b.status,
        'event_details': b.event_details,
    } for b in bookings]
    
    return Response(data)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_booking_reason_templates(request):
    return Response({
        'decline_reasons': DECLINE_REASON_TEMPLATES,
        'cancel_reasons': CANCEL_REASON_TEMPLATES,
    })

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_bookings(request):
    bookings = Booking.objects.all().prefetch_related('status_history')
    data = []
    for b in bookings:
        payment_reference = ''
        try:
            payment_reference = b.payment.reference_number
        except Payment.DoesNotExist:
            payment_reference = ''
        proof_url = None
        if b.payment_proof:
            try:
                url = b.payment_proof.url
                proof_url = url if url.startswith('http') else request.build_absolute_uri(url)
            except Exception:
                proof_url = str(b.payment_proof)
        data.append({
            'id': b.id,
            'user': f"{b.user.first_name} {b.user.last_name}",
            'event_type': b.event_type,
            'capacity': b.capacity,
            'date': b.date,
            'time': b.time,
            'status': b.status,
            'payment_status': b.payment_status,
            'gcash_reference': b.gcash_reference or '',
            'payment_proof': proof_url,
            'payment_method': b.payment_method,
            'total_amount': float(b.total_amount),
            'reference_number': payment_reference,
            'decline_reason': b.decline_reason or '',
            'cancel_reason': b.cancel_reason or '',
            'status_history': _booking_status_history(b),
        })
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_bookings(request):
    try:
        bookings = Booking.objects.filter(user=request.user).prefetch_related('status_history')
        data = []
        for b in bookings:
            payment_reference = ''
            try:
                payment_reference = b.payment.reference_number
            except Payment.DoesNotExist:
                payment_reference = ''
            booking_data = {
                'id': b.id,
                'event_type': b.event_type,
                'description': b.description,
                'capacity': b.capacity,
                'date': str(b.date),
                'time': str(b.time) if b.time else None,
                'location': b.location,
                'status': b.status,
                'payment_status': b.payment_status,
                'payment_method': b.payment_method,
                'total_amount': float(b.total_amount),
                'reference_number': payment_reference,
                'created_at': b.created_at.isoformat(),
                'event_details': b.event_details,
                'gcash_reference': b.gcash_reference or '',
                'payment_proof': str(b.payment_proof) if b.payment_proof else None,
                'invited_emails': b.invited_emails,
                'whole_day': b.whole_day,
                'special_requests': b.special_requests,
                'decline_reason': b.decline_reason or '',
                'cancel_reason': b.cancel_reason or '',
                'status_history': _booking_status_history(b),
                'has_review': b.reviews.filter(user=request.user).exists(),
            }
            data.append(booking_data)
        
        return Response(data)
    except Exception as e:
        return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_booking(request):
    try:
        if request.user.is_organizer:
            return Response({'message': 'Organizers cannot create bookings'}, status=status.HTTP_403_FORBIDDEN)

        acceptance_block = _get_recent_acceptance_block(request.user)
        if acceptance_block:
            return Response(
                {
                    'message': (
                        'You cannot create another booking yet. '
                        f'Your last accepted booking was confirmed on '
                        f"{timezone.localtime(acceptance_block['accepted_at']).strftime('%B %d, %Y %I:%M %p')} "
                        f'and you can book again after '
                        f"{timezone.localtime(acceptance_block['unlock_at']).strftime('%B %d, %Y %I:%M %p')}."
                    ),
                    'lock_until': acceptance_block['unlock_at'].isoformat(),
                    'accepted_booking_id': acceptance_block['booking'].id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = request.data
        date = data.get('date')
        event_type = data.get('event_type')
        selected_halls = _resolve_selected_halls(data.get('selected_halls'), event_type)
        capacity = data.get('capacity')
        description = data.get('description') or ''
        invited_emails = data.get('invited_emails') or ''
        payment_method = data.get('payment_method') or ''
        event_details = data.get('event_details') or {}
        special_requests = data.get('special_requests') or ''
        whole_day = data.get('whole_day', False)
        if isinstance(whole_day, str):
            whole_day = whole_day.lower() == 'true'

        if not payment_method:
            return Response({'message': 'Payment method is required'}, status=status.HTTP_400_BAD_REQUEST)

        if not date:
            return Response({'message': 'Event date is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            booking_date = datetime.strptime(date, '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return Response({'message': 'Invalid event date'}, status=status.HTTP_400_BAD_REQUEST)

        if booking_date < timezone.localdate():
            return Response({'message': 'You cannot create a booking for a past date'}, status=status.HTTP_400_BAD_REQUEST)

        normalized_emails, invalid_emails = _normalize_invited_emails(invited_emails, request.user.email)
        if invalid_emails:
            return Response(
                {'message': f'Invalid guest email(s): {", ".join(invalid_emails)}'},
                status=status.HTTP_400_BAD_REQUEST
            )

        invited_emails = ', '.join(normalized_emails)

        # Validate invited emails count against event type max
        if invited_emails:
            try:
                et_obj_check = EventType.objects.get(event_type=event_type, is_active=True)
                if len(normalized_emails) > et_obj_check.max_invited_emails:
                    return Response(
                        {'message': f'You can only invite up to {et_obj_check.max_invited_emails} guests by email for {event_type}.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except EventType.DoesNotExist:
                pass

        # Slot-aware availability check
        raw_slot = data.get('time_slot', '')
        if whole_day:
            time_slot = 'whole_day'
        elif raw_slot in ('morning', 'afternoon', 'whole_day'):
            time_slot = raw_slot
        else:
            time_slot = 'morning'  # safe default

        duplicate_booking = _duplicate_booking_queryset(
            request.user,
            date,
            time_slot,
            booking_time=data.get('time') if time_slot != 'whole_day' else None,
        ).order_by('-created_at').first()
        if duplicate_booking:
            return Response(
                {
                    'message': 'You already have a booking request for the same date and time slot.',
                    'duplicate_booking': {
                        'booking_id': duplicate_booking.id,
                        'status': duplicate_booking.status,
                        'payment_status': duplicate_booking.payment_status,
                        'date': str(duplicate_booking.date),
                        'time': str(duplicate_booking.time) if duplicate_booking.time else None,
                        'time_slot': duplicate_booking.time_slot,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        active = _active_booking_queryset().filter(date=date)
        whole_day_booked = active.filter(time_slot='whole_day').count()

        if time_slot == 'whole_day':
            morning_used = active.filter(time_slot='morning').count() + whole_day_booked
            afternoon_used = active.filter(time_slot='afternoon').count() + whole_day_booked
            if morning_used >= MAX_SLOTS or afternoon_used >= MAX_SLOTS:
                return Response({'message': 'This date is fully booked for whole day'}, status=status.HTTP_400_BAD_REQUEST)
        elif time_slot == 'morning':
            morning_used = active.filter(time_slot='morning').count() + whole_day_booked
            if morning_used >= MAX_SLOTS:
                return Response({'message': 'Morning slots are fully booked for this date'}, status=status.HTTP_400_BAD_REQUEST)
        elif time_slot == 'afternoon':
            afternoon_used = active.filter(time_slot='afternoon').count() + whole_day_booked
            if afternoon_used >= MAX_SLOTS:
                return Response({'message': 'Afternoon slots are fully booked for this date'}, status=status.HTTP_400_BAD_REQUEST)

        guest_count = _get_guest_count(capacity)
        if guest_count <= 0:
            return Response({'message': 'Guest count must be at least 1.'}, status=status.HTTP_400_BAD_REQUEST)

        event_type_obj = EventType.objects.filter(event_type=event_type, is_active=True).first()
        combo_pricing = None
        if len(selected_halls) > 1:
            combo_pricing = _get_hall_combo_pricing(selected_halls, guest_count)
            if not combo_pricing or len(combo_pricing['selected_halls']) != len(selected_halls):
                return Response({'message': 'One or more selected halls are invalid or unavailable.'}, status=status.HTTP_400_BAD_REQUEST)
            if guest_count > combo_pricing['max_capacity']:
                return Response(
                    {'message': f'The selected hall combination supports up to {combo_pricing["max_capacity"]} guests only.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        elif guest_count > HALL_SINGLE_HALL_LIMIT:
            combo_suggestions = _build_combo_suggestions(event_type, guest_count)
            return Response(
                {
                    'message': (
                        f'{event_type} supports up to {HALL_SINGLE_HALL_LIMIT} guests in one hall only. '
                        'Please use one of the suggested hall combinations for bigger events.'
                    ),
                    'pricing': _get_pricing_payload(event_type_obj, guest_count),
                    'combo_suggestions': combo_suggestions,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        booking = Booking.objects.create(
            user=request.user,
            event_type=combo_pricing['display_name'] if combo_pricing else event_type,
            description=description,
            capacity=guest_count,
            date=date,
            time=data.get('time'),
            location="Ralphy's Venue, Basak San Nicolas Villa Kalubihan Cebu City 6000.",
            invited_emails=invited_emails,
            event_details={
                **event_details,
                'selected_halls': combo_pricing['selected_halls'] if combo_pricing else selected_halls,
            },
            special_requests=special_requests,
            whole_day=whole_day,
            time_slot=time_slot,
            status='pending',
            payment_status='paid',
            payment_method=payment_method,
            payment_deadline=timezone.now() + timedelta(days=3),
        )

        # Calculate total amount
        booking.total_amount = Decimal(str((combo_pricing or _get_pricing_payload(event_type_obj, guest_count))['total_amount']))
        booking.save()
        booking.refresh_from_db()  # ensure date/time are proper Python objects
        _record_booking_history(
            booking,
            to_status='pending',
            actor=request.user,
            metadata={'payment_method': payment_method, 'time_slot': booking.time_slot, 'invited_email_count': len(normalized_emails)},
        )

        # Notify all organizers about the new booking via WebSocket
        organizers = User.objects.filter(is_organizer=True, is_active=True)
        for org in organizers:
            org_msg = f'New booking: {booking.event_type} on {date} by {request.user.first_name} {request.user.last_name}'
            Notification.objects.create(user=org, message=org_msg)
            send_ws_notification(org.id, org_msg, notif_type='new_booking')

        # Send booking confirmation email to client (async - non-blocking)
        send_booking_confirmation_email(request.user.email, request.user.first_name, booking)

        # Send invitation emails to guests
        invitation_result = _send_invitation_emails(booking, confirmed=False)

        # Handle payment based on method
        if payment_method in ['GCash', 'QRPh']:
            booking.payment_status = 'pending'
            booking.save()
            _record_booking_history(
                booking,
                from_status='pending',
                to_status='payment_submitted',
                actor=request.user,
                reason=f'{payment_method} payment selected.',
                metadata={'payment_status': booking.payment_status, 'payment_method': payment_method},
            )
            return Response({
                'message': 'Booking created successfully',
                'booking_id': booking.id,
                'total_amount': float(booking.total_amount),
                'payment_method': payment_method,
                'requires_payment': True,
                'warnings': _conflict_summary(date, time_slot, booking.time)['warnings'],
                'invitation_status': invitation_result,
            }, status=status.HTTP_201_CREATED)
        else:
            booking.payment_status = 'paid'
            booking.save()
            _record_booking_history(
                booking,
                from_status='pending',
                to_status='payment_submitted',
                actor=request.user,
                reason='Booking marked as paid at creation.',
                metadata={'payment_status': booking.payment_status, 'payment_method': payment_method},
            )
            reference_number = f"PAY-{uuid.uuid4().hex[:12].upper()}"
            client_name = f"{request.user.first_name} {request.user.last_name}"
            Payment.objects.create(
                booking=booking,
                event_id=booking.id,
                event_name=booking.event_type,
                client_name=client_name,
                payment_method=payment_method,
                reference_number=reference_number,
                amount=booking.total_amount
            )
            return Response({
                'message': 'Booking created successfully',
                'booking_id': booking.id,
                'total_amount': float(booking.total_amount),
                'reference_number': reference_number,
                'requires_payment': False,
                'warnings': _conflict_summary(date, time_slot, booking.time)['warnings'],
                'invitation_status': invitation_result,
            }, status=status.HTTP_201_CREATED)
    except Exception as e:
        logger.exception('create_booking error: %s', e)
        return Response({'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def update_booking_status(request, booking_id):
    if not request.user.is_organizer:
        return Response({'message': 'Only organizers can update booking status'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        booking = Booking.objects.get(id=booking_id)
        new_status = request.data.get('status')
        decline_reason = _template_reason(
            request.data.get('reason_template', '').strip(),
            request.data.get('decline_reason', '').strip(),
            DECLINE_REASON_TEMPLATES,
        )
        
        if new_status not in ['confirmed', 'declined']:
            return Response({'message': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)

        if (
            new_status == 'confirmed'
            and booking.payment_method == 'GCash'
            and booking.payment_status != 'paid'
        ):
            return Response(
                {'message': 'Review and approve the GCash proof of payment first before accepting this booking.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        
        if new_status == 'declined' and not decline_reason:
            return Response({'message': 'Please provide a reason for declining.'}, status=status.HTTP_400_BAD_REQUEST)

        previous_status = booking.status
        booking.status = new_status
        if new_status == 'confirmed' and previous_status != 'confirmed':
            booking.accepted_at = timezone.now()
        if new_status == 'declined':
            booking.decline_reason = decline_reason
        booking.save()
        _record_booking_history(
            booking,
            from_status=previous_status,
            to_status=new_status,
            actor=request.user,
            reason=decline_reason if new_status == 'declined' else 'Booking confirmed by organizer.',
            metadata={'payment_status': booking.payment_status},
        )

        # Create in-app notification for the client
        if new_status == 'confirmed':
            notif_msg = f'Your {booking.event_type} booking on {booking.date} has been confirmed!'
            Notification.objects.create(user=booking.user, message=notif_msg)
            send_ws_notification(booking.user.id, notif_msg, notif_type='booking_confirmed')
        elif new_status == 'declined':
            notif_msg = f'Your {booking.event_type} booking on {booking.date} was declined. Reason: {decline_reason}'
            Notification.objects.create(user=booking.user, message=notif_msg)
            send_ws_notification(booking.user.id, notif_msg, notif_type='booking_declined')

        # Send confirmation email to client (async - non-blocking)
        if new_status == 'confirmed':
            send_booking_status_email(booking.user.email, booking.user.first_name, booking, 'confirmed')
            invitation_result = _send_invitation_emails(booking, confirmed=True)
            return Response({
                'message': f'Booking {new_status} successfully',
                'invitation_status': invitation_result,
            })
        elif new_status == 'declined':
            send_booking_status_email(booking.user.email, booking.user.first_name, booking, 'declined', decline_reason)

        return Response({'message': f'Booking {new_status} successfully'})
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_notifications(request):
    notifs = Notification.objects.filter(user=request.user)
    unread = notifs.filter(is_read=False).count()
    return Response({
        'notifications': [{
            'id': n.id,
            'message': n.message,
            'is_read': n.is_read,
            'created_at': n.created_at.isoformat(),
        } for n in notifs],
        'unread_count': unread,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_notifications_read(request):
    Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
    return Response({'message': 'All notifications marked as read'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def clear_notifications(request):
    Notification.objects.filter(user=request.user).delete()
    return Response({'message': 'Notifications cleared'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def cancel_booking(request, booking_id):
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)

        if booking.status == 'confirmed':
            return Response({'message': 'Cannot cancel confirmed bookings. Please contact organizer.'}, status=status.HTTP_400_BAD_REQUEST)

        cancel_reason = request.data.get('reason', '').strip() if request.data else ''
        cancel_reason = _template_reason(
            request.data.get('reason_template', '').strip() if request.data else '',
            cancel_reason,
            CANCEL_REASON_TEMPLATES,
        )
        event_type = booking.event_type
        date = booking.date

        previous_status = booking.status
        booking.status = 'cancelled'
        booking.cancel_reason = cancel_reason
        booking.decline_reason = f'Cancelled by client{(": " + cancel_reason) if cancel_reason else "."}'
        booking.save()
        _record_booking_history(
            booking,
            from_status=previous_status,
            to_status='cancelled',
            actor=request.user,
            reason=cancel_reason or 'Booking cancelled by client.',
            metadata={'payment_status': booking.payment_status},
        )

        # Notify organizers
        organizers = User.objects.filter(is_organizer=True, is_active=True)
        for org in organizers:
            org_msg = f'{request.user.first_name} {request.user.last_name} cancelled their {event_type} booking on {date}.'
            Notification.objects.create(user=org, message=org_msg)
            send_ws_notification(org.id, org_msg, notif_type='booking_cancelled')

        send_cancellation_email(request.user.email, request.user.first_name, event_type, date, cancel_reason)

        return Response({'message': 'Booking cancelled successfully'})
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_booking(request, booking_id):
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
        
        if booking.status == 'confirmed':
            return Response({'message': 'Cannot modify confirmed bookings'}, status=status.HTTP_400_BAD_REQUEST)
        
        data = request.data
        new_date = data.get('date')
        new_time = data.get('time')
        new_time_slot = data.get('time_slot') or booking.time_slot
        if new_time_slot not in ['morning', 'afternoon', 'whole_day']:
            new_time_slot = booking.time_slot

        if new_date:
            try:
                parsed_new_date = datetime.strptime(str(new_date), '%Y-%m-%d').date()
            except (TypeError, ValueError):
                return Response({'message': 'Invalid event date'}, status=status.HTTP_400_BAD_REQUEST)
            if parsed_new_date < timezone.localdate():
                return Response({'message': 'You cannot move a booking to a past date'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check availability for new date if date is changed
        if new_date and new_date != str(booking.date):
            existing_bookings = _active_booking_queryset().filter(date=new_date).exclude(id=booking_id).count()
            if existing_bookings >= 5:
                return Response({'message': 'New date is fully booked'}, status=status.HTTP_400_BAD_REQUEST)
            booking.date = new_date

        duplicate_booking = _duplicate_booking_queryset(
            request.user,
            new_date or booking.date,
            new_time_slot,
            booking_time=new_time or booking.time,
            exclude_booking_id=booking_id,
        ).order_by('-created_at').first()
        if duplicate_booking:
            return Response(
                {
                    'message': 'You already have a booking request for the same date and time slot.',
                    'duplicate_booking': {
                        'booking_id': duplicate_booking.id,
                        'status': duplicate_booking.status,
                        'payment_status': duplicate_booking.payment_status,
                    },
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if new_time:
            booking.time = new_time
        booking.time_slot = new_time_slot
        booking.save()
        return Response({
            'message': 'Booking updated successfully',
            'warnings': _conflict_summary(booking.date, booking.time_slot, booking.time, exclude_booking_id=booking.id)['warnings'],
        })
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def process_payment(request, booking_id):
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
        
        if booking.payment_status == 'paid':
            return Response({'message': 'Payment already completed'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Simulate payment processing
        payment_method = request.data.get('payment_method')
        
        if not payment_method:
            return Response({'message': 'Payment method required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # In real implementation, integrate with Stripe/PayPal here
        previous_payment_status = booking.payment_status
        booking.payment_status = 'paid'
        booking.save()
        _record_booking_history(
            booking,
            from_status=previous_payment_status or booking.status,
            to_status='payment_confirmed',
            actor=request.user,
            reason='Payment processed from the client payment flow.',
            metadata={'payment_status': booking.payment_status, 'payment_method': payment_method},
        )
        
        return Response({
            'message': 'Payment successful',
            'booking_id': booking.id,
            'amount_paid': float(booking.total_amount),
            'payment_method': payment_method
        })
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_booking_payment_method(request, booking_id):
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

    if booking.payment_status == 'paid':
        return Response({'message': 'Paid bookings can no longer change payment method.'}, status=status.HTTP_400_BAD_REQUEST)

    payment_method = (request.data.get('payment_method') or '').strip()
    if payment_method not in ['Cash', 'GCash', 'QRPh']:
        return Response({'message': 'Invalid payment method'}, status=status.HTTP_400_BAD_REQUEST)

    previous_payment_method = booking.payment_method
    previous_payment_status = booking.payment_status
    booking.payment_method = payment_method

    if payment_method == 'Cash':
        booking.payment_status = 'paid'
        if not Payment.objects.filter(booking=booking).exists():
            Payment.objects.create(
                booking=booking,
                event_id=booking.id,
                event_name=booking.event_type,
                client_name=f'{booking.user.first_name} {booking.user.last_name}',
                payment_method='Cash',
                reference_number=f"PAY-{uuid.uuid4().hex[:12].upper()}",
                amount=booking.total_amount,
            )
    else:
        booking.payment_status = 'pending'
        booking.payment_proof = None
        booking.gcash_reference = ''

    update_fields = ['payment_method', 'payment_status', 'payment_proof', 'gcash_reference']
    if payment_method == 'Cash':
        update_fields = ['payment_method', 'payment_status']
    booking.save(update_fields=update_fields)

    _record_booking_history(
        booking,
        from_status=previous_payment_status or booking.status,
        to_status='payment_method_changed',
        actor=request.user,
        reason=f'Payment method changed from {previous_payment_method or "N/A"} to {payment_method}.',
        metadata={'payment_status': booking.payment_status, 'payment_method': booking.payment_method},
    )

    return Response({
        'message': 'Payment method updated successfully.',
        'payment_method': booking.payment_method,
        'payment_status': booking.payment_status,
        'total_amount': float(booking.total_amount),
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def change_password(request):
    user = request.user
    current_password = request.data.get('current_password')
    new_password = request.data.get('new_password')
    
    if not user.check_password(current_password):
        return Response({'message': 'Current password is incorrect'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        validate_password(new_password, user)
    except ValidationError as e:
        return Response({'message': ' '.join(e.messages)}, status=status.HTTP_400_BAD_REQUEST)
    user.set_password(new_password)
    user.save()
    return Response({'message': 'Password changed successfully'})

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_profile(request):
    user = request.user
    photo_url = None
    if user.profile_photo:
        photo_url = request.build_absolute_uri(user.profile_photo.url)
    return Response({
        'id': user.id,
        'email': user.email,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'address': user.address,
        'preferred_payment_method': user.preferred_payment_method,
        'profile_photo': photo_url,
        'is_superuser': user.is_superuser,
        'is_staff': user.is_staff,
        'is_organizer': user.is_organizer,
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_profile_photo(request):
    photo = request.FILES.get('photo')
    if not photo:
        return Response({'message': 'No photo provided'}, status=status.HTTP_400_BAD_REQUEST)
    request.user.profile_photo = photo
    request.user.save()
    photo_url = request.build_absolute_uri(request.user.profile_photo.url)
    return Response({'message': 'Photo updated', 'profile_photo': photo_url})

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_profile(request):
    user = request.user
    first_name = request.data.get('first_name')
    last_name = request.data.get('last_name')
    address = request.data.get('address', '')
    
    if not first_name or not last_name:
        return Response({'message': 'First name and last name are required'}, status=status.HTTP_400_BAD_REQUEST)
    
    user.first_name = first_name
    user.last_name = last_name
    user.address = address
    user.save()
    
    return Response({
        'message': 'Profile updated successfully',
        'first_name': user.first_name,
        'last_name': user.last_name,
        'address': user.address
    })

@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def update_payment_preference(request):
    user = request.user
    payment_method = request.data.get('payment_method')
    
    if payment_method not in ['Cash', 'GCash', 'QRPh']:
        return Response({'message': 'Invalid payment method'}, status=status.HTTP_400_BAD_REQUEST)
    
    user.preferred_payment_method = payment_method
    user.save()
    
    return Response({
        'message': 'Payment preference updated successfully',
        'preferred_payment_method': user.preferred_payment_method
    })

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def initiate_gcash_payment(request):
    """Legacy manual GCash payment initiation."""
    booking_id = request.data.get('booking_id')
    if not booking_id:
        return Response({'message': 'Booking ID is required'}, status=status.HTTP_400_BAD_REQUEST)
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
        if booking.payment_status == 'paid':
            return Response({'message': 'Booking already paid'}, status=status.HTTP_400_BAD_REQUEST)
        booking.payment_method = 'GCash'
        previous_payment_status = booking.payment_status
        booking.payment_status = 'pending'
        booking.save()
        _record_booking_history(
            booking,
            from_status=previous_payment_status or booking.status,
            to_status='payment_submitted',
            actor=request.user,
            reason='GCash payment initiated.',
            metadata={'payment_status': booking.payment_status},
        )
        return Response({
            'success': True,
            'gcash_number': getattr(settings, 'GCASH_RECEIVER_NUMBER', '09939261681'),
            'gcash_name': getattr(settings, 'GCASH_RECEIVER_NAME', 'Liberato Villarojo'),
            'amount': float(booking.total_amount),
            'booking_id': booking.id,
        })
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _mark_booking_paid_from_paymongo(booking, reference_number, payment_method, actor=None, history_reason='PayMongo marked the payment as paid.'):
    previous_payment_status = booking.payment_status
    booking.payment_status = 'paid'
    booking.payment_method = payment_method or booking.payment_method
    booking.save(update_fields=['payment_status', 'payment_method'])
    _record_booking_history(
        booking,
        from_status=previous_payment_status or booking.status,
        to_status='payment_confirmed',
        actor=actor,
        reason=history_reason,
        metadata={'payment_status': booking.payment_status, 'payment_method': booking.payment_method},
    )

    Payment.objects.get_or_create(
        booking=booking,
        defaults={
            'event_id': booking.id,
            'event_name': booking.event_type,
            'client_name': f'{booking.user.first_name} {booking.user.last_name}',
            'payment_method': booking.payment_method,
            'reference_number': reference_number,
            'amount': booking.total_amount,
        }
    )

    client_msg = f'Your {booking.payment_method} payment for {booking.event_type} booking on {booking.date} has been confirmed!'
    Notification.objects.create(user=booking.user, message=client_msg)
    send_ws_notification(booking.user.id, client_msg, notif_type='payment_confirmed')

    organizers = User.objects.filter(is_organizer=True, is_active=True)
    for org in organizers:
        org_msg = (
            f'{booking.payment_method} payment received via PayMongo for {booking.event_type} '
            f'booking (#{booking.id}) by {booking.user.first_name} {booking.user.last_name}. '
            f'Amount: ₱{booking.total_amount}'
        )
        Notification.objects.create(user=org, message=org_msg)
        send_ws_notification(org.id, org_msg, notif_type='payment_confirmed')

    send_payment_confirmed_email(booking.user.email, booking.user.first_name, booking, reference_number)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_paymongo_gcash(request):
    import requests as http
    import base64

    booking_id = request.data.get('booking_id')
    if not booking_id:
        return Response({'message': 'booking_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        amount_cents = int(float(str(booking.total_amount)) * 100)
        secret_key = getattr(settings, 'PAYMONGO_SECRET_KEY', '')
        credentials = base64.b64encode(f'{secret_key}:'.encode()).decode()

        resp = http.post(
            'https://api.paymongo.com/v1/sources',
            json={
                'data': {
                    'attributes': {
                        'amount': amount_cents,
                        'currency': 'PHP',
                        'type': 'gcash',
                        'redirect': {
                            'success': f'{settings.FRONTEND_URL}/payment-success?id={booking.id}&method=gcash',
                            'failed': f'{settings.FRONTEND_URL}/payment?id={booking.id}&amount={booking.total_amount}&method=gcash&failed=1',
                        },
                    }
                }
            },
            headers={
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )

        if not resp.ok:
            return Response({'message': resp.text}, status=status.HTTP_400_BAD_REQUEST)

        data = resp.json()
        source = data['data']
        checkout_url = source['attributes']['redirect']['checkout_url']

        previous_payment_status = booking.payment_status
        booking.gcash_reference = source['id']
        booking.payment_status = 'pending'
        booking.save(update_fields=['gcash_reference', 'payment_status'])
        _record_booking_history(
            booking,
            from_status=previous_payment_status or booking.status,
            to_status='payment_submitted',
            actor=request.user,
            reason='PayMongo GCash checkout created.',
            metadata={'payment_status': booking.payment_status, 'gcash_reference': booking.gcash_reference},
        )

        return Response({'checkout_url': checkout_url, 'source_id': source['id']})

    except Exception as e:
        logger.error('create_paymongo_gcash: %s', e)
        return Response({'message': 'Payment initiation failed. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def create_paymongo_qrph(request):
    import requests as http
    import base64

    booking_id = request.data.get('booking_id')
    if not booking_id:
        return Response({'message': 'booking_id is required'}, status=status.HTTP_400_BAD_REQUEST)

    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

    try:
        amount_cents = int(float(str(booking.total_amount)) * 100)
        secret_key = getattr(settings, 'PAYMONGO_SECRET_KEY', '')
        credentials = base64.b64encode(f'{secret_key}:'.encode()).decode()

        resp = http.post(
            'https://api.paymongo.com/v1/checkout_sessions',
            json={
                'data': {
                    'attributes': {
                        'billing': {
                            'name': f'{request.user.first_name} {request.user.last_name}'.strip() or request.user.email,
                            'email': request.user.email,
                        },
                        'send_email_receipt': False,
                        'show_description': True,
                        'show_line_items': True,
                        'description': f'EventPro Booking #{booking.id} - {booking.event_type}',
                        'line_items': [
                            {
                                'currency': 'PHP',
                                'amount': amount_cents,
                                'name': booking.event_type,
                                'quantity': 1,
                                'description': f'EventPro venue booking #{booking.id}',
                            }
                        ],
                        'payment_method_types': ['qrph'],
                        'success_url': f'{settings.FRONTEND_URL}/payment-success?id={booking.id}&method=qrph',
                        'cancel_url': f'{settings.FRONTEND_URL}/payment?id={booking.id}&amount={booking.total_amount}&method=qrph&failed=1',
                        'metadata': {
                            'booking_id': str(booking.id),
                            'payment_method': 'QRPh',
                        },
                    }
                }
            },
            headers={
                'Authorization': f'Basic {credentials}',
                'Content-Type': 'application/json',
            },
            timeout=15,
        )

        if not resp.ok:
            return Response({'message': resp.text}, status=status.HTTP_400_BAD_REQUEST)

        data = resp.json()
        checkout_session = data['data']
        checkout_url = checkout_session['attributes']['checkout_url']

        previous_payment_status = booking.payment_status
        booking.payment_method = 'QRPh'
        booking.gcash_reference = checkout_session['id']
        booking.payment_status = 'pending'
        booking.save(update_fields=['payment_method', 'gcash_reference', 'payment_status'])
        _record_booking_history(
            booking,
            from_status=previous_payment_status or booking.status,
            to_status='payment_submitted',
            actor=request.user,
            reason='PayMongo QR Ph checkout created.',
            metadata={'payment_status': booking.payment_status, 'payment_method': booking.payment_method, 'checkout_session_id': booking.gcash_reference},
        )

        return Response({'checkout_url': checkout_url, 'checkout_session_id': checkout_session['id']})

    except Exception as e:
        logger.error('create_paymongo_qrph: %s', e)
        return Response({'message': 'QR payment initiation failed. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@csrf_exempt
def paymongo_webhook(request):
    """PayMongo sends a POST here when a source becomes chargeable."""
    import requests as http
    try:
        event = request.data
        event_type = event.get('data', {}).get('attributes', {}).get('type', '')
        payload_data = event.get('data', {}).get('attributes', {}).get('data', {})

        if event_type in ['checkout_session.payment.paid', 'payment.paid']:
            booking = None
            reference_number = None
            payment_method = 'QRPh'

            if event_type == 'checkout_session.payment.paid':
                session_attrs = payload_data.get('attributes', {})
                metadata = session_attrs.get('metadata', {}) or {}
                booking_id = metadata.get('booking_id')
                if booking_id:
                    booking = Booking.objects.filter(id=booking_id).first()
                payment_entries = session_attrs.get('payments') or []
                if payment_entries:
                    payment_payload = payment_entries[0]
                    payment_attrs = payment_payload.get('attributes', {})
                    reference_number = payment_payload.get('id') or payload_data.get('id')
                    if not booking:
                        payment_intent_id = payment_attrs.get('payment_intent_id')
                        if payment_intent_id:
                            booking = Booking.objects.filter(gcash_reference=payment_intent_id).first()
                payment_method = metadata.get('payment_method') or (booking.payment_method if booking else 'QRPh')
            elif event_type == 'payment.paid':
                payment_attrs = payload_data.get('attributes', {})
                metadata = payment_attrs.get('metadata', {}) or {}
                payment_intent_id = payment_attrs.get('payment_intent_id')
                booking_id = metadata.get('booking_id')
                if booking_id:
                    booking = Booking.objects.filter(id=booking_id).first()
                if not booking and payment_intent_id:
                    booking = Booking.objects.filter(gcash_reference=payment_intent_id).first()
                reference_number = payload_data.get('id') or payment_intent_id
                payment_method = metadata.get('payment_method') or (booking.payment_method if booking else 'QRPh')

            if booking and reference_number and booking.payment_status != 'paid':
                _mark_booking_paid_from_paymongo(
                    booking,
                    reference_number=reference_number,
                    payment_method=payment_method,
                    history_reason='PayMongo webhook marked the payment as paid.',
                )
            return Response({'received': True})

        if event_type != 'source.chargeable':
            return Response({'received': True})

        source_id = payload_data.get('id')
        amount_cents = payload_data.get('attributes', {}).get('amount')

        try:
            booking = Booking.objects.get(gcash_reference=source_id)
        except Booking.DoesNotExist:
            return Response({'received': True})

        secret_key = getattr(settings, 'PAYMONGO_SECRET_KEY', '')
        # Create a payment to capture the charge
        resp = http.post(
            'https://api.paymongo.com/v1/payments',
            json={
                'data': {
                    'attributes': {
                        'amount': amount_cents,
                        'currency': 'PHP',
                        'source': {'id': source_id, 'type': 'source'},
                        'description': f'EventPro Booking #{booking.id} - {booking.event_type}',
                    }
                }
            },
            auth=(secret_key, ''),
            timeout=15,
        )
        resp.raise_for_status()
        payment = resp.json()['data']

        if payment['attributes']['status'] == 'paid':
            _mark_booking_paid_from_paymongo(
                booking,
                reference_number=payment['id'],
                payment_method='GCash',
                history_reason='PayMongo webhook marked the payment as paid.',
            )

        return Response({'received': True})
    except Exception as e:
        logger.error('paymongo_webhook error: %s', e)
        return Response({'received': True})


@api_view(['POST'])
@csrf_exempt
def gcash_payment_notify(request):
    return Response({'received': True})

@api_view(['POST'])
@permission_classes([IsAuthenticated])
def upload_payment_proof(request, booking_id):
    """Upload GCash payment proof"""
    try:
        booking = Booking.objects.get(id=booking_id, user=request.user)

        if booking.payment_method != 'GCash':
            return Response({'message': 'Manual payment proof is only available for GCash bookings.'}, status=status.HTTP_400_BAD_REQUEST)

        if booking.status in ['declined', 'cancelled']:
            return Response({'message': 'You cannot upload payment proof for a declined or cancelled booking.'}, status=status.HTTP_400_BAD_REQUEST)
        
        payment_proof = request.FILES.get('payment_proof')
        gcash_reference = request.data.get('gcash_reference', '')
        
        if not payment_proof:
            return Response({'message': 'Payment proof image is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not gcash_reference or gcash_reference.strip() == '':
            return Response({'message': 'GCash Reference Number is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if fields exist before setting
        try:
            booking.payment_proof = payment_proof
            booking.gcash_reference = gcash_reference.strip()
        except AttributeError:
            return Response({
                'message': 'Database not updated. Please run: setup_gcash_manual.bat',
                'error': 'Missing payment_proof fields in database'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        previous_payment_status = booking.payment_status
        booking.payment_status = 'paid' if previous_payment_status == 'paid' else 'pending_verification'
        booking.save()
        _record_booking_history(
            booking,
            from_status=previous_payment_status or booking.status,
            to_status='payment_submitted',
            actor=request.user,
            reason='Payment proof uploaded for organizer verification.',
            metadata={
                'payment_status': booking.payment_status,
                'gcash_reference': booking.gcash_reference,
                'paymongo_paid': previous_payment_status == 'paid',
            },
        )

        # Notify organizers about payment proof
        organizers = User.objects.filter(is_organizer=True, is_active=True)
        for org in organizers:
            proof_msg = f'Payment proof submitted for {booking.event_type} booking (#{booking.id}) by {booking.user.first_name} {booking.user.last_name}'
            Notification.objects.create(user=org, message=proof_msg)
            send_ws_notification(org.id, proof_msg, notif_type='payment_proof')

        return Response({
            'message': 'Payment proof uploaded successfully.'
            if previous_payment_status == 'paid'
            else 'Payment proof uploaded successfully. Waiting for organizer verification.',
            'booking_id': booking.id
        })
        
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    except Exception as e:
        return Response({'message': str(e), 'error': 'upload_failed'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def check_guest_review_eligibility(request):
    """Check if the logged-in user was an invited guest in any confirmed past booking."""
    from datetime import date as date_today
    today = date_today.today()
    guest_booking = Booking.objects.filter(
        status='confirmed',
        date__lte=today,
        invited_emails__icontains=request.user.email,
    ).first()
    if not guest_booking:
        return Response({'eligible': False})
    already_reviewed = Review.objects.filter(user=request.user, booking=guest_booking).exists()
    return Response({
        'eligible': not already_reviewed,
        'already_reviewed': already_reviewed,
        'event_type': guest_booking.event_type,
        'event_date': str(guest_booking.date),
    })


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def submit_review(request):
    user = request.user
    if user.is_organizer:
        return Response({'message': 'Organizers cannot submit reviews'}, status=status.HTTP_403_FORBIDDEN)

    rating = request.data.get('rating')
    comment = request.data.get('comment', '')
    booking_id = request.data.get('booking_id')

    if not rating or int(rating) not in range(1, 6):
        return Response({'message': 'Rating must be between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)

    from datetime import date as date_today
    today = date_today.today()

    # Check if user is the booking owner
    if booking_id:
        try:
            booking = Booking.objects.get(id=booking_id, user=user, status='confirmed')
            if booking.date > today:
                return Response({'message': "You can't leave a review yet — the event date hasn't happened yet."}, status=status.HTTP_403_FORBIDDEN)
            if Review.objects.filter(user=user, booking=booking).exists():
                return Response({'message': 'You already reviewed this booking.'}, status=status.HTTP_400_BAD_REQUEST)
            review = Review.objects.create(user=user, booking=booking, rating=int(rating), comment=comment)
            return Response({'message': 'Review submitted successfully!', 'id': review.id}, status=status.HTTP_201_CREATED)
        except Booking.DoesNotExist:
            pass  # fall through to guest check

    # Check if user was an invited guest in any confirmed past booking
    guest_booking = Booking.objects.filter(
        status='confirmed',
        date__lte=today,
        invited_emails__icontains=user.email,
    ).first()

    if not guest_booking:
        return Response({'message': 'You must have attended an event to leave a review.'}, status=status.HTTP_403_FORBIDDEN)

    if Review.objects.filter(user=user, booking=guest_booking).exists():
        return Response({'message': 'You already reviewed this event.'}, status=status.HTTP_400_BAD_REQUEST)

    review = Review.objects.create(user=user, booking=guest_booking, rating=int(rating), comment=comment)
    return Response({'message': 'Review submitted successfully!', 'id': review.id}, status=status.HTTP_201_CREATED)


@api_view(['GET'])
def get_reviews(request):
    reviews = Review.objects.select_related('user', 'booking').prefetch_related('replies__user').all()
    data = []
    for r in reviews:
        replies = [{
            'id': rp.id,
            'user_id': rp.user.id,
            'user': f"{rp.user.first_name} {rp.user.last_name}",
            'is_organizer': rp.user.is_organizer,
            'comment': rp.comment,
            'created_at': rp.created_at.isoformat(),
        } for rp in r.replies.all()]
        data.append({
            'id': r.id,
            'user': f"{r.user.first_name} {r.user.last_name}",
            'rating': r.rating,
            'comment': r.comment,
            'event_type': r.booking.event_type if r.booking else None,
            'created_at': r.created_at.isoformat(),
            'replies': replies,
        })
    return Response(data)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reply_to_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id)
    except Review.DoesNotExist:
        return Response({'message': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)

    comment = request.data.get('comment', '').strip()
    if not comment:
        return Response({'message': 'Reply cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)

    reply = ReviewReply.objects.create(review=review, user=request.user, comment=comment)

    # Notify everyone involved in this review thread (except the replier)
    replier_name = f"{request.user.first_name} {request.user.last_name}"

    notified_ids = set()

    # Notify the review author
    if review.user and review.user.id != request.user.id:
        msg = f'{replier_name} replied to your review: "{comment[:60]}"'
        Notification.objects.create(user=review.user, message=msg)
        send_ws_notification(review.user.id, msg, notif_type='review_reply')
        notified_ids.add(review.user.id)

    # Notify other repliers in the thread
    other_replier_ids = (
        ReviewReply.objects.filter(review=review)
        .exclude(user=request.user)
        .exclude(user_id__in=notified_ids)
        .values_list('user_id', flat=True)
        .distinct()
    )
    for uid in other_replier_ids:
        try:
            other_user = User.objects.get(id=uid)
            msg = f'{replier_name} also replied on a review you commented on: "{comment[:60]}"'
            Notification.objects.create(user=other_user, message=msg)
            send_ws_notification(uid, msg, notif_type='review_reply')
        except User.DoesNotExist:
            pass

    return Response({
        'id': reply.id,
        'user_id': request.user.id,
        'user': f"{request.user.first_name} {request.user.last_name}",
        'is_organizer': request.user.is_organizer,
        'comment': reply.comment,
        'created_at': reply.created_at.isoformat(),
    }, status=status.HTTP_201_CREATED)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def edit_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id, user=request.user)
    except Review.DoesNotExist:
        return Response({'message': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)

    comment = request.data.get('comment', '').strip()
    rating = request.data.get('rating')

    if rating is not None:
        if int(rating) not in range(1, 6):
            return Response({'message': 'Rating must be between 1 and 5'}, status=status.HTTP_400_BAD_REQUEST)
        review.rating = int(rating)
    if comment is not None:
        review.comment = comment
    review.save()
    return Response({'message': 'Review updated', 'comment': review.comment, 'rating': review.rating})


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def edit_reply(request, reply_id):
    try:
        reply = ReviewReply.objects.get(id=reply_id)
    except ReviewReply.DoesNotExist:
        return Response({'message': 'Reply not found'}, status=status.HTTP_404_NOT_FOUND)

    if reply.user != request.user:
        return Response({'message': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)

    comment = request.data.get('comment', '').strip()
    if not comment:
        return Response({'message': 'Reply cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
    reply.comment = comment
    reply.save()
    return Response({'message': 'Reply updated', 'comment': reply.comment})


@api_view(['POST'])
def contact_form(request):
    name = request.data.get('name', '').strip()
    email = request.data.get('email', '').strip()
    subject = request.data.get('subject', '').strip()
    message = request.data.get('message', '').strip()
    if not all([name, email, subject, message]):
        return Response({'message': 'All fields are required'}, status=status.HTTP_400_BAD_REQUEST)

    # Save to database
    user = request.user if request.user.is_authenticated else None
    contact = ContactMessage.objects.create(
        user=user, name=name, email=email, subject=subject, message=message
    )

    try:
        send_html_email(
            subject=f'[EventPro Contact] {subject}',
            html_body=f'<p>From: {name} &lt;{email}&gt;</p><p>{message}</p>',
            recipient_list=['ralph.villarojo@gmail.com'],
            plain_text=f'From: {name} <{email}>\n\n{message}',
        )
        # Auto-reply to sender
        send_html_email(
            subject='We received your message — EventPro',
            html_body=(
                f'<h1 style="color:#fff;font-size:22px;font-weight:900;margin:0 0 8px;">Message Received! ✉️</h1>'
                f'<p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 16px;">Hi <strong style="color:#e2e8f0;">{name}</strong>, thanks for reaching out! We\'ll get back to you within 24 hours.</p>'
                f'<div style="background:rgba(255,255,255,0.04);border-radius:10px;padding:16px;margin:16px 0;">'
                f'<p style="color:#64748b;font-size:12px;margin:0 0 4px;text-transform:uppercase;letter-spacing:1px;">Your message</p>'
                f'<p style="color:#e2e8f0;font-size:14px;margin:0;">{message}</p></div>'
            ),
            recipient_list=[email],
            plain_text=f'Hi {name},\n\nThanks for reaching out! We received your message and will get back to you within 24 hours.\n\n— EventPro Team',
        )
    except OSError as e:
        logger.warning('Contact form email failed: %s', e)
    return Response({'message': 'Message sent successfully!', 'id': contact.id})


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_contact_messages(request):
    if not request.user.is_organizer:
        return Response({'message': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    try:
        contact_msgs = ContactMessage.objects.all()
        data = []
        for m in contact_msgs:
            try:
                data.append({
                    'id': m.id,
                    'name': m.name,
                    'email': m.email,
                    'subject': m.subject,
                    'message': m.message,
                    'reply': m.reply or '',
                    'is_read': m.is_read,
                    'replied_at': m.replied_at.isoformat() if m.replied_at else None,
                    'created_at': m.created_at.isoformat(),
                })
            except Exception as e:
                logger.error('get_contact_messages row error id=%s: %s', m.id, e)
        return Response(data)
    except Exception as e:
        logger.exception('get_contact_messages error: %s', e)
        return Response({'message': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def reply_contact_message(request, message_id):
    if not request.user.is_organizer:
        return Response({'message': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    try:
        contact = ContactMessage.objects.get(id=message_id)
    except ContactMessage.DoesNotExist:
        return Response({'message': 'Message not found'}, status=status.HTTP_404_NOT_FOUND)
    reply_text = request.data.get('reply', '').strip()
    if not reply_text:
        return Response({'message': 'Reply cannot be empty'}, status=status.HTTP_400_BAD_REQUEST)
    contact.reply = reply_text
    contact.is_read = True
    contact.replied_at = timezone.now()
    contact.save()
    send_html_email(
        subject=f'Re: {contact.subject} — EventPro',
        html_body=(
            f'<h1 style="color:#fff;font-size:22px;font-weight:900;margin:0 0 8px;">We replied to your message 💬</h1>'
            f'<p style="color:#94a3b8;font-size:14px;line-height:1.6;margin:0 0 16px;">Hi <strong style="color:#e2e8f0;">{contact.name}</strong>, here is our response to your inquiry.</p>'
            f'<div style="background:rgba(14,165,233,0.08);border:1px solid rgba(14,165,233,0.2);border-radius:10px;padding:16px;margin:16px 0;">'
            f'<p style="color:#64748b;font-size:12px;margin:0 0 6px;text-transform:uppercase;letter-spacing:1px;">Our reply</p>'
            f'<p style="color:#e2e8f0;font-size:14px;margin:0;line-height:1.6;">{reply_text}</p></div>'
        ),
        recipient_list=[contact.email],
        plain_text=f'Hi {contact.name},\n\nOur reply:\n{reply_text}\n\n— EventPro Team',
    )
    return Response({'message': 'Reply sent successfully'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def mark_contact_read(request, message_id):
    if not request.user.is_organizer:
        return Response({'message': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    try:
        contact = ContactMessage.objects.get(id=message_id)
        contact.is_read = True
        contact.save()
        return Response({'message': 'Marked as read'})
    except ContactMessage.DoesNotExist:
        return Response({'message': 'Not found'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_calendar_bookings(request):
    """Return confirmed bookings for a given month for the calendar view."""
    year = request.GET.get('year', datetime.now().year)
    month = request.GET.get('month', datetime.now().month)
    bookings = Booking.objects.filter(
        status='confirmed',
        date__year=year,
        date__month=month,
    ).select_related('user')
    data = [{
        'id': b.id,
        'event_type': b.event_type,
        'date': str(b.date),
        'time': str(b.time) if b.time else None,
        'user': f'{b.user.first_name} {b.user.last_name}',
        'capacity': b.capacity,
        'whole_day': b.whole_day,
    } for b in bookings]
    return Response(data)


@api_view(['GET'])
def test_email(request):
    """Test endpoint to verify the bridge-backed email flow is working."""
    test_to = request.GET.get('to', settings.EMAIL_HOST_USER)
    try:
        send_html_email(
            subject='EventPro Email Test',
            html_body='<p>If you receive this, the EventPro email bridge is working correctly.</p>',
            recipient_list=[test_to],
            plain_text='If you receive this, the EventPro email bridge is working correctly.',
            sync=True,
        )
        return Response({
            'status': 'sent',
            'to': test_to,
            'bridge_url': settings.EMAIL_BRIDGE_URL,
            'has_bridge_secret': bool(settings.EMAIL_BRIDGE_SECRET),
        })
    except Exception as e:
        return Response({
            'status': 'failed',
            'error': str(e),
            'bridge_url': settings.EMAIL_BRIDGE_URL,
            'has_bridge_secret': bool(settings.EMAIL_BRIDGE_SECRET),
        }, status=500)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_damages(request):
    if not request.user.is_organizer:
        return Response({'message': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    from .models import DamageReport
    reports = DamageReport.objects.select_related('booking', 'booking__user', 'reported_by').all()
    reports_data = []
    for r in reports:
        photo_url = None
        if r.photo:
            try:
                url = r.photo.url
                photo_url = url if url.startswith('http') else request.build_absolute_uri(url)
            except Exception:
                photo_url = str(r.photo)
        reports_data.append({
            'id': r.id,
            'booking_id': r.booking_id,
            'booking_event_type': r.booking.event_type,
            'booking_date': str(r.booking.date),
            'client_name': f'{r.booking.user.first_name} {r.booking.user.last_name}',
            'item_type': r.item_type,
            'item_name': r.item_name,
            'quantity': r.quantity,
            'estimated_cost': float(r.estimated_cost),
            'recovered_amount': float(r.recovered_amount),
            'net_loss': float(r.estimated_cost - r.recovered_amount),
            'charge_to_client': r.charge_to_client,
            'status': r.status,
            'notes': r.notes,
            'photo': photo_url,
            'reported_by': r.reported_by.get_full_name() if r.reported_by else None,
            'created_at': r.created_at.isoformat(),
            'updated_at': r.updated_at.isoformat(),
        })
    total_damage = sum(float(r.estimated_cost) for r in reports)
    total_recovered = sum(float(r.recovered_amount) for r in reports)
    gross_revenue = float(Booking.objects.filter(payment_status='paid').aggregate(
        total=__import__('django.db.models', fromlist=['Sum']).Sum('total_amount')
    )['total'] or 0)
    summary = {
        'gross_revenue': gross_revenue,
        'total_damage_cost': total_damage,
        'total_recovered': total_recovered,
        'total_net_loss': total_damage - total_recovered,
        'net_profit': gross_revenue - (total_damage - total_recovered),
        'damage_reports_count': reports.count(),
    }
    return Response({'reports': reports_data, 'summary': summary})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def report_damage(request, booking_id):
    if not request.user.is_organizer:
        return Response({'message': 'Not authorized'}, status=status.HTTP_403_FORBIDDEN)
    from .models import DamageReport
    try:
        booking = Booking.objects.get(id=booking_id)
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
    item_type = request.data.get('item_type', 'other')
    item_name = request.data.get('item_name', '').strip()
    quantity = int(request.data.get('quantity', 1))
    estimated_cost = float(request.data.get('estimated_cost', 0))
    recovered_amount = float(request.data.get('recovered_amount', 0))
    charge_to_client = str(request.data.get('charge_to_client', 'false')).lower() == 'true'
    status_val = request.data.get('status', 'reported')
    notes = request.data.get('notes', '').strip()
    photo = request.FILES.get('photo')
    report = DamageReport.objects.create(
        booking=booking,
        reported_by=request.user,
        item_type=item_type,
        item_name=item_name,
        quantity=quantity,
        estimated_cost=estimated_cost,
        recovered_amount=recovered_amount,
        charge_to_client=charge_to_client,
        status=status_val,
        notes=notes,
        photo=photo,
    )
    return Response({'message': 'Damage report saved.', 'id': report.id}, status=status.HTTP_201_CREATED)


@api_view(['DELETE'])
def remove_concert_event_type(request):
    EventType.objects.filter(event_type__icontains='concert').delete()
    return Response({'message': 'Concert event type removed'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_review(request, review_id):
    try:
        review = Review.objects.get(id=review_id, user=request.user)
    except Review.DoesNotExist:
        return Response({'message': 'Review not found'}, status=status.HTTP_404_NOT_FOUND)
    review.delete()
    return Response({'message': 'Review deleted'})


@api_view(['DELETE'])
@permission_classes([IsAuthenticated])
def delete_reply(request, reply_id):
    try:
        reply = ReviewReply.objects.get(id=reply_id)
    except ReviewReply.DoesNotExist:
        return Response({'message': 'Reply not found'}, status=status.HTTP_404_NOT_FOUND)

    if reply.user != request.user:
        return Response({'message': 'Not allowed'}, status=status.HTTP_403_FORBIDDEN)

    reply.delete()
    return Response({'message': 'Reply deleted'})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def verify_payment(request, booking_id):
    """Organizer verifies payment proof"""
    if not request.user.is_organizer:
        return Response({'message': 'Only organizers can verify payments'}, status=status.HTTP_403_FORBIDDEN)
    
    try:
        booking = Booking.objects.get(id=booking_id)
        action = request.data.get('action')
        
        if action == 'approve':
            if booking.payment_method != 'GCash':
                return Response({'message': 'Manual proof verification is only available for GCash bookings.'}, status=status.HTTP_400_BAD_REQUEST)
            if not booking.payment_proof or not booking.gcash_reference:
                return Response({'message': 'Payment proof and GCash reference are required before approval.'}, status=status.HTTP_400_BAD_REQUEST)

            previous_payment_status = booking.payment_status
            booking.payment_status = 'paid'
            booking.save(update_fields=['payment_status'])
            _record_booking_history(
                booking,
                from_status=previous_payment_status or booking.status,
                to_status='payment_confirmed',
                actor=request.user,
                reason='Organizer approved the uploaded payment proof.',
                metadata={'payment_status': booking.payment_status},
            )
            
            client_name = f"{booking.user.first_name} {booking.user.last_name}"

            existing_payment = Payment.objects.filter(booking=booking).first()
            if existing_payment:
                updates = []
                if existing_payment.payment_method != 'GCash':
                    existing_payment.payment_method = 'GCash'
                    updates.append('payment_method')
                if existing_payment.client_name != client_name:
                    existing_payment.client_name = client_name
                    updates.append('client_name')
                if existing_payment.amount != booking.total_amount:
                    existing_payment.amount = booking.total_amount
                    updates.append('amount')
                if updates:
                    existing_payment.save(update_fields=updates)
            else:
                Payment.objects.create(
                    booking=booking,
                    event_id=booking.id,
                    event_name=booking.event_type,
                    client_name=client_name,
                    payment_method='GCash',
                    reference_number=f"PAY-{uuid.uuid4().hex[:12].upper()}",
                    amount=booking.total_amount,
                )

            return Response({'message': 'Payment verified and approved'})
        elif action == 'reject':
            previous_payment_status = booking.payment_status
            booking.payment_status = 'rejected'
            booking.save()
            _record_booking_history(
                booking,
                from_status=previous_payment_status or booking.status,
                to_status='payment_rejected',
                actor=request.user,
                reason='Organizer rejected the uploaded payment proof.',
                metadata={'payment_status': booking.payment_status},
            )
            Notification.objects.create(
                user=booking.user,
                message=f'Your payment proof for {booking.event_type} on {booking.date} was rejected. Please upload a new proof and reference number.',
            )
            send_ws_notification(booking.user.id, 'Your uploaded payment proof was rejected. Please submit a new one.', notif_type='payment_rejected')
            return Response({'message': 'Payment rejected. Client can upload a new proof.'})
        else:
            return Response({'message': 'Invalid action'}, status=status.HTTP_400_BAD_REQUEST)
            
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
