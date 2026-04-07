from django.db import models
from django.contrib.auth.models import AbstractUser
from decimal import Decimal

class User(AbstractUser):
    email = models.EmailField(unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    address = models.TextField(blank=True)
    is_organizer = models.BooleanField(default=False)
    preferred_payment_method = models.CharField(max_length=50, default='Cash', choices=[('Cash', 'Cash'), ('GCash', 'GCash')])
    profile_photo = models.ImageField(upload_to='profile_photos/', null=True, blank=True)
    email_verified = models.BooleanField(default=False)
    verification_code = models.CharField(max_length=6, blank=True)

    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_set',
        blank=True
    )
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_set',
        blank=True
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username', 'first_name', 'last_name']

    def __str__(self):
        return self.email


class EventType(models.Model):
    event_type = models.CharField(max_length=100, unique=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    max_capacity = models.IntegerField(default=50)
    max_invited_emails = models.IntegerField(default=50)
    people_per_table = models.IntegerField(default=5)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='event_types/', null=True, blank=True)
    image_url = models.URLField(max_length=500, blank=True, help_text='Paste an image URL (use this on Render instead of uploading)')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_image(self):
        if self.image:
            return self.image.url
        return self.image_url or None

    class Meta:
        ordering = ['event_type']
        verbose_name = 'Event Type'
        verbose_name_plural = 'Event Types'

    def __str__(self):
        return f"{self.event_type} - \u20b1{self.price}"


class Booking(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='bookings')
    event_type = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    capacity = models.IntegerField()
    date = models.DateField()
    time = models.TimeField(null=True, blank=True)
    location = models.CharField(max_length=255, default='VILLAROJO RESIDENCES CEBU CITY 6000')
    invited_emails = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='pending')
    payment_status = models.CharField(max_length=20, default='pending')
    payment_method = models.CharField(max_length=50, blank=True)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    payment_proof = models.FileField(upload_to='payment_proofs/', null=True, blank=True)
    gcash_reference = models.CharField(max_length=100, blank=True)
    event_details = models.JSONField(default=dict, blank=True)
    whole_day = models.BooleanField(default=False)
    time_slot = models.CharField(max_length=20, default='morning', choices=[('morning', 'Morning'), ('afternoon', 'Afternoon'), ('whole_day', 'Whole Day')])
    reminder_sent = models.BooleanField(default=False)
    decline_reason = models.TextField(blank=True, default='')
    cancel_reason = models.TextField(blank=True, default='')
    special_requests = models.TextField(blank=True, null=True, default='')
    payment_deadline = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.email} - {self.event_type} on {self.date}"

    def calculate_amount(self):
        try:
            event_type_obj = EventType.objects.get(event_type=self.event_type, is_active=True)
            base = event_type_obj.price
        except EventType.DoesNotExist:
            base = Decimal('5000')
        if self.time_slot == 'whole_day' or self.whole_day:
            return round(base * 2 * Decimal('0.8'), 2)
        return base


class Payment(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, related_name='payment')
    event_id = models.IntegerField()
    event_name = models.CharField(max_length=100)
    client_name = models.CharField(max_length=200)
    payment_method = models.CharField(max_length=50, blank=True)
    reference_number = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Payment {self.reference_number} - {self.client_name}"


class Review(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews', null=True, blank=True)
    guest_email = models.EmailField(blank=True, default='')
    booking = models.ForeignKey(Booking, on_delete=models.SET_NULL, null=True, blank=True, related_name='reviews')
    rating = models.IntegerField(choices=[(i, i) for i in range(1, 6)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        identifier = self.user.email if self.user else self.guest_email
        return f"{identifier} - {self.rating}\u2605"


class ReviewReply(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name='replies')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='review_replies')
    comment = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Reply by {self.user.email} on Review #{self.review.id}"


class Notification(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='notifications')
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Notification for {self.user.email}: {self.message[:40]}"


class ContactMessage(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='contact_messages')
    name = models.CharField(max_length=200)
    email = models.EmailField()
    subject = models.CharField(max_length=300)
    message = models.TextField()
    reply = models.TextField(blank=True, default='')
    is_read = models.BooleanField(default=False)
    replied_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} \u2014 {self.subject}"

