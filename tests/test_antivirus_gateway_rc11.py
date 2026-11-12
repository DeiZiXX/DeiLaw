"""Offline HTTP contract checks for optional ClamAV gateway (mock scanner)."""
import importlib.util
import json
import os
from pathlib import Path
import threading
import unittest
from unittest import mock
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT/'security/av_gateway/clamav_gateway.py'
spec = importlib.util.spec_from_file_location('deilaw_av_gateway',MODULE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class AVGatewayContract(unittest.TestCase):
 def setUp(self):
  self.mock_fresh=mock.patch.object(module,'signatures_fresh',return_value=True)
  self.mock_fresh.start()
 def tearDown(self):
  self.mock_fresh.stop()
 @classmethod
 def setUpClass(cls):
  cls.server = ThreadingHTTPServer(('127.0.0.1',0),module.Handler)
  cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True)
  cls.thread.start()
  cls.endpoint=f'http://127.0.0.1:{cls.server.server_address[1]}/scan'
 @classmethod
 def tearDownClass(cls):
  cls.server.shutdown();cls.thread.join(timeout=5);cls.server.server_close()
 def post(self,payload=b'payload-data',token=None):
  headers={'Content-Type':'application/octet-stream'}
  if token is not None:headers['Authorization']='Bearer '+token
  req=Request(self.endpoint,data=payload,headers=headers,method='POST')
  try:
   with urlopen(req,timeout=3) as res:return res.status,json.loads(res.read())
  except HTTPError as err:return err.code,json.loads(err.read())
 def test_rejects_unauthorized(self):
  with mock.patch.dict(os.environ,{'DEILAW_AV_SERVER_TOKEN':'z'*40}):
   self.assertEqual(self.post()[0],401)
 def test_clean_verdict_binds_sha256(self):
  with mock.patch.dict(os.environ,{'DEILAW_AV_SERVER_TOKEN':'z'*40}):
   with mock.patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=0)):
    status,obj=self.post(b'safe-test',token='z'*40)
    import hashlib
    self.assertEqual(status,200)
    self.assertEqual(obj,{'verdict':'clean','sha256':hashlib.sha256(b'safe-test').hexdigest()})
 def test_infected_never_reports_clean(self):
  with mock.patch.dict(os.environ,{'DEILAW_AV_SERVER_TOKEN':'z'*40}):
   with mock.patch.object(module.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
    status,obj=self.post(token='z'*40)
    self.assertEqual(status,200);self.assertEqual(obj['verdict'],'infected')
 def test_signature_database_unavailable_rejects_upload(self):
  with mock.patch.dict(os.environ,{'DEILAW_AV_SERVER_TOKEN':'z'*40}):
   with mock.patch.object(module,'signatures_fresh',return_value=False):
    with mock.patch.object(module.subprocess,'run') as scanner:
     status,_=self.post(token='z'*40)
     self.assertEqual(status,503)
     scanner.assert_not_called()
 def test_health_reports_unavailable_signatures(self):
  req=Request(self.endpoint.replace('/scan','/health'))
  with mock.patch.object(module,'signatures_fresh',return_value=False):
   with self.assertRaises(HTTPError) as exc:urlopen(req,timeout=3)
   self.assertEqual(exc.exception.code,503)
 def test_scanner_failure_is_server_error(self):
  with mock.patch.dict(os.environ,{'DEILAW_AV_SERVER_TOKEN':'z'*40}):
   with mock.patch.object(module.subprocess,'run',side_effect=OSError('no scanner')):
    status,obj=self.post(token='z'*40)
    self.assertEqual(status,503)

if __name__=='__main__':unittest.main()
