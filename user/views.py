from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from .models import Booking, Payment, EventType, Review, ReviewReply, Notification, ContactMessage
from datetime import datetime, date as date_type, timedelta
from django.core.mail import send_mail
from django.conf import settings
from .email_utils import (
    send_verification_email, send_password_reset_email, send_email_change_verification,
    send_booking_confirmation_email, send_booking_status_email, send_guest_invitation_email,
    send_cancellation_email, send_payment_confirmed_email, send_html_email,
)
from django.utils import timezone
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.views.decorators.csrf import csrf_exempt
import logging
import uuid
import json
import random
import string
import threading

logger = logging.getLogger(__name__)

User = get_user_model()


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

def _check_payment_deadlines():
    from django.utils import timezone
    now = timezone.now()
    overdue = Booking.objects.filter(
        status='pending',
        payment_status__in=['pending', 'rejected'],
        payment_deadline__lt=now,
    )
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

_start_deadline_checker()


def _send_invitation_emails(booking, confirmed=False):
    """Send HTML invitation emails to all guests listed in invited_emails."""
    if not booking.invited_emails:
        return
    emails = [e.strip() for e in booking.invited_emails.replace(';', ',').split(',') if e.strip()]
    if not emails:
        return
    host_name = f'{booking.user.first_name} {booking.user.last_name}'
    for email in emails:
        send_guest_invitation_email(email, host_name, booking, confirmed=confirmed)



@api_view(['GET'])
def get_event_types(request):
    event_types = EventType.objects.filter(is_active=True)
    data = []
    for et in event_types:
        image = None
        if et.image_url:
            image = et.image_url
        elif et.image:
            try:
                image = request.build_absolute_uri(et.image.url)
            except Exception:
                image = None
        data.append({
            'id': et.id,
            'event_type': et.event_type,
            'price': float(et.price),
            'max_capacity': et.max_capacity,
            'max_invited_emails': et.max_invited_emails,
            'people_per_table': et.people_per_table,
            'description': et.description,
            'image': image,
        })
    return Response(data)

