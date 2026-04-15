"""Compatibility wrapper for the Nodemailer bridge mailer."""

from .mailer import (
    EmailDeliveryError,
    send_booking_confirmation_email,
    send_booking_status_email,
    send_cancellation_email,
    send_email_change_verification,
    send_guest_invitation_email,
    send_html_email,
    send_password_reset_email,
    send_payment_confirmed_email,
    send_verification_email,
)

__all__ = [
    'EmailDeliveryError',
    'send_booking_confirmation_email',
    'send_booking_status_email',
    'send_cancellation_email',
    'send_email_change_verification',
    'send_guest_invitation_email',
    'send_html_email',
    'send_password_reset_email',
    'send_payment_confirmed_email',
    'send_verification_email',
]
