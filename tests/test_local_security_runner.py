import unittest

from scripts.test_local_rls import LocalSupabase, NoRedirects, require_local_url
import urllib.request


class LocalSecurityRunnerTests(unittest.TestCase):
    def test_test_runner_accepts_only_local_stack(self):
        self.assertEqual(require_local_url("http://127.0.0.1:54321/"),
                         "http://127.0.0.1:54321")
        self.assertEqual(require_local_url("http://localhost:54321"),
                         "http://localhost:54321")
        for unsafe in (
            "https://project.supabase.co", "http://project.supabase.co:54321",
            "http://127.0.0.1:54322", "https://127.0.0.1:54321",
            "http://localhost:54321@project.supabase.co/",
            "http://localhost:54321/rest/v1", "http://localhost:54321/?x=1",
        ):
            with self.subTest(unsafe=unsafe):
                with self.assertRaises(ValueError):
                    require_local_url(unsafe)

    def test_empty_key_rejected(self):
        with self.assertRaises(ValueError):
            LocalSupabase("http://localhost:54321", "  ")

    def test_external_redirect_is_blocked(self):
        with self.assertRaises(ValueError):
            NoRedirects().redirect_request(None, None, 302, "Moved", {},
                                           "https://production.supabase.co")


if __name__ == "__main__":
    unittest.main()
