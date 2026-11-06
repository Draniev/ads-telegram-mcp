# ads-telegram-mcp

Модульный **MCP-сервер** через stdio: MCP-хост вызывает инструменты,
а сервер обращается к Telegram Ads через синхронный Python-клиент TeleAd.
Основа использует официальный MCP Python SDK **2.x** (`MCPServer`).

## Запуск

Нужны `uv` и Python 3.15, как в исходном проекте пользователя.

```sh
cd /Users/spopov/dev/ads-telegram-mcp
uv sync --locked
uv run --locked python -m ads_telegram_mcp
```

Либо `uv run --locked python main.py`. Сервер ожидает JSON-RPC на stdin;
отсутствие приглашения в терминале нормально. stdout занят протоколом MCP,
сообщения SDK идут в stderr.

## Авторизация и подключение

API-токен берётся в настройках Telegram Ads: <https://ads.telegram.org/account/api>.
Браузерная сессия служит для чтения документации и не авторизует API-сервер.
Токен задаётся переменной **`TELEGRAM_ADS_TOKEN`** в окружении MCP-хоста
или в `.env` в корне проекта (рядом с `pyproject.toml`). `Settings` использует
`pydantic-settings` и загружает этот файл независимо от рабочего каталога запуска.
Скопируйте `.env.example` в `.env` и заполните нужные значения локально.
Приоритет: явные аргументы `Settings(...)`, переменные окружения, `.env`,
значения по умолчанию. Пустая переменная окружения тоже перекрывает `.env`.
Пробелы по краям значений удаляются; пустой account ID означает владельца токена.
Сервер не запрашивает токен аргументом инструмента; поле токена исключено
из repr и сериализации настроек. `.env` исключён из Git.

Необязательная **`TELEGRAM_ADS_ACCOUNT_ID`** задаёт связанный аккаунт по умолчанию.
Явный `account_id` у инструмента имеет приоритет. Если оба не заданы,
используется владелец токена. `get_current_account` всегда возвращает владельца
токена; `get_accounts_by_id` использует переданный список ID;
`list_related_accounts` возвращает связанные аккаунты владельца токена.
Для обращения к владельцу токена при настроенном default укажите его ID явно.

Пример JSON-конфигурации для MCP-хоста, поддерживающего `mcpServers`:

```json
{
  "mcpServers": {
    "telegram-ads": {
      "command": "/Users/spopov/.local/bin/uv",
      "args": [
        "--directory", "/Users/spopov/dev/ads-telegram-mcp",
        "run", "--locked", "python", "-m", "ads_telegram_mcp"
      ],
      "env": {
        "TELEGRAM_ADS_TOKEN": "<supply locally>",
        "TELEGRAM_ADS_ACCOUNT_ID": ""
      }
    }
  }
}
```

Это пример, подключение к MCP-хосту автоматически не менялось.
Если используете `.env`, удалите секцию `env` из примера: иначе её значения
перекроют файл, включая пустой `TELEGRAM_ADS_ACCOUNT_ID`.
Без токена сервер запускается и отдаёт `tools/list`; вызов API-инструмента
вернёт MCP-ошибку с именем недостающей переменной.

## Первые инструменты

Все восемь инструментов только читают данные.

| Область | MCP-инструмент | TeleAd |
|---|---|---|
| Аккаунты | `get_current_account` | `get_current_account` |
| Аккаунты | `list_related_accounts` | `get_related_accounts_list` |
| Аккаунты | `get_accounts_by_id` | `get_accounts_by_id` |
| Объявления | `list_ads` | `get_ads_list` |
| Объявления | `get_ads_by_id` | `get_ads_by_id` |
| Статистика | `get_account_stats` | `get_account_stats` |
| Статистика | `get_ad_stats` | `get_ad_stats` |
| Отчёты | `get_account_report` | `get_account_report` |

- Списки возвращают одну страницу: по умолчанию 20 записей, максимум 100.
  Для связанных аккаунтов увеличивайте числовой `offset` на число полученных
  элементов до `total_count`. Для объявлений передавайте `next_offset` без изменений.
- Групповые запросы ID ограничены обёрткой до 100 элементов за вызов;
  это локальный предел, а не утверждение о лимите Telegram.
- Таргетинг включается `return_target=true`, по умолчанию выключен.
- Даты статистики — Unix seconds, период `[from_time, to_time)`.
  API округляет границы к началу интервала; интервалы 300 или 86400 секунд,
  максимум 1000 интервалов. Месячный отчёт: `year` и `month`.
