# knw

Exports all topics and messages from a Telegram forum to JSON, ready to use as
input for a knowledge graph.

## Requirements

- [uv](https://docs.astral.sh/uv/) (installs Python 3.13+ automatically)

## Setup

1. Get your API credentials at <https://my.telegram.org> -> API development tools.
2. Export the required environment variables.

## Configuration

All configuration is read from environment variables. Secrets (`KNW_API_ID`,
`KNW_API_HASH`) are never hardcoded.

| Variable | Required | Default | Description |
| --- | --- | --- | --- |
| `KNW_API_ID` | yes | — | Your Telegram api_id (number) |
| `KNW_API_HASH` | yes | — | Your Telegram api_hash |
| `KNW_GROUP_IDENTIFIER` | yes | — | Group username, invite link, or numeric ID |
| `KNW_SESSION_NAME` | no | `mi_sesion` | Local `.session` filename (reusable, kept out of git) |
| `KNW_TOPICS_DIR` | no | `topics` | Output folder; one subfolder per topic |
| `KNW_DOWNLOAD_MEDIA` | no | `true` | Set to `false` to skip media downloads |
| `KNW_MEDIA_DOWNLOAD_RETRIES` | no | `4` | Retries per file before giving up |

## Usage

```bash
export KNW_API_ID=12345
export KNW_API_HASH=abcdef1234567890abcdef1234567890
export KNW_GROUP_IDENTIFIER="https://t.me/+ABC123"

uv run main.py
```

The first run will ask for your phone number (with the country prefix, e.g. `+54 11 2345 6789`) and a code sent to your Telegram.

### Real-time listening (incremental)

Once the bulk export is done, keep the group updated without re-downloading
everything. New messages are captured as they arrive and written straight into
the same `topics/<topic_id>_<title>/data.json` (same format as the bulk
export; files are written atomically).

```bash
export KNW_API_ID=12345
export KNW_API_HASH=abcdef1234567890abcdef1234567890
export KNW_GROUP_IDENTIFIER="https://t.me/+ABC123"

uv run main.py --listen
```

Leave it running in the background (tmux, screen, systemd). If you re-run the
bulk export while the listener is on, both write `data.json` and the last
writer wins — re-run the bulk export afterwards to flatten everything.

The General topic (no topic, `topic_id` 0) lives in `0_General/`; it is not
part of the bulk export.

### Optional: one-liner

```bash
KNW_API_ID=12345 KNW_API_HASH=abcdef... KNW_GROUP_IDENTIFIER=... uv run main.py
```

## Output

Each topic gets a `topics/<topic_id>_<title>/` folder containing:

- `data.json` — messages with ids, dates, senders, text, captions, and media metadata
- `media/` — downloaded files (unless `KNW_DOWNLOAD_MEDIA=false`)

Plus `topics/_index.json` with a lightweight summary of all topics.

## Security notes

`.env`, `*.session`, and `topics/` are gitignored so credentials and exported
data never end up in version control. If you want to ship your own `.env`
template, create `.env.example` committing only placeholder values.
