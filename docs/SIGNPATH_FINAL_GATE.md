# SignPath Foundation — выпуск DeiLaw: контрольный список

Этот документ не является подтверждением допуска к SignPath. Работы из PR
являются кандидатом; текущий `LICENSE` пока `All rights reserved`.

## Автоматизировано в исходниках

- [x] Новый NSIS installer (zlib, без внешних plugins) как замена Inno Setup для будущих релизов.
- [x] На установке показывается политика приватности + включение/отключение трёх фоновых сетевых функций.
- [x] На новых установках эти сетевые функции по умолчанию выключены; на старых учитываются сохранённые настройки.
- [x] Установщик сохраняет папку `data` и поддерживает деинсталляцию.
- [x] Регрессионные тесты и source integrity проверки.
- [x] Пример unsigned Windows CI и gated SignPath CI с последовательной подписью EXE и setup.
- [x] Инвентаризация файлов и библиотек с SHA-256, не равнозначна окончательному аудиту лицензий.
- [x] Отдельный `release/license_evidence.json`: проверка SHA-256 сохранённых notice и каталог EXE/DLL/PYD; нет автоматического утверждения о соблюдении LGPL/SignPath.
- [x] Code signing policy и уведомление о статусе подписи на README.

## Нельзя закрыть без владельца, проверенного CI или решения SignPath

