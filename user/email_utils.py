"""Email helpers for EventPro — sends via Django SMTP."""
import logging
import threading

import requests
from django.conf import settings
from django.core.mail import EmailMultiAlternatives

logger = logging.getLogger(__name__)


def send_html_email(subject, html_body, recipient_list, plain_text=None, sync=False):
    """Send HTML email — tries Nodemailer bridge first, falls back to SMTP."""
    plain = plain_text or 'Please view this email in an HTML-capable client.'
    bridge_url = getattr(settings, 'EMAIL_BRIDGE_URL', '').rstrip('/')
    bridge_secret = getattr(settings, 'EMAIL_BRIDGE_SECRET', '')

    def _send_one(recipient):
        # Try bridge first
        if bridge_url and bridge_secret:
            try:
                import requests as http_req
                resp = http_req.post(
                    f'{bridge_url}/api/send-email',
                    json={'recipient': recipient, 'subject': subject, 'htmlBody': html_body, 'textBody': plain},
                    headers={'x-email-bridge-secret': bridge_secret},
                    timeout=15,
                )
                if resp.status_code == 200:
                    logger.info('Email sent via bridge to %s', recipient)
                    return
                logger.warning('Bridge failed (%s) for %s: %s', resp.status_code, recipient, resp.text)
            except Exception as e:
                logger.warning('Bridge error for %s: %s', recipient, e)
        # Fallback: SMTP
        try:
            from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'EventPro <noreply@eventpro.com>')
            msg = EmailMultiAlternatives(subject, plain, from_email, [recipient])
            msg.attach_alternative(html_body, 'text/html')
            msg.send()
            logger.info('Email sent via SMTP to %s', recipient)
        except Exception as e:
            logger.error('SMTP also failed to %s: %s', recipient, e)

    def _send_all():
        for recipient in recipient_list:
            _send_one(recipient)

    if sync:
        _send_all()
    else:
        threading.Thread(target=_send_all, daemon=True).start()


# ── Email builders ────────────────────────────────────────────────────────────

def send_verification_email(email, first_name, code):
    body = (
        _h1('Verify Your Email Address') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, thanks for signing up! Enter the code below to activate your account.') +
        _code_box(code) +
        _p("If you didn't create an account, you can safely ignore this email.", '#64748b')
    )
    send_html_email(
        subject='Your EventPro Verification Code',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour verification code is: {code}\n\nValid for 15 minutes.\n\n— EventPro Team',
        sync=False,
    )


def send_password_reset_email(email, first_name, code):
    body = (
        _h1('Password Reset Request') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, we received a request to reset your password.') +
        _code_box(code, label='Your Reset Code', valid='Valid for 10 minutes') +
        _p("If you didn't request this, you can safely ignore this email.", '#64748b')
    )
    send_html_email(
        subject='Your EventPro Password Reset Code',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour password reset code is: {code}\n\n— EventPro Team',
        sync=False,
    )


def send_email_change_verification(email, first_name, new_email, code):
    body = (
        _h1('Confirm Email Change') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, you requested to change your email to <strong style="color:#0ea5e9;">{new_email}</strong>.') +
        _code_box(code, label='Your Verification Code', valid='Valid for 10 minutes') +
        _p("If you didn't request this, please ignore this email.", '#64748b')
    )
    send_html_email(
        subject='Verify Your Email Change — EventPro',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour email change verification code is: {code}\n\n— EventPro Team',
        sync=False,
    )


def send_booking_confirmation_email(email, first_name, booking):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    event_time = 'Whole Day' if not booking.time else (booking.time.strftime('%I:%M %p') if hasattr(booking.time, 'strftime') else str(booking.time))
    rows = (
        _detail_row('Event', booking.event_type) +
        _detail_row('Date', event_date) +
        _detail_row('Time', event_time) +
        _detail_row('Guests', str(booking.capacity)) +
        _detail_row('Venue', booking.location) +
        _detail_row('Amount', f'\u20b1{float(booking.total_amount):,.2f}') +
        _detail_row('Payment', booking.payment_method) +
        (_detail_row('Special Requests', booking.special_requests) if booking.special_requests else '') +
        _detail_row('Status', _badge('Pending Review', '#f59e0b'))
    )
    body = (
        _h1('Booking Request Received! \U0001f389') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, we received your booking request. Here are the details:') +
        _detail_table(rows) +
        _p('Your booking is <strong>pending organizer review</strong>. You\'ll receive another email once it\'s confirmed.', '#94a3b8')
    )
    send_html_email(
        subject='Your EventPro Booking Request Received',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nBooking received for {booking.event_type} on {event_date}.\nAmount: \u20b1{float(booking.total_amount):,.2f}\n\n— EventPro Team',
    )


def send_booking_status_email(email, first_name, booking, new_status, decline_reason=''):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    if new_status == 'confirmed':
        rows = (
            _detail_row('Event', booking.event_type) +
            _detail_row('Date', event_date) +
            _detail_row('Venue', booking.location) +
            _detail_row('Guests', str(booking.capacity)) +
            _detail_row('Status', _badge('Confirmed \u2713', '#22c55e'))
        )
        body = (
            _h1('Your Booking is Confirmed! \u2705') +
            _p(f'Great news, <strong style="color:#e2e8f0;">{first_name}</strong>! Your event has been confirmed.') +
            _detail_table(rows) +
            _p('We look forward to making your event special!', '#94a3b8')
        )
        subject = 'Your EventPro Booking is Confirmed!'
        plain = f'Hi {first_name},\n\nYour {booking.event_type} booking on {event_date} is confirmed!\n\n— EventPro Team'
    else:
        body = (
            _h1('Booking Update') +
            _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, unfortunately your booking could not be confirmed.') +
            _detail_table(
                _detail_row('Event', booking.event_type) +
                _detail_row('Date', event_date) +
                _detail_row('Reason', decline_reason or 'N/A') +
                _detail_row('Status', _badge('Declined', '#ef4444'))
            ) +
            _p('Please contact us or try booking a different date.', '#94a3b8')
        )
        subject = 'Update on Your EventPro Booking'
        plain = f'Hi {first_name},\n\nYour {booking.event_type} booking on {event_date} was declined.\nReason: {decline_reason}\n\n— EventPro Team'
    send_html_email(subject=subject, html_body=body, recipient_list=[email], plain_text=plain)


