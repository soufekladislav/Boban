"""Read-only Seznam Nákupy / Sklik Fénix client.

Separate API-key verification from the presence of a Nákupy premise/feed.
Refresh/access tokens must not appear in logs or exception messages.
"""
import requests

BASE = 'https://api.sklik.cz/v1'


class FenixError(ValueError):
    def __init__(self, stage, status=None):
        self.stage = stage
        self.status = status
        description = ('HTTP %s' % status) if status is not None else 'neplatná odpověď'
        super().__init__('Fénix: %s – %s. Ověř API klíč a oprávnění účtu.' % (stage, description))


def _json(response, stage):
    if response.status_code >= 400:
        raise FenixError(stage, response.status_code)
    try:
        value = response.json()
    except ValueError as exc:
        raise FenixError(stage) from exc
    if not isinstance(value, (dict, list)):
        raise FenixError(stage)
    return value


def get_access_token(refresh_token, timeout=12):
    if not isinstance(refresh_token, str) or len(refresh_token.strip()) < 12:
        raise ValueError('Chybí platný API klíč Fénix.')
    response = requests.post(
        BASE + '/user/token',
        data={'grant_type': 'refresh_token', 'refresh_token': refresh_token.strip()},
        timeout=timeout, allow_redirects=False,
    )
    payload = _json(response, 'ověření klíče')
    token = payload.get('access_token') if isinstance(payload, dict) else None
    if not isinstance(token, str) or not token:
        raise FenixError('získání přístupového tokenu')
    return token


def api_get(access_token, path, timeout=12):
    response = requests.get(
        BASE + path,
        headers={'Authorization': 'Bearer ' + access_token, 'Accept': 'application/json'},
        timeout=timeout, allow_redirects=False,
    )
    return _json(response, 'načtení ' + path)


def verify_key(refresh_token, timeout=12):
    """Verify the Fénix account without demanding an existing Nákupy feed."""
    access = get_access_token(refresh_token, timeout=timeout)
    # Account metadata does not depend on whether a shop/premise exists.
    user = api_get(access, '/user/me', timeout=timeout)
    return {'verified': True, 'user': user if isinstance(user, dict) else {}}


def list_feeds(refresh_token, timeout=12):
    access = get_access_token(refresh_token, timeout=timeout)
    return api_get(access, '/nakupy/feeds', timeout=timeout)


def probe_feeds(refresh_token, timeout=12):
    """Return operational status without failing a valid key on missing premise."""
    access = get_access_token(refresh_token, timeout=timeout)
    api_get(access, '/user/me', timeout=timeout)
    try:
        result = api_get(access, '/nakupy/feeds', timeout=timeout)
    except FenixError as exc:
        return {'feed_status': 'unavailable', 'feed_http_status': exc.status, 'feed_count': None}
    feeds = result if isinstance(result, list) else result.get('items', result.get('feeds', [])) if isinstance(result, dict) else []
    return {'feed_status': 'ok', 'feed_http_status': 200, 'feed_count': len(feeds) if isinstance(feeds, list) else None}
