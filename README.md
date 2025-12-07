# DRFizzleBOT — Lichess bot

Quick notes to run this bot and configure the scheduler.

- Set your Lichess API token as a GitHub Actions secret named `LICHESS_API_TOKEN`.
- Do NOT commit real API tokens into the repository. `config/lichess_api.yml.example` is provided as a template.

Local run

1. Create a virtualenv and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```
2. Export your token and run the bot:
```bash
export LICHESS_API_TOKEN="<your-token-here>"
python DRFizzle-BOT-Lichess/lichess_bot.py
```

GitHub Actions

- The workflow `.github/workflows/lichess-bot-scheduler.yml` runs on weekends at 07:00 America/Chicago (DST-aware).
- The workflow reads the `LICHESS_API_TOKEN` secret and starts a 3-hour shift using `scripts/run_bot_with_standby.sh`.

Standby & graceful shutdown

- The runner sends `SIGUSR1` 5 minutes before the end of the shift to request standby.
- The bot handles `SIGUSR1` by entering standby (stops accepting or issuing challenges).
- The runner sends `SIGTERM` at shift end; the bot handles `SIGTERM`/`SIGINT` and performs cleanup.
# DRFizzleBOT
Runs DRFizzle
