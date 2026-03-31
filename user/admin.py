from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Booking, Payment, EventType, Video, Review

class OrganizerAdmin(admin.AdminSite):
    site_header = 'Organizer Management'
    site_title = 'Organizer Portal'
    index_title = 'Manage Bookings'

organizer_site = OrganizerAdmin(name='organizer_admin')

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ['email', 'first_name', 'last_name', 'is_organizer', 'is_staff']
    list_filter = ['is_staff', 'is_superuser', 'is_active', 'is_organizer']
    search_fields = ['email', 'first_name', 'last_name']
    ordering = ['email']
    
    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'date_of_birth', 'address')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'is_organizer', 'email_verified', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'first_name', 'last_name', 'is_organizer', 'is_active', 'email_verified'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:  # creating new user
            obj.is_active = True
            obj.email_verified = True
        super().save_model(request, obj, form, change)

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'event_type', 'date', 'time', 'capacity', 'status', 'created_at']
    list_filter = ['status', 'date', 'event_type']
    search_fields = ['user__email', 'user__first_name', 'user__last_name', 'event_type']
    ordering = ['-created_at']
    actions = ['approve_bookings', 'decline_bookings']
    
    def approve_bookings(self, request, queryset):
        queryset.update(status='confirmed')
        self.message_user(request, f'{queryset.count()} bookings approved.')
    approve_bookings.short_description = 'Approve selected bookings'
    
    def decline_bookings(self, request, queryset):
        queryset.update(status='declined')
        self.message_user(request, f'{queryset.count()} bookings declined.')
    decline_bookings.short_description = 'Decline selected bookings'

# Register for organizer site (limited access)
class OrganizerBookingAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'event_type', 'date', 'capacity', 'status']
    list_filter = ['status', 'date', 'event_type']
    search_fields = ['user__email', 'event_type']
    ordering = ['-created_at']
    actions = ['approve_bookings', 'decline_bookings']
    
    def has_add_permission(self, request):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False
    
    def approve_bookings(self, request, queryset):
        queryset.update(status='confirmed')
        self.message_user(request, f'{queryset.count()} bookings approved.')
    approve_bookings.short_description = 'Approve selected bookings'
    
    def decline_bookings(self, request, queryset):
        queryset.update(status='declined')
        self.message_user(request, f'{queryset.count()} bookings declined.')
    decline_bookings.short_description = 'Decline selected bookings'

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ['reference_number', 'client_name', 'event_name', 'payment_method', 'amount', 'created_at']
    list_filter = ['payment_method', 'created_at']
    search_fields = ['reference_number', 'client_name', 'event_name']
    ordering = ['-created_at']
    readonly_fields = ['reference_number', 'created_at']

@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'price', 'max_capacity', 'people_per_table', 'is_active', 'updated_at']
    list_editable = ['price', 'max_capacity', 'people_per_table', 'is_active']
    list_filter = ['is_active']
    search_fields = ['event_type', 'description']
    ordering = ['event_type']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('event_type', 'description', 'is_active')
        }),
        ('Pricing & Capacity', {
            'fields': ('price', 'max_capacity', 'people_per_table')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(Video)
class VideoAdmin(admin.ModelAdmin):
    list_display = ['title', 'category', 'order', 'is_active', 'created_at']
    list_editable = ['order', 'is_active']
    list_filter = ['is_active', 'category']
    search_fields = ['title', 'description']
    ordering = ['order', '-created_at']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Video Information', {
            'fields': ('title', 'description', 'category')
        }),
        ('URLs', {
            'fields': ('video_url', 'thumbnail_url'),
            'description': 'Enter YouTube video URL (e.g., https://www.youtube.com/watch?v=VIDEO_ID)'
        }),
        ('Display Settings', {
            'fields': ('order', 'is_active')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['user', 'rating', 'event_type_display', 'comment', 'created_at']
    list_filter = ['rating', 'created_at']
    search_fields = ['user__email', 'comment']
    ordering = ['-created_at']
    readonly_fields = ['created_at']

    def event_type_display(self, obj):
        return obj.booking.event_type if obj.booking else '—'
    event_type_display.short_description = 'Event Type'


organizer_site.register(Booking, OrganizerBookingAdmin)