def send_guest_invitation_email(guest_email, host_name, booking, confirmed=False):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    event_time = 'Whole Day' if not booking.time else (booking.time.strftime('%I:%M %p') if hasattr(booking.time, 'strftime') else str(booking.time))
    rows = (
        _detail_row('Event', booking.event_type) +
        _detail_row('Host', host_name) +
        _detail_row('Date', event_date) +
        _detail_row('Time', event_time) +
        _detail_row('Venue', booking.location)
    )
    if confirmed:
        body = (
            _h1("You're Invited! \U0001f389") +
            _p(f'<strong style="color:#e2e8f0;">{host_name}</strong> has invited you to their <strong style="color:#0ea5e9;">{booking.event_type}</strong> — and it\'s been confirmed!') +
            _detail_table(rows) +
            _p('We look forward to seeing you there!', '#94a3b8')
        )
        subject = f"You're Invited! {booking.event_type} on {event_date} — Confirmed!"
    else:
        body = (
            _h1("You've Been Invited! \u2709\ufe0f") +
            _p(f'<strong style="color:#e2e8f0;">{host_name}</strong> has invited you to their upcoming <strong style="color:#0ea5e9;">{booking.event_type}</strong> event.') +
            _detail_table(rows) +
            _p('Note: This booking is still <strong>pending organizer confirmation</strong>. You\'ll receive another email once confirmed.', '#94a3b8')
        )
        subject = f"You've Been Invited to {host_name}'s {booking.event_type}!"
    send_html_email(subject=subject, html_body=body, recipient_list=[guest_email],
                    plain_text=f'Hi,\n\n{host_name} invited you to their {booking.event_type} on {event_date} at {booking.location}.\n\n— EventPro Team')


def send_cancellation_email(email, first_name, event_type, date, cancel_reason=''):
    body = (
        _h1('Booking Cancelled') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, your booking has been cancelled.') +
        _detail_table(
            _detail_row('Event', event_type) +
            _detail_row('Date', str(date)) +
            (_detail_row('Reason', cancel_reason) if cancel_reason else '') +
            _detail_row('Status', _badge('Cancelled', '#ef4444'))
        ) +
        _p('If this was a mistake, please create a new booking.', '#94a3b8')
    )
    send_html_email(
        subject='Your EventPro Booking Has Been Cancelled',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour {event_type} booking on {date} has been cancelled.\n\n— EventPro Team',
    )


def send_payment_confirmed_email(email, first_name, booking, reference):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    body = (
        _h1('Payment Confirmed! \U0001f4b3') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, your GCash payment has been confirmed.') +
        _detail_table(
            _detail_row('Event', booking.event_type) +
            _detail_row('Date', event_date) +
            _detail_row('Amount', f'\u20b1{float(booking.total_amount):,.2f}') +
            _detail_row('Reference', reference) +
            _detail_row('Status', _badge('Paid \u2713', '#22c55e'))
        )
    )
    send_html_email(
        subject='EventPro — GCash Payment Confirmed!',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nPayment of \u20b1{float(booking.total_amount):,.2f} confirmed. Ref: {reference}\n\n— EventPro Team',
    )


# ── HTML helpers ──────────────────────────────────────────────────────────────

def _wrap(content):
    return (
        '<div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;'
        'background:#1e293b;color:#e2e8f0;border-radius:12px;overflow:hidden;">'
        '<div style="background:linear-gradient(135deg,#0ea5e9,#6366f1);padding:30px;text-align:center;">'
        '<h1 style="color:#fff;margin:0;font-size:24px;">EventPro</h1></div>'
        f'<div style="padding:30px;">{content}</div>'
        '<div style="background:#0f172a;padding:20px;text-align:center;color:#64748b;font-size:12px;">'
        '© 2025 EventPro. All rights reserved.</div></div>'
    )


def _h1(text):
    return f'<h2 style="color:#e2e8f0;margin-bottom:16px;">{text}</h2>'


def _p(text, color='#cbd5e1'):
    return f'<p style="color:{color};line-height:1.6;margin-bottom:16px;">{text}</p>'


def _code_box(code, label='Your Verification Code', valid='Valid for 15 minutes'):
    return (
        f'<div style="background:#0f172a;border:2px solid #0ea5e9;border-radius:8px;'
        f'padding:20px;text-align:center;margin:20px 0;">'
        f'<p style="color:#94a3b8;margin:0 0 8px;">{label}</p>'
        f'<p style="font-size:36px;font-weight:bold;color:#0ea5e9;letter-spacing:8px;margin:0;">{code}</p>'
        f'<p style="color:#64748b;font-size:12px;margin:8px 0 0;">{valid}</p></div>'
    )


def _badge(text, color):
    return f'<span style="background:{color};color:#fff;padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;">{text}</span>'


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
