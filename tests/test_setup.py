import json
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from print3d import setup
from print3d.paths import skill_dir


def _apply(home, agents, which=lambda _: None, run=None):
    for change in setup.plan(agents, home=home, which=which, run=run or subprocess.run):
        change.apply()


def _assert_skill_installed(path):
    expected = {p.relative_to(skill_dir()): p.read_bytes() for p in skill_dir().rglob("*") if p.is_file()}
    actual = {p.relative_to(path): p.read_bytes() for p in path.rglob("*") if p.is_file()}
    assert actual == expected


@pytest.fixture
def no_symlinks(monkeypatch):
    def denied(*args, **kwargs):
        raise PermissionError("Symlink privilege is not held")
    monkeypatch.setattr(Path, "symlink_to", denied)


def test_only_agents_present_are_planned(tmp_path):
    (tmp_path / ".cursor").mkdir()
    which = {"codex": "/bin/codex"}.get
    assert setup.detect(tmp_path, which) == ["codex", "cursor"]


def test_codex_section_is_added_once_and_keeps_the_rest(tmp_path):
    config = tmp_path / ".codex" / "config.toml"
    config.parent.mkdir()
    config.write_text('model = "o5"\n\n[mcp_servers.other]\ncommand = "x"\n')
    _apply(tmp_path, ["codex"])
    _apply(tmp_path, ["codex"])
    text = config.read_text()
    assert text.count("[mcp_servers.print3d]") == 1
    assert 'model = "o5"' in text and "[mcp_servers.other]" in text
    assert json.dumps(sys.executable) in text
    assert list(config.parent.glob("config.toml.print3d-backup-*"))


def test_codex_update_preserves_windows_command_escapes(tmp_path, monkeypatch):
    command = r"C:\Users\Alice\Python\python.exe"
    monkeypatch.setattr(setup, "server_command", lambda: [command, "-m", "print3d", "mcp"])
    config = tmp_path / "config.toml"
    setup._merge_codex_toml(config)
    setup._merge_codex_toml(config)
    server = tomllib.loads(config.read_text())["mcp_servers"]["print3d"]
    assert server == {"command": command, "args": ["-m", "print3d", "mcp"]}


@pytest.mark.parametrize("header", [
    "[mcp_servers.print3d] # existing server",
    "  [mcp_servers.print3d] \t# existing server",
])
def test_codex_update_accepts_comments_and_keeps_following_tables(tmp_path, monkeypatch, header):
    monkeypatch.setattr(setup, "server_command", lambda: ["/usr/bin/python", "-m", "print3d", "mcp"])
    config = tmp_path / "config.toml"
    other = '  [mcp_servers.other] # keep this comment\ncommand = "other-server"\n'
    config.write_text(f'model = "example"\n{header}\ncommand = "/old/python"\n\n{other}')
    setup._merge_codex_toml(config)
    text = config.read_text()
    parsed = tomllib.loads(text)
    assert parsed["model"] == "example"
    assert parsed["mcp_servers"] == {
        "print3d": {"command": "/usr/bin/python", "args": ["-m", "print3d", "mcp"]},
        "other": {"command": "other-server"},
    }
    assert other in text


@pytest.mark.parametrize("original", [
    "[not valid TOML",
    # A valid spelling the text editor cannot recognize must not become a duplicate table.
    '[mcp_servers."print3d"]\ncommand = "old"\n',
])
def test_codex_invalid_or_unsupported_toml_is_left_alone(tmp_path, original):
    config = tmp_path / "config.toml"
    config.write_text(original)
    with pytest.raises(setup.SetupError, match="TOML"):
        setup._merge_codex_toml(config)
    assert config.read_text() == original
    assert not list(tmp_path.glob("config.toml.print3d-backup-*"))


def test_json_configs_keep_other_servers(tmp_path):
    settings = tmp_path / ".gemini" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"theme": "dark", "mcpServers": {"other": {"command": "x"}}}))
    _apply(tmp_path, ["gemini"])
    config = json.loads(settings.read_text())
    assert config["theme"] == "dark"
    assert set(config["mcpServers"]) == {"other", "print3d"}
    assert config["mcpServers"]["print3d"]["args"] == ["-m", "print3d", "mcp"]


def test_broken_json_is_left_alone(tmp_path):
    mcp = tmp_path / ".cursor" / "mcp.json"
    mcp.parent.mkdir()
    mcp.write_text("{not json")
    with pytest.raises(setup.SetupError):
        _apply(tmp_path, ["cursor"])
    assert mcp.read_text() == "{not json"


