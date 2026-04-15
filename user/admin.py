from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.html import format_html
from .models import (
    User, Booking, Payment, EventType,
    Review, ReviewReply, Notification, ContactMessage, BookingStatusHistory, EmailDeliveryLog,
    LandingCarouselImage, DamageReport,
)

# organizer_site kept for backward compat with urls.py import
from django.contrib.admin import AdminSite
class OrganizerAdminSite(AdminSite):
    site_header = 'EventPro Organizer'
    site_title = 'Organizer Portal'
    index_title = 'Manage Bookings'
organizer_site = OrganizerAdminSite(name='organizer_admin')

admin.site.site_header = 'Django administration'
admin.site.site_title = 'Django site admin'
admin.site.index_title = 'Site administration'


def _badge(text, color):
    return format_html(
        '<span style="padding:3px 10px;border-radius:12px;font-size:11px;'
        'font-weight:600;color:#fff;background:{}">{}</span>',
        color, text,
    )

STATUS_COLORS = {
    'pending':              '#f59e0b',
    'confirmed':            '#10b981',
    'declined':             '#ef4444',
    'cancelled':            '#6b7280',
    'paid':                 '#10b981',
    'pending_verification': '#6366f1',
    'rejected':             '#ef4444',
}


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display  = ['email', 'full_name', 'role_badge', 'email_verified', 'is_active', 'date_joined']
    list_filter   = ['is_organizer', 'is_active', 'email_verified', 'is_staff']
    search_fields = ['email', 'first_name', 'last_name']
    ordering      = ['-date_joined']
    readonly_fields = ['date_joined', 'last_login']

    fieldsets = (
        ('Account', {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'date_of_birth', 'address', 'profile_photo')}),
        ('Preferences', {'fields': ('preferred_payment_method',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_organizer', 'email_verified', 'groups', 'user_permissions')}),
        ('Dates', {'fields': ('last_login', 'date_joined'), 'classes': ('collapse',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'first_name', 'last_name', 'password1', 'password2', 'is_organizer', 'is_active', 'email_verified'),
        }),
    )

    def full_name(self, obj):
        return f'{obj.first_name} {obj.last_name}'.strip() or '—'
    full_name.short_description = 'Name'

    def role_badge(self, obj):
        if obj.is_superuser:
            return _badge('Superadmin', '#7c3aed')
        if obj.is_organizer:
            return _badge('Organizer', '#0ea5e9')
        return _badge('Client', '#64748b')
    role_badge.short_description = 'Role'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.is_active = True
            obj.email_verified = True
        super().save_model(request, obj, form, change)


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display  = ['id', 'client_name', 'event_type', 'date', 'time_slot', 'capacity', 'status_badge', 'payment_badge', 'total_amount', 'created_at']
    list_filter   = ['status', 'payment_status', 'event_type', 'time_slot', 'date']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'event_type']
    ordering      = ['-created_at']
    readonly_fields = ['created_at', 'total_amount', 'payment_deadline', 'accepted_at']
    date_hierarchy = 'date'
    list_per_page = 25
    actions = ['approve_bookings', 'decline_bookings']

    fieldsets = (
        ('Client & Event', {
            'fields': ('user', 'event_type', 'description', 'capacity', 'invited_emails')
        }),
        ('Schedule', {
            'fields': ('date', 'time', 'time_slot', 'whole_day', 'location')
        }),
        ('Status', {
            'fields': ('status', 'accepted_at', 'decline_reason', 'cancel_reason')
        }),
        ('Payment', {
            'fields': ('payment_status', 'payment_method', 'total_amount', 'payment_deadline', 'gcash_reference', 'payment_proof')
        }),
        ('Extra', {
            'fields': ('event_details', 'reminder_sent', 'created_at'),
            'classes': ('collapse',),
        }),
    )

    def client_name(self, obj):
        return f'{obj.user.first_name} {obj.user.last_name}'
    client_name.short_description = 'Client'

    def status_badge(self, obj):
        return _badge(obj.status.title(), STATUS_COLORS.get(obj.status, '#64748b'))
    status_badge.short_description = 'Status'

    def payment_badge(self, obj):
        return _badge(obj.payment_status.replace('_', ' ').title(), STATUS_COLORS.get(obj.payment_status, '#64748b'))
    payment_badge.short_description = 'Payment'

    def approve_bookings(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='confirmed', accepted_at=timezone.now())
        self.message_user(request, f'{updated} booking(s) confirmed.')
    approve_bookings.short_description = 'Approve selected bookings'

    def decline_bookings(self, request, queryset):
        updated = queryset.filter(status='pending').update(status='declined')
        self.message_user(request, f'{updated} booking(s) declined.')
    decline_bookings.short_description = 'Decline selected bookings'


@admin.register(BookingStatusHistory)
class BookingStatusHistoryAdmin(admin.ModelAdmin):
    list_display = ['booking', 'from_status', 'to_status', 'actor', 'created_at']
    list_filter = ['to_status', 'created_at']
    search_fields = ['booking__user__email', 'booking__event_type', 'reason', 'actor__email']
    ordering = ['-created_at']
    readonly_fields = ['booking', 'from_status', 'to_status', 'reason', 'actor', 'metadata', 'created_at']


@admin.register(EmailDeliveryLog)
class EmailDeliveryLogAdmin(admin.ModelAdmin):
    list_display = ['recipient', 'subject', 'status', 'channel', 'created_at']
    list_filter = ['status', 'channel', 'created_at']
    search_fields = ['recipient', 'subject', 'error_message', 'provider_message_id']
    ordering = ['-created_at']
    readonly_fields = ['recipient', 'subject', 'status', 'channel', 'error_message', 'provider_message_id', 'payload', 'created_at', 'updated_at']


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display  = ['reference_number', 'client_name', 'event_name', 'method_badge', 'amount', 'created_at']
    list_filter   = ['payment_method', 'created_at']
    search_fields = ['reference_number', 'client_name', 'event_name']
    ordering      = ['-created_at']
    readonly_fields = ['reference_number', 'created_at']

    fieldsets = (
        ('Payment Info', {'fields': ('booking', 'reference_number', 'amount', 'payment_method')}),
        ('Event Info',   {'fields': ('event_id', 'event_name', 'client_name')}),
        ('Timestamps',   {'fields': ('created_at',), 'classes': ('collapse',)}),
    )

    def method_badge(self, obj):
        colors = {'GCash': '#0ea5e9', 'Cash': '#10b981', 'Card': '#6366f1'}
        return _badge(obj.payment_method, colors.get(obj.payment_method, '#64748b'))
    method_badge.short_description = 'Method'


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display  = ['event_type', 'image_preview', 'price_display', 'max_capacity', 'people_per_table', 'active_badge', 'updated_at']
    list_editable = ['max_capacity', 'people_per_table']
    list_filter   = ['is_active']
    search_fields = ['event_type', 'description']
    ordering      = ['event_type']
    readonly_fields = ['created_at', 'updated_at', 'image_preview']

    fieldsets = (
        ('Basic Info',         {'fields': ('event_type', 'description', 'is_active')}),
        ('Image',              {'fields': ('image', 'image_url', 'image_preview')}),
        ('Pricing & Capacity', {'fields': ('price', 'max_capacity', 'people_per_table', 'max_invited_emails')}),
        ('Timestamps',         {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def price_display(self, obj):
        return f'P{obj.price:,.2f}'
    price_display.short_description = 'Price'

    def active_badge(self, obj):
        return _badge('Active', '#10b981') if obj.is_active else _badge('Inactive', '#ef4444')
    active_badge.short_description = 'Status'

    def image_preview(self, obj):
        if obj.image:
            try:
                return format_html('<img src="{}" style="height:80px;border-radius:8px;object-fit:cover;" />', obj.image.url)
            except Exception:
                pass
        if obj.image_url:
            return format_html('<img src="{}" style="height:80px;border-radius:8px;object-fit:cover;" />', obj.image_url)
        return '— Paste an image URL above'
    image_preview.short_description = 'Preview'


@admin.register(LandingCarouselImage)
class LandingCarouselImageAdmin(admin.ModelAdmin):
    list_display = ['title', 'image_preview', 'display_order', 'is_active', 'updated_at']
    list_editable = ['display_order', 'is_active']
    list_filter = ['is_active']
    search_fields = ['title', 'subtitle']
    ordering = ['display_order', 'id']
    readonly_fields = ['created_at', 'updated_at', 'image_preview']

    fieldsets = (
        ('Content', {'fields': ('title', 'subtitle', 'is_active')}),
        ('Image', {'fields': ('image', 'image_url', 'image_preview')}),
        ('Display', {'fields': ('display_order',)}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def image_preview(self, obj):
        image = obj.get_image() if obj else None
        if image:
            return format_html('<img src="{}" style="height:90px;width:150px;border-radius:12px;object-fit:cover;" />', image)
        return 'No image yet'
    image_preview.short_description = 'Preview'




@admin.register(DamageReport)
class DamageReportAdmin(admin.ModelAdmin):
    list_display  = ['id', 'booking_link', 'client_name', 'item_type', 'item_name', 'quantity', 'estimated_cost', 'recovered_amount', 'status_badge', 'charge_to_client', 'created_at']
    list_filter   = ['status', 'item_type', 'charge_to_client', 'created_at']
    search_fields = ['booking__user__email', 'item_name', 'notes']
    ordering      = ['-created_at']
    readonly_fields = ['created_at', 'updated_at', 'photo_preview']

    fieldsets = (
        ('Booking Info', {'fields': ('booking', 'reported_by')}),
        ('Damage Details', {'fields': ('item_type', 'item_name', 'quantity', 'notes')}),
        ('Financials', {'fields': ('estimated_cost', 'recovered_amount', 'charge_to_client')}),
        ('Status & Photo', {'fields': ('status', 'photo', 'photo_preview')}),
        ('Timestamps', {'fields': ('created_at', 'updated_at'), 'classes': ('collapse',)}),
    )

    def booking_link(self, obj):
        return format_html('<a href="/admin/user/booking/{}/change/">Booking #{}</a>', obj.booking_id, obj.booking_id)
    booking_link.short_description = 'Booking'

    def client_name(self, obj):
        u = obj.booking.user
        return f'{u.first_name} {u.last_name}'.strip() or u.email
    client_name.short_description = 'Client'

    def status_badge(self, obj):
        colors = {'reported': '#f59e0b', 'billed': '#0ea5e9', 'resolved': '#10b981', 'waived': '#6b7280'}
        return _badge(obj.get_status_display(), colors.get(obj.status, '#64748b'))
    status_badge.short_description = 'Status'

    def photo_preview(self, obj):
        if not obj.photo:
            return 'No photo uploaded'
        try:
            return format_html('<img src="{}" style="height:120px;border-radius:8px;object-fit:cover;" />', obj.photo.url)
        except Exception:
            return 'Preview unavailable'
    photo_preview.short_description = 'Photo Preview'

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display  = ['reviewer', 'stars', 'event_type_display', 'short_comment', 'created_at']
    list_filter   = ['rating', 'created_at']
    search_fields = ['user__email', 'comment']
    ordering      = ['-created_at']
    readonly_fields = ['created_at']

    def reviewer(self, obj):
        return obj.user.email if obj.user else obj.guest_email or '—'
    reviewer.short_description = 'Reviewer'

    def stars(self, obj):
        filled = '*' * obj.rating
        empty  = '-' * (5 - obj.rating)
        color  = '#f59e0b' if obj.rating >= 4 else ('#ef4444' if obj.rating <= 2 else '#94a3b8')
        return format_html('<span style="color:{};font-size:14px">{}{}</span>', color, filled, empty)
    stars.short_description = 'Rating'

    def event_type_display(self, obj):
        return obj.booking.event_type if obj.booking else '—'
    event_type_display.short_description = 'Event'

    def short_comment(self, obj):
        return obj.comment[:60] + '...' if len(obj.comment) > 60 else obj.comment
    short_comment.short_description = 'Comment'


@admin.register(ReviewReply)
class ReviewReplyAdmin(admin.ModelAdmin):
    list_display  = ['user', 'review_link', 'short_comment', 'created_at']
    search_fields = ['user__email', 'comment']
    ordering      = ['-created_at']
    readonly_fields = ['created_at']

    def review_link(self, obj):
        return format_html('<a href="/admin/user/review/{}/change/">Review #{}</a>', obj.review.id, obj.review.id)
    review_link.short_description = 'Review'

    def short_comment(self, obj):
        return obj.comment[:60] + '...' if len(obj.comment) > 60 else obj.comment
    short_comment.short_description = 'Reply'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display  = ['user', 'short_message', 'read_badge', 'created_at']
    list_filter   = ['is_read', 'created_at']
    search_fields = ['user__email', 'message']
    ordering      = ['-created_at']
    readonly_fields = ['created_at']
    actions = ['mark_read']

    def short_message(self, obj):
        return obj.message[:80] + '...' if len(obj.message) > 80 else obj.message
    short_message.short_description = 'Message'

    def read_badge(self, obj):
        return _badge('Read', '#10b981') if obj.is_read else _badge('Unread', '#f59e0b')
    read_badge.short_description = 'Status'

    def mark_read(self, request, queryset):
        queryset.update(is_read=True)
        self.message_user(request, 'Marked as read.')
    mark_read.short_description = 'Mark selected as read'


@admin.register(ContactMessage)
class ContactMessageAdmin(admin.ModelAdmin):
    list_display  = ['name', 'email', 'subject', 'read_badge', 'replied_badge', 'created_at']
    list_filter   = ['is_read', 'created_at']
    search_fields = ['name', 'email', 'subject', 'message']
    ordering      = ['-created_at']
    readonly_fields = ['created_at', 'replied_at']

    fieldsets = (
        ('From',    {'fields': ('user', 'name', 'email')}),
        ('Message', {'fields': ('subject', 'message')}),
        ('Reply',   {'fields': ('reply', 'is_read', 'replied_at')}),
        ('Dates',   {'fields': ('created_at',), 'classes': ('collapse',)}),
    )

    def read_badge(self, obj):
        return _badge('Read', '#10b981') if obj.is_read else _badge('Unread', '#f59e0b')
    read_badge.short_description = 'Read'

    def replied_badge(self, obj):
        return _badge('Replied', '#10b981') if obj.reply else _badge('Pending', '#94a3b8')
    replied_badge.short_description = 'Reply'
