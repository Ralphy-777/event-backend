"""HTML email helpers for EventPro."""
from django.core.mail import EmailMultiAlternatives
from django.conf import settings
import threading
import logging

logger = logging.getLogger(__name__)

_BASE = """
<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#0a1628;font-family:Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#0a1628;padding:40px 20px;">
  <tr><td align="center">
    <table width="100%" style="max-width:560px;background:#0d1f35;border-radius:16px;border:1px solid rgba(14,165,233,0.2);overflow:hidden;">
      <!-- Header -->
      <tr><td style="background:linear-gradient(135deg,#0ea5e9,#0369a1);padding:28px 32px;">
        <table width="100%"><tr>
          <td><span style="display:inline-block;width:36px;height:36px;background:rgba(255,255,255,0.2);border-radius:8px;text-align:center;line-height:36px;font-weight:900;color:#fff;font-size:18px;margin-right:10px;">E</span>
          <span style="color:#fff;font-size:20px;font-weight:900;vertical-align:middle;">EventPro</span></td>
        </tr></table>
      </td></tr>
      <!-- Body -->
      <tr><td style="padding:32px;">
        {body}
      </td></tr>
      <!-- Footer -->
      <tr><td style="padding:20px 32px;border-top:1px solid rgba(14,165,233,0.1);text-align:center;">
        <p style="color:#475569;font-size:12px;margin:0;">© EventPro · Ralphy's Venue, Cebu City</p>
      </td></tr>
    </table>
  </td></tr>
</table>
</body></html>
"""

def _h1(text):
    return f'<h1 style="color:#fff;font-size:22px;font-weight:900;margin:0 0 8px;">{text}</h1>'

def _p(text, color='#94a3b8'):
    return f'<p style="color:{color};font-size:14px;line-height:1.6;margin:0 0 16px;">{text}</p>'

def _code_box(code):
    return f'''
<div style="background:rgba(14,165,233,0.1);border:1px solid rgba(14,165,233,0.3);border-radius:12px;padding:24px;text-align:center;margin:20px 0;">
  <p style="color:#94a3b8;font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:2px;">Your Verification Code</p>
  <span style="color:#0ea5e9;font-size:40px;font-weight:900;letter-spacing:12px;">{code}</span>
  <p style="color:#64748b;font-size:12px;margin:8px 0 0;">Valid for 15 minutes</p>
</div>'''

def _detail_row(label, value):
    return f'''
<tr>
  <td style="padding:8px 0;color:#64748b;font-size:13px;width:120px;">{label}</td>
  <td style="padding:8px 0;color:#e2e8f0;font-size:13px;font-weight:600;">{value}</td>
</tr>'''

def _detail_table(rows_html):
    return f'<table width="100%" style="background:rgba(255,255,255,0.04);border-radius:10px;padding:16px;margin:16px 0;">{rows_html}</table>'

def _badge(text, color='#0ea5e9'):
    return f'<span style="display:inline-block;background:{color}22;color:{color};border:1px solid {color}44;border-radius:6px;padding:3px 10px;font-size:12px;font-weight:700;">{text}</span>'


def send_html_email(subject, html_body, recipient_list, plain_text=None):
    """Send an HTML email (with plain-text fallback) asynchronously."""
    def _send():
        try:
            plain = plain_text or 'Please view this email in an HTML-capable client.'
            html = _BASE.replace('{body}', html_body)
            msg = EmailMultiAlternatives(
                subject=subject,
                body=plain,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=recipient_list,
            )
            msg.attach_alternative(html, 'text/html')
            msg.send(fail_silently=False)
        except Exception as e:
            logger.error('send_html_email failed to %s: %s', recipient_list, e)
    threading.Thread(target=_send, daemon=True).start()


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
    )


def send_password_reset_email(email, first_name, code):
    body = (
        _h1('Password Reset Request') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, we received a request to reset your password.') +
        _code_box(code).replace('Your Verification Code', 'Your Reset Code').replace('Valid for 15 minutes', 'Valid for 10 minutes') +
        _p("If you didn't request this, you can safely ignore this email.", '#64748b')
    )
    send_html_email(
        subject='Your EventPro Password Reset Code',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour password reset code is: {code}\n\n— EventPro Team',
    )


def send_email_change_verification(email, first_name, new_email, code):
    body = (
        _h1('Confirm Email Change') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, you requested to change your email to <strong style="color:#0ea5e9;">{new_email}</strong>.') +
        _code_box(code).replace('Valid for 15 minutes', 'Valid for 10 minutes') +
        _p("If you didn't request this, please ignore this email.", '#64748b')
    )
    send_html_email(
        subject='Verify Your Email Change — EventPro',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nYour email change verification code is: {code}\n\n— EventPro Team',
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
        _detail_row('Amount', f'₱{float(booking.total_amount):,.2f}') +
        _detail_row('Payment', booking.payment_method) +
        _detail_row('Status', _badge('Pending Review', '#f59e0b'))
    )
    body = (
        _h1('Booking Request Received! 🎉') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, we received your booking request. Here are the details:') +
        _detail_table(rows) +
        _p('Your booking is <strong>pending organizer review</strong>. You\'ll receive another email once it\'s confirmed.', '#94a3b8')
    )
    send_html_email(
        subject='Your EventPro Booking Request Received',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nBooking received for {booking.event_type} on {event_date}.\nAmount: ₱{float(booking.total_amount):,.2f}\n\n— EventPro Team',
    )


def send_booking_status_email(email, first_name, booking, new_status, decline_reason=''):
    event_date = booking.date.strftime('%B %d, %Y') if hasattr(booking.date, 'strftime') else str(booking.date)
    if new_status == 'confirmed':
        rows = (
            _detail_row('Event', booking.event_type) +
            _detail_row('Date', event_date) +
            _detail_row('Venue', booking.location) +
            _detail_row('Guests', str(booking.capacity)) +
            _detail_row('Status', _badge('Confirmed ✓', '#22c55e'))
        )
        body = (
            _h1('Your Booking is Confirmed! ✅') +
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
            _h1(f"You're Invited! 🎉") +
            _p(f'<strong style="color:#e2e8f0;">{host_name}</strong> has invited you to their <strong style="color:#0ea5e9;">{booking.event_type}</strong> — and it\'s been confirmed!') +
            _detail_table(rows) +
            _p('We look forward to seeing you there!', '#94a3b8')
        )
        subject = f"You're Invited! {booking.event_type} on {event_date} — Confirmed!"
    else:
        body = (
            _h1(f"You've Been Invited! ✉️") +
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
        _h1('Payment Confirmed! 💳') +
        _p(f'Hi <strong style="color:#e2e8f0;">{first_name}</strong>, your GCash payment has been confirmed.') +
        _detail_table(
            _detail_row('Event', booking.event_type) +
            _detail_row('Date', event_date) +
            _detail_row('Amount', f'₱{float(booking.total_amount):,.2f}') +
            _detail_row('Reference', reference) +
            _detail_row('Status', _badge('Paid ✓', '#22c55e'))
        )
    )
    send_html_email(
        subject='EventPro — GCash Payment Confirmed!',
        html_body=body,
        recipient_list=[email],
        plain_text=f'Hi {first_name},\n\nPayment of ₱{float(booking.total_amount):,.2f} confirmed. Ref: {reference}\n\n— EventPro Team',
    )
