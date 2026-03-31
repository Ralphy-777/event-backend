# Add these to backend/backend/settings.py

# ========================================
# GCASH PAYMENT CONFIGURATION
# ========================================

# GCash API Credentials (Get from https://open.alipay.com/)
GCASH_APP_ID = 'your_gcash_app_id_here'

# RSA Private Key (for signing requests)
GCASH_PRIVATE_KEY = '''-----BEGIN PRIVATE KEY-----
YOUR_PRIVATE_KEY_HERE
-----END PRIVATE KEY-----'''

# RSA Public Key (for verifying responses)
GCASH_PUBLIC_KEY = '''-----BEGIN PUBLIC KEY-----
YOUR_PUBLIC_KEY_HERE
-----END PUBLIC KEY-----'''

# GCash Gateway URL
GCASH_GATEWAY_URL = 'https://open-na.alipay.com/gateway.do'

# Webhook URL (GCash will send payment notifications here)
# IMPORTANT: Must be publicly accessible (use ngrok for local testing)
GCASH_NOTIFY_URL = 'http://your-domain.com/api/user/gcash/notify/'

# Return URL (where user is redirected after payment)
GCASH_RETURN_URL = 'http://localhost:3000/payment-success'

# ========================================
# TESTING WITH NGROK (Local Development)
# ========================================
# 1. Install ngrok: https://ngrok.com/
# 2. Run: ngrok http 8000
# 3. Copy the https URL (e.g., https://abc123.ngrok.io)
# 4. Update GCASH_NOTIFY_URL to: https://abc123.ngrok.io/api/user/gcash/notify/
