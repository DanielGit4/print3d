"""Register print3d with the coding agents on this machine.

Each agent gets the MCP server, launched with the Python print3d is installed
in. Claude Code and Hermes also get the skill, linked when possible or copied
otherwise. Rerun setup after upgrades to refresh a copied skill.
Nothing is changed until the plan has been shown; every file edited is
backed up beside itself first.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from print3d.paths import skill_dir

AGENTS = ("claude", "codex", "cursor", "gemini", "hermes")
NAME = "print3d"


class SetupError(RuntimeError):
    """Raised when an agent's config cannot be changed safely."""


@dataclass(frozen=True)
class Change:
    agent: str
    target: str
    action: str
    apply: Callable[[], None]

    def describe(self) -> str:
        return f"{self.agent:7} {self.action}  ({self.target})"


def server_command() -> list[str]:
    return [sys.executable, "-m", "print3d", "mcp"]


def _backup(path: Path) -> Path | None:
    if path.exists() or path.is_symlink():
        name = f"{path.name}.print3d-backup-{time.strftime('%Y%m%d-%H%M%S')}"
        backup = path.with_name(name)
        suffix = 1
        while backup.exists() or backup.is_symlink():
            backup = path.with_name(f"{name}-{suffix}")
            suffix += 1
        path.rename(backup)
        return backup
    return None


def _link(link: Path, target: Path) -> None:
    target = target.resolve()
    if not (target / "SKILL.md").is_file():
        raise SetupError(f"Skill not found at {target}; reinstall print3d and run setup again.")
    if link.is_symlink() and link.resolve() == target:
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    # Prepare first so a failed copy leaves the existing installation untouched.
    with tempfile.TemporaryDirectory(prefix=f".{NAME}-", dir=link.parent) as staging:
        prepared = Path(staging) / NAME
        try:
            prepared.symlink_to(target, target_is_directory=True)
        except OSError:
            shutil.copytree(target, prepared)
        backup = _backup(link)
        try:
            prepared.rename(link)
        except OSError:
            if backup is not None:
                backup.rename(link)
            raise


def _write_with_backup(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_name(f"{path.name}.print3d-backup-{time.strftime('%Y%m%d-%H%M%S')}"))
    path.write_text(text, encoding="utf-8")


def _merge_mcp_json(path: Path) -> None:
    """Add the server under `mcpServers`, the shape Cursor and Gemini CLI share."""
    try:
        config = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
    except json.JSONDecodeError as exc:
        raise SetupError(f"{path} is not valid JSON ({exc}); fix it and run setup again.") from exc
    command, *args = server_command()
    config.setdefault("mcpServers", {})[NAME] = {"command": command, "args": args}
    _write_with_backup(path, json.dumps(config, indent=2) + "\n")


CODEX_SECTION = re.compile(
    rf"^[ \t]*\[mcp_servers\.{NAME}\][ \t]*(?:#[^\n]*)?(?:\n|$)"
    r"(?:(?![ \t]*\[)[^\n]*\n)*(?:(?![ \t]*\[)[^\n]+$)?",
    re.MULTILINE,
)


def _merge_codex_toml(path: Path) -> None:
    command, *args = server_command()
    block = (
        f"[mcp_servers.{NAME}]\n"
        f"command = {json.dumps(command)}\n"
        f"args = {json.dumps(args)}\n"
    )
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(f"{path} is not valid TOML ({exc}); fix it and run setup again.") from exc
    if CODEX_SECTION.search(text):
        # A replacement string would interpret the backslashes in Windows paths.
        text = CODEX_SECTION.sub(lambda _: block + "\n", text, count=1)
    else:
        text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + block
    try:
        tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise SetupError(
            f"Cannot update {path} safely as TOML ({exc}); add print3d by hand. The file was not changed."
        ) from exc
    _write_with_backup(path, text)


