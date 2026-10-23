# Running My Tracks as a systemd User Service

The unit **template** (with `@@REPO_DIR@@`) lives in this repo at `etc/systemd/my-tracks.service`. `setup-service` from [repository-helpers](https://github.com/the-hcma/repository-helpers) expands it into `~/.config/systemd/user/` and mirrors the expanded unit under `~/.config/share/systemd-units/`.

## Prerequisites

- systemd user session (`systemctl --user status` works)
- [repository-helpers](https://github.com/the-hcma/repository-helpers) cloned locally
- `bash scripts/setup` completed in this repo
- `~/.config/user-services-host` — short hostname label for the service host (or pass `--condition-host` on first setup)
- `~/.config/user-services-host-fqdn` — FQDN on the service host (or `--condition-host-fqdn`)
- `~/.config/user-services-machine-id` — machine-id from `/etc/machine-id`; setup injects `ConditionHost=|` guards (see repository-helpers `docs/SYSTEMD.md`)

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

## Hardening

The unit sets `NoNewPrivileges=true`, `PrivateTmp=true`, `ProtectSystem=full` (read-only `/usr`, `/boot` and `/etc`) and `RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX` (HTTP, MQTT, the database socket when PostgreSQL is local, and the C library's interface listing; raw packet sockets are not used) and `SystemCallArchitectures=native` (on a host that also runs 32-bit x86 code, the address-family filter does not cover those calls, so systemd recommends pinning the architecture).

`NoNewPrivileges`, `RestrictAddressFamilies` and `SystemCallArchitectures` are enforced everywhere. `PrivateTmp` and `ProtectSystem` need a mount namespace, which a user manager builds inside an unprivileged user namespace. Where that is not allowed (`kernel.apparmor_restrict_unprivileged_userns=1`, the default on recent Ubuntu; observed on Ubuntu 24.04 with systemd 255), systemd starts the unit without them and without an error, so `systemctl --user show` reports them as set even though they do nothing. To see what a unit really gets, run `readlink /proc/self/ns/mnt` inside a transient unit (`systemd-run --user --wait --pipe -p PrivateTmp=true readlink /proc/self/ns/mnt`) and compare it with the same command in your shell: the same value means no mount namespace.

Where `PrivateTmp` is enforced, a local PostgreSQL whose Unix socket lives under `/tmp` (the default of source builds; the Debian and Ubuntu packages use `/var/run/postgresql`) becomes unreachable for the service, because it sees an empty private `/tmp`: point `DATABASE_URL` at a socket directory outside `/tmp`, or set `PrivateTmp=false` in a drop-in. The default SQLite database and a PostgreSQL reached over TCP are not affected.

`PrivateTmp` is worth having: the MQTT broker writes its TLS key and certificates to the temp directory for the SSL context, and a private `/tmp` that systemd removes at stop keeps them from lingering after a crash. `ProtectHome` and `ProtectSystem=strict` stay off on purpose, because the log is under the home directory and the SQLite database and media live in the checkout. `SystemCallFilter=` stays off because it can break a service at runtime.

Before adding a directive, run the real server under it in an isolated transient unit on other ports and check `/api/health/`, the MQTT broker and the web UI. Run it from a separate checkout or worktree, never the one the installed service runs from: the server writes `config/.runtime-config.json` in its working directory and removes it on exit, so a probe started from the live checkout would clobber the running service's file.

```bash
systemd-run --user --unit=my-tracks-probe -p NoNewPrivileges=true -p PrivateTmp=true -p ProtectSystem=full \
  -p "RestrictAddressFamilies=AF_INET AF_INET6 AF_NETLINK AF_UNIX" -p SystemCallArchitectures=native -p RuntimeMaxSec=300 -p WorkingDirectory="$PWD" \
  -E PATH="$PATH" -E HOME="$HOME" "$PWD/scripts/my-tracks-server" --http-port 18080 --mqtt-port 0 --mqtt-tls-port 0
```

`systemd-run` returns while the probe keeps running, so stop it when you are done (`systemctl --user stop my-tracks-probe`) before starting another run under the same name; the `RuntimeMaxSec` below is a safety net.

If a host does enforce the mount namespace but the unit fails with `status=226/NAMESPACE`, set `PrivateTmp=false` and `ProtectSystem=no` in a drop-in (`systemctl --user edit my-tracks`), which survives a `setup-service` reinstall, instead of editing the shipped unit. `tests/python/test_systemd_unit_hardening.py` pins the directives and the ones that must stay off.

## Uninstall

```bash
systemctl --user disable --now my-tracks
rm ~/.config/systemd/user/my-tracks.service
rm -f ~/.config/share/systemd-units/my-tracks.service
systemctl --user daemon-reload
```
