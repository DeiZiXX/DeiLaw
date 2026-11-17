# SignPath Foundation — подготовленный текст заявки / eligibility inquiry

**Состояние: не подана.** Форма находится на https://signpath.org/apply.html. Встроенная форма требует действий и контактных данных владельца; нельзя утверждать, что она отправлена. До полноценной заявки нужно выпустить соответствующее OSS-приложение и проверить все компоненты.

## Данные проекта для переноса в форму

**Project / Application name:** DeiLaw

**GitHub repository:** https://github.com/DeiZiXX/DeiLaw

**Contact / maintainer:** DeiZiXX (контакт и 2FA подтверждаются владельцем; личный адрес не подставлять автоматически)

**Type / description (English):**

DeiLaw is an independently maintained Windows desktop companion for role-play players using RMRP. The application provides local legal reference search, notes, penalty calculation, configurable in-game overlays and optional cloud/community features. It is not affiliated with or endorsed by RMRP. The public GitHub repository includes client source code, a cloud function, Windows build scripts, a documented privacy policy and a code signing policy.

**OSS license:** GNU GPL-3.0-only for project-owned source and eligible media. This GPL text is present in a public draft pull request and must be merged to `main` after ownership and third-party license clearance, prior to submission as an *already released* OSS application.

**Current GitHub version:** `0.3.1`; future tag must match release binary and source archive.

**Code signing policy:** https://github.com/DeiZiXX/DeiLaw/blob/prepare/gpl3-signpath-readiness-20261112/CODE_SIGNING_POLICY.md

**Privacy policy:** https://github.com/DeiZiXX/DeiLaw/blob/prepare/gpl3-signpath-readiness-20261112/PRIVACY.md

**Proposed signing:** only the project-owned `DeiLaw.exe` and NSIS `DeiLaw_Setup_v0.3.1.exe`; third-party Qt DLLs are included as unsigned upstream dependencies, not signed as DeiLaw-authored files.

**Build and test evidence:** https://github.com/DeiZiXX/DeiLaw/actions/runs/44162320730 — 116 tests passed; Windows NSIS install/reinstall/uninstall smoke passed; unsigned candidate includes commit-matched project source snapshot and license notices. This is *not* a SignPath build approval.

## Важный вопрос на предварительное согласование

> Subject: DeiLaw Foundation eligibility — GPL-only PyQt6 wheel and Microsoft system libraries
>
> Hello SignPath Foundation team,
>
> We are preparing DeiLaw (https://github.com/DeiZiXX/DeiLaw) as an open-source Windows application distributed under GPL-3.0-only. Our Windows build uses GPL-3.0-only **PyQt6 6.12.0** Python bindings and LGPL/GPL Qt 6.12 dynamic libraries, together with Python and Windows runtime DLLs. Riverbank Computing also offers a separate commercial licensing option for PyQt6, although we use the GPL wheels and do not distribute DeiLaw under a commercial license.
>
> Your Foundation conditions mention “without commercial dual-licensing for all components”. Would this disqualify our use of the **GPL edition** of PyQt6 because the upstream supplier separately offers commercial licensing? We would also appreciate guidance on the treatment of redistributable Microsoft VC/UCRT/API-set runtime DLLs under the GPLv3 System Libraries exception.
>
> The project is already publicly maintained and has passed a Windows CI build with 116 tests and installer smoke tests. Our first fully GPL release and final dependency notices/source review are in preparation, so we are **not yet claiming Foundation eligibility or approval**.
>
> Could you confirm the eligibility interpretation before we publish the new license/release and complete the Foundation application?
>
> Thank you,
> DeiLaw maintainers / @DeiZiXX

## Что пользователь должен сделать

1. Завершить проверку прав, лицензионных условий и GUI/сети, после чего выпустить под GPL **тот же проект**, который хотят подписать. Не объявлять закрытые проверки завершёнными.
2. На [официальной странице](https://signpath.org/apply.html) использовать сведения выше. Если форму нельзя отправить без уже опубликованного GPL-релиза, не указывать ложную дату/статус и предварительно прояснить критерий PyQt6 через подходящий контакт SignPath.
3. Подтвердить в собственных аккаунтах MFA, GitHub branch protection, reviewer, approver и SignPath trusted build integration.
4. После независимого решения SignPath настроить политики/секреты и только после этого отправить `signpath-release.yml` на ручную подпись.

**Запрещено писать “одобрено SignPath” или “подписано SignPath”, пока SignPath не предоставит фактическое одобрение и проверяемый Authenticode.**

## Фактическая GitHub-проверка (18.11.2026)

- GitHub Releases API подтверждает публичный [DeiLaw v0.3.0](https://github.com/DeiZiXX/DeiLaw/releases/tag/v0.3.0), опубликованный **3 октября 2026 года**. Он не является доказательством состоявшегося `GPL-3.0-only` релиза новой версии.
- На дату проверки репозиторный GitHub API `/repos/DeiZiXX/DeiLaw/rulesets` вернул **пустой список**. Это значит, что правил GitHub *rulesets* не найдено. Состояние классической branch protection через подключение проверить не получилось (HTTP 403); нельзя делать вывод, что защиты ветки вообще нет.
- [Актуальные условия SignPath Foundation](https://signpath.org/terms): уже опубликованное в том же виде OSS-приложение, открытая OSI-лицензия без коммерческого двойного лицензирования, роли подписи, MFA и ручное утверждение каждого релиза. PyQt6 имеет коммерческую/ GPL двойную модель у правообладателя ([Riverbank](https://www.riverbankcomputing.com/software/)), поэтому перед формальной заявкой необходимо согласовать именно используемый GPL wheel.
- Официальная заявка **не отправлялась**, доступ владельца к форме и SignPath Foundation credentials не предоставлен.

## Инструмент публикации GPL-кандидата

Новый [`.github/workflows/gpl-release-draft.yml`](../.github/workflows/gpl-release-draft.yml) готовит **только закрытый черновик GitHub Release** после подтверждения прав/лицензий и совпадения полного SHA `main`. Не создаёт SignPath заявку, не выдаёт цифровую подпись и не публикует автоматически. Для официальной публикации требуются реальный аудит и действие владельца в GitHub.
