"""External input and update-metadata security regression tests."""
import io
import unittest
import zipfile
from unittest.mock import patch
from pathlib import Path

import gibdd_charter
from gibdd_charter import (
    _fetch_public_charter, _safe_docx_member, normalize_charter_url,
)
from update_download_security import validate_signed_download

class FakeHTTPResponse:
    def __init__(self, *, data=b"ok", status_code=200, headers=None):
        self.data = data
        self.status_code = status_code
        self.headers = headers or {}
        self.encoding = 'utf-8'
    def __enter__(self): return self
    def __exit__(self,*args): return False
    def raise_for_status(self):
        if self.status_code >= 400:
            raise gibdd_charter.requests.HTTPError('http error')
    def iter_content(self, chunk_size):
        yield self.data

PUBLIC_DNS = [(None,None,None,None,('8.8.8.8',443))]
PRIVATE_DNS = [(None,None,None,None,('127.0.0.1',443))]

class NetworkDownloadSecurityTests(unittest.TestCase):
    def test_url_requires_https_host_and_no_credentials(self):
        for url in ('http://google.com', 'https://127.0.0.1/a',
                    'https://username:password@example.com/',
                    'https://localhost/a', 'https://example.com:8080/',
                    'https://example.com\\@evil.test/a'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):
                    normalize_charter_url(url)
        self.assertEqual(normalize_charter_url('example.com/doc'), 'https://example.com/doc')

    def test_private_dns_is_blocked_before_http_request(self):
        with patch.object(gibdd_charter.socket,'getaddrinfo',return_value=PRIVATE_DNS), \
             patch.object(gibdd_charter.requests,'get') as get:
            with self.assertRaises(ValueError):
                _fetch_public_charter('https://example.com/doc',{})
            get.assert_not_called()

    def test_redirect_to_internal_or_http_target_denied(self):
        response=FakeHTTPResponse(status_code=302,headers={'Location':'http://127.0.0.1/internal'})
        with patch.object(gibdd_charter.socket,'getaddrinfo',return_value=PUBLIC_DNS), \
             patch.object(gibdd_charter.requests,'get',return_value=response) as get:
            with self.assertRaises(ValueError):
                _fetch_public_charter('https://example.com/doc',{})
            self.assertEqual(get.call_count,1)

    def test_streamed_download_is_bounded_even_with_lying_length(self):
        response=FakeHTTPResponse(data=b'x' * (gibdd_charter.MAX_CHARTER_DOWNLOAD+1),headers={'Content-Length':'2'})
        with patch.object(gibdd_charter.socket,'getaddrinfo',return_value=PUBLIC_DNS), \
             patch.object(gibdd_charter.requests,'get',return_value=response):
            with self.assertRaisesRegex(ValueError,'8 МБ'):
                _fetch_public_charter('https://example.com/doc',{})

    def test_safe_public_download_stream(self):
        response=FakeHTTPResponse(data=b'hello',headers={'Content-Type':'text/html'})
        with patch.object(gibdd_charter.socket,'getaddrinfo',return_value=PUBLIC_DNS), \
             patch.object(gibdd_charter.requests,'get',return_value=response):
            data,mime,encoding=_fetch_public_charter('https://example.com/doc',{})
            self.assertEqual((data,mime,encoding),(b'hello','text/html','utf-8'))

    def test_zip_bomb_is_rejected(self):
        stream=io.BytesIO()
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('word/document.xml',b'A'*300000)
        stream.seek(0)
        with zipfile.ZipFile(stream) as archive:
            with self.assertRaisesRegex(ValueError,'сжатие|сжатый'):
                _safe_docx_member(archive,'word/document.xml')

    def test_signed_update_rejects_path_escape_or_unbounded_file(self):
        base={'installer_name':'DeiLaw_Setup.exe','sha256':'a'*64,'size':1234,
              'download_url':'https://github.com/DeiZiXX/DeiLaw/releases/download/v1/DeiLaw_Setup.exe'}
        self.assertEqual(validate_signed_download(base)[2],1234)
        for override in ({'size':10**10},{'installer_name':'../bad.exe'},
                         {'installer_name':'bad\\evil.exe'},
                         {'download_url':'http://github.com/DeiZiXX/DeiLaw/releases/download/v1/a.exe'},
                         {'download_url':'https://github.com.evil.test/DeiZiXX/DeiLaw/releases/download/v1/a.exe'},
                         {'sha256':'not-a-hash'}):
            with self.subTest(override=override),self.assertRaises(ValueError):
                validate_signed_download({**base,**override})

if __name__=='__main__': unittest.main()
