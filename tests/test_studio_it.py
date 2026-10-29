import json
import os
from pathlib import Path

import pytest

from print3d.paths import repo_root
from print3d.pipeline import run_job

pytestmark = pytest.mark.skipif(
    os.environ.get("PRINT3D_STUDIO_IT") != "1",
    reason="Set PRINT3D_STUDIO_IT=1 to run a live Blender model and Bambu Studio slice",
)


@pytest.mark.parametrize("execute", [False, True], ids=["dry-run", "failed-dfm"])
def test_rerun_cannot_handoff_a_previous_slice(tmp_path: Path, monkeypatch, execute):
    from print3d.dfm import DfmError, inspect_mesh
    from print3d.handoff import HandoffError, build_handoff

    monkeypatch.setenv("PRINT3D_FITS", str(tmp_path / "fits.json"))
    script = tmp_path / "model.py"
    script.write_text("import bpy\nbpy.ops.mesh.primitive_cube_add(size=20)\n")
    initial = run_job("state test cube", script=script, jobs_dir=tmp_path)
    assert initial["status"] == "ready_for_review"
    job_dir = Path(initial["job_dir"])
    project = Path(initial["open_in_studio"])
    previous_project = project.read_bytes()

    side = 300 if execute else 30
    script.write_text(f"import bpy\nbpy.ops.mesh.primitive_cube_add(size={side})\n")
    if execute:
        with pytest.raises(DfmError, match="exceeds"):
            run_job("state test cube", script=script, jobs_dir=tmp_path)
    else:
        assert run_job("state test cube", script=script, jobs_dir=tmp_path, execute=False)["status"] == "dry_run"
    assert inspect_mesh(Path(initial["model"]["mesh"])).size_mm == (side, side, side)
    assert project.read_bytes() == previous_project
    with pytest.raises(HandoffError):
        build_handoff(job_dir, render=False)
    assert json.loads((job_dir / "report.json").read_text())["status"] == ("failed" if execute else "dry_run")

    script.write_text("import bpy\nbpy.ops.mesh.primitive_cube_add(size=20)\n")
    assert run_job("state test cube", script=script, jobs_dir=tmp_path)["status"] == "ready_for_review"
    delivery = build_handoff(job_dir, render=False)
    stl = next(Path(path) for path in delivery["files"] if path.endswith(".stl"))
    assert inspect_mesh(stl).size_mm == (20, 20, 20)


def test_nameplate_end_to_end(tmp_path: Path):
    report = run_job(
        "a 40mm nameplate that says MARCO",
        script=repo_root() / "examples" / "nameplate.py",
        jobs_dir=tmp_path,
        execute=True,
    )
    assert report["status"] == "ready_for_review"
    assert report["severity"] != "error"
    assert report["model"]["non_manifold_edges"] == 0
    assert report["model"]["size_mm"] == pytest.approx([40.0, 16.0, 3.0], abs=0.01)
    plate = report["inspection"]["plates"][0]
    assert plate["layer_count"] == 15
    assert Path(report["open_in_studio"]).is_file()


def test_advice_catches_an_unsupported_ceiling(tmp_path: Path):
    script = tmp_path / "tee.py"
    script.write_text(
        "import bpy\n"
        "bpy.ops.mesh.primitive_cube_add(size=1)\n"
        "stem = bpy.context.active_object\n"
        "stem.scale = (6, 6, 30); bpy.ops.object.transform_apply(scale=True)\n"
        "stem.location.z = 15; bpy.ops.object.transform_apply(location=True)\n"
        "bpy.ops.mesh.primitive_cube_add(size=1)\n"
        "cap = bpy.context.active_object\n"
        "cap.scale = (40, 40, 4); bpy.ops.object.transform_apply(scale=True)\n"
        "cap.location.z = 32; bpy.ops.object.transform_apply(location=True)\n"
        "m = stem.modifiers.new('u', 'BOOLEAN'); m.operation = 'UNION'\n"
        "m.object = cap; m.solver = 'EXACT'\n"
        "bpy.context.view_layer.objects.active = stem\n"
        "bpy.ops.object.modifier_apply(modifier='u')\n"
        "bpy.data.objects.remove(cap, do_unlink=True)\n",
        encoding="utf-8",
    )
    report = run_job("a t shaped bracket", script=script, jobs_dir=tmp_path, execute=True)
    assert report["status"] == "needs_work"
    assert report["severity"] == "error"
    codes = {note["code"] for note in report["advice"]}
    assert "overhang" in codes
    # The slice must agree with the mesh: material appears where the cap starts.
    assert report["slice_metrics"]["max_layer_growth_z"] == pytest.approx(30.2, abs=0.3)



