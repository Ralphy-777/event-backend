import requests
import base64
from django.conf import settings


def get_auth_header():
    key = f"{settings.PAYMONGO_SECRET_KEY}:"
    encoded = base64.b64encode(key.encode()).decode()
    return {"Authorization": f"Basic {encoded}", "Content-Type": "application/json"}


def create_gcash_payment(booking_id, amount_php, description, success_url, failed_url):
    """Create a GCash payment link via PayMongo."""
    try:
        response = requests.post(
            f"{settings.PAYMONGO_BASE_URL}/links",
            headers=get_auth_header(),
            json={
                "data": {
                    "attributes": {
                        "amount": int(float(amount_php) * 100),  # convert to centavos
                        "description": description,
                        "remarks": f"Booking #{booking_id}",
                    }
                }
            },
            timeout=30,
        )
        result = response.json()

        if response.status_code in (200, 201):
            data = result["data"]
            return {
                "success": True,
                "payment_link_id": data["id"],
                "checkout_url": data["attributes"]["checkout_url"],
                "reference_number": data["attributes"]["reference_number"],
                "status": data["attributes"]["status"],
            }
        else:
            errors = result.get("errors", [{}])
            return {"success": False, "error": errors[0].get("detail", "PayMongo error")}

    except Exception as e:
        return {"success": False, "error": str(e)}


def get_payment_link_status(payment_link_id):
    """Check the status of a PayMongo payment link."""
    try:
        response = requests.get(
            f"{settings.PAYMONGO_BASE_URL}/links/{payment_link_id}",
            headers=get_auth_header(),
            timeout=30,
        )
        result = response.json()
        if response.status_code == 200:
            attrs = result["data"]["attributes"]
            return {
                "success": True,
                "status": attrs["status"],  # 'unpaid' | 'paid'
                "amount": attrs["amount"] / 100,
            }
        return {"success": False, "error": "Failed to fetch status"}
    except Exception as e:
        return {"success": False, "error": str(e)}
