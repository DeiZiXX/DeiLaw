"""Regression tests of the localhost Turnstile token exchange without Cloudflare."""
from __future__ import annotations
import threading
import unittest
from urllib.parse import urlsplit

import requests
from turnstile_browser import get_turnstile_token, CaptchaChallengeError


class TestTurnstileBrowser(unittest.TestCase):
    def test_loopback_token_is_returned_without_url_or_debug_log(self):
        seen = []
        def fake_open(url):
            seen.append(url)
            def complete():
                resp = requests.get(url, timeout=4)
                self.assertEqual(resp.status_code, 200)
                self.assertIn('https://challenges.cloudflare.com/turnstile/v0/api.js', resp.text)
                self.assertIn('Content-Security-Policy', resp.headers)
                finished = requests.post(url+'/finish', data={'cf-turnstile-response':'signed-test-token'},timeout=4)
                self.assertEqual(finished.status_code, 200)
            threading.Thread(target=complete, daemon=True).start()
            return True
        token = get_turnstile_token('0x4AAAAAA_PUBLIC_TEST_KEY',browser_open=fake_open,timeout=3)
        self.assertEqual(token,'signed-test-token')
        self.assertEqual(len(seen),1)
        self.assertNotIn('signed-test-token',seen[0])
        self.assertEqual(urlsplit(seen[0]).hostname,'127.0.0.1')

    def test_missing_sitekey_is_rejected(self):
        with self.assertRaises(CaptchaChallengeError):
            get_turnstile_token('')

    def test_browser_open_failure_is_rejected(self):
        with self.assertRaises(CaptchaChallengeError):
            get_turnstile_token('0x4AAAAAA_PUBLIC_TEST_KEY',browser_open=lambda _:False)

    def test_wrong_origin_cannot_submit(self):
        def fake_open(url):
            def complete():
                rejected=requests.post(url+'/finish',data={'cf-turnstile-response':'blocked'},
                            headers={'Origin':'https://evil.example'},timeout=4)
                self.assertEqual(rejected.status_code,403)
                accepted=requests.post(url+'/finish',data={'cf-turnstile-response':'signed-token'},timeout=4)
                self.assertEqual(accepted.status_code,200)
            threading.Thread(target=complete,daemon=True).start()
            return True
        self.assertEqual(get_turnstile_token('0x4AAAAAA_PUBLIC_TEST_KEY',browser_open=fake_open), 'signed-token')


if __name__=='__main__': unittest.main()
