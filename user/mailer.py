"""Reliable email helpers for SpacioGrande."""

import logging
import threading

import requests
from django.conf import settings

logger = logging.getLogger(__name__)
BRAND_NAME = 'SpacioGrande'
BRAND_FOOTER = f'{BRAND_NAME} Team'


class EmailDeliveryError(RuntimeError):
    """Raised when bridge delivery fails."""


def _display_name(value, fallback='there'):
    value = str(value or '').strip()
    return value or fallback


def _bridge_base_url():
    bridge_url = getattr(settings, 'EMAIL_BRIDGE_URL', '').strip().rstrip('/')
    if bridge_url:
        return bridge_url

    frontend_url = getattr(settings, 'FRONTEND_URL', '').strip().rstrip('/')
    if frontend_url:
        return frontend_url

    return ''


def _create_delivery_log(recipient, subject, plain, html_body):
    from .models import EmailDeliveryLog

    return EmailDeliveryLog.objects.create(
        channel='bridge',
        recipient=recipient,
        subject=subject[:255],
        status='pending',
        payload={
            'textBody': plain[:1000],
            'htmlBodyPreview': html_body[:1000],
        },
    )


def _mark_delivery_log(log_entry, status_value, error_message='', provider_message_id=''):
    if not log_entry:
        return
    log_entry.status = status_value
    log_entry.error_message = error_message[:5000]
    if provider_message_id:
        log_entry.provider_message_id = provider_message_id[:255]
    log_entry.save(update_fields=['status', 'error_message', 'provider_message_id', 'updated_at'])


def _send_via_bridge(subject, html_body, plain, recipient):
    bridge_url = _bridge_base_url()
    bridge_secret = getattr(settings, 'EMAIL_BRIDGE_SECRET', '').strip()
    if not bridge_url or not bridge_secret:
        raise EmailDeliveryError('Email bridge is not configured. Set EMAIL_BRIDGE_SECRET and EMAIL_BRIDGE_URL or FRONTEND_URL.')

    try:
        response = requests.post(
            f'{bridge_url}/api/send-email',
            json={
                'recipient': recipient,
                'subject': subject,
                'textBody': plain,
                'htmlBody': html_body,
            },
            headers={'x-email-bridge-secret': bridge_secret},
            timeout=(10, 20),
        )
    except requests.RequestException as exc:
        raise EmailDeliveryError(f'Could not reach email bridge at {bridge_url}: {exc}') from exc
    if response.status_code == 200:
        logger.info('Email sent via bridge to %s', recipient)
        provider_message_id = ''
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if isinstance(payload, dict):
            provider_message_id = str(payload.get('message_id') or payload.get('message') or '')
        return provider_message_id

    detail = response.text.strip()
    try:
        payload = response.json()
    except ValueError:
        payload = {}
    if isinstance(payload, dict):
        detail = str(payload.get('detail') or payload.get('message') or detail)
    raise EmailDeliveryError(f'Bridge failed with status {response.status_code}: {detail or "unknown error"}')


def _send_one(subject, html_body, plain, recipient):
    log_entry = _create_delivery_log(recipient, subject, plain, html_body)
    try:
        provider_message_id = _send_via_bridge(subject, html_body, plain, recipient)
        _mark_delivery_log(log_entry, 'sent', provider_message_id=provider_message_id)
        return
    except Exception as exc:
        logger.error('Bridge delivery failed for %s: %s', recipient, exc)
        _mark_delivery_log(log_entry, 'failed', error_message=str(exc))
        raise EmailDeliveryError(str(exc)) from exc


def send_html_email(subject, html_body, recipient_list, plain_text=None, sync=True, fail_silently=False):
    """Send HTML email through the Nodemailer bridge only."""
    plain = plain_text or 'Please view this email in an HTML-capable client.'
    recipients = [recipient.strip() for recipient in recipient_list if recipient and recipient.strip()]
    if not recipients:
        if fail_silently:
            return False
        raise EmailDeliveryError('No recipients were provided.')

    def _deliver_all():
        errors = []
        for recipient in recipients:
            try:
                _send_one(subject, html_body, plain, recipient)
            except Exception as exc:
                errors.append(f'{recipient}: {exc}')

        if errors and not fail_silently:
            raise EmailDeliveryError(' | '.join(errors))
        return not errors

    if sync:
        return _deliver_all()

    def _run_async():
        try:
            _deliver_all()
        except Exception as exc:
            logger.error('Async email delivery failed for %s: %s', recipients, exc)

    threading.Thread(target=_run_async, daemon=False).start()
    return True