- [ ] Владелец проверил авторство всего Python/TS/SQL кода и соавторов; третьи элементы медиа проверены.
- [x] Полный GPL-3.0-only внесён в публичную **подготовительную ветку PR №1**, лицензируется только собственная часть (см. `LICENSE_SCOPE.md`).
- [ ] После полного аудита прав, компонентов и notices перенести GPL-3.0-only в **main** и выпустить соответствующий исходный код с новым релизом; в main пока All rights reserved.
- [x] Добавлен автоматический экспорт присутствующих wheel-лицензий в `THIRD_PARTY_LICENSES` и JSON-отчёт о пропусках (не юридический аудит).
- [ ] Подготовить полный перечень и отсутствующие тексты лицензий Qt DLL/плагинов и зависимостей из нового Windows EXE, решить LGPL compliance и возможные права на OpenSSL/Windows system DLL.
- [x] Windows GitHub Actions успешно собрал неподписанный EXE и NSIS setup: [run #43258654077](https://github.com/DeiZiXX/DeiLaw/actions/runs/43258654077), 101/101 тестов, инвентаризация 220 файлов и 22 Python-пакетов, artifact `Deilaw-unsigned-candidate`.
- [ ] Провести интерактивную проверку Windows-установки/удаления, опций приватности и перехода со старых Inno-версий; CI только **собирал**, без испытания установленного приложения.
- [ ] Подтвердить, что использование NSIS и zlib в поставляемом installer удовлетворяет **именно SignPath** (официальный аудит не заменяется выбором OSS-установщика).
- [ ] Проверить необходимость самостоятельного офлайн-режима / отсутствия обязательного облачного входа и полное соблюдение privacy policy для всех сетевых запросов.
- [ ] В GitHub включить 2FA, защиту main от force-push, PR reviews и ограничения workflows.
- [ ] Назначить maintainer/reviewer и release approver, включить им 2FA.
- [ ] Подать заявку https://signpath.org/apply и **получить её одобрение**; проект должен иметь репутацию и уже существующие публичные OSS-релизы.
- [ ] В SignPath связать GitHub.com Trusted Build System + GitHub App, включить verified origin и создать policies/artifact configurations: отдельные для DeiLaw.exe и DeiLaw_Setup_v*.exe.
- [ ] Установить GitHub secret `SIGNPATH_API_TOKEN`, vars `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_SIGNING_POLICY`, `SIGNPATH_CONFIG_APP`, `SIGNPATH_CONFIG_SETUP` и защищённую Environment `signpath-production` с reviewer approval.
- [ ] Добавить *доверенный* offline Ed25519 публичный ключ в `update_trust.py`; закрытый ключ не загружать в GitHub/чат. Signed update manifest создавать отдельно, после SignPath signing setup.
- [ ] Вручную одобрить каждое подписание и проверить оба артефакта Authenticode перед выпуском.
- [x] CI подписи требует отдельное подтверждение проверки лицензий для полного SHA выпуска, но сам факт подтверждения **не заменяет** документов по правам и внешней проверки.

Работа второго этапа и оставшиеся действия: [PHASE2_STATUS_20261118.md](PHASE2_STATUS_20261118.md).

## Точки отказа по умолчанию

`signpath-release.yml` **не запускает подпись** без применённой GPL,
настроенных secrets/vars и SignPath-проекта. `build_signpath_candidate.ps1`
производит только **неподписанный** setup, пригодный для испытания.

## Переход со старого Inno Setup

Новый NSIS installer специально отказывается в тихом режиме перезаписывать
установку, где лежит `unins000.exe`. Перед миграцией сохраните `data`, удалите
старый Inno setup через Windows и установите NSIS версию. Автоматически
преобразовывать старую установку небезопасно без теста на Windows.

## Источники

- https://signpath.org/terms
- https://docs.signpath.io/trusted-build-systems/github
- https://nsis.sourceforge.io/License
- https://www.gnu.org/licenses/gpl-3.0.html


## Исправление перехода Inno → NSIS и кодировки (18.11.2026)

- NSIS вызывается с `/INPUTCHARSET UTF8`: корректный русский текст в GUI независимо от региональных настроек GitHub Windows runner. `Unicode true` само по себе не задаёт кодировку исходника.
- Существующая установка Inno Setup (`unins000.exe`) **продолжает намеренно блокировать перезапись**; выводится понятная подсказка с копированием `data` и удалением через Параметры Windows → Приложения.
- Безопасная автоматическая миграция без потери данных не заявляется: интерактивное удаление и восстановление пользовательских файлов ещё нужно проверять на Windows. Не удалять чужие файлы из `data` в NSIS.


## Этап GPL-3.0 — повторная Windows CI-проверка (18.11.2026)

- [x] GPL-3.0-only применяется к собственному коду в **публичной ветке PR №1**. В `main` лицензия пока не изменена.
- [x] Автоматически сохраняются wheel-license-файлы в каждом новом Windows onedir/NSIS-кандидате, включая JSON-манифест и SHA-256.
- [x] [Windows CI 44153689429](https://github.com/DeiZiXX/DeiLaw/actions/runs/44153689429): **104 теста OK**, 272 файла, 52 файла в `THIRD_PARTY_LICENSES/`, 22 пакета сборочной среды, новые Qt/license предупреждения не скрыты.
- [ ] Вручную проверить Qt DLL/плагины, OpenSSL, Microsoft runtime, исходный код и лицензии сторонних компонентов; подтвердить возможность замены LGPL-библиотек и наличие всего соответствующего исходного кода.
- [ ] Финально проверить и перенести в `main` после аудита. **Нельзя считать проект уже принятым SignPath.**


## Этап 3 — новые технические проверки и нерешённые пункты (18.11.2026)

- [x] На основе реального unsigned CI [run #44155840585](https://github.com/DeiZiXX/DeiLaw/actions/runs/44155840585): 109 тестов, 282 файла, 61 upstream notice, 105 native файлов; это **не** верификация всех лицензий.
- [x] Ветка PR генерирует `release/component_review.json`: классификация Qt/CPython/OpenSSL/Microsoft Runtime/прочих native компонентов без утверждения о правах на них.
- [x] Windows CI [run #44158776436](https://github.com/DeiZiXX/DeiLaw/actions/runs/44158776436) прошёл 112 unit-тестов и silent NSIS install/reinstall/uninstall с сохранением `data/` и default-deny privacy. Интерактивные Windows/сетевые проверки по-прежнему нужны.
- [ ] Снять ограничения по внешним компонентам: Qt LGPL (заменяемость DLL, upstream sources/notices), MSVC/UCRT (точная квалификация под `System Libraries`), OpenSSL/CPython и другие компоненты.
- [ ] Владелец проверил права на код/соавторов и медиа, утвердил выпуск matching GPL-исходников и названия релиза.
- [ ] Не объединять PR, пока открыт хотя бы один юридический или обязательный UX блокер.

Детали и сценарий ручной проверки: [PHASE3_RELEASE_GATE.md](PHASE3_RELEASE_GATE.md).
