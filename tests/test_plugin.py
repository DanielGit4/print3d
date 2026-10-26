import json
import tomllib
from pathlib import Path

from print3d.blender import BLENDER_LOCATIONS
from print3d.paths import skill_dir

ROOT = Path(__file__).resolve().parents[1]


def test_hermes_plugin_matches_the_package():
    manifest = json.loads((ROOT / "plugin.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
    assert manifest["version"] == project["version"]
    assert (ROOT / "skills" / "print3d").is_dir()
    assert not (ROOT / "skills" / "print3d").is_symlink()
    assert (ROOT / "skills" / "print3d").resolve() == skill_dir()
    server = json.loads((ROOT / "mcp.json").read_text())["mcpServers"]["print3d"]
    assert server["args"][-2:] == ["print3d", "mcp"]
    hermes = manifest["extensions"]["com.nousresearch.hermes"]
    assert hermes["servers"]["print3d"]["trust"] == "untrusted"
    assert hermes["servers"]["print3d"]["requires"] == {"app": True, "min_version": "4.2"}
    assert "Blender](https://www.blender.org/download/) 4.2+" in (ROOT / "README.md").read_text()


def test_find_blender_looks_wherever_hermes_does():
    """A Blender that passes Hermes's install check must also be found when make runs."""
    manifest = json.loads((ROOT / "plugin.json").read_text())
    app = manifest["extensions"]["com.nousresearch.hermes"]["servers"]["print3d"]["app"]
    expected = []
    for location in app["darwin"]["location"]:
        if isinstance(location, str):
            expected.append(f"{location}/Contents/MacOS/Blender")
        else:
            expected += [f"{root}/{location['name']}/Contents/MacOS/Blender" for root in ("/Applications", "~/Applications")]
    for location in app["linux"]["location"]:
        if isinstance(location, str):
            expected.append(location)
        elif location["kind"] == "flatpak":
            expected += [f"{root}/exports/bin/{location['app_id']}" for root in ("/var/lib/flatpak", "~/.local/share/flatpak")]
        elif location["kind"] == "snap":
            expected.append(f"/snap/bin/{location['name']}")
        else:
            assert location == {"kind": "command", "name": "blender"}  # shutil.which covers it
    assert set(expected) <= set(BLENDER_LOCATIONS)
