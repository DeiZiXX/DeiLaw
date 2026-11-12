# DeiLaw 0.3.1 — предварительный аудит лицензий и авторских прав

Дата: 12.11.2026. Основа: публичное дерево `DeiZiXX/DeiLaw` (коммит `1fea2d230fcac18333b3eee92925a7672222d36f`) и официальная документация поставщиков.

**СТАТУС: ПРАВА НА ВСЕ КОМПОНЕНТЫ НЕ ПОДТВЕРЖДЕНЫ.** Содержимое GitHub само по себе не доказывает авторство. `LICENSE` в `main` по-прежнему `All rights reserved`; данный файл не переводит проект на GPL.

| Компонент | Основание | Предварительная оценка |
| --- | --- | --- |
| Код Python, SQL, TS, сборочные скрипты | В `LICENSE` указан DeiZi / DeiZiXX, но история всех соавторов/заимствований не проверена | Кандидат на GPL-3.0-only после заявления владельца о правах |
| `PyQt6==6.12.0` | GPL-3.0-only или коммерческая лицензия (Riverbank) | GPL-3.0-only подходит |
| Qt DLL и плагины из `PyQt6-Qt6` | Qt LGPL-3.0/GPL-3.0 + сторонние лицензии | Нужен SBOM конкретного Windows-пакета, notices и соблюдение LGPL (в т.ч. возможность замены библиотек, когда требуется) |
| `PyQt6-sip` | BSD-2-Clause | Совместимо |
| `requests==2.34.2` | Apache-2.0 | Совместимо с GPLv3, notices сохранить |
| `beautifulsoup4==4.15.0` | MIT | Совместимо, notices сохранить |
| `cryptography==50.0.2` | Apache-2.0 OR BSD-3-Clause | Совместимо |
| `PyInstaller==6.22.3` | GPL-2.0 с исключением для собранных программ, часть файлов Apache-2.0 | Допустим для сборки; проверить notices фактического пакета |
| `@supabase/supabase-js@2.117.2` и `2.119.0` | MIT | Совместимо; отдельно проверить транзитивные библиотеки |
| Inno Setup и `installer/DeiLaw.iss` | Inno Setup License (`InnoSetup`, особая лицензия) | **Требуется разъяснение SignPath**, допускается ли такой runtime установщика при требовании OSI для всех компонентов |
| ClamAV / Caddy (удалённый VPS) | Отдельные внешние программы | Не входят в Windows-дистрибутив DeiLaw; лицензионные обязанности сервера проверяются отдельно |
| Стандартные Python / Windows API | Системные библиотеки | Проверить фактическую упаковку |

## Неподтверждённые медиа — блокирующие вопросы

Не найдено доказательств оригинального авторства, разрешения на переработку и **публикацию по GPL** для:

- `assets/sounds/report_reply.wav` (аудиозапись может включать отдельные права на текст, голос/исполнение и фонограмму);
- `docs/media/deilaw-icon.png`;
- `installer/assets/deilaw_installer.ico`, `installer_preview.png`;
- `installer/assets/wizard_background.png`, `wizard_small.png`;
- `installer/assets/pages/back_directory.png`, `back_finish.png`, `back_installing.png`, `back_ready.png`, `back_tasks.png`, `back_welcome.png`.

**Действие:** получить от правообладателя лицензию, допускающую открытое распространение, либо заменить материалы оригинальными. Факт передачи файла разработчику, покупка обычного стока или использование генератора изображений **не доказывают** право на перелицензирование.

## Игровое законодательство и сторонние сервисы

В репозитории есть лишь `data/README.md`, а не фактическая база законов RMRP. Программа загружает законы по сети при использовании. GPL для кода DeiLaw не распространяет права на сторонние тексты, товарные знаки RMRP или их графику. Нельзя включать в релиз сторонние материалы без подходящих прав.

Discord, Supabase, OpenAI, GitHub и форум RMRP — удалённые сервисы; условия услуг и приватность нужно раскрывать отдельно. GPL на клиент не означает публикацию чужого серверного кода или API-ключей.

## Чего не хватает до вывода «всё совместимо»

1. Заявления правообладателя о правах на собственный код и вклады соавторов.
2. Реестра подтверждённых авторских прав на каждый медиафайл (см. `ASSET_RIGHTS_REGISTER.md`).
3. SBOM **реального** `DeiLaw_Setup_v0.3.1.exe`: полный список DLL, Qt-плагинов и лицензий транзитивных зависимостей с уведомлениями.
4. Разъяснения Inno Setup/SignPath о лицензии установочного runtime.
5. Финальной проверки соответствия GPL/LGPL и комплекта исходников выпускаемому EXE.

Ссылки: https://www.riverbankcomputing.com/software ; https://doc.qt.io/qt-6/licensing.html ; https://pypi.org/project/requests/2.34.2/ ; https://pypi.org/project/beautifulsoup4/ ; https://pypi.org/project/cryptography/ ; https://www.pyinstaller.org/en/stable/license.html ; https://github.com/supabase/supabase-js/blob/master/LICENSE ; https://github.com/jrsoftware/issrc/blob/main/license.txt ; https://signpath.org/terms .
