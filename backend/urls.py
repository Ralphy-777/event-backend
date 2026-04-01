from django.contrib import admin
from django.urls import path, include
from django.http import JsonResponse, HttpResponse
from django.conf import settings
from django.conf.urls.static import static
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from rest_framework_simplejwt.views import TokenRefreshView

# Safe import of organizer_site — if admin.py has an error this won't crash the whole server
try:
    from user.admin import organizer_site
    _organizer_urls = [path('organizer-admin/', organizer_site.urls)]
except Exception:
    _organizer_urls = []


def health(request):
    return JsonResponse({'status': 'ok', 'service': 'EventPro API'})


urlpatterns = [
    path('', lambda r: HttpResponse(
        '<h1 style="font-family:sans-serif;padding:40px">EventPro API is running ✅</h1>'
        '<p style="font-family:sans-serif;padding:0 40px">Go to <a href="/admin/">/admin/</a> for the admin panel.</p>',
        content_type='text/html'
    )),
    path('health/', health),
    path('favicon.ico', lambda r: HttpResponse(status=204)),
    path('admin/', admin.site.urls),
    path('api/user/', include('user.urls')),
    path('api/user/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    *_organizer_urls,
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)

urlpatterns += staticfiles_urlpatterns()
