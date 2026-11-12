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
- [x] Code signing policy и уведомление о статусе подписи на README.

## Нельзя закрыть без владельца, проверенного CI или решения SignPath

- [ ] Владелец проверил авторство всего Python/TS/SQL кода и соавторов; третьи элементы медиа проверены.
- [ ] Ввести полный GPL-3.0-only в `LICENSE` **отдельным осознанным решением**. Предложенный текст: `docs/GPL-3.0-PROPOSED.txt`. При публикации это выдаёт пользователям права использовать и распространять код на условиях GPL.
- [ ] Подготовить полный перечень и тексты лицензий Qt DLL/плагинов и зависимостей из собранного Windows EXE (не только исходного requirements.txt); решить LGPL compliance.
- [ ] Запустить Windows GitHub Actions, исправить возникающие ошибки NSIS/PyInstaller, проверить установку, обновление со старых Inno-версий и деинсталляцию.
- [ ] Подтвердить, что использование NSIS и zlib в поставляемом installer удовлетворяет **именно SignPath** (официальный аудит не заменяется выбором OSS-установщика).
- [ ] Проверить необходимость самостоятельного офлайн-режима / отсутствия обязательного облачного входа и полное соблюдение privacy policy для всех сетевых запросов.
- [ ] В GitHub включить 2FA, защиту main от force-push, PR reviews и ограничения workflows.
- [ ] Назначить maintainer/reviewer и release approver, включить им 2FA.
- [ ] Подать заявку https://signpath.org/apply и **получить её одобрение**; проект должен иметь репутацию и уже существующие публичные OSS-релизы.
- [ ] В SignPath связать GitHub.com Trusted Build System + GitHub App, включить verified origin и создать policies/artifact configurations: отдельные для DeiLaw.exe и DeiLaw_Setup_v*.exe.
- [ ] Установить GitHub secret `SIGNPATH_API_TOKEN`, vars `SIGNPATH_ORGANIZATION_ID`, `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_SIGNING_POLICY`, `SIGNPATH_CONFIG_APP`, `SIGNPATH_CONFIG_SETUP` и защищённую Environment `signpath-production` с reviewer approval.
- [ ] Добавить *доверенный* offline Ed25519 публичный ключ в `update_trust.py`; закрытый ключ не загружать в GitHub/чат. Signed update manifest создавать отдельно, после SignPath signing setup.
- [ ] Вручную одобрить каждое подписание и проверить оба артефакта Authenticode перед выпуском.

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
