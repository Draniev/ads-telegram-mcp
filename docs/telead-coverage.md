# Беглая сверка TeleAd с Telegram Ads API

Дата: **5 ноября 2026**. Официальная документация открыта под пользовательской
сессией: <https://ads.telegram.org/docs/api>. Последнее изменение на странице —
**18 сентября 2026**. Сверены список методов и основные параметры с локальными
исходниками `/Users/spopov/dev/TeleAd/telead/client.py` и установленным
`telead==0.1.1`; эти два файла клиента совпадают.

**Результат: 44 из 44 актуальных методов представлены именованными методами
TeleAd.** Ещё один заголовок документации, `editAdStatus`, помечен Deprecated;
его замена — `editAd(..., is_paused=...)`, у TeleAd есть `pause_ad`/`resume_ad`.

| Область | Количество | Имена методов API, покрытых TeleAd |
|---|---:|---|
| Аккаунты, бюджеты, транзакции, отчёты | 12 | createAccount, editAccountInfo, getAccountInfo, getRelatedAccountsList, increaseAccountBudget, decreaseAccountBudget, getTransactionStatus, getCurrentAccount, getAccountsById, getAccountTransactionsList, getAccountStats, getAccountReport |
| Медиа | 3 | uploadAdPhoto, uploadAdVideo, uploadWebsitePhoto |
| Объявления | 10 | createAd, editAd, increaseAdBudget, decreaseAdBudget, submitAdForReview, deleteAd, getAdsById, getAdsList, getAdTransactionsList, getAdStats |
| Аудитории | 5 | createAudience, editAudience, deleteAudience, getAudiencesById, getAudiencesList |
| Пиксель и события | 7 | createPixel, getPixel, createPixelEvent, editPixelEvent, deletePixelEvent, getPixelEventsById, getPixelEventsList |
| Таргетинг и справочники | 7 | getTargetLanguagesList, getTargetTopicsList, getTargetCountriesList, getTargetLocationsById, getTargetLocationsList, getTargetChannel, getTargetBot |

Также видны четыре входных типа таргетинга (channels/users/bots/search),
расписание, currency, placement, conversion_event_id и submitAdForReview.
Базовый URL `https://promoteapi.telegram.org`, Bearer-авторизация,
JSON/multipart и обработка `ok/result/error` соответствуют описанию API.
Есть исходный `Client.call`, idempotency keys, retries и helpers пагинации.

При использовании важно:

- Account ID — строка, ad ID — целое число внутри аккаунта.
- `get_current_account` не переключается на default related account;
  scoped методы принимают `account_id`.
- У различных списков разные offsets: счётчик и непрозрачный `next_offset`.
- Деньги имеют валюту аккаунта; суммы нельзя считать всегда евро или TON.
- Числовые ID каналов/ботов требуют предварительного разрешения username
  тем же аккаунтом; документация рекомендует usernames.
- `is_paused` у `editAd` сбрасывает activate/deactivate dates.
- У TeleAd синхронный requests-клиент; MCP-обёртка выносит вызов в worker thread.

Это **инвентаризация интерфейсов**, без аудита каждой ветки валидации,
каждого поля модели и политики повторов. Наличие метода не доказывает его
корректность или доступность конкретному аккаунту. Работа сервера Telegram,
права токена и операции с реальными кабинетами не проверялись.
Первый MCP-каркас публикует только 8 инструментов чтения; остальное покрытие
относится к библиотеке TeleAd, а не к текущему набору MCP-инструментов.
