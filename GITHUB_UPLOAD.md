# Как загрузить подготовленный репозиторий на GitHub

Репозиторий проекта: `https://github.com/DeiZiXX/DeiLaw`

Если локальная папка ещё не связана с GitHub:

```bash
git init
git branch -M main
git remote add origin https://github.com/DeiZiXX/DeiLaw.git
git add .
git commit -m "Publish DeiLaw v0.3.4 source for verification"
git push -u origin main
```

Если репозиторий уже существует и клонирован:

```bash
git add .
git status
git commit -m "Update source and verification documentation"
git push
```

Перед `git add .` обязательно выполните:

```bash
python scripts/verify_source.py
```

После загрузки откройте GitHub в браузере и проверьте, что видны `README.md`, `main.py`, `ui/`, `ai_core/`, `supabase/functions/deilaw-ai/index.ts` и `docs/VERIFICATION.md`.

## Готовый ответ верификатору

Здравствуйте! Подготовил репозиторий DeiLaw для проверки:  
https://github.com/DeiZiXX/DeiLaw

В репозитории опубликован исходный код desktop-клиента и Cloud AI backend, в README подробно описан функционал и указаны контакты для связи. Для отдельной быстрой проверки добавлен файл `docs/VERIFICATION.md`.
