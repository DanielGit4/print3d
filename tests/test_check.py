"""Exercise check through both the CLI and the MCP protocol."""
import json
from pathlib import Path
from zipfile import ZipFile

import anyio
import pytest
from mcp import Client

from conftest import write_cube_stl
from print3d.cli import main
from print3d.dfm import read_stl
from print3d.mcp_server import server


@pytest.fixture(params=["cli", "mcp"])
def check_entrypoint(request, capsys):
    def call(mesh, project=None):
        if request.param == "cli":
            args = ["check", str(mesh)]
            if project:
                args.extend(["--project", str(project)])
            code = main(args)
            output = capsys.readouterr()
            return code, json.loads(output.out) if output.out else {"error": output.err}

        async def run():
            async with Client(server) as client:
                args = {"mesh": str(mesh)}
                if project:
                    args["project"] = str(project)
                return await client.call_tool("check", args)

        result = anyio.run(run)
        text = result.content[0].text
        return (1, {"error": text}) if result.is_error else (0, json.loads(text))

    return request.param, call


def _mesh(tmp_path, case):
    size = {"oversize": 300, "tiny": 0.5, "overhang": 10}.get(case, 20)
    mesh = write_cube_stl(tmp_path / "cube.stl", size)
    triangles = read_stl(mesh)
    if case == "open":
        triangles = [tri for tri in triangles if not all(v[2] == size for v in tri)]
    elif case == "floating":
        triangles = [tuple((x, y, z + 10) for x, y, z in tri) for tri in triangles]
    elif case == "overhang":
        # Two closed cubes, with the upper one suspended above the lower one.
        upper = read_stl(write_cube_stl(tmp_path / "upper.stl", 20))
        triangles += [tuple((x, y, z + 20) for x, y, z in tri) for tri in upper]
    lines = ["solid check"]
    for tri in triangles:
        lines.extend(["facet normal 0 0 0", "outer loop"])
        lines.extend("vertex %g %g %g" % vertex for vertex in tri)
        lines.extend(["endloop", "endfacet"])
    lines.append("endsolid check")
    mesh.write_text("\n".join(lines), encoding="ascii")
    return mesh


@pytest.mark.parametrize("case,dfm_ok,severity,message", [
    ("valid", True, "note", "No printability problems"),
    ("open", False, "error", "not manifold"),
    ("oversize", False, "error", "exceeds"),
    ("tiny", False, "error", "Volume"),
    ("floating", True, "warn", "Lowest Z"),
    ("overhang", True, "error", "overhang"),
])
def test_check_reports_structural_and_printability_findings(check_entrypoint, tmp_path, case, dfm_ok, severity, message):
    entrypoint, call = check_entrypoint
    code, payload = call(_mesh(tmp_path, case))
    if entrypoint == "cli":
        assert code == (1 if severity == "error" else 0)
    else:
        # Invalid geometry is a finding; missing or unreadable input is a tool error.
        assert code == 0
    assert any(note["severity"] == severity and message in note["message"] for note in payload["advice"])
    assert payload["dfm"]["ok"] is dfm_ok
    assert payload["severity"] == severity
    assert "mesh_metrics" in payload
    if case != "valid":
        assert "clean" not in {note["code"] for note in payload["advice"]}


@pytest.mark.parametrize("case,message", [("missing", "does not exist"), ("empty", "no triangles")])
def test_check_reports_unusable_input_as_an_error(check_entrypoint, tmp_path, case, message):
    _, call = check_entrypoint
    mesh = tmp_path / "input.stl"
    if case == "empty":
        mesh.write_bytes(bytes(84))  # Binary STL header with a zero triangle count.
    code, payload = call(mesh)
    assert code == 1
    assert message in payload["error"]


def test_check_keeps_slice_analysis(check_entrypoint, tmp_path):
    entrypoint, call = check_entrypoint
    project = Path(__file__).parent / "fixtures" / "cube_20mm.gcode.3mf"
    code, payload = call(write_cube_stl(tmp_path / "cube.stl"), project)
    assert code == 0
    assert payload["dfm"]["ok"]
    assert payload["severity"] != "error"
    if entrypoint == "cli":
        assert payload["slice_metrics"]["filament_g"] == 3.63
        assert payload["layers"]


def test_project_findings_are_combined_with_mesh_checks(check_entrypoint, tmp_path):
    _, call = check_entrypoint
    mesh = write_cube_stl(tmp_path / "cube.stl")
    project = tmp_path / "slow.gcode.3mf"
    with ZipFile(project, "w") as archive:
        archive.writestr("Metadata/plate_1.gcode", "; total estimated time: 5h\n; CONFIG_BLOCK_END\n")
    code, payload = call(mesh, project)
    assert code == 0
    assert payload["dfm"]["ok"]
    assert any(note["code"] == "duration" for note in payload["advice"])
    assert "clean" not in {note["code"] for note in payload["advice"]}
