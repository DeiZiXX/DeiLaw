# Security Policy

## Секреты

Не коммитьте в репозиторий:

- `OPENAI_API_KEY`;
- Supabase `service_role` / secret key;
- пароли администратора;
- access/refresh tokens;
- `.env` и локальные файлы credentials;
- пользовательские `data/*.db`, identity, логи, бэкапы и вложения.

Cloud AI Edge Function читает серверные секреты через environment variables (`Deno.env`). Desktop-клиент использует только publishable client configuration.

## Сообщить об уязвимости

Не публикуйте рабочие секреты или персональные данные в публичном Issue. Для первичного контакта используйте Telegram: https://t.me/DeiZiS и укажите, что сообщение касается безопасности DeiLaw.

Для обычных ошибок и предложений используйте GitHub Issues.

## Проверка перед публикацией

Запустите:

```bash
python scripts/verify_source.py
```

Скрипт выполняет статическую проверку типовых секретов и компиляцию Python-файлов без сетевых запросов.
