"""Baseline hardening of the shipped systemd user unit (my-tracks#1400)."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_USER_UNIT = _REPO_ROOT / "etc" / "systemd" / "my-tracks.service"
# What the process needs: sockets for HTTP, MQTT and its TLS port (AF_INET*), the database socket when PostgreSQL is
# local (AF_UNIX), and the C library's interface listing (AF_NETLINK). Raw packet sockets are not used.
_REQUIRED_ADDRESS_FAMILIES = frozenset({"AF_INET", "AF_INET6", "AF_NETLINK", "AF_UNIX"})


def _assignments(path: Path) -> dict[str, list[str]]:
    """Return every ``[Service]`` assignment of a unit file, in order, per key.

    A trailing backslash joins the next line, comment and blank lines inside a continued value are skipped, and
    repeats are kept because systemd accumulates some keys (``RestrictAddressFamilies``) instead of letting the last
    one win.
    """

    joined: list[str] = []
    pending = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        stripped = raw.strip()
        if pending and (not stripped or stripped.startswith(("#", ";"))):
            continue
        line = pending + stripped
        if line.endswith("\\"):
            pending = line[:-1].rstrip() + " "
            continue
        pending = ""
        joined.append(line)
    assignments: dict[str, list[str]] = {}
    in_service = False
    for line in joined:
        if not line or line.startswith(("#", ";")):
            continue
        header = re.fullmatch(r"\[(\w+)\]", line)
        if header is not None:
            in_service = header.group(1) == "Service"
            continue
        if in_service and "=" in line:
            key, _, value = line.partition("=")
            assignments.setdefault(key.strip(), []).append(value.strip())
    return assignments


def _single(path: Path, key: str) -> str:
    values = _assignments(path).get(key, [])
    assert len(values) == 1, f"Expected exactly one {key}= assignment, got {values}"
    return values[0]


def test_user_unit_forbids_gaining_privileges() -> None:
    assert _single(_USER_UNIT, "NoNewPrivileges") == "true"


def test_user_unit_asks_for_a_private_tmp_for_the_broker_tls_files() -> None:
    # The MQTT broker writes the server's TLS key and certificates to the temp directory for the SSL context. Only
    # this process reads them, so a private /tmp that systemd removes at stop (even after a crash) loses nothing. It
    # is enforced only where the user manager can build a mount namespace.
    assert _single(_USER_UNIT, "PrivateTmp") == "true"


def test_user_unit_mounts_the_system_directories_read_only() -> None:
    assert _single(_USER_UNIT, "ProtectSystem") == "full"


def test_user_unit_restricts_address_families_to_what_the_service_uses() -> None:
    families = set(_single(_USER_UNIT, "RestrictAddressFamilies").split())
    assert families == _REQUIRED_ADDRESS_FAMILIES, (
        f"Expected {sorted(_REQUIRED_ADDRESS_FAMILIES)}, got {sorted(families)}"
    )


def test_user_unit_pins_the_system_call_architecture_so_the_address_family_filter_holds() -> None:
    # On a host that also runs 32-bit x86 code, RestrictAddressFamilies does not cover those calls, so systemd
    # recommends pairing it with SystemCallArchitectures=native.
    assert _single(_USER_UNIT, "SystemCallArchitectures") == "native"


def test_user_unit_keeps_the_home_directory_writable_and_the_syscalls_unfiltered() -> None:
    # The service writes its log under the home directory and the SQLite database and media inside its checkout, and a
    # syscall filter can break a service at runtime.
    assignments = _assignments(_USER_UNIT)
    assert "ProtectHome" not in assignments
    assert "SystemCallFilter" not in assignments
    assert assignments.get("ProtectSystem") != ["strict"]


def test_the_parser_ignores_other_sections_and_comments(tmp_path: Path) -> None:
    unit = tmp_path / "x.service"
    unit.write_text("[Unit]\nNoNewPrivileges=false\n[Service]\n# PrivateTmp=false\nPrivateTmp=true\n", encoding="utf-8")
    assert _assignments(unit) == {"PrivateTmp": ["true"]}


def test_the_parser_joins_continued_lines_skips_comments_inside_them_and_keeps_repeated_keys(tmp_path: Path) -> None:
    unit = tmp_path / "x.service"
    unit.write_text(
        "[Service]\nRestrictAddressFamilies=AF_INET \\\n# a comment between the lines\n  AF_UNIX\n"
        "RestrictAddressFamilies=AF_PACKET\n",
        encoding="utf-8",
    )
    assert _assignments(unit) == {"RestrictAddressFamilies": ["AF_INET AF_UNIX", "AF_PACKET"]}


def test_a_repeated_pinned_directive_is_rejected(tmp_path: Path) -> None:
    unit = tmp_path / "x.service"
    unit.write_text("[Service]\nRestrictAddressFamilies=AF_INET\nRestrictAddressFamilies=AF_PACKET\n", encoding="utf-8")
    try:
        _single(unit, "RestrictAddressFamilies")
    except AssertionError as exc:
        assert "exactly one" in str(exc)
    else:
        raise AssertionError("Expected a repeated directive to be rejected")