@api_view(['POST'])
def register(request):
    try:
        data = request.data
        email = data.get('email', '').strip().lower()

        from django.core.cache import cache

        if User.objects.filter(email=email).exists():
            return Response({'message': 'Email already exists'}, status=status.HTTP_400_BAD_REQUEST)

        code = ''.join(random.choices(string.digits, k=6))

        # Always overwrite any existing pending entry so re-submits always work
        cache.delete(f'pending_reg_{email}')
        cache.set(f'pending_reg_{email}', {
            'email': email,
            'password': data.get('password'),
            'first_name': data.get('first_name'),
            'last_name': data.get('last_name'),
            'date_of_birth': data.get('date_of_birth'),
            'address': data.get('address', ''),
            'code': code,
        }, timeout=900)  # 15 minutes

        try:
            send_verification_email(email, data.get('first_name', ''), code)
        except Exception as mail_err:
            # Email failed but still allow registration — log the code for manual verification
            logger.error('Registration email failed for %s: %s | CODE: %s', email, mail_err, code)
            # Still return success so user can proceed — code is logged in Render logs

        return Response({
            'message': 'Registration successful. Check your email for the verification code.',
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
    email = request.data.get('email')
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

    MAX_SLOTS = 5
    active = Booking.objects.filter(date=date).exclude(status='declined')

    whole_day_count = active.filter(time_slot='whole_day').count()
    morning_count = active.filter(time_slot='morning').count() + whole_day_count
    afternoon_count = active.filter(time_slot='afternoon').count() + whole_day_count

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
def get_bookings(request):
    bookings = Booking.objects.all()
    data = [{
        'id': b.id,
        'user': f"{b.user.first_name} {b.user.last_name}",
        'event_type': b.event_type,
        'capacity': b.capacity,
        'date': b.date,
        'time': b.time,
        'status': b.status,
        'payment_status': b.payment_status,
        'gcash_reference': b.gcash_reference or '',
        'payment_proof': request.build_absolute_uri(b.payment_proof.url) if b.payment_proof else None,
        'payment_method': b.payment_method,
        'total_amount': float(b.total_amount),
        'decline_reason': b.decline_reason or '',
    } for b in bookings]
    return Response(data)

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_my_bookings(request):
    try:
        bookings = Booking.objects.filter(user=request.user)
        data = []
        for b in bookings:
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
                'created_at': b.created_at.isoformat(),
                'event_details': b.event_details,
                'gcash_reference': b.gcash_reference or '',
                'payment_proof': str(b.payment_proof) if b.payment_proof else None,
                'invited_emails': b.invited_emails,
                'whole_day': b.whole_day,
                'special_requests': b.special_requests,
                'decline_reason': b.decline_reason or '',
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

        data = request.data
        date = data.get('date')
        event_type = data.get('event_type')
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

        # Validate invited emails count against event type max
        if invited_emails:
            email_list = [e.strip() for e in invited_emails.replace(';', ',').split(',') if e.strip()]
            try:
                et_obj_check = EventType.objects.get(event_type=event_type, is_active=True)
                if len(email_list) > et_obj_check.max_invited_emails:
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

        MAX_SLOTS = 5
        active = Booking.objects.filter(date=date).exclude(status='declined')
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

        # Validate capacity against EventType max_capacity
        try:
            event_type_obj = EventType.objects.get(event_type=event_type, is_active=True)
            if int(capacity) > event_type_obj.max_capacity:
                return Response({'message': f'Maximum capacity for {event_type} is {event_type_obj.max_capacity} guests.'}, status=status.HTTP_400_BAD_REQUEST)
        except EventType.DoesNotExist:
            if int(capacity) > 100:
                return Response({'message': 'Maximum capacity is 100'}, status=status.HTTP_400_BAD_REQUEST)

        booking = Booking.objects.create(
            user=request.user,
            event_type=event_type,
            description=description,
            capacity=capacity,
            date=date,
            time=data.get('time'),
            location="Ralphy's Venue, Basak San Nicolas Villa Kalubihan Cebu City 6000.",
            invited_emails=invited_emails,
            event_details=event_details,
            special_requests=special_requests,
            whole_day=whole_day,
            time_slot=time_slot,
            status='pending',
            payment_status='paid',
            payment_method=payment_method,
            payment_deadline=timezone.now() + timedelta(days=3),
        )

        # Calculate total amount
        booking.total_amount = booking.calculate_amount()
        booking.save()
        booking.refresh_from_db()  # ensure date/time are proper Python objects

        # Notify all organizers about the new booking via WebSocket
        organizers = User.objects.filter(is_organizer=True, is_active=True)
        for org in organizers:
            org_msg = f'New booking: {event_type} on {date} by {request.user.first_name} {request.user.last_name}'
            Notification.objects.create(user=org, message=org_msg)
            send_ws_notification(org.id, org_msg, notif_type='new_booking')

        # Send booking confirmation email to client (async - non-blocking)
        send_booking_confirmation_email(request.user.email, request.user.first_name, booking)

        # Send invitation emails to guests
        _send_invitation_emails(booking, confirmed=False)

        # Handle payment based on method
        if payment_method == 'GCash':
            booking.payment_status = 'pending'
            booking.save()
            return Response({
                'message': 'Booking created successfully',
                'booking_id': booking.id,
                'total_amount': float(booking.total_amount),
                'payment_method': 'GCash',
                'requires_payment': True
            }, status=status.HTTP_201_CREATED)
        else:
            booking.payment_status = 'paid'
            booking.save()
            reference_number = f"PAY-{uuid.uuid4().hex[:12].upper()}"
            client_name = f"{request.user.first_name} {request.user.last_name}"
            Payment.objects.create(
                booking=booking,
                event_id=booking.id,
                event_name=event_type,
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
                'requires_payment': False
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
        decline_reason = request.data.get('decline_reason', '').strip()
        
        if new_status not in ['confirmed', 'declined']:
            return Response({'message': 'Invalid status'}, status=status.HTTP_400_BAD_REQUEST)
        
        if new_status == 'declined' and not decline_reason:
            return Response({'message': 'Please provide a reason for declining.'}, status=status.HTTP_400_BAD_REQUEST)
        
        booking.status = new_status
        if new_status == 'declined':
            booking.decline_reason = decline_reason
        booking.save()

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
            _send_invitation_emails(booking, confirmed=True)
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
        event_type = booking.event_type
        date = booking.date

        booking.status = 'declined'
        booking.cancel_reason = cancel_reason
        booking.decline_reason = f'Cancelled by client{(": " + cancel_reason) if cancel_reason else "."}'
        booking.save()

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
        
        # Check availability for new date if date is changed
        if new_date and new_date != str(booking.date):
            existing_bookings = Booking.objects.filter(date=new_date).exclude(id=booking_id).count()
            if existing_bookings >= 5:
                return Response({'message': 'New date is fully booked'}, status=status.HTTP_400_BAD_REQUEST)
            booking.date = new_date
        
        if new_time:
            booking.time = new_time
        
        booking.save()
        return Response({'message': 'Booking updated successfully'})
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
        booking.payment_status = 'paid'
        booking.save()
        
        return Response({
            'message': 'Payment successful',
            'booking_id': booking.id,
            'amount_paid': float(booking.total_amount),
            'payment_method': payment_method
        })
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)

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
    
    if payment_method not in ['Cash', 'GCash']:
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
        booking.payment_status = 'pending'
        booking.save()
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
                            'success': f'{settings.FRONTEND_URL}/payment-success?id={booking.id}',
                            'failed': f'{settings.FRONTEND_URL}/payment?id={booking.id}&amount={booking.total_amount}&failed=1',
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

        booking.gcash_reference = source['id']
        booking.payment_status = 'pending'
        booking.save(update_fields=['gcash_reference', 'payment_status'])

        return Response({'checkout_url': checkout_url, 'source_id': source['id']})

    except Exception as e:
        logger.error('create_paymongo_gcash: %s', e)
        return Response({'message': 'Payment initiation failed. Please try again.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


@api_view(['POST'])
@csrf_exempt
def paymongo_webhook(request):
    """PayMongo sends a POST here when a source becomes chargeable."""
    import requests as http
    try:
        event = request.data
        event_type = event.get('data', {}).get('attributes', {}).get('type', '')
        source_data = event.get('data', {}).get('attributes', {}).get('data', {})

        if event_type != 'source.chargeable':
            return Response({'received': True})

        source_id = source_data.get('id')
        amount_cents = source_data.get('attributes', {}).get('amount')

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
        payment_status = payment['attributes']['status']

        if payment_status == 'paid':
            booking.payment_status = 'paid'
            booking.save(update_fields=['payment_status'])
            reference_number = payment['id']
            Payment.objects.get_or_create(
                booking=booking,
                defaults={
                    'event_id': booking.id,
                    'event_name': booking.event_type,
                    'client_name': f'{booking.user.first_name} {booking.user.last_name}',
                    'payment_method': 'GCash',
                    'reference_number': reference_number,
                    'amount': booking.total_amount,
                }
            )
            # Notify client
            client_msg = f'Your GCash payment for {booking.event_type} booking on {booking.date} has been confirmed!'
            Notification.objects.create(user=booking.user, message=client_msg)
            send_ws_notification(booking.user.id, client_msg, notif_type='payment_confirmed')
            # Notify all organizers
            organizers = User.objects.filter(is_organizer=True, is_active=True)
            for org in organizers:
                org_msg = f'GCash payment received via PayMongo for {booking.event_type} booking (#{booking.id}) by {booking.user.first_name} {booking.user.last_name}. Amount: ₱{booking.total_amount}'
                Notification.objects.create(user=org, message=org_msg)
                send_ws_notification(org.id, org_msg, notif_type='payment_confirmed')
            send_payment_confirmed_email(booking.user.email, booking.user.first_name, booking, reference_number)

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
        
        if booking.payment_status == 'paid':
            return Response({'message': 'Payment already confirmed'}, status=status.HTTP_400_BAD_REQUEST)
        
        payment_proof = request.FILES.get('payment_proof')
        gcash_reference = request.data.get('gcash_reference', '')
        
        if not payment_proof:
            return Response({'message': 'Payment proof image is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not gcash_reference or gcash_reference.strip() == '':
            return Response({'message': 'GCash Reference Number is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        if not gcash_reference or gcash_reference.strip() == '':
            return Response({'message': 'GCash Reference Number is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if fields exist before setting
        try:
            booking.payment_proof = payment_proof
            booking.gcash_reference = gcash_reference
        except AttributeError:
            return Response({
                'message': 'Database not updated. Please run: setup_gcash_manual.bat',
                'error': 'Missing payment_proof fields in database'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        
        booking.payment_status = 'pending_verification'
        booking.save()

        # Notify organizers about payment proof
        organizers = User.objects.filter(is_organizer=True, is_active=True)
        for org in organizers:
            proof_msg = f'Payment proof submitted for {booking.event_type} booking (#{booking.id}) by {booking.user.first_name} {booking.user.last_name}'
            Notification.objects.create(user=org, message=proof_msg)
            send_ws_notification(org.id, proof_msg, notif_type='payment_proof')

        return Response({
            'message': 'Payment proof uploaded successfully. Waiting for organizer verification.',
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
    messages = ContactMessage.objects.all()
    return Response([{
        'id': m.id,
        'name': m.name,
        'email': m.email,
        'subject': m.subject,
        'message': m.message,
        'reply': m.reply,
        'is_read': m.is_read,
        'replied_at': m.replied_at.isoformat() if m.replied_at else None,
        'created_at': m.created_at.isoformat(),
    } for m in messages])


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


@api_view(['DELETE'])
def remove_concert_event_type(request):
    """One-time cleanup — remove Concert event type from DB"""
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
            booking.payment_status = 'paid'
            booking.save()
            
            reference_number = booking.gcash_reference or f"PAY-{uuid.uuid4().hex[:12].upper()}"
            client_name = f"{booking.user.first_name} {booking.user.last_name}"
            
            Payment.objects.get_or_create(
                booking=booking,
                defaults={
                    'event_id': booking.id,
                    'event_name': booking.event_type,
                    'client_name': client_name,
                    'payment_method': 'GCash',
                    'reference_number': reference_number,
                    'amount': booking.total_amount
                }
            )
            
            return Response({'message': 'Payment verified and approved'})
        elif action == 'reject':
            booking.payment_status = 'rejected'
            booking.save()
            return Response({'message': 'Payment rejected'})
        else:
            return Response({'message': 'Invalid action'}, status=status.HTTP_400_BAD_REQUEST)
            
    except Booking.DoesNotExist:
        return Response({'message': 'Booking not found'}, status=status.HTTP_404_NOT_FOUND)
