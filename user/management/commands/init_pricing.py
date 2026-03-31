from django.core.management.base import BaseCommand
from user.models import EventPricing


class Command(BaseCommand):
    help = 'Initialize default event pricing'

    def handle(self, *args, **kwargs):
        default_pricing = [
            {'event_type': 'Wedding', 'price': 5000, 'max_capacity': 50},
            {'event_type': 'Birthday', 'price': 5000, 'max_capacity': 50},
            {'event_type': 'Christening', 'price': 5000, 'max_capacity': 50},
            {'event_type': 'Conference', 'price': 7000, 'max_capacity': 100},
            {'event_type': 'Corporate Event', 'price': 7000, 'max_capacity': 100},
        ]

        for pricing in default_pricing:
            EventPricing.objects.get_or_create(
                event_type=pricing['event_type'],
                defaults={'price': pricing['price'], 'max_capacity': pricing['max_capacity']}
            )
            self.stdout.write(self.style.SUCCESS(f'Created/Updated pricing for {pricing["event_type"]}'))

        self.stdout.write(self.style.SUCCESS('Successfully initialized event pricing!'))