def test_claude_gets_the_skill_and_the_server_added(tmp_path, no_symlinks):
    old = tmp_path / ".claude" / "skills" / "print3d"
    old.mkdir(parents=True)
    calls = []

    def run(cmd, **_):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    _apply(tmp_path, ["claude"], which={"claude": "/bin/claude"}.get, run=run)
    _assert_skill_installed(old)
    assert not old.is_symlink()
    assert list(old.parent.glob("print3d.print3d-backup-*"))
    assert calls[-1][:6] == ["/bin/claude", "mcp", "add", "--scope", "user", "print3d"]
    assert calls[-1][-3:] == ["-m", "print3d", "mcp"]


def test_hermes_gets_the_skill_and_the_server_added_once(tmp_path, no_symlinks):
    hermes = tmp_path / ".hermes"
    (hermes / "skills").mkdir(parents=True)
    config = hermes / "config.yaml"
    config.write_text(
        "model: x\n"
        "mcp_servers:\n"
        "  other:\n"
        "    command: npx\n"
        "\n"
        "  print3d:\n"
        "    command: /old/python\n"
        "    args: [-m, print3d, mcp]\n"
        "skills:\n"
        "  disabled: []\n"
    )
    _apply(tmp_path, ["hermes"])
    _apply(tmp_path, ["hermes"])
    text = config.read_text()
    _assert_skill_installed(hermes / "skills" / "print3d")
    assert text.count("  print3d:") == 1 and "/old/python" not in text
    assert json.dumps(sys.executable) in text
    assert "  other:\n    command: npx\n" in text
    assert text.startswith("model: x\n") and text.endswith("skills:\n  disabled: []\n")


def test_hermes_config_without_servers_gets_the_section(tmp_path):
    config = tmp_path / ".hermes" / "config.yaml"
    config.parent.mkdir()
    config.write_text("model: x\nmcp_servers: {}\n")
    _apply(tmp_path, ["hermes"])
    assert config.read_text().startswith("model: x\nmcp_servers:\n  print3d:\n")


def test_copied_skill_updates_and_preserves_each_previous_version(tmp_path, no_symlinks, monkeypatch):
    monkeypatch.setattr(setup.time, "strftime", lambda _: "20260101-000000")
    source = tmp_path / "source"
    source.mkdir()
    (source / "SKILL.md").write_text("version 1")
    link = tmp_path / "installed"
    setup._link(link, source)
    (link / "local.md").write_text("local changes")
    (source / "SKILL.md").write_text("version 2")
    setup._link(link, source)
    (source / "SKILL.md").write_text("version 3")
    setup._link(link, source)
    assert (link / "SKILL.md").read_text() == "version 3"
    assert not (link / "local.md").exists()
    backups = sorted(tmp_path.glob("installed.print3d-backup-*"))
    assert [(p / "SKILL.md").read_text() for p in backups] == ["version 1", "version 2"]
    assert (backups[0] / "local.md").read_text() == "local changes"


@pytest.mark.parametrize("failure", ["missing_source", "copy", "rename"])
def test_failed_skill_install_preserves_previous_directory(tmp_path, no_symlinks, monkeypatch, failure):
    link = tmp_path / "installed"
    link.mkdir()
    (link / "SKILL.md").write_text("previous installation")
    source = tmp_path / "source"
    source.mkdir()
    if failure != "missing_source":
        (source / "SKILL.md").write_text("new installation")
    if failure == "copy":
        def failed_copy(source, destination):
            destination.mkdir()
            (destination / "partial.md").write_text("partial copy")
            raise OSError("copy failed")
        monkeypatch.setattr(setup.shutil, "copytree", failed_copy)
    elif failure == "rename":
        rename = Path.rename
        def failed_rename(path, destination):
            if path.name == "print3d" and destination == link:
                raise OSError("rename failed")
            return rename(path, destination)
        monkeypatch.setattr(Path, "rename", failed_rename)
    with pytest.raises((OSError, setup.SetupError)):
        setup._link(link, source)
    assert (link / "SKILL.md").read_text() == "previous installation"
    assert not list(tmp_path.glob("installed.print3d-backup-*"))
    assert not list(tmp_path.glob(".print3d-*"))


def test_skill_uses_a_symlink_when_supported_and_replaces_a_broken_link(tmp_path):
    link = tmp_path / "installed"
    try:
        link.symlink_to(tmp_path / "gone", target_is_directory=True)
    except OSError:
        pytest.skip("This environment does not allow directory symlinks")
    setup._link(link, skill_dir())
    assert link.is_symlink()
    assert link.resolve() == skill_dir()
    _assert_skill_installed(link)
    backups = list(tmp_path.glob("installed.print3d-backup-*"))
    assert len(backups) == 1 and backups[0].is_symlink()
    setup._link(link, skill_dir())
    assert list(tmp_path.glob("installed.print3d-backup-*")) == backups
