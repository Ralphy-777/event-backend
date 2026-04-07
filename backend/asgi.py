import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')

import django
django.setup()

from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from backend.routing import websocket_urlpatterns

django_asgi_app = get_asgi_application()

application = ProtocolTypeRouter({
    # Let Django handle HTTP requests directly. Static files are served via
    # WhiteNoiseMiddleware from the standard Django middleware stack.
    'http': django_asgi_app,
    'websocket': URLRouter(websocket_urlpatterns),
})
