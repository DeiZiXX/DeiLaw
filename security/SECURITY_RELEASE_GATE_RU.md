# Проверка безопасности релиза DeiLaw 0.3.5rc11

**Это набор инструментов, а не сертификат прохождения аудита.**

## 1. Подпись Windows

`build_release.ps1` отказывает в выпуске без настоящего Authenticode-сертификата в Windows Certificate Store и офлайн Ed25519 ключа. Теперь он подписывает **оба** файла: `DeiLaw.exe` и `DeiLaw_Setup_v...exe`, проверяет их с помощью `signtool verify /pa /v`, затем выпускает Ed25519-подписанный манифест GitHub Releases.

Ключ Authenticode должен принадлежать издателю и храниться в защищённом хранилище/HSM. Закрытый ключ Ed25519 не помещайте в исходники, ZIP, GitHub, Supabase или чат. Публичную половину зафиксируйте в `update_trust.py` **до** сборки установщика. Подписи нельзя заменить одним SHA-256.

Проверка на Windows (PowerShell): `Get-AuthenticodeSignature .\release\DeiLaw_Setup_vVERSION.exe` — статус `Valid`. Дополнительно: `signtool verify /pa /v FILE.exe`.

## 2. CAPTCHA и администраторские пароли (требуется доступ владельца к Supabase)

Войдите в [Supabase Auth](https://supabase.com/dashboard/project/ntizjwncrbokebjsfwgu/auth/providers) и настройте Cloudflare Turnstile или hCaptcha в Settings → Authentication → Bot and Abuse Protection. **Не включайте обязательную CAPTCHA для существующего desktop OAuth/password/guest потока до E2E-проверки токена с этих клиентов:** иначе вход может сломаться. Нужны Site key и Secret key стороннего провайдера, секрет хранится только в Supabase. Официальная инструкция: https://supabase.com/docs/guides/auth/auth-captcha

В [Supabase Auth Settings](https://supabase.com/dashboard/project/ntizjwncrbokebjsfwgu/auth/users) включите **Leaked Password Protection** (доступность зависит от тарифа, Pro+ по документации) и минимальную длину пароля не меньше 12; проверьте политику для существующей админской учётной записи и включите MFA администратора. Без этого предупреждения Advisor остаются открытыми.

## 3. Внешний бэкап

`security/backup_encrypted.py` запускайте на отдельной машине с `pg_dump`, `gpg` и доступом к DB. Переменные `PGHOST,PGDATABASE,PGUSER,PGPASSWORD,PGSSLMODE` задавайте только в окружении, не в скриптах/командной строке. Должен существовать GPG публичный ключ получателя (отпечаток указывается `--recipient`). Для запуска:

```
python security/backup_encrypted.py --recipient <GPG_FINGERPRINT> --destination D:\DeiLawBackups
```

Выходной формат — зашифрованный PostgreSQL custom dump, сырой незашифрованный dump не пишется на диск. Для проверки: `python security/backup_restore_check.py D:\DeiLawBackups\...dump.gpg`. **Дополнительно экспортируйте приватные Storage bucket objects** (pg_dump содержит метаданные Storage, но НЕ байты файлов). Для этого есть `security/backup_storage_encrypted.py` с `--recipient`, `--destination` и `--bucket bug-report-attachments`; на резервной машине в окружении должны быть `SUPABASE_URL` и `SUPABASE_SERVICE_ROLE_KEY`, который нельзя сохранять в ZIP/исходниках. Проверяйте восстановление только в отдельной staging DB. Штатное резервирование Supabase не заменяет независимое хранилище. Планируйте задачу Windows Task Scheduler и политику хранения.

## 4. Антивирус файлов

Без внешнего антивирусного шлюза и его секрета нельзя утверждать, что файлы отсканированы. Для безопасного fail-closed режима загрузка новых вложений при недоступности сканера должна отклоняться, но просмотр прежних не должен ломаться. Сервис сканирования обязан возвращать verdict `clean`, проверенный SHA-256, и иметь короткий тайм-аут. Не принимайте решение по клиентскому имени или MIME типу. Релиз с новым scanner gateway требует развернутой среды ClamAV/аналогичного сервиса и отдельного E2E теста.

## 5. Независимый аудит

Перед сертификацией необходим **внешний** security review (инженер, не автор кода), Windows 10/11 smoke + malware scans, SAST/DAST, dependency/SBOM review, Auth/RLS тест с двумя пользователями, полная проверка backup/restore и release pipeline. Внутренние автотесты не являются независимой экспертизой. Нельзя заявлять «100% без уязвимостей».
