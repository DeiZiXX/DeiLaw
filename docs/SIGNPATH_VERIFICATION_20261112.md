# DeiLaw 0.3.1 — результаты проверки SignPath Foundation / GPL

Дата: 12 ноября 2026 г. Основание: архив исходников `DeiLaw_0.3.1_FIXED_BUILD_WITH_ICON.zip` и GitHub `DeiZiXX/DeiLaw`.

**Результат: НЕ ГОТОВО к подаче в SignPath.** Проверка не является юридическим заключением, сертификацией безопасности, независимой аудиопроверкой или доказательством отсутствия вредоносного ПО.

## Фактически выполненные проверки

| Проверка | Результат | Что означает |
| --- | --- | --- |
| `scripts/verify_source.py` | OK, 58 Python-файлов | Базовая структура, компиляция/синтаксис, распространённые шаблоны секретов |
| `python -m unittest discover -s tests -q` | 95/95, OK | Пройден имеющийся набор автоматических модульных тестов |
| Распаковка исходного ZIP | OK, 137 элементов | Все ожидаемые исходники и 12 медиафайлов присутствуют |
| Изображения | 11 PNG/ICO корректно открываются | На визуальном осмотре нет очевидных чужих игровых логотипов, известных персонажей или официальной эмблемы RMRP. Отсутствие совпадений не доказано |
| Звук | WAV PCM, 16 бит, mono, 44.1kHz, 2.194 с | Поток читается. Кто его создал/озвучил и с какими правами — по формату не установить |
| Медиа права | Декларация владельца зафиксирована 12.11.2026 | Разрешение на будущую открытую публикацию получено; третьи права не проверены |
| Официальные лицензии | PyQt GPL-3.0; Requests Apache-2.0; Beautiful Soup MIT; cryptography Apache/BSD; PyInstaller GPL с исключением | Основные прямые зависимости предварительно совместимы; список **фактических транзитивных DLL** не проверен |
| Windows EXE / setup | НЕ ПРОВЕРЕНО | Готового комплекта `dist/DeiLaw` и установщика в исходном ZIP нет, Windows-сборку в данной среде не проводили |
| GitHub Actions / SignPath signing | НЕ НАСТРОЕНО | `build_release.ps1` использует локальные Authenticode-ключи и не является SignPath pipeline |

## SHA-256 проверенных медиафайлов

Хеш устанавливает неизменность конкретных байтов; **не устанавливает права собственности**.

| Файл | SHA-256 |
| --- | --- |
| `assets/sounds/report_reply.wav` | `12a45009e4072929fbae11dbb43bd1bbe75bb9b803763eead760d417e619c2fc` |
| `docs/media/deilaw-icon.png` | `916ceec0133879d3edfeeae36d89ef315bfccc9ca05c5880cb38fd76e535bbee` |
| `installer/assets/deilaw_installer.ico` | `aa49cf1b7a89a62fde66ad023321f28a9720917a0bb2d64b085a067cdfda0f73` |
| `installer/assets/installer_preview.png` | `a71fbf01623831d45b0e4c28e0ae2da5b08a62bfdae534883658c5a9751d45a9` |
| `installer/assets/pages/back_directory.png` | `2a25f9f195ae90f2308fb7a664d866b18ba72dded952301524b6d8f1fe2d6180` |
| `installer/assets/pages/back_finish.png` | `8561fb299474519a3849625dec0174e7d83f858e513c1145935ae037e13deb70` |
| `installer/assets/pages/back_installing.png` | `4454c59f2293e9b2c679bece3d10f786a330f8067cd08faf7e2ab1189dfdb272` |
| `installer/assets/pages/back_ready.png` | `a59c57c35599b4df2a04478c0607de6a68998e84ef6ec3e877b5688ae3c1ad6f` |
| `installer/assets/pages/back_tasks.png` | `db3f60522e40c232b212da0fbdccb828164c874ad849cca8ab8304c5917bce91` |
| `installer/assets/pages/back_welcome.png` | `79cab1c8a030afdca7541cb51ac58e41b9b864c11b0fc9b6d03feb4f91f293d3` |
| `installer/assets/wizard_background.png` | `3735062544551262a2cd24ef30421884f994f3ef8e768a1fba195e512ede3a39` |
| `installer/assets/wizard_small.png` | `5f1a6b7b58de771b7944ba9ef5d2488453742cb2a1b075e3b2c5a56afa38e199` |