def test_dolly_peg_from_a_museum_photo(tmp_path: Path):
    from test_peg_benchmark import build_spec

    build_spec(tmp_path / "a_dolly_peg")
    report = run_job("a dolly peg", script=repo_root() / "examples" / "dolly_peg.py", jobs_dir=tmp_path, execute=True)
    assert report["status"] == "ready_for_review", report["advice"]
    assert report["model"]["non_manifold_edges"] == 0
    dims = report["spec"]["dims"]
    assert report["model"]["size_mm"][2] == pytest.approx(dims["length"]["mm"], abs=0.01)
    [likeness] = report["likeness"]
    assert likeness["iou"] > 0.89
    assert "better_pose" not in likeness


def test_shelf_bracket_from_its_listing(tmp_path: Path):
    from test_bracket_benchmark import build_spec

    build_spec(tmp_path / "a_shelf_bracket")
    report = run_job("a shelf bracket", script=repo_root() / "examples" / "shelf_bracket.py",
                     jobs_dir=tmp_path, execute=True)
    assert report["status"] == "ready_for_review", report["advice"]
    assert report["model"]["non_manifold_edges"] == 0
    assert report["listing"]["name"] == "Heavy duty shelf bracket, 20 x 12 cm"
    assert report["model"]["size_mm"][2] == pytest.approx(20.0, abs=0.01)
    [likeness] = report["likeness"]
    assert likeness["iou"] > 0.88


def test_lidded_box_in_two_colours(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PRINT3D_FITS", str(tmp_path / "fits.json"))
    report = run_job('a lidded box that says "BOX"', script=repo_root() / "examples" / "lidded_box.py",
                     jobs_dir=tmp_path, execute=True)
    assert report["status"] == "ready_for_review", report["advice"]
    assert [p["name"] for p in report["parts"]] == ["body", "lid", "name"]
    assert {f["color"]: f["used_g"] > 0 for f in report["filaments"]} == {"white": True, "black": True}
    [fit] = report["fits"]
    assert (fit["declared"], fit["verdict"]) == ("slide", "ok")
    assert fit["clearance_mm"] == pytest.approx(0.2, abs=0.01)
    assert Path(report["open_in_studio"]).is_file()


def test_a_flush_cutter_buries_the_inlay(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PRINT3D_FITS", str(tmp_path / "fits.json"))
    source = (repo_root() / "examples" / "lidded_box.py").read_text()
    script = tmp_path / "flush.py"
    script.write_text(source.replace('top + 1.0), "DIFFERENCE")', 'top), "DIFFERENCE")'))
    report = run_job("a lidded box", script=script, jobs_dir=tmp_path, execute=False)
    assert report["severity"] == "error"
    assert ("buried", "name") in {(a["code"], a["part"]) for a in report["advice"]}


def test_fit_coupon_slices_clean(tmp_path: Path):
    from print3d.paths import coupon_script

    report = run_job("fit coupon", script=coupon_script(), jobs_dir=tmp_path, execute=True)
    assert report["status"] == "ready_for_review", report["advice"]
    assert {p["name"] for p in report["parts"]} == {"holes", "pin"}
    assert report["model"]["non_manifold_edges"] == 0


def test_pen_caddy_fits_and_plates(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("PRINT3D_FITS", str(tmp_path / "fits.json"))
    report = run_job("a rotating pen caddy", script=repo_root() / "examples" / "pen_caddy.py",
                     jobs_dir=tmp_path, execute=True)
    assert report["status"] == "ready_for_review", report["advice"]
    declared = {(f["a"], f["b"]): (f["declared"], f["verdict"], f["clearance_mm"])
                for f in report["fits"] if f["declared"]}
    assert declared == {
        ("base", "axle"): ("press", "ok", pytest.approx(0.05, abs=0.01)),
        ("axle", "cap"): ("snug", "ok", pytest.approx(0.10, abs=0.01)),
        ("axle", "cup"): ("free", "ok", pytest.approx(0.35, abs=0.01)),
    }
    assert [p["objects"] for p in report["plates"]] == [["base", "axle", "cap"], ["cup"]]
    axle = next(p for p in report["parts"] if p["name"] == "axle")
    assert axle["settings"] == {"wall_loops": "6", "sparse_infill_density": "100%"}
    assert all(f["used_g"] > 0 for f in report["filaments"])


def test_hinged_tin_from_a_museum_photo(tmp_path: Path, monkeypatch):
    from test_tin_benchmark import build_spec

    monkeypatch.setenv("PRINT3D_FITS", str(tmp_path / "fits.json"))
    build_spec(tmp_path / "sd_cards")
    report = run_job('recreate this tin, "SD CARDS" on the lid', script=repo_root() / "examples" / "tobacco_tin.py",
                     jobs_dir=tmp_path, execute=True)
    assert report["status"] == "ready_for_review", report["advice"]
    assert report["model"]["non_manifold_edges"] == 0
    [likeness] = report["likeness"]
    assert likeness["iou"] > 0.98
    assert {(f["a"], f["b"]): f["verdict"] for f in report["fits"] if f["declared"]} == {
        ("body", "lid"): "ok", ("body", "pin"): "ok", ("lid", "pin"): "ok",
    }
    assert {f["color"] for f in report["filaments"]} == {"gold", "black"}
    assert len(report["plates"]) == 1
