"""The release scanner must inspect project source, not pip's vendor code."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from scripts import verify_source

class SourceVerifyTests(unittest.TestCase):
    def test_skips_venv_binaries_and_catches_project_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'.venv'/'Lib'/'site-packages').mkdir(parents=True)
            (root/'.venv'/'Lib'/'site-packages'/'foreign.py').write_text('sk-'+ 'A'*35)
            (root/'project.py').write_text('print("hello")')
            with patch.object(verify_source, 'ROOT', root):
                names=[p.relative_to(root).as_posix() for p in verify_source.project_files()]
                self.assertEqual(names, ['project.py'])
                errors=[]
                verify_source.check_secrets(errors)
                self.assertEqual(errors,[])
                (root/'oops.env').write_text('OPENAI=sk-' + 'B'*35)
                verify_source.check_secrets(errors)
                self.assertEqual(len(errors),1)

if __name__=='__main__': unittest.main()
