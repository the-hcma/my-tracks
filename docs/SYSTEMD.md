# Running My Tracks as a systemd User Service

This guide covers how to install, manage, and troubleshoot My Tracks as a
persistent background service using systemd's user session support.

The service runs under your user account (no root required), starts on boot
via lingering on the designated **ConditionHost**, and is managed using
`setup-service` from
[repository-helpers](https://github.com/the-hcma/repository-helpers).

Unit templates live in **repository-helpers**
`share/systemd-unit-templates/`.

## Prerequisites

- systemd user session available (`systemctl --user status` returns output)
- `~/work/ai/repository-helpers` cloned locally
- My Tracks dependencies installed (`bash scripts/setup`)
- `~/.config/user-services-host` set to your service host (or pass
  `--condition-host` on first `setup-service` run)

## Install the Service

Run `setup-service` from the my-tracks repo directory:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

This will:

1. Read `share/systemd-unit-templates/my-tracks.service` from repository-helpers,
   substitute `@@REPO_DIR@@`, inject `ConditionHost=`, and write the result to
   `~/.config/systemd/user/my-tracks.service`.
2. Create the log directory at `~/scratch/my-tracks/`.
3. Enable systemd lingering on the ConditionHost machine.
4. Run `scripts/on-deploy` — applies pending migrations, builds frontend
   assets (including PWA icons via `pnpm run build`), and collects static files.
5. Enable and start (or restart) the service on the ConditionHost only.

The service listens on **`http://localhost:8080`** by default. That is enough for
[PWA](PWA.md) install from the same machine (loopback). Installing from another
device on your LAN requires HTTPS in front of the app — see [PWA.md](PWA.md).

## Check Status

```bash
~/work/ai/repository-helpers/scripts/setup-service --status
```

Or use systemctl directly:

```bash
systemctl --user status my-tracks
```

## View Logs

With `--console`, systemd captures logs in the journal. The `--log-file` flag
also writes them to `~/scratch/my-tracks/my-tracks.log`:

```bash
# Follow live (journal)
journalctl --user -u my-tracks -f

# Follow live (log file)
tail -f ~/scratch/my-tracks/my-tracks.log

# Last 100 lines
journalctl --user -u my-tracks -n 100
```

## Start / Stop / Restart Manually

```bash
systemctl --user start   my-tracks
systemctl --user stop    my-tracks
systemctl --user restart my-tracks
```

## Update After Code Changes

Run `setup-service` again — it re-runs `on-deploy` and restarts the service
if anything changed:

```bash
~/work/ai/repository-helpers/scripts/setup-service
```

At the start of each development session, `start-development --refresh`
handles this automatically:

```bash
~/work/ai/repository-helpers/scripts/dev/start-development --refresh
```

## Service Configuration

The canonical template is
[repository-helpers/share/systemd-unit-templates/my-tracks.service](https://github.com/the-hcma/repository-helpers/blob/main/share/systemd-unit-templates/my-tracks.service).

Key settings:

| Setting            | Value                                                              |
|--------------------|--------------------------------------------------------------------|
| `ExecStart`        | `scripts/my-tracks-server --http-port 8080 --log-level info --console --log-file ~/scratch/my-tracks/my-tracks.log` |
| `ExecStartPost`    | polls `http://localhost:8080/api/health/` (30 × 1 s) to confirm startup |
| `Restart`          | `on-failure`                                                       |
| `RestartSec`       | `5s`                                                               |
| `WantedBy`         | `default.target` (user session)                                    |

To change startup flags (e.g. a different port), edit the template in
repository-helpers and re-run `setup-service`.

## Uninstall

```bash
systemctl --user stop    my-tracks
systemctl --user disable my-tracks
rm ~/.config/systemd/user/my-tracks.service
systemctl --user daemon-reload
```