def send_verification_email(email, first_name, code):
    first_name = _display_name(first_name)
    body = (
        _h1('Verify Your Email Address')
        + _p(
            f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, thanks for signing up! '
            'Enter the code below to activate your account.'
        )
        + _code_box(code)
        + _p("If you didn't create an account, you can safely ignore this email.", '#64748b')
    )
    send_html_email(
        subject=f'Your {BRAND_NAME} Verification Code',
        html_body=_wrap(body),
        recipient_list=[email],
        plain_text=(
            f'Hi {first_name},\n\nYour verification code is: {code}\n\n'
            f'Valid for 15 minutes.\n\n{BRAND_FOOTER}'
        ),
        sync=True,
    )


def send_password_reset_email(email, first_name, code):
    first_name = _display_name(first_name)
    body = (
        _h1('Password Reset Request')
        + _p(
            f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, '
            'we received a request to reset your password.'
        )
        + _code_box(code, label='Your Reset Code', valid='Valid for 10 minutes')
        + _p("If you didn't request this, you can safely ignore this email.", '#64748b')
    )
    send_html_email(
        subject=f'Your {BRAND_NAME} Password Reset Code',
        html_body=_wrap(body),
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour password reset code is: {code}\n\n{BRAND_FOOTER}',
        sync=True,
    )


def send_email_change_verification(email, first_name, new_email, code):
    body = (
        _h1('Confirm Email Change')
        + _p(
            f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, you requested to change your '
            f'email to <strong style="color:#0ea5e9;">{new_email}</strong>.'
        )
        + _code_box(code, label='Your Verification Code', valid='Valid for 10 minutes')
        + _p("If you didn't request this, please ignore this email.", '#64748b')
    )
    send_html_email(
        subject=f'Verify Your Email Change - {BRAND_NAME}',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour email change verification code is: {code}\n\n{BRAND_FOOTER}',
        sync=True,
    )


def send_booking_confirmation_email(email, first_name, booking):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    event_time = 'Whole Day' if not booking.time else (
        booking.time.strftime('%I:%M %p') if hasattr(booking.time, 'strftime') else str(booking.time)
    )
    rows = (
        _detail_row('Event', booking.event_type)
        + _detail_row('Date', event_date)
        + _detail_row('Time', event_time)
        + _detail_row('Guests', str(booking.capacity))
        + _detail_row('Venue', booking.location)
        + _detail_row('Amount', f'PHP {float(booking.total_amount):,.2f}')
        + _detail_row('Payment', booking.payment_method)
        + (_detail_row('Special Requests', booking.special_requests) if booking.special_requests else '')
        + _detail_row('Status', _badge('Pending Review', '#f59e0b'))
    )
    body = (
        _h1('Booking Request Received')
        + _p(
            f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, we received your booking request. '
            'Here are the details:'
        )
        + _detail_table(rows)
        + _p(
            "Your booking is <strong>pending organizer review</strong>. You'll receive another email "
            'once it is confirmed.',
            '#94a3b8',
        )
    )
    send_html_email(
        subject=f'Your {BRAND_NAME} Booking Request Received',
        html_body=body,
        recipient_list=[email],
        plain_text=(
            f'Hi {first_name},\n\nBooking received for {booking.event_type} on {event_date}.\n'
            f'Amount: PHP {float(booking.total_amount):,.2f}\n\n{BRAND_FOOTER}'
        ),
        sync=True,
        fail_silently=False,
    )


