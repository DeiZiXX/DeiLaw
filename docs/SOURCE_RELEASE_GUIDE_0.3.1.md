# Как опубликовать DeiLaw v0.3.1 — исходный код, без неподписанного EXE

1. Убедитесь, что [`main`](https://github.com/DeiZiXX/DeiLaw/tree/main) содержит именно `LICENSE` GNU GPL Version 3 и `app_version.py` со значением `0.3.1`. Источник обновлён через PR №1. Запомните полный SHA коммита ветки `main`.
2. Скачайте приложенный к подготовке `DeiLaw_Source_v0.3.1.zip`, созданный **из этого коммита**. Он содержит исходники приложения, ресурсы и скрипты. Не используйте старые архивы с иной лицензией/коммитом.
3. Откройте https://github.com/DeiZiXX/DeiLaw/releases/new
4. В `Choose a tag` введите `v0.3.1`, затем создайте тег **из текущей `main`** с проверенным SHA. Не используйте старые теги.
5. Название: `DeiLaw v0.3.1 — GPL-3.0 Source Release`.
6. Скопируйте в описание текст из [SOURCE_RELEASE_NOTES_0.3.1.md](SOURCE_RELEASE_NOTES_0.3.1.md).
7. Приложите `DeiLaw_Source_v0.3.1.zip`. GitHub сам предоставит `Source code (zip)` и `Source code (tar.gz)` для тега.
8. **Не** прикладывайте `DeiLaw_Setup_v0.3.1.exe`, пока его третьи лицензии, GUI, приватность и цифровая подпись не подтверждены. Не создавайте `update_manifest.json` для неподписанного кандидата и не заявляйте, что установщик SignPath-approved.
9. Проверьте, что публичная страница релиза показывает нужную версию, лицензию, исходный архив и примечание об отсутствии подписанного EXE. После этого можно использовать её как ссылку на первый GPL-исходный релиз при обсуждении заявки SignPath Foundation.

### Описание для поля GitHub About

> DeiLaw — open-source GPL-3.0 Windows RMRP law assistant: article search, Quick Memo F7/F8/F9, penalty calculator, Cloud AI, updates and community tools.

В настройках репозитория (справа от заголовка **About** → шестерёнка) можно заменить краткое описание и добавить темы: `python`, `pyqt6`, `windows`, `open-source`, `gpl-3`, `rmrp`. Записи в поле About не меняются автоматически через GitHub файловый API.

### Чего это не завершает

Открытая публикация исходников сама по себе не доказывает право на все сторонние материалы или соответствие SignPath. Для подписываемого Windows-установщика остаются [SIGNPATH_FINAL_GATE.md](SIGNPATH_FINAL_GATE.md), [OWNER_RIGHTS_REVIEW.md](OWNER_RIGHTS_REVIEW.md), [PHASE3_RELEASE_GATE.md](PHASE3_RELEASE_GATE.md).
