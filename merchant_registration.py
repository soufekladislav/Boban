"""One-time platform-level Merchant API developer registration.

Only invoked after a superadmin starts a separate OAuth consent flow.
Never stores a user OAuth access token in application settings.
"""
import re

REGISTER_URL = 'https://merchantapi.googleapis.com/accounts/v1/accounts/{account}/developerRegistration:registerGcp'
SCOPE = 'https://www.googleapis.com/auth/content'


def validate(account_id, email):
    account_id = str(account_id or '').strip()
    email = str(email or '').strip()
    if not re.fullmatch(r'[1-9][0-9]{3,19}', account_id):
        raise ValueError('Vyplň číselné Merchant ID registračního účtu.')
    if len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
        raise ValueError('Vyplň platný kontaktní Google e-mail.')
    return account_id, email


def register(api_post, account_id, email):
    account_id, email = validate(account_id, email)
    response = api_post(REGISTER_URL.format(account=account_id), {'developerEmail': email})
    if not isinstance(response, dict) or response.get('name') != f'accounts/{account_id}/developerRegistration':
        raise ValueError('Google nevrátil očekávané potvrzení registrace.')
    gcp_ids = response.get('gcpIds') or []
    if not isinstance(gcp_ids, list) or not gcp_ids:
        raise ValueError('Google nevrátil identifikátor registrovaného Cloud projektu.')
    return {'merchant_id':account_id, 'developer_email':email,
            'registration_name':response['name'], 'gcp_ids':[str(x) for x in gcp_ids]}
