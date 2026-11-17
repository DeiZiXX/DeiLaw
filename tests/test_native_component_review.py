"""Phase 3 controls: native binary attribution is transparent and fail-closed."""
import unittest
from scripts.classify_native_components import classify_inventory, classify

class NativeComponentReviewTests(unittest.TestCase):
    def test_grouping_flags_microsoft_and_qt_individually(self):
        rows = [
            {"path": "DeiLaw.exe", "sha256": "0" * 64},
            {"path": "_internal/PyQt6/Qt6/bin/Qt6Core.dll", "sha256": "1" * 64},
            {"path": "_internal/PyQt6/Qt6/bin/MSVCP140.dll", "sha256": "2" * 64},
            {"path": "_internal/libcrypto-3.dll", "sha256": "3" * 64},
            {"path": "_internal/python313.dll", "sha256": "4" * 64},
            {"path": "_internal/unknown.dll", "sha256": "5" * 64},
            {"path": "_internal/not-a-binary.txt", "sha256": "6" * 64},
        ]
        result = classify_inventory({"files": rows})
        self.assertEqual(result["counts"]["microsoft_runtime"], 1)
        self.assertEqual(result["counts"]["qt"], 1)
        self.assertEqual(result["counts"]["openssl"], 1)
        self.assertEqual(result["counts"]["cpython"], 1)
        self.assertEqual(result["counts"]["other_native"], 1)
        self.assertEqual(result["counts"]["deilaw"], 1)
        self.assertTrue(result["classification_only_not_legal_clearance"])
        self.assertEqual(result["release_clearance_status"], "BLOCKED_MANUAL_REVIEW")

    def test_required_exe_and_unique_paths(self):
        with self.assertRaisesRegex(ValueError, "DeiLaw.exe"):
            classify_inventory({"files": [{"path": "_internal/x.dll"}]})
        with self.assertRaisesRegex(ValueError, "duplicate"):
            classify_inventory({"files": [{"path": "DeiLaw.exe"}, {"path": "DeiLaw.exe"}]})

    def test_unassigned_native_binary_requires_review(self):
        self.assertEqual(classify("_internal/custom.dll"), "other_native")
        self.assertEqual(classify("_internal/ucrtbase.dll"), "microsoft_runtime")
        self.assertEqual(classify("_internal/PyQt6/Qt6/plugins/platforms/qwindows.dll"), "qt")

if __name__ == "__main__":
    unittest.main()
