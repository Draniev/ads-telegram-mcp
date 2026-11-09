# ads-telegram-mcp

English | [Русский](README.md)

An MCP server for working with Telegram Ads from AI assistants.
Browse accounts and ads, query statistics, get monthly reports,
choose targeting options, create and edit ads, fund ads and return unused budget,
submit them for review and upload media.

The server runs locally over **stdio**. It provides **20 tools**:
14 for reading data and 6 for changing ads and budgets and uploading media.

## Installation

Requirements:

- Python **3.15 or later**;
- [uv](https://docs.astral.sh/uv/);
- An API token from [Telegram Ads settings](https://ads.telegram.org/account/api);
- An MCP client with stdio support.

Video uploads also require `ffprobe` from [FFmpeg](https://ffmpeg.org/download.html)
in the server process's `PATH`. Text ads and photos do not require it.

Download the project source, open its directory and install the dependencies:

```sh
cd ads-telegram-mcp
uv sync --locked
cp .env.example .env
```

Open `.env` and set the list of tokens, even if you only have one:

```dotenv
TELEGRAM_ADS_TOKENS=["your_api_token"]
```

## Configuration

The server reads `.env` from the project root regardless of the working directory.
Environment variables override `.env`, including empty values.
You can set these values in the MCP client's environment instead of the file.
`.env` is excluded from Git.

### Multiple keys

Put the tokens in one JSON array. You can also supply a second array of
unique names in the same order:

```dotenv
TELEGRAM_ADS_TOKENS=["first_token", "second_token", "third_token"]
TELEGRAM_ADS_TOKEN_NAMES=["personal", "agency", "test"]
```

In this example, `agency` selects the second token. If `TELEGRAM_ADS_TOKEN_NAMES`
is omitted, use the string labels `"1"`, `"2"`, `"3"` and so on.
Restart the MCP server after changing `.env`.

`list_profiles` returns the names or labels in configuration order, without
keys. Pass the desired value as `profile`, for example to `get_current_account`:

```json
{"profile": "agency"}
```

With one token, `profile` is optional. With multiple tokens, it is required.
Unknown names are rejected before any API request.

The legacy `TELEGRAM_ADS_TOKEN` variable is used only when `TELEGRAM_ADS_TOKENS`
is unset. An empty array `[]` means no keys are configured.

### Account within a profile

`profile` selects the key. For tools that accept `account_id`, the account
under that key is selected in this order:

1. The `account_id` passed to the tool.
2. `TELEGRAM_ADS_ACCOUNT_ID`, if only one token is configured.
3. The account that owns the token.

`get_current_account` always returns the token owner's account.
`list_related_accounts` retrieves the token owner's related accounts,
while `get_accounts_by_id` uses the supplied list of IDs.
To access the token owner's account when a default account is configured,
pass its ID explicitly.

Targeting catalogues and channel/bot lookups accept `profile`, but do not
accept `account_id`: their scope is determined by the selected profile's key.
Use the same profile and account for related operations, such as uploading
media and creating an ad, or retrying a budget top-up.

## Connecting to an MCP client

For clients that use `mcpServers` configuration:

```json
{
  "mcpServers": {
    "telegram-ads": {
      "command": "uv",
      "args": [
        "--directory", "/absolute/path/ads-telegram-mcp",
        "run", "--locked", "python", "-m", "ads_telegram_mcp"
      ]
    }
  }
}
```

Replace `/absolute/path/ads-telegram-mcp` with the project's absolute path.
If your MCP client cannot find `uv`, set `command` to the executable's full path.
The token will be loaded from `.env`.

For Codex, add this to `~/.codex/config.toml`:

```toml
[mcp_servers.telegram_ads]
command = "uv"
args = ["--directory", "/absolute/path/ads-telegram-mcp", "run", "--locked", "python", "-m", "ads_telegram_mcp"]
tool_timeout_sec = 300
```

Restart the MCP connection after saving the configuration.

To start the server manually from the project directory:

```sh
uv run --locked python -m ads_telegram_mcp
```

When started manually, the server waits for MCP messages on stdin.
It is normal to see no prompt or terminal output.

## Usage

Once connected, ask your assistant, for example:

- "Show the current Telegram Ads account's balance and currency."
- "List the first 20 ads and their statuses."
- "Get daily account statistics for last week and calculate the spend."
- "Show last week's totals separately for each ad."
- "Show the monthly ad report for October 2026."
- "Validate two new ads using dry_run."
- "Upload a photo and create a paused ad with it and no budget."
- "Find the Travel topic ID and the Istanbul location in Turkey for targeting."
- "Get the ID and name of the channel @example_placement."
- "Resume ad 42."
- "Add 5 units of the account currency to ad 42's budget."

The assistant selects the tools and supplies their parameters.
Data access depends on the API token's permissions.

## Available tools

| Tool | Returns |
|---|---|
| `list_profiles` | Profile names and the default profile, without keys or API requests. |
| `get_current_account` | The token owner's account, balances and currency. |
| `list_related_accounts` | One page of related accounts. |
| `get_accounts_by_id` | Account details for a list of IDs. |
| `list_ads` | One page of ads from the selected account. |
| `get_ads_by_id` | Ads for a list of IDs, optionally including targeting. |
| `get_account_stats` | Account statistics for a period, split into intervals. |
| `get_ad_stats` | Statistics for one ad over a period, split into intervals. |
| `get_ads_stats` | Period totals for selected or all ads, optionally including interval data. |
| `get_account_report` | Monthly totals for active ads in an account. |
| `get_targeting_options` | A complete catalogue of languages, topics or countries. |
| `get_target_locations` | All location search results for a country and query. |
| `get_target_channel` | A channel's ID and available details by username or numeric ID. |
| `get_target_bot` | A bot's ID and available details by username or numeric ID. |
| `create_ads` | Results of creating one or more ads, or local validation with `dry_run`. |
| `increase_ad_budget` | The result of transferring funds from the account to one ad's budget. |
| `decrease_ad_budget` | The result of returning funds from an ad's budget to its account balance. |
| `edit_ad` | The result of changing the supplied fields of one ad, including pause or resume. |
| `submit_ad_for_review` | The result of explicitly submitting one ad for moderation. |
| `upload_media` | The uploaded ad photo, video or website image ID and validated file metadata. |

### Targeting catalogues

`get_targeting_options` accepts `catalog`:

| `catalog` | Data in `options` |
|---|---|
| `languages` | `language_code` and the language name. |
| `topics` | `topic_id` and the topic name. |
| `countries` | `country_code` and the country name. |

Languages, topics and countries are returned as complete lists in one tool call.

Example: get all topics:

```json
{"catalog": "topics"}
```

The response contains `catalog`, the complete `options` list and the number of
returned entries, `total_count`. You do not need to manage pagination.

The server does not cache or save catalogues: every call queries the API.
The model instructions recommend reusing catalogues already retrieved and
normally refreshing them no more than once a week. An explicit request to
refresh them or signs of stale data are reasons to fetch them again.

Pass the returned codes and IDs to `create_ads` as `language_codes`,
`topic_ids` and `country_codes` within the appropriate `target` type.
For `channels`, language and topic refer to placements; for `users`, they refer
to users and their interests. Countries and locations apply to `users`.

### Location search

Call `get_target_locations` separately when location targeting is needed.
Both `country_code` (a two-letter country code) and a nonblank `query` are required.
The tool automatically retrieves all pages of search results:

```json
{"country_code": "TR", "query": "Istanbul"}
```

The response contains `locations` and the number of returned entries, `total_count`.
Each location has a `location_id` and name, plus country and region when available.
Pass the ID in `location_ids` when creating an ad with `users` targeting.
The API does not provide a global list of all locations without a search query.

There is no programmatic cache. You can reuse previously retrieved results
for the same country and query.

### Channels and bots for targeting

`get_target_channel` accepts `channel_id`, and `get_target_bot` accepts `bot_id`.
Pass an `@username` or numeric ID. For channels, you can also set
`for_excluding=true` when resolving a channel to exclude from targeting.

The response contains `channel_id` or `bot_id` and, when available, `title`,
`username` and `photo_url`. These methods do not return subscriber counts,
reach, CPM or placement performance statistics.
Using a numeric ID requires prior username resolution by the same account.
You can pass usernames directly to `create_ads`; a separate ID lookup
before each creation is not required.

### Creating ads

`create_ads` accepts a nonempty `ads` list. Shared parameters:

- `account_id`: the account, selected using the configuration rules above;
- `dry_run=false`: when `true`, validates only input data without API requests;
- `stop_on_error=true`: stops creating further items after the first error.
  When `false`, processing continues; authentication, permission and rate-limit
  errors always stop the batch. Unexpected client errors also stop further writes.

Each ad requires `title`, `promote_url`, `cpm`, `placement`, `target` and
`idempotency_key`. `text` is required except for `search` targeting.
Targeting types are `channels`, `users`, `bots` and `search`; each type's
parameters are described in the tool schema. `placement` is set separately
from the targeting type.

Example: validate one ad locally:

```json
{
  "dry_run": true,
  "ads": [
    {
      "title": "First variant",
      "text": "Travel routes and notes in our channel.",
      "promote_url": "https://t.me/example_channel",
      "cpm": 0.3,
      "placement": "channel_post",
      "target": {"type": "channels", "channel_ids": ["@example_placement"]},
      "idempotency_key": "3b284a89-7d93-48e0-986d-7866a90d8801"
    }
  ]
}
```

Replace the example with your own parameters. Set `dry_run=false` to create the ad.
The allowed CPM depends on the account and ad parameters; the example value is
illustrative. Local validation does not verify permissions, available budget,
bid eligibility, media IDs or moderation approval. During a dry run, the currency
is not queried and is returned as `null`.

By default, `initial_budget=0` and `is_paused=true`. A positive `initial_budget`
transfers funds from the account to the ad and may trigger automatic submission
for review. `activate_date` and `deactivate_date` override the paused state
according to API rules. All monetary parameters use the selected account's currency.

External website settings, photos or videos, frequency, a daily limit, dates,
schedules and an existing conversion event are supported. External links require
`website_name`. You cannot use `photo_id` and `video_id` together.

The response contains `account_id`, `currency`, counters, `complete` and `results`
in the original order. Each result has a zero-based `index`, its key and an `outcome`:

- `succeeded`: a successful API response and ad data were received;
- `failed`: the request was rejected;
- `unknown`: the outcome is unconfirmed, for example because of a network error;
- `not_attempted`: the item was not attempted after the batch stopped.

`complete=true` means all items succeeded. Ads already created remain in place
if the batch only partially succeeds. A successful response may be a replay
of an earlier request rather than a newly created ad.

When retrying, keep the same `profile`, `idempotency_key` and all ad parameters.
Telegram retains the result for a key for up to 24 hours. After that,
the same request may create another ad. The server preserves item order,
repeated keys and duplicate ads. Use `get_ads_by_id` for additional details.

### Managing an existing ad

`increase_ad_budget`, `decrease_ad_budget`, `edit_ad` and `submit_ad_for_review`
operate on one `ad_id` per call. All accept `profile` and `account_id` using
the configuration rules above, plus `return_target=false`.
Set `return_target=true` to include targeting in the returned ad.

`increase_ad_budget` transfers funds from the account to an ad's budget.
`amount` is a positive **increment**, not the desired final balance,
in the selected account's currency. A stable `idempotency_key` is required:

```json
{
  "ad_id": 42,
  "amount": 5,
  "idempotency_key": "4fb8ee23-9d37-4529-b9ec-cb0ec4d71ae3"
}
```

When retrying within 24 hours, keep the same profile, key and all parameters.
A new key or a retry after that period may transfer funds again.
The pause state is unchanged; funding may resume delivery if other conditions
allow. The tool does not make a separate review-submission call.

`decrease_ad_budget` returns `amount` from the ad's remaining budget to its
account balance. Pass a positive amount in the account's currency and an
`idempotency_key`, just as for a top-up. Telegram checks that the ad has been
inactive for at least 10 minutes and has enough budget remaining.

`edit_ad` accepts a nonempty `changes` object. Only supplied, non-null fields
are changed; omitted fields and `null` are ignored. To resume an ad:

```json
{"ad_id": 42, "changes": {"is_paused": false}}
```

To change the bid and daily limit:

```json
{"ad_id": 42, "changes": {"cpm": 0.5, "daily_budget_limit": 10}}
```

You can change the title, text, URL, CPM, media, website settings, frequency,
daily limit, pause state, dates and schedule. Targeting and placement cannot
be changed with this method. Individual fields have these effects:

- `is_paused=true` pauses delivery; `false` resumes it and may enable spending.
  Changing the pause state clears activation and deactivation dates; if new dates
  are supplied, they take precedence over `is_paused` according to API rules.
- `daily_budget_limit=0` removes the daily limit; `schedule=false` removes the schedule.
- A new `photo_id` or `video_id` replaces existing media.
- `conversion_event_id` can only be set while it is unset;
  `additional_info` also cannot be changed once set.
- Editing a funded ad may trigger review. The API checks compatibility
  with the ad's current state.

`submit_ad_for_review` explicitly submits an ad with status `ready_for_review`
for moderation:

```json
{"ad_id": 42}
```

Creating or editing a funded ad may already submit it for review automatically;
the extra call is only needed for the appropriate status. The tool does not
add budget or change the pause state. After approval, the ad may start running
if other conditions allow.

All four tools return `account_id`, `ad_id`, `currency`, `outcome` and the original
`ad` object on success, or a safe `error` description. Both budget tools also return
`idempotency_key`. The possible `outcome` values are:

- `succeeded`: a successful API response was received;
- `failed`: the API or client rejected the request;
- `unknown`: the write outcome is unconfirmed, for example because the response was lost.

For `unknown`, inspect the ad with `get_ads_by_id` before further actions.
For a budget transfer retry within 24 hours, preserve the original key,
profile and parameters. Editing and review submission have no key:
check the current fields or status first. Invalid input and account-lookup
errors are returned as tool errors before any write.

### Uploading media

`upload_media` accepts an absolute `file_path` on the machine running the server,
`kind` and an optional `account_id`. The file is uploaded to Telegram Ads.

| `kind` | Requirements |
|---|---|
| `ad_photo` | JPEG/PNG, up to 5 MiB, width at least 640 px, 16:9. |
| `ad_video` | MP4, up to 20 MiB, width at least 640 px, 16:9, 3–60 seconds. Requires `ffprobe`. |
| `website_photo` | JPEG/PNG, up to 1 MiB, at least 150×150 px. |

The response contains `account_id`, `kind`, `photo_id`/`photo_url` or
`video_id`/`video_url`, plus `metadata` with the format, file size,
frame dimensions and video duration.

Pass the returned ID to `create_ads`. You can reuse it for multiple ads
in the same account. Uploading the same file again may return a new ID.
Uploading media alone does not create an ad.

### Statistics for multiple ads

`get_ads_stats` retrieves statistics for each ad in a single MCP call.
Pass `from_time` and `to_time`, along with these optional parameters:

- `ad_ids`: a list of IDs. An empty or omitted list selects all ads available
  in the account's list, including stopped ads. The server retrieves all list
  pages automatically. A supplied list of IDs is used unchanged.
- `include_timeseries`: defaults to `false`. Set to `true` to add the original
  statistics rows for each interval alongside the totals.
- `interval`: 86400 seconds by default, or 300 seconds.
- `account_id`: the account, selected using the configuration rules above.

Example parameters for all ads from October 30 through November 5, 2026, in UTC:

```json
{
  "from_time": 1793318400,
  "to_time": 1793923200,
  "ad_ids": []
}
```

For selected ads, replace `[]` with a list such as `[101, 202]`.

In the response, `ads` contains each ad's `ad_id`, the number of data points
(`data_points`) and `totals`: views, opens, clicks, actions, spend and currency.
If the API returns an empty time series, `totals` is `null`.
With `include_timeseries=true`, each item also includes `stats` with interval data.

Check `complete`, `succeeded_count`, `failed_count` and `errors`:
if an individual ad fails, the server returns the available results and marks
the response as incomplete with `complete: false`. Authentication, permission
or rate-limit errors stop the operation.
`total_count` is the number of processed ID list entries, including duplicates;
`from_time` and `to_time` in the response are the period bounds after rounding
down to the start of an interval.

The number of Telegram API requests depends on the number of ads.
For large accounts, increase the tool timeout in your MCP client.

### Parameters and limits

- Account IDs are strings. Ad IDs are integers and are unique within an account.
- `list_ads` and `list_related_accounts` return 20 entries by default;
  `limit` ranges from 1 to 100.
  These tools do not automatically retrieve all pages. For related accounts,
  increase `offset` by the number of returned entries until reaching `total_count`.
  For ads, pass the returned `next_offset` unchanged while it is present
  in the response.
- `get_accounts_by_id` and `get_ads_by_id` accept 1 to 100 IDs per call.
- For `list_ads` and `get_ads_by_id`, set `return_target=true` to include
  targeting settings in the response. It is disabled by default.
- Statistics require `from_time` and `to_time` in Unix seconds.
  The start is inclusive and the end is exclusive. `interval` defaults to
  **86400** seconds; **300** seconds is also supported.
  Bounds are rounded down to the start of an interval; a period must span
  no more than **1000 intervals**. For `get_ads_stats`, at least one interval
  must remain after rounding.
- For monthly reports, set `year` from 2021 to 2100 and `month` from 1 to 12.
- Monetary values are returned in the account's currency: `EUR`, `TON` or `XTR`.

If a tool reports a missing key or profile, check `.env` and the MCP client's
environment: an empty environment variable overrides the value in the file.

## Dependencies and documentation

Main dependencies: [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk),
[TeleAd](https://github.com/Elimeshi1/TeleAd), a Telegram Ads API client,
Pydantic, pydantic-settings, AnyIO and Pillow. Versions are specified in
`pyproject.toml` and pinned in `uv.lock`.

- [Telegram Ads API](https://ads.telegram.org/docs/api).
- [Architecture, adding tools and checks (in Russian)](docs/development.md).

## License

[MIT](LICENSE). Copyright (c) 2026 Sergei Popov.