def send_booking_status_email(email, first_name, booking, new_status, decline_reason=''):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    if new_status == 'confirmed':
        rows = (
            _detail_row('Event', booking.event_type)
            + _detail_row('Date', event_date)
            + _detail_row('Venue', booking.location)
            + _detail_row('Guests', str(booking.capacity))
            + _detail_row('Status', _badge('Confirmed', '#22c55e'))
        )
        body = (
            _h1('Your Booking is Confirmed')
            + _p(
                f'Great news, <strong style="color:#e2e8f0;">{first_name}</strong>. '
                'Your event has been confirmed.'
            )
            + _detail_table(rows)
            + _p('We look forward to making your event special.', '#94a3b8')
        )
        subject = f'Your {BRAND_NAME} Booking is Confirmed'
        plain = f'Hi {first_name},\n\nYour {booking.event_type} booking on {event_date} is confirmed.\n\n{BRAND_FOOTER}'
    else:
        body = (
            _h1('Booking Update')
            + _p(
                f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, unfortunately your booking '
                'could not be confirmed.'
            )
            + _detail_table(
                _detail_row('Event', booking.event_type)
                + _detail_row('Date', event_date)
                + _detail_row('Reason', decline_reason or 'N/A')
                + _detail_row('Status', _badge('Declined', '#ef4444'))
            )
            + _p('Please contact us or try booking a different date.', '#94a3b8')
        )
        subject = f'Update on Your {BRAND_NAME} Booking'
        plain = (
            f'Hi {first_name},\n\nYour {booking.event_type} booking on {event_date} was declined.\n'
            f'Reason: {decline_reason or "N/A"}\n\n{BRAND_FOOTER}'
        )
    send_html_email(
        subject=subject,
        html_body=body,
        recipient_list=[email],
        plain_text=plain,
        sync=True,
        fail_silently=False,
    )


def send_guest_invitation_email(guest_email, host_name, booking, confirmed=False):
    host_name = _display_name(host_name, fallback='Your host')
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    event_time = 'Whole Day' if not booking.time else (
        booking.time.strftime('%I:%M %p') if hasattr(booking.time, 'strftime') else str(booking.time)
    )
    rows = (
        _detail_row('Event', booking.event_type)
        + _detail_row('Host', host_name)
        + _detail_row('Date', event_date)
        + _detail_row('Time', event_time)
        + _detail_row('Venue', booking.location)
    )
    if confirmed:
        body = (
            _h1("You're Invited")
            + _p(
                f'<strong style="color:#e2e8f0;">{host_name}</strong> has invited you to their '
                f'<strong style="color:#0ea5e9;">{booking.event_type}</strong>, and it has been confirmed.'
            )
            + _detail_table(rows)
            + _p('We look forward to seeing you there.', '#94a3b8')
        )
        subject = f"You're Invited: {booking.event_type} on {event_date}"
    else:
        body = (
            _h1("You've Been Invited")
            + _p(
                f'<strong style="color:#e2e8f0;">{host_name}</strong> has invited you to their upcoming '
                f'<strong style="color:#0ea5e9;">{booking.event_type}</strong> event.'
            )
            + _detail_table(rows)
            + _p(
                'Note: This booking is still <strong>pending organizer confirmation</strong>. '
                "You'll receive another email once confirmed.",
                '#94a3b8',
            )
        )
        subject = f"You've Been Invited to {host_name}'s {booking.event_type}"
    send_html_email(
        subject=subject,
        html_body=_wrap(body),
        recipient_list=[guest_email],
        plain_text=(
            f'Hi,\n\n{host_name} invited you to their {booking.event_type} on {event_date} '
            f'at {event_time} in {booking.location}.\n\n{BRAND_FOOTER}'
        ),
        sync=True,
        fail_silently=False,
    )


def send_cancellation_email(email, first_name, event_type, date, cancel_reason=''):
    body = (
        _h1('Booking Cancelled')
        + _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, your booking has been cancelled.')
        + _detail_table(
            _detail_row('Event', event_type)
            + _detail_row('Date', str(date))
            + (_detail_row('Reason', cancel_reason) if cancel_reason else '')
            + _detail_row('Status', _badge('Cancelled', '#ef4444'))
        )
        + _p('If this was a mistake, please create a new booking.', '#94a3b8')
    )
    send_html_email(
        subject=f'Your {BRAND_NAME} Booking Has Been Cancelled',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour {event_type} booking on {date} has been cancelled.\n\n{BRAND_FOOTER}',
        sync=True,
        fail_silently=False,
    )


def send_payment_confirmed_email(email, first_name, booking, reference):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    body = (
        _h1('Payment Confirmed')
        + _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, your GCash payment has been confirmed.')
        + _detail_table(
            _detail_row('Event', booking.event_type)
            + _detail_row('Date', event_date)
            + _detail_row('Amount', f'PHP {float(booking.total_amount):,.2f}')
            + _detail_row('Reference', reference)
            + _detail_row('Status', _badge('Paid', '#22c55e'))
        )
    )
    send_html_email(
        subject=f'{BRAND_NAME} - GCash Payment Confirmed',
        html_body=body,
        recipient_list=[email],
        plain_text=(
            f'Hi {first_name},\n\nPayment of PHP {float(booking.total_amount):,.2f} confirmed. '
            f'Ref: {reference}\n\n{BRAND_FOOTER}'
        ),
        sync=True,
        fail_silently=False,
    )


