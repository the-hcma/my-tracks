# Running My Tracks as a systemd User Service

The unit **template** (with `@@REPO_DIR@@`) lives in this repo at
`etc/systemd/my-tracks.service`. `setup-service` from
[repository-helpers](https://github.com/the-hcma/repository-helpers) expands it
into `~/.config/systemd/user/` and mirrors the expanded unit under
`~/.config/share/systemd-units/`.

## Prerequisites

- systemd user session (`systemctl --user status` works)
- [repository-helpers](https://github.com/the-hcma/repository-helpers) cloned locally
- `bash scripts/setup` completed in this repo
- `~/.config/user-services-host` — readable label for the service host (or pass
  `--condition-host` on first setup). On that host, setup captures machine-id into
  `~/.config/user-services-machine-id` and injects `ConditionMachineId=` into units.

## Install

From this repo:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

Default HTTP port is **8080** (`http://localhost:8080`).

## Status, logs, manual control

```bash
~/work/ai/repository-helpers/scripts/setup-service --status
journalctl --user -u my-tracks -f
tail -f ~/scratch/my-tracks/my-tracks.log
systemctl --user restart my-tracks
```

## Configuration

Edit `etc/systemd/my-tracks.service` and re-run `setup-service`.

## Uninstall

```bash
systemctl --user disable --now my-tracks
rm ~/.config/systemd/user/my-tracks.service
rm -f ~/.config/share/systemd-units/my-tracks.service
systemctl --user daemon-reload
```