## Важные проблемы для заявки

1. **Лицензия проекта:** корневой `LICENSE` пока `All rights reserved`. GPL-3.0-only ещё не введена. Нельзя заявлять ОСS-совместимость, пока переход не оформлен.
2. **Установщик Inno Setup:** лицензия `InnoSetup` отдельно указана в SPDX, однако не помечена как OSI-approved. SignPath требует OSI-approved для **всех** компонентов. Не делаем поспешный вывод, что установщик точно запрещён: нужен ответ SignPath по включённому runtime либо миграция, например на NSIS с лицензионной проверкой выбранных компрессоров/плагинов.
3. **Конфиденциальность:** `installer/DeiLaw.iss` не содержит страницы с политикой и флажков отключения необязательных внешних передач. `updater.py` настроен на проверку при старте, а `ui/main_window.py` (`update_program_update_monitor_state`) принудительно включает проверки и делает переключатель неактивным. Условие SignPath о privacy policy + installer opt-out может требовать доработки. **До SignPath — реализовать и проверить на Windows.**
4. **Состав приложения:** отсутствуют фактически собранные Windows DLL, Qt-плагины, транспонированные зависимости и комплект лицензий. Нужна свежая CI-сборка на Windows, SBOM и third-party notices.
5. **Code signing pipeline:** `build_release.ps1` использует личный Authenticode; SignPath использует доверенные сборки и **ручное одобрение каждого подписания**. Нужна отдельная интеграция, MFA/роли/review, управление доверенным источником.
6. **Авторство всего кода:** заявление о правах на медиа есть; инвентаризация вкладов в код и внешних копирований не подтверждена независимо.
7. **Предыдущие релизы:** в публичном репозитории есть более старые установщики. Убедиться, что поставка GPL PyQt в каждой старой версии соответствует её лицензии; по одному только новому дереву это нельзя подтвердить.

## Подтверждающие первоисточники

- SignPath условия: https://signpath.org/terms
- Inno Setup SPDX: https://spdx.org/licenses/InnoSetup.html
- NSIS лицензия: https://nsis.sourceforge.io/License
- Riverbank PyQt: https://en.riverbankcomputing.com/software/pyqt
- Qt: https://doc.qt.io/qt-6/licensing.html
- Requests: https://pypi.org/project/requests/2.34.2/
- BeautifulSoup: https://pypi.org/project/beautifulsoup4/4.15.0/
- Cryptography: https://pypi.org/project/cryptography/50.0.2/
- PyInstaller: https://pypi.org/project/pyinstaller/6.22.3/

## Следующий порядок действий

1. В PR подтвердить происхождение кода и медиа и решить сторонние права.
2. Для Inno Setup запросить разрешимость SignPath либо подготовить OSI-совместимую альтернативу и проверить готовую сборку.
3. Добавить installer-time privacy policy и реальные переключатели необязательной сетевой активности; проверить на Windows.
4. Собрать unsigned Windows build из CI, зафиксировать SBOM и notices.
5. Отдельным, осознанно одобренным изменением ввести GPL-3.0-only на собственные материалы; не применять её к внешним игровым текстам.
6. После выполнения требований и накопления репутации проекта подать заявку в SignPath Foundation. **Не представлять заявку как уже одобренную.**


## Дополнение 13.11.2026: работы по подготовке

Этот отчёт описывает исходную проверку **до исправлений**. В отдельной ветке после неё
подготовлены NSIS installer (вместо Inno Setup), privacy opt-in, GitHub Actions Windows
candidate and gated SignPath signing workflow. Локальная статическая проверка
исходников и **100 модульных тестов** прошла. Однако реальные Windows установщик,
подписи и полный SBOM ещё не проверены. Подробности:
[SIGNPATH_FINAL_GATE.md](SIGNPATH_FINAL_GATE.md).
