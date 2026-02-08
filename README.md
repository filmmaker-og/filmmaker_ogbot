# filmmaker.og Intelligence Bot

A private Telegram bot that monitors film industry publications and Instagram accounts, delivers new content to your chat, and stores everything in a searchable vault for content planning.

Built for a single operator. Not a public tool, not a SaaS product — a private intelligence pipeline.

## What it does

The bot replaces the daily grind of checking Deadline, Variety, IndieWire, and dozens of Instagram accounts by hand. It monitors your curated source list on a rolling schedule and pushes new content directly to your Telegram chat. You triage each post in seconds with three buttons — Approve, Archive, or Erase — and everything you keep goes into a searchable SQLite vault. When you sit down for a content planning session, your best material from the past week is organized and retrievable by keyword.

## Two source pipelines

- Web publications (RSS): Free, standards-based, low maintenance. Checks Tier 1 trades (Deadline, Variety, IndieWire, TheWrap, Filmmaker Magazine) every two hours and Tier 2 sources (No Film School, Screen Daily, Cineuropa) every four hours.
- Instagram (Apify): Paid service (~$25/month) that handles Instagram's anti-scraping measures. Monitors up to 60 accounts, downloads media, and delivers posts with images embedded directly in the Telegram notification. Captures enhanced metadata including hashtags, location tags, tagged users, video view counts, and follower counts.

## Three-button triage

Every notification arrives with three inline buttons:

| Button | What it does |
|---|---|
| ✅ Approve | Saves to your vault as high-value content worth revisiting. |
| 📦 Archive | Stores as interesting-but-not-actionable (searchable, but hidden from default browsing). |
| 🗑️ Erase | Hides permanently — row stays in the database to prevent duplicate notifications. |

## Searchable vault

- `/vault` opens a browsing interface with separate Approved and Archived views, paged navigation (10 posts per page), full post detail with re-triage buttons, and keyword search powered by SQLite FTS5.
- `/stats` shows a quick count of total posts captured, approved, archived, and erased.

## Prerequisites

Before setup, you need three things:

