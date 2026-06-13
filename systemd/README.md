# systemd Scheduling

These units are examples for deploying the briefing bot as scheduled one-shot
jobs. They currently target this checkout at:

```text
/home/aureate/code/huginn
```

If you deploy somewhere else, edit `WorkingDirectory`, `EnvironmentFile`, and
`ExecStart` in `briefing@.service` before copying it into systemd.

## Install

```bash
sudo cp systemd/briefing@.service /etc/systemd/system/
sudo cp systemd/briefing-bot.service /etc/systemd/system/
sudo cp systemd/briefing-daily.timer /etc/systemd/system/
sudo cp systemd/briefing-tech.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now briefing-daily.timer
```

Enable additional timers only for profiles that exist in `config.toml`:

```bash
sudo systemctl enable --now briefing-tech.timer
```

The weekend timer expects a `[profiles.weekend]` entry. Add that profile before
enabling `briefing-weekend.timer`.

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
```

The service passes `--send`. For safe manual tests outside systemd, use:

```bash
.venv/bin/briefing run --profile daily
```

## Slash Command Bot

Enable interactive mode in `config.toml`, set `DISCORD_BOT_TOKEN` in `.env`,
then start the long-running bot service:

```bash
sudo systemctl enable --now briefing-bot.service
```