HERMES_SERVERS = re.compile(r"^mcp_servers:[ \t]*(\{\})?[ \t]*\n?", re.MULTILINE)
HERMES_ENTRY = re.compile(rf"^  {NAME}:.*\n(?:(?:    .*)?\n)*", re.MULTILINE)


def _merge_hermes_yaml(path: Path) -> None:
    """Add the server under the top-level `mcp_servers:` of Hermes's config.yaml."""
    command, *args = server_command()
    entry = (
        f"  {NAME}:\n"
        f"    command: {json.dumps(command)}\n"
        f"    args: {json.dumps(args)}\n"
        f"    enabled: true\n"
    )
    text = path.read_text(encoding="utf-8") if path.is_file() else ""
    servers = HERMES_SERVERS.search(text)
    if servers is None:
        if re.search(r"^mcp_servers:", text, re.MULTILINE):
            raise SetupError(f"{path} has mcp_servers in a form setup cannot edit; add print3d by hand.")
        text = (text.rstrip("\n") + "\n" if text.strip() else "") + "mcp_servers:\n" + entry
    else:
        head, tail = text[:servers.start()], text[servers.end():]
        block_end = re.search(r"^\S", tail, re.MULTILINE)
        block, rest = (tail[:block_end.start()], tail[block_end.start():]) if block_end else (tail, "")
        text = head + "mcp_servers:\n" + entry + HERMES_ENTRY.sub("", block) + rest
    _write_with_backup(path, text)


def _claude_mcp(claude: str, run: Callable[..., subprocess.CompletedProcess]) -> None:
    run([claude, "mcp", "remove", "--scope", "user", NAME], capture_output=True, text=True, check=False)
    added = run(
        [claude, "mcp", "add", "--scope", "user", NAME, "--", *server_command()],
        capture_output=True, text=True, check=False,
    )
    if added.returncode != 0:
        raise SetupError(f"claude mcp add failed: {(added.stderr or added.stdout).strip()}")


def detect(home: Path, which: Callable[[str], str | None] = shutil.which) -> list[str]:
    return [agent for agent in AGENTS if which(agent) or (home / f".{agent}").is_dir()]


def plan(
    agents: list[str] | None = None,
    *,
    home: Path | None = None,
    which: Callable[[str], str | None] = shutil.which,
    run: Callable[..., subprocess.CompletedProcess] = subprocess.run,
) -> list[Change]:
    home = home or Path.home()
    changes: list[Change] = []
    for agent in agents or detect(home, which):
        if agent == "claude":
            link = home / ".claude" / "skills" / NAME
            changes.append(Change(agent, str(link), f"install the skill from {skill_dir()} (link or copy)",
                                  lambda link=link: _link(link, skill_dir())))
            if claude := which("claude"):
                changes.append(Change(agent, "user scope", "claude mcp add print3d",
                                      lambda claude=claude: _claude_mcp(claude, run)))
        elif agent == "codex":
            path = home / ".codex" / "config.toml"
            changes.append(Change(agent, str(path), "add [mcp_servers.print3d]",
                                  lambda path=path: _merge_codex_toml(path)))
        elif agent == "hermes":
            link = home / ".hermes" / "skills" / NAME
            changes.append(Change(agent, str(link), f"install the skill from {skill_dir()} (link or copy)",
                                  lambda link=link: _link(link, skill_dir())))
            path = home / ".hermes" / "config.yaml"
            changes.append(Change(agent, str(path), "add mcp_servers.print3d",
                                  lambda path=path: _merge_hermes_yaml(path)))
        elif agent in ("cursor", "gemini"):
            path = home / f".{agent}" / ("mcp.json" if agent == "cursor" else "settings.json")
            changes.append(Change(agent, str(path), "add mcpServers.print3d",
                                  lambda path=path: _merge_mcp_json(path)))
        else:
            raise SetupError(f"Unknown agent {agent!r}; choose from {', '.join(AGENTS)}.")
    return changes