- A Telegram bot token — create one through [@BotFather](https://t.me/BotFather) on Telegram.
- Your Telegram user ID — get it from [@userinfobot](https://t.me/userinfobot) or similar.
- An Apify API token — sign up at [console.apify.com](https://console.apify.com/) (free tier works for testing).

You also need Python 3.10 or higher installed on your system.

## Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/filmmaker-og/filmmaker_ogbot.git
cd filmmaker_ogbot
pip install -r requirements.txt
```

Copy the config template to its runtime location and edit it with your actual credentials:

```bash
mkdir -p ~/.filmmaker-og-bot
cp config/config.yaml.template ~/.filmmaker-og-bot/config.yaml
nano ~/.filmmaker-og-bot/config.yaml
```

At minimum, you need to fill in:

```yaml
telegram:
  bot_token: "YOUR_BOT_TOKEN"
  allowed_user_id: 123456789       # your numeric Telegram user ID

apify:
  api_token: "YOUR_APIFY_API_TOKEN"
```

Everything else has sensible defaults. See the template file for the full configuration reference, including RSS feed URLs, Instagram account lists, and monitoring intervals.

## Usage

### Starting the bot

```bash
python main.py
```

On first run, the bot validates all credentials, initializes the SQLite database, registers your configured sources, and starts monitoring. You should see output like this:

```text
[INFO] Loading config from ~/.filmmaker-og-bot/config.yaml
[INFO] Validating Telegram bot token... OK (bot: @filmmaker_og_intel_bot)
[INFO] Validating Apify API token... OK
[INFO] Initializing database at ~/.filmmaker-og-bot/vault.db
[INFO] Created tables: accounts, posts, posts_fts
[INFO] Registered 7 Tier 1 RSS feeds, 3 Tier 2 RSS feeds, 10 Instagram accounts
[INFO] Scheduling RSS Tier 1 check every 120 minutes
[INFO] Scheduling RSS Tier 2 check every 240 minutes
[INFO] Scheduling Instagram check every 120 minutes
[INFO] Running initial RSS check...
[INFO] Fetched 47 articles from 7 Tier 1 feeds
[INFO] Bot is running. Press Ctrl+C to stop.
```

Open Telegram, find your bot, and send `/start`. Notifications will begin arriving as the monitoring cycles detect new content.

### Commands

| Command | Description |
|---|---|
| `/start` | Welcome message with basic usage instructions. |
| `/help` | Lists all available commands. |
| `/vault` | Opens the vault menu — browse approved posts, browse archived posts, or search. |
| `/vault search {keywords}` | Keyword search across all non-erased posts. |
| `/stats` | Post counts by triage status. |

## Daily workflow

Notifications arrive throughout the day as sources publish new content. During natural breaks — morning coffee, between meetings, commute — you triage by tapping Approve, Archive, or Erase on each one. When you sit down for a dedicated content session (once or twice a week), you open `/vault`, browse or search your approved posts, and use them as source material.

## Running as a service

For long-running deployment on a VPS, use the included systemd service file:

```bash
sudo cp filmmaker-og-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable filmmaker-og-bot
sudo systemctl start filmmaker-og-bot
```

Check status and logs:

```bash
sudo systemctl status filmmaker-og-bot
journalctl -u filmmaker-og-bot -f
```

The bot automatically restarts on crash or reboot.

## Configuration reference

All configuration lives in `~/.filmmaker-og-bot/config.yaml`. Here are the key sections.

### Monitoring intervals

```yaml
monitoring:
  rss_tier1_interval_minutes: 120    # How often to check Tier 1 RSS feeds (default: 2 hours)
  rss_tier2_interval_minutes: 240    # How often to check Tier 2 RSS feeds (default: 4 hours)
  instagram_interval_minutes: 120    # How often to check Instagram accounts (default: 2 hours)
  failure_alert_threshold: 3         # Alert after this many consecutive failures on a source
```

### RSS feeds

Feeds are organized into two tiers. Tier 1 sources are checked more frequently.

```yaml
rss_feeds:
  tier1:
    - name: "Deadline Film"
      url: "https://deadline.com/v/film/feed"
    - name: "Variety"
      url: "https://variety.com/feed/"
    # ... add more
  tier2:
    - name: "No Film School"
      url: "https://nofilmschool.com/rss.xml"
    # ... add more
```

### Instagram accounts

List Instagram handles (without the `@` symbol). The system supports up to 60 accounts:

```yaml
instagram_accounts:
  - "filmcourage"
  - "nofilmschool"
  - "deadline"
  # ... add up to 60
```

### Storage

```yaml
storage:
  database_path: "~/.filmmaker-og-bot/vault.db"
  media_path: "~/.filmmaker-og-bot/media/"
```

Instagram images are downloaded to the media directory. RSS posts don't download media — the article text is what matters for content planning.

## Project structure

```text
filmmaker_ogbot/
├── main.py                      # Entry point
├── config/
│   └── config.yaml.template     # Configuration template
├── bot/
│   ├── handlers.py              # Telegram command and callback handlers
│   ├── notifications.py         # Notification formatting and delivery
│   └── keyboards.py             # Inline keyboard builders
├── ingestion/
│   ├── rss_monitor.py           # RSS feed checking with feedparser
│   ├── instagram_monitor.py     # Apify integration
│   └── scheduler.py             # APScheduler job setup
├── storage/
│   ├── database.py              # SQLite connection, schema, queries
│   └── media.py                 # Media download and file management
├── requirements.txt
├── install.sh
└── README.md
```

Runtime data is stored outside the repo at `~/.filmmaker-og-bot/`:

```text
~/.filmmaker-og-bot/
├── config.yaml                  # Your configuration (not in repo)
├── vault.db                     # SQLite database
├── bot.log                      # Application logs
└── media/
    └── instagram/               # Downloaded Instagram media
        └── {handle}/
            └── {post_id}_{index}.jpg
```

## Dependencies

| Package | Version | Purpose |
|---|---:|---|
| python-telegram-bot | 20.7 | Telegram Bot API (async). |
| APScheduler | 3.10.4 | Periodic monitoring jobs. |
| feedparser | 6.0.11 | RSS/Atom feed parsing. |
| requests | 2.31.0 | HTTP client for Apify and media downloads. |
| pyyaml | 6.0.2 | Configuration file parsing. |
| python-dotenv | 1.0.1 | Environment variable loading. |

SQLite is built into Python — no external database required.

## Error handling

The bot is designed to never crash. Each pipeline operates independently, so an RSS feed going down doesn't affect Instagram monitoring (and vice versa). Network errors are retried with exponential backoff, malformed RSS or Apify timeouts are logged and skipped, and authentication failures trigger an alert to your Telegram chat and pause the affected pipeline without stopping the bot. After three consecutive failures on any source, you get a warning message identifying which source is broken.

Logs are written to `~/.filmmaker-og-bot/bot.log` with automatic rotation at 10MB (keeps 5 backups).

## Backup

The bot stores all data locally. To back up everything:

```bash
cp -r ~/.filmmaker-og-bot/ ~/filmmaker-og-bot-backup-$(date +%Y%m%d)
```

The critical file is `vault.db` — that's your entire post history and triage decisions. The `media/` directory contains downloaded Instagram images and can be rebuilt from Apify if lost.

## What this bot does *not* do

This is a monitoring and triage tool. It deliberately does not generate content, post to Instagram, automate Canva, provide analytics, or support multiple users. Content generation via Claude API is planned as a future addition — the approved posts in your vault will be waiting for it.
