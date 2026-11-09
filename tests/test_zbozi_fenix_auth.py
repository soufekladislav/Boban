"""Contract tests for separating key verification from shop/feed availability."""
import unittest
from unittest.mock import patch
import zbozi_fenix


class DummyResponse:
    def __init__(self, code=200, data=None):
        self.status_code = code
        self.data = data or {}

    def json(self):
        return self.data


class FenixAuthTests(unittest.TestCase):
    @patch('zbozi_fenix.requests.get')
    @patch('zbozi_fenix.requests.post')
    def test_valid_key_without_premise_can_connect(self, post, get):
        post.return_value = DummyResponse(data={'access_token': 'temporary-access'})
        get.side_effect = [DummyResponse(data={'id':123}), DummyResponse(code=404)]
        status = zbozi_fenix.probe_feeds('test-refresh-token-123')
        self.assertEqual(status['feed_status'], 'unavailable')
        self.assertEqual(status['feed_http_status'], 404)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(get.call_count, 2)

    @patch('zbozi_fenix.requests.get')
    @patch('zbozi_fenix.requests.post')
    def test_valid_key_and_feeds(self, post, get):
        post.return_value = DummyResponse(data={'access_token': 'temporary-access'})
        get.side_effect = [DummyResponse(data={'id':123}), DummyResponse(data={'items':[{'id':1}]})]
        status = zbozi_fenix.probe_feeds('test-refresh-token-123')
        self.assertEqual(status['feed_count'], 1)

    @patch('zbozi_fenix.requests.post')
    def test_invalid_key_not_saved(self, post):
        post.return_value = DummyResponse(code=401)
        with self.assertRaises(zbozi_fenix.FenixError):
            zbozi_fenix.probe_feeds('invalid-refresh-token')

    @patch('zbozi_fenix.requests.get')
    @patch('zbozi_fenix.requests.post')
    def test_access_token_not_exposed_in_error(self, post, get):
        post.return_value = DummyResponse(data={'access_token': 'secret-access-value'})
        get.return_value = DummyResponse(code=403)
        with self.assertRaises(zbozi_fenix.FenixError) as ctx:
            zbozi_fenix.probe_feeds('test-refresh-token-123')
        self.assertNotIn('secret', str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