- Денежные значения сохраняются в валюте ответа (`EUR`, `TON`, `XTR`).
- Ответы — исходные API payload из `model.raw`, без дублирования typed/raw.
  Массивы оборачиваются в `accounts`, `ads`, `stats` или `report`.
  Новые поля API сохраняются. Сокращения полей и агрегирования пока нет.
- Ошибки TeleAd преобразуются в MCP tool errors. Наружу не передаются
  тела ошибочных ответов и транспортные сообщения. Для API-ошибок сохраняются
  код и HTTP-статус. Timeout чтения 30 секунд, максимум один повтор средствами
  TeleAd; с учётом подключения и backoff весь вызов может длиться дольше.

## Как расширять

```text
ads_telegram_mcp/
  __main__.py        # python -m
  server.py          # сборка MCPServer и запуск stdio
  config.py          # pydantic-settings: окружение и .env проекта
  execution.py       # typed операции с TeleAd, worker thread, ошибки MCP
  tools/
    __init__.py      # явный реестр областей
    common.py        # общие типы параметров и annotations
    accounts.py     # аккаунты
    ads.py          # объявления
    stats.py        # статистика и отчёты
docs/
  telead-coverage.md # краткая сверка покрытия API
tests/
  test_server.py    # проверки без сети
  test_execution.py # составные операции и время жизни Client
  test_settings.py  # источники настроек и их приоритет
```

Для новой области добавьте `tools/targeting.py`, `budgets.py`, `audiences.py`,
`media.py` или `pixel.py` с `register(server, runner)` и включите модуль
в реестр. Внутри регистрируйте функции с явными Python-параметрами через
`@server.tool(...)`; вызывайте методы клиента через `await runner.run(operation)`.
`TeleAdRunner.run` принимает синхронную функцию `Client -> T` и возвращает `T`
без преобразования моделей в словари. Для короткого вызова подойдёт lambda,
для нескольких API-вызовов и обработки результатов — обычная функция.

```python
from telead import Client
from telead.models import Ad

def load_active_ads(client: Client) -> list[Ad]:
    # Два последовательных вызова через один Client; здесь явно выбран владелец токена.
    account = client.get_current_account()
    page = client.get_ads_list(account_id=account.account_id, limit=20)
    return [ad for ad in page.ads if ad.status == "active"]

# Внутри async MCP-инструмента:
ads = await runner.run(load_active_ads)
return {"ads": [ad.raw for ad in ads]}
```

`TeleAdRunner` создаёт один Client на всю операцию и закрывает его по её
завершении, включая ошибку. Операция целиком выполняется в worker thread:
цикл MCP не блокируется, HTTP-сессии не разделяются между параллельными операциями.
Генераторы и итераторы TeleAd нужно прочитать внутри операции, пока Client открыт.
Составные операции вызывают методы Client и обычные функции обработки;
вызывать собственные MCP-инструменты через MCP внутри сервера не требуется.
MCP-инструмент формирует конечный ответ: использует `model.raw` для исходного
payload либо выбирает и агрегирует поля типизированных моделей. Сериализацию
ответа в JSON выполняет MCP SDK. Общего рекурсивного адаптера нет.
Реальные методы TeleAd доступны только из кода; универсального MCP-инструмента
для произвольного API-вызова нет.

Для будущих изменений объявлений задавайте собственные MCP annotations:
`READ_ONLY` предназначен только для чтения. При добавлении бюджетов/создания
объявлений явно опишите последствия и передавайте стабильные idempotency keys
для повторения одной бизнес-операции; автоключ TeleAd защищает только повторы
внутри одного вызова клиента. Компрессию ответов, агрегаты, batch-операции
и выбор областей при запуске можно добавить на этих границах позже.

## Локальная проверка

```sh
uv run --locked python -m unittest discover -s tests -v
```

HTTP в проверках подменён; subprocess stdio запускается без токена.
Проверяются пагинация, выбор аккаунта, сохранение новых полей API,
валидация, скрытие транспортных подробностей, MCP initialize/list/call и завершение,
составные операции с типизированными результатами, рабочий поток и закрытие Client.
Никаких запросов к реальным кабинетам.

Источники: [Telegram Ads API](https://ads.telegram.org/docs/api),
[TeleAd](https://github.com/Elimeshi1/TeleAd),
[официальный MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk).
