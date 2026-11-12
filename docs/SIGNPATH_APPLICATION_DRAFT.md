# SignPath Foundation: проект заявки для DeiLaw (НЕ ОТПРАВЛЕНА)

- Name: DeiLaw, Windows legal/RP companion for RMRP players (unofficial).
- Repository: https://github.com/DeiZiXX/DeiLaw
- Main source version: 0.3.1. Last verified GitHub release was `v0.3.0`; версия `0.3.1` не является доказанным подписанным релизом.
- Owner candidate: `@DeiZiXX` (подтвердить владельца и MFA).
- Planned OSS license: GPL-3.0-only **not yet applied**, current: All rights reserved.
- Files proposed for signing: `DeiLaw.exe`, `DeiLaw_Setup_v0.3.1.exe`.
- Policy: [CODE_SIGNING_POLICY.md](../CODE_SIGNING_POLICY.md)
- Privacy: [PRIVACY.md](../PRIVACY.md)

## Требования и остающиеся доказательства

| Условие SignPath | Оценка |
| --- | --- |
| Только OSI-одобренные компоненты и отсутствие proprietary-компонентов | БЛОКЕР: текущий `LICENSE`, остаётся независимая проверка возможных сторонних элементов медиа (владелец подтвердил их открытое использование 12.11.2026), неоднозначный статус runtime Inno Setup |
| Реальный поддерживаемый выпущенный OSS-проект | ЧАСТИЧНО: публичный репозиторий и старые релизы есть; OSS-лицензии пока нет, репутацию оценивает SignPath |
| Подпись только своих бинарников из своих источников | НЕТ полного SBOM и доказанной сборки; сторонние DLL отдельно |
| Доверенная CI / origin verification | Ещё не настроены |
| MFA, авторы, ревьюеры, апруверы | Владелец должен подтвердить настройки; подписывание вручную для каждого релиза |
| Ссылка на code signing policy на странице проекта/загрузок | Черновик подготовлен; после принятия добавить в README и Releases |
| Privacy policy при установке + возможность отказаться от необязательных сетевых передач | Privacy.md есть, но установщик ещё не подтверждает соответствие этим требованиям |
| Единые ProductName/ProductVersion; чистая деинсталляция | Исходники содержат 0.3.1 и Inno Setup uninstall, требуется тест готового Windows EXE |

## Вопрос для SignPath до заявления «готово»

'Our project uses GPLv3-licensed PyQt6 and will publish all owned source code. Our Windows setup uses Inno Setup (SPDX `InnoSetup`, separate upstream license). Does its bundled setup runtime satisfy your policy that all shipped components use OSI-approved licenses? If not, we will choose another installer.'

## Рекомендуемые шаги

1. Владелец подтвердил разрешение на открытое использование 12 медиафайлов; проверить возможные чужие элементы, оригинальность кода и права на материалы RMRP.
2. Выбрать допустимый установщик; составить полный SBOM Windows DLL и лицензий.
3. Перевести собственный код на GPL-3.0-only отдельным проверенным PR; приложить notices и исходники соответствующего бинарного релиза.
4. Настроить trusted Windows GitHub Actions build, защиту релизной ветки, тесты и MFA.
5. Подготовить installer-time privacy disclosure и пользовательский выбор для необязательной передачи данных.
6. Подать https://signpath.org/apply, после одобрения интегрировать официальный SignPath CI Action, origin-verification и ручной approve каждого выпуска.

**Ничего не подписано и не сертифицировано этим документом.**


## Уточнение по проверке 12.11.2026

- Лицензионный аудит исходной сборки: 95 тестов OK, все 12 медиафайлов доступны и открываются. Это **не проверка готового Windows-дистрибутива**.
- Inno Setup: `InnoSetup` является отдельной лицензией и не обозначена как OSI-approved в SPDX. **Приостановить заявку** до ответа SignPath или перевода упаковки на компоненты с подходящей лицензией.
- `DeiLaw.iss` не показывает политику приватности при установке и не даёт opt-out для необязательных сетевых функций; `ui/main_window.py` принудительно включает автоопрос обновлений. **Исправить до заявки.**
- `build_release.ps1` требует личный сертификат; SignPath CI не интегрирован и не тестировался. Требуется подтверждённая Windows CI-сборка и перечень реальных DLL.
- Подробный протокол: [SIGNPATH_VERIFICATION_20261112.md](SIGNPATH_VERIFICATION_20261112.md).


## Изменения 13.11.2026 — заявка всё ещё НЕ отправлена

- Inno Setup **планируется заменить** NSIS/zlib в будущей подписываемой сборке:
  `installer/DeiLaw.nsi` и `scripts/build_signpath_candidate.ps1` подготовлены.
  До проверки собранного setup в Windows нельзя отмечать этот критерий выполненным.
- Privacy: подготовлена страница уведомления в установщике и необязательные opt-in
  на фоновые проверки GitHub, RMRP и Supabase. Ручные сетевые запросы, включая
  обязательный на данном этапе облачный вход, описаны в обновлённой Privacy policy;
  это ещё требуется согласовать с критериями SignPath.
- GitHub Actions: source-only workflow для unsigned кандидата и gated SignPath workflow
  с двумя последовательными запросами подписи. **Не проверен на runner**, SignPath
  токен/проекты, правила origin verification и утверждающие не настроены.
- `LICENSE` всё ещё All rights reserved; предложенная GPL находится отдельно
  в `docs/GPL-3.0-PROPOSED.txt`, правовая проверка ещё не завершена.
- Контрольный перечень до реальной заявки: [SIGNPATH_FINAL_GATE.md](SIGNPATH_FINAL_GATE.md).
