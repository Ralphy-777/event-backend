import json
from urllib.parse import parse_qs
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


@database_sync_to_async
def get_user_from_token(token_str):
    try:
        from rest_framework_simplejwt.tokens import AccessToken
        from django.contrib.auth import get_user_model
        User = get_user_model()
        token = AccessToken(token_str)
        return User.objects.get(id=token['user_id'])
    except Exception:
        return None


class NotificationConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        qs = parse_qs(self.scope['query_string'].decode())
        token_list = qs.get('token', [])

        if not token_list:
            await self.close(code=4001)
            return

        user = await get_user_from_token(token_list[0])
        if not user:
            await self.close(code=4001)
            return

        self.user = user
        self.group_name = f'notifications_{user.id}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

        # Confirm connection to client
        await self.send(text_data=json.dumps({
            'type': 'connected',
            'message': 'Real-time notifications connected'
        }))

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        # ping/pong keepalive
        try:
            data = json.loads(text_data or '{}')
            if data.get('type') == 'ping':
                await self.send(text_data=json.dumps({'type': 'pong'}))
        except Exception:
            pass

    # Called by channel_layer.group_send from views.py send_ws_notification()
    async def notification_message(self, event):
        await self.send(text_data=json.dumps(event['data']))
