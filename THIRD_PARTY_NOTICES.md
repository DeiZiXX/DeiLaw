# DeiLaw third-party licenses and notices — release audit draft

This is a **license inventory, not a complete certified Windows SBOM**. Before
shipping a GPL release, inspect the actual `release/build_inventory.json`, the
PyInstaller `_internal` directory, bundled Qt libraries/plugins, license files,
and all transitive dependencies. Publish their complete license texts/required
notices with the binary, and provide corresponding source code when required.

| Component | Upstream licensing | Distribution use |
| --- | --- | --- |
| PyQt6 6.12.0 | GPLv3, or separate commercial license | GPL-3.0-only is intended for owned DeiLaw sources. Preserve relevant notices. |
| Qt6 libraries & plugins | LGPLv3 / GPLv3 and separate third-party terms | Inventory actual DLLs/plugins and satisfy LGPL replacement/relinking requirements where applicable. |
| PyQt6-sip | BSD-2-Clause | Include notice when deployed. |
| Requests 2.34.2 | Apache-2.0 | Include copyright & license notices. |
| Beautiful Soup 4.15.0 | MIT | Include license notice. |
| Cryptography 50.0.2 | Apache-2.0 OR BSD-3-Clause | Preserve license conditions. |
| PyInstaller 6.22.3 bootloader | GPL-2.0 with exception and some Apache-2.0 materials | Include appropriate license and exception. |
| NSIS installer | zlib/libpng for core/used zlib compressor (see upstream for exceptions) | Uses `SetCompressor zlib`; do not add third-party plugins without audit. |
| supabase-js 2.117.2 / 2.119.0 | MIT | Server-only, not bundled in desktop EXE. |

Upstream sources:

- https://www.riverbankcomputing.com/software/pyqt/license
- https://doc.qt.io/qt-6/licensing.html
- https://pypi.org/project/requests/
- https://pypi.org/project/beautifulsoup4/
- https://pypi.org/project/cryptography/
- https://pyinstaller.org/en/stable/license.html
- https://nsis.sourceforge.io/License

**STOP CONDITION**: This draft alone is not sufficient for a public signed
release. Supply the required actual license texts from package metadata and Qt
components after the Windows build. Never assert that audit is complete when
any component license/provenance is unknown.
