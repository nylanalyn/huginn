# systemd Scheduling

These units are examples for deploying the briefing bot as scheduled one-shot
jobs. They currently target this checkout at:

```text
/home/aureate/code/huginn
```

If you deploy somewhere else, edit `WorkingDirectory`, `EnvironmentFile`, and
`ExecStart` in `briefing@.service` before copying it into systemd.

## Schedule

| Timer | Profile | When |
|-------|---------|------|
| `briefing-daily.timer` | `daily` | Every day at 05:30 |
| `briefing-tech.timer` | `tech` | Mondays at 06:00 |
| `briefing-weekend.timer` | `ai` | Wednesdays at 06:00 |
| `briefing-local.timer` | `local` | Fridays at 06:00 |
| `briefing-music.timer` | `music` | Saturdays at 06:00 |

`tech`, `ai`, `local`, and `music` are news-only briefings (no weather/calendar).

## Install

```bash
sudo cp systemd/briefing@.service /etc/systemd/system/
sudo cp systemd/briefing-bot.service /etc/systemd/system/
sudo cp systemd/briefing-daily.timer /etc/systemd/system/
sudo cp systemd/briefing-tech.timer /etc/systemd/system/
sudo cp systemd/briefing-weekend.timer /etc/systemd/system/
sudo cp systemd/briefing-local.timer /etc/systemd/system/
sudo cp systemd/briefing-music.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now briefing-daily.timer
sudo systemctl enable --now briefing-tech.timer
sudo systemctl enable --now briefing-weekend.timer
sudo systemctl enable --now briefing-local.timer
sudo systemctl enable --now briefing-music.timer
```

## Check

```bash
systemctl list-timers 'briefing*'
systemctl status briefing-daily.timer
systemctl status briefing-bot.service
journalctl -u briefing@daily.service -n 100 --no-pager
journalctl -u briefing-bot.service -n 100 --no-pager
```

## Manual Run

```bash
sudo systemctl start briefing@daily.service
sudo systemctl start briefing@tech.service
sudo systemctl start briefing@ai.service
sudo systemctl start briefing@local.service
sudo systemctl start briefing@music.service
```

The service passes `--send`. For safe manual tests outside systemd, use:

```bash
.venv/bin/briefing run --profile daily --dry-run
.venv/bin/briefing run --profile tech --dry-run
.venv/bin/briefing run --profile ai --dry-run
.venv/bin/briefing run --profile local --dry-run
.venv/bin/briefing run --profile music --dry-run
```

## Slash Command Bot

Enable interactive mode in `config.toml`, set `DISCORD_BOT_TOKEN` in `.env`,
then start the long-running bot service:

```bash
sudo systemctl enable --now briefing-bot.service
```
