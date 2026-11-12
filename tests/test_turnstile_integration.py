"""No network: CAPTCHA must be sent to Supabase Auth for new anonymous users."""
import unittest
from unittest.mock import patch
from cloud_auth import AnonymousSupabaseSession, CloudAuthError
from turnstile_browser import CaptchaChallengeError

class Store:
    def __init__(self): self.saved={}
    def load(self): return self.saved
    def save(self,payload): self.saved=payload

class Reply:
    ok=True
    def json(self):
        return {'access_token':'temporary-jwt','refresh_token':'temporary-refresh',
                'user':{'id':'abcdef00-1234-4567-8000-123456789abc','is_anonymous':True},
                'expires_in':3600}

class HTTP:
    def __init__(self): self.posts=[]
    def post(self,url,headers,json,timeout):
        self.posts.append((url,json))
        return Reply()

class TestCaptchaSupabaseGuest(unittest.TestCase):
    def test_new_guest_passes_captcha_token_to_signup(self):
        http=HTTP()
        auth=AnonymousSupabaseSession('https://example.supabase.co','public',store=Store(),http=http)
        with patch('captcha_config.TURNSTILE_SITE_KEY','PUBLIC_SITEKEY'), \
             patch('turnstile_browser.get_turnstile_token', return_value='cf-one-time-token') as widget:
            token=auth.select_guest()
        self.assertEqual(token,'temporary-jwt')
        self.assertEqual(http.posts[0][0], 'https://example.supabase.co/auth/v1/signup')
        self.assertEqual(http.posts[0][1]['gotrue_meta_security']['captcha_token'],'cf-one-time-token')
        widget.assert_called_once()

    def test_captcha_error_does_not_create_guest_account(self):
        http=HTTP()
        auth=AnonymousSupabaseSession('https://example.supabase.co','public',store=Store(),http=http)
        with patch('captcha_config.TURNSTILE_SITE_KEY','PUBLIC_SITEKEY'), \
             patch('turnstile_browser.get_turnstile_token', side_effect=CaptchaChallengeError('cancelled')):
            with self.assertRaises(CloudAuthError):auth.select_guest()
        self.assertEqual(http.posts,[])

if __name__=='__main__':unittest.main()
