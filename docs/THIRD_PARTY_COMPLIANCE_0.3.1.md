# DeiLaw 0.3.1 — проверка третьих лицензий реальной Windows-сборки

Дата оценки: 18.11.2026. Источник: успешный Windows CI [run 44149889835](https://github.com/DeiZiXX/DeiLaw/actions/runs/44149889835) и файлы `DeiLaw_0.3.1_NSIS_UTF8_FIXED_UNSIGNED.zip`, включая `build_inventory.json`.

## Что подтверждено по фактически созданным артефактам

- `build_inventory.json`: 220 файлов в `dist/DeiLaw` и список 22 **установленных в сборочной среде** Python-пакетов. Важно: все 22 **НЕ** обязательно входят в дистрибутив; часть (`pip`, PyInstaller и его hooks) нужна только для сборки. Это не точный перечень runtime-модулей.
- В комплекте есть `PyQt6/Qt6/bin/Qt6Core.dll`, `Qt6Gui.dll`, `Qt6Widgets.dll`, `Qt6Network.dll`, `Qt6Svg.dll`, плагины Qt (`qwindows.dll`, форматы изображений и др.), `opengl32sw.dll`, а также библиотеки Microsoft VC Runtime/UCRT и OpenSSL 3 (`libssl-3.dll`, `libcrypto-3.dll`).
- В указанном исходном бинарном дистрибутиве отдельные LICENSE-файлы обнаружены только в `_internal/cryptography-50.0.2.dist-info/licenses/`. **Этого недостаточно** для одновременного выполнения уведомлений всех сторонних лицензий.
- Информация об оригинальных медиа: [ASSET_RIGHTS_REGISTER.md](ASSET_RIGHTS_REGISTER.md). Заявление владельца не является независимой проверкой отсутствия прав третьих лиц.

## Установленные в CI пакеты

| Пакет | Версия в реальном CI | Примечание |
| --- | --- | --- |
| PyQt6 | 6.12.0 | GPL-3.0-only; Python-обвязки Qt |
| PyQt6-Qt6 | 6.12.0 | LGPL-3.0 для доступного публичного бинарного колеса; проверить модули и плагины |
| PyQt6_sip | 13.13.1 | BSD-2-Clause; сохранить уведомление |
| requests | 2.34.2 | Apache-2.0 |
| beautifulsoup4 | 4.15.0 | MIT |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause |
| certifi | 2026.10.23 | Mozilla Public License 2.0; проверить дистрибутив |
| urllib3 | 2.8.0 | MIT |
| idna | 3.20 | BSD-3-Clause |
| charset-normalizer | 3.5.2 | MIT |
| cffi | 2.1.1 | MIT-0 |
| pycparser | 3.12 | BSD-3-Clause |
| soupsieve | 4.1.1 | MIT |
| typing_extensions | 4.16.0 | PSF-2.0 |
| altgraph | 0.17.5 | Build-time (PyInstaller), проверить фактическую поставку |
| packaging | 26.3 | Build-time, может попасть в PyInstaller bundle |
| pefile | 2024.8.26 | Build-time, проверить фактическую поставку |
| pyinstaller | 6.22.3 | Build-time, bootloader распространяется с исключением |
| pyinstaller-hooks-contrib | 2026.10 | Build-time |
| pywin32-ctypes | 0.2.3 | Build-time |
| setuptools | 84.2.1 | Build-time, может попасть в bundle |
| pip | 26.2.2 | Build-time |

**Точность:** лицензии выше отражают основные upstream-декларации и потребуют проверки пакетов в конкретной сборке; особенно Qt-плагины, сертификаты Mozilla PSL, MSVC/UCRT и OpenSSL 3. Разрешения OSI на «все компоненты» не удостоверены автоматическим тестом.

## Предпринятая автоматизация

В [`scripts/collect_runtime_licenses.py`](../scripts/collect_runtime_licenses.py) добавлен экспорт лицензионных файлов из `*.dist-info` установленной сборочной среды. Скрипт копирует только существующие `LICENSE`, `COPYING`, `NOTICE`, `COPYRIGHT` в `dist/DeiLaw/THIRD_PARTY_LICENSES/`, создаёт JSON manifest с SHA-256 и отдельно отмечает пакеты без этих файлов. Ничего не генерирует «по предположению». Файлы попадают в NSIS setup через `File /r`.

**Ограничение:** сертификаты и GPL/LGPL-лицензии оригинального Qt-колеса могут находиться вне `dist-info`. Поэтому отсутствие у Qt `LICENSE` отмечается как проблема: нужно получить и вложить полные тексты (в том числе LGPLv3 + GPLv3), уведомления и исходники Qt, либо подтверждённый способ их получения. Страницы Qt предусматривают право пользователя заменить/relink динамически поставляемые LGPL DLL; тест запуска с заменёнными библиотеками ещё не проведён.

## Дополнительное доказательство целостности, добавлено в PR №1

`review_windows_bundle.py` на каждом новом Windows-кандидате сверяет SHA-256 фактически собранных upstream-license файлов, формирует список распространяемых EXE/DLL/PYD и сохраняет `release/license_evidence.json`. Отсутствие файла, хеш-несовпадение или пропуск `DeiLaw.exe` блокируют сборочный сценарий. GitHub CI прикладывает этот JSON и оригинальный `license_manifest.json` для независимой проверки. **Это не заменяет полные тексты недостающих лицензий и подтверждение соответствия Qt/LGPL/SignPath**. Проверять состав и точные версии требуется по каждому новому артефакту, а не переносить выводы прошлой сборки.

## Остаточные блокеры до публичного GPL-релиза

- [ ] Получить и включить точные лицензии Qt DLL/плагинов, OpenSSL, Python runtime и других включённых компонентов и проверить `THIRD_PARTY_LICENSES/license_manifest.json` из **новой** сборки.
- [ ] Убедиться, что SSL/VC Runtime/MSVC подпадают под допустимые лицензии или системные библиотеки в политике SignPath и в GPL.
- [ ] Проверить, что GPL исходники поставляются с соответствующим бинарным релизом, не считать старые бинарники автоматически перелицензированными.
- [ ] Протестировать заменяемость динамических Qt DLL/LGPL и разрешённость сторонних Qt-плагинов.
- [ ] Подтвердить авторские права на весь собственный код, включая вклады возможных соавторов; медиа подтверждены только заявлением владельца.

Источники: [SignPath условия](https://signpath.org/terms), [Riverbank PyQt](https://www.riverbankcomputing.com/software/), [PyQt6-Qt6](https://pypi.org/project/PyQt6-Qt6/6.12.0/), [обязательства Qt](https://www.qt.io/faq/qt-open-source-licensing), [PyInstaller лицензия](https://www.pyinstaller.org/en/stable/license.html), [NSIS license](https://nsis.sourceforge.io/License).


## Повторная проверка Windows CI — второй этап GPL (18.11.2026)

[GitHub Actions run 44153689429](https://github.com/DeiZiXX/DeiLaw/actions/runs/44153689429) **завершился успешно**. Подтверждено: `104` теста OK, `DeiLaw.exe` и NSIS installer собраны, новый `build_inventory.json` учитывает **272 файла** и прежние **22 пакета сборочного окружения**. Из них **52 файла** находятся в `THIRD_PARTY_LICENSES/`, включая `license_manifest.json`. Скрипт вывел «Priority packages without upstream license file: none». Сборка доступна только как **неподписанный тестовый artifact**.

Это подтверждает наличие license-файлов установленных wheel-пакетов, а не юридическую проверку каждого Qt DLL и OpenSSL/Windows runtime и не выполнение LGPL с правом замены библиотек. Исходный исторический аудит 220-файлового комплекта выше сохранён для сравнения.