def send_damage_report_email(email, first_name, booking, report):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    photo_note = 'The owner also attached a photo proof of the damage.' if getattr(report, 'photo', None) else 'No photo proof was attached.'
    body = (
        _h1('Damage Report Filed')
        + _p(
            f'Hi <strong style="color:#e2e8f0;">{_display_name(first_name)}</strong>, '
            'the owner recorded a damage report for your booking.'
        )
        + _detail_table(
            _detail_row('Event', booking.event_type)
            + _detail_row('Date', event_date)
            + _detail_row('Status', _badge(str(report.status).title(), '#ef4444'))
            + _detail_row('Estimated Cost', f'PHP {float(report.estimated_cost):,.2f}')
            + _detail_row('Recovered', f'PHP {float(report.recovered_amount):,.2f}')
            + _detail_row('Charge To Client', 'Yes' if report.charge_to_client else 'No')
        )
        + _p('Open your booking details to review the damaged items list and the uploaded proof image.')
        + _p(photo_note, '#94a3b8')
    )
    send_html_email(
        subject=f'{BRAND_NAME} - Damage Report Added To Your Booking',
        html_body=body,
        recipient_list=[email],
        plain_text=(
            f'Hi {_display_name(first_name)},\n\n'
            f'A damage report was added to your {booking.event_type} booking on {event_date}.\n'
            f'Estimated cost: PHP {float(report.estimated_cost):,.2f}\n'
            f'Charge to client: {"Yes" if report.charge_to_client else "No"}\n\n'
            f'Please open your booking details to review the damaged items and uploaded proof image.\n\n'
            f'{BRAND_FOOTER}'
        ),
        sync=True,
        fail_silently=False,
    )


def _wrap(content):
    return (
        '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'
        'background:#1e293b;color:#e2e8f0;border-radius:12px;overflow:hidden;">'
        '<div style="background:linear-gradient(135deg,#0ea5e9,#6366f1);padding:30px;text-align:center;">'
        f'<h1 style="color:#fff;margin:0;font-size:24px;">{BRAND_NAME}</h1></div>'
        f'<div style="padding:30px;">{content}</div>'
        '<div style="background:#0f172a;padding:20px;text-align:center;color:#64748b;font-size:12px;">'
        f'&copy; 2025 {BRAND_NAME}. All rights reserved.</div></div>'
    )


def _h1(text):
    return f'<h2 style="color:#e2e8f0;margin-bottom:16px;">{text}</h2>'


def _p(text, color='#cbd5e1'):
    return f'<p style="color:{color};line-height:1.6;margin-bottom:16px;">{text}</p>'


def _code_box(code, label='Your Verification Code', valid='Valid for 15 minutes'):
    return (
        '<div style="background:#0f172a;border:2px solid #0ea5e9;border-radius:8px;'
        'padding:20px;text-align:center;margin:20px 0;">'
        f'<p style="color:#94a3b8;margin:0 0 8px;">{label}</p>'
        f'<p style="font-size:36px;font-weight:bold;color:#0ea5e9;letter-spacing:8px;margin:0;">{code}</p>'
        f'<p style="color:#64748b;font-size:12px;margin:8px 0 0;">{valid}</p></div>'
    )


def _badge(text, color):
    return (
        f'<span style="background:{color};color:#fff;padding:3px 10px;'
        f'border-radius:12px;font-size:12px;font-weight:600;">{text}</span>'
    )


def _detail_row(label, value):
    return (
        f'<tr><td style="padding:8px 12px;color:#94a3b8;font-size:14px;width:40%;">{label}</td>'
        f'<td style="padding:8px 12px;color:#e2e8f0;font-size:14px;">{value}</td></tr>'
    )


def _detail_table(rows):
    return (
        '<table style="width:100%;border-collapse:collapse;background:#0f172a;'
        f'border-radius:8px;overflow:hidden;margin:16px 0;">{rows}</table>'
    )
