# Code signing policy — DeiLaw / ПОДГОТОВКА

**Статус:** проект пока НЕ принят SignPath Foundation. Никакой доступный
релиз нельзя называть подписанным SignPath, пока не получен реально
проверенный Authenticode артефакт.

После одобрения проекта официальное упоминание SignPath:

> Free code signing provided by SignPath.io, certificate by SignPath Foundation

## Roles / Роли

- Maintainer / author and reviewer: [@DeiZiXX](https://github.com/DeiZiXX),
  при условии подтверждения владения и MFA. Вклады других авторов — только через
  PR с ревью. Для участия независимых ревьюеров их необходимо назначить в GitHub.
- SignPath release approver: **не назначен**. Владелец должен назначить роль в
  SignPath после одобрения и требовать ручного одобрения каждого запроса.
- Signing submitter: GitHub Actions, только с проверенным origin verification,
  никогда не локальный двоичный файл неизвестного происхождения.

**MFA обязательно** для всех авторов/ревьюеров/утверждающих релизы.

## Signing process

1. Обязательный PR, code review, без force-push, защищённые ветки,
   проверка изменений сборочных сценариев и зависимостей.
2. Сборка из конкретного GitHub commit на GitHub-hosted Windows runner с
   проверкой тестов и сохранением исходного SHA и списка файлов.
3. GitHub Actions workflow `.github/workflows/signpath-release.yml` формирует
   сначала бинарный `DeiLaw.exe`, передаёт GitHub artifact в SignPath, ждёт
   **ручного одобрения**, проверяет Authenticode, а затем собирает NSIS setup,
   отдельно подписывает и проверяет его в SignPath.
4. В SignPath администратор настраивает GitHub.com trusted build system,
   устанавливает SignPath GitHub App, включает origin verification и разрешает
   только защищённую релизную ветку; артефактные конфигурации для EXE и setup
   имеют ограничения ProductName=DeiLaw и единой версии.
5. Публичный выпуск требует отдельно проверенного GPL-3.0-only LICENSE,
   актуального Third Party Notices, исходного кода и подтверждения прав на
   проектные аудио/изображения и DLL.
6. Для **автоматических обновлений** дополнительно требуется проверяемый
   Ed25519-манифест; Authenticode не заменяет ключ подписи манифеста.

## Privacy and user choice

Политика: [PRIVACY.md](PRIVACY.md). Installer показывает
[PRIVACY_INSTALL.txt](installer/PRIVACY_INSTALL.txt) и предлагает выбор для
необязательных фоновых сетевых подключений; их значения по умолчанию — OFF.
Сетевые запросы по явному действию пользователя описаны в PRIVACY.
Согласие на облачную авторизацию и условия внешних сервисов проверяется отдельно.

## Incident handling

При компрометации токена, ключа, действий подписи или pipeline приостановить
подписание и публикацию, сообщить SignPath и пользователям, при необходимости
отозвать подписанный выпуск. Секреты не помещать в исходники, артефакты или логи.

## Upstream rules

- https://signpath.org/terms
- https://docs.signpath.io/trusted-build-systems/github
- https://docs.signpath.io/origin-verification/
