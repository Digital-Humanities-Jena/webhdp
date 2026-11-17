"""Research adapter contracts; subprocess fixtures do not represent neural inference."""
import ast
import json
import os
from pathlib import Path
import sys
import types
import zipfile

from PIL import Image
import pytest

from external_code.historic_reconstruction_runtime import upstream as u


def test_mvs_jit_cache_is_writable_per_run_without_mutating_pinned_cache(tmp_path):
    repository = tmp_path / "mvs"
    sources = repository / "src/mvsanywhere/tools/marching_cubes"
    sources.mkdir(parents=True)
    for name in ("ext.cpp", "marching_cubes_cpu.cpp", "marching_cubes.cu"):
        (sources / name).write_text("// source fixture\n")
    cache = tmp_path / "compiled-cache"
    cache.mkdir()
    (cache / "ext.so").write_bytes(b"cache fixture")
    before = u.tree_sha256(cache)
    output = tmp_path / "run"
    output.mkdir()
    config = {"_assets": {"mvs_repository": repository, "mvs_extension_cache": cache,
              "mvs_cuda_compiler": tmp_path / "env/bin/nvcc",
              "mvs_cxx_compiler": tmp_path / "env/bin/c++", "mvs_ninja": tmp_path / "env/bin/ninja"}}
    env = {"PATH": "/usr/bin", "OMP_NUM_THREADS": "2"}
    assert u._mvs_runtime_context(config, env, output) == repository
    (Path(env["TORCH_EXTENSIONS_DIR"]) / "lock").write_text("run-owned")
    assert u.tree_sha256(cache) == before
    assert env["CUDA_HOME"] == str(tmp_path / "env")
    assert env["LD_LIBRARY_PATH"] == str(tmp_path / "env/lib")
    assert env["CXX"] == str(tmp_path / "env/bin/c++")
    assert env["MAX_JOBS"] == "2"
    assert env["PATH"].startswith(str(tmp_path / "env/bin") + os.pathsep)


def test_mvs_rejects_repository_without_extension_before_build(tmp_path):
    with pytest.raises(ValueError, match="extension sources"):
        u._mvs_runtime_context({"_assets": {"mvs_repository": tmp_path}}, {}, tmp_path)


@pytest.mark.parametrize("parameter,value", [("fusion_max_depth", float("nan")),
    ("fusion_max_depth", float("inf")), ("fusion_max_depth", True),
    ("fusion_max_depth", 0), ("fusion_resolution", 0), ("fusion_resolution", 100)])
def test_mvs_rejects_invalid_fusion_settings_before_subprocess(tmp_path, parameter, value):
    config = {"_python": Path(sys.executable), "_source": tmp_path,
              "_assets": {name: tmp_path for name in ("mvs_model_config", "mvs_data_config", "mvs_checkpoint")}}
    with pytest.raises(ValueError, match=parameter):
        u.build_command("mvs", config, tmp_path, tmp_path / "output", {parameter: value})


def test_mvs_fusion_controls_preserve_model_units_in_exact_upstream_arguments(tmp_path):
    config = {"_python": Path(sys.executable), "_source": tmp_path,
              "_assets": {name: tmp_path for name in ("mvs_model_config", "mvs_data_config", "mvs_checkpoint")}}
    command = u.build_command("mvs", config, tmp_path, tmp_path / "output", {"fusion_max_depth": 30, "fusion_resolution": 0.04})
    assert command[command.index("--fusion_max_depth") + 1] == "30.0"
    assert command[command.index("--fusion_resolution") + 1] == "0.04"
    assert command[command.index("--batch_size") + 1] == "1"


def configured(tmp_path, monkeypatch, stages=None):
    package = tmp_path / "runtime" / "historic_reconstruction_pipeline"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "marker.py").write_text("VALUE = 1\n")
    config = {"schema_version": 1, "enabled_stages": stages or sorted(u.STAGES),
              "python": {"path": str(Path(sys.executable).absolute()), "sha256": u.file_sha256(sys.executable)},
              "source": {"path": str(package), "sha256": u.tree_sha256(package)},
              "dependencies": [], "assets": {}, "timeout_seconds": 60}
    path = tmp_path / "operator.json"
    path.write_text(json.dumps(config))
    monkeypatch.setenv("HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG", str(path))
    return config, path, package


def dataset_zip(tmp_path, monkeypatch, extra=None):
    staged = tmp_path / "inputs"
    staged.mkdir(exist_ok=True)
    source = staged / "image.jpg"
    Image.new("RGB", (48, 32), "orange").save(source)
    bundle = staged / "dataset.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        for index in range(3):
            archive.write(source, f"images/{index:06d}.jpg")
        for name, content in (extra or {}).items():
            archive.writestr(name, content)
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(staged))
    return {"input_file": str(bundle)}


def test_missing_operator_installation_is_not_silently_substituted(monkeypatch):
    monkeypatch.delenv("HISTORIC_RECONSTRUCTION_UPSTREAM_CONFIG", raising=False)
    with pytest.raises(ValueError, match="not installed"):
        u.load_config("original_sfm")


@pytest.mark.parametrize("stage,error", [("geolocalization", "network acquisition disabled"),
    ("dense_intrinsics", "workspace/scenes"), ("original_sfm", "at least three images"),
    ("refine_keypoints", "at least three images"), ("mvs", "at least three images")])
def test_panorama_supported_stages_allow_one_historic_image_only(tmp_path, monkeypatch, stage, error):
    configured(tmp_path, monkeypatch)
    staged = tmp_path / "inputs"
    staged.mkdir()
    image = staged / "photo.jpg"
    Image.new("RGB", (48, 32), "orange").save(image)
    bundle = staged / "scene.zip"
    with zipfile.ZipFile(bundle, "w") as archive:
        archive.write(image, "images/photo.jpg")
        archive.writestr("gps.json", json.dumps({"photo.jpg": [47.4, 19.0]}))
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(staged))
    parameters = {"skip_doppelgangers": True} if stage == "geolocalization" else {}
    with pytest.raises(ValueError, match=error):
        u.run(stage, {"input_file": str(bundle)}, parameters, tmp_path / "output")


@pytest.mark.parametrize("allocation,requested,expected", [("3", "8", "3"), ("8", "2", "2"), ("", "", "8")])
def test_research_subprocess_respects_allocated_and_requested_cpus(tmp_path, monkeypatch, allocation, requested, expected):
    monkeypatch.setattr(u.os, "cpu_count", lambda: 64)
    monkeypatch.setenv("SLURM_CPUS_PER_TASK", allocation)
    monkeypatch.setenv("OMP_NUM_THREADS", requested)
    monkeypatch.setenv("OPENBLAS_NUM_THREADS", "64")
    monkeypatch.setenv("TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD", "1")
    config = {"_source": tmp_path / "source", "_dependencies": [], "_assets": {}}
    env = u._environment(config, tmp_path)
    assert {env[key] for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")} == {expected}
    assert "TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD" not in env


@pytest.mark.parametrize("fails", [False, True])
def test_original_launcher_scopes_only_namespace_checkpoint_allowlist(tmp_path, monkeypatch, fails):
    """Execute the fixed launcher's control flow, without pretending neural inference."""
    import argparse
    events = []
    active = []
    class SafeGlobals:
        def __init__(self, values):
            assert values == [argparse.Namespace]
        def __enter__(self):
            active.append(argparse.Namespace)
            events.append("enter")
        def __exit__(self, *args):
            active.clear()
            events.append("exit")
    model_weights = tmp_path / "operator-pinned-checkpoint.pth"
    config = {"_python": Path(sys.executable), "_assets": {"doppelgangers_weights": model_weights}}
    command = u.build_command("original_sfm", config, tmp_path / "data", tmp_path / "workspace",
                              {"min_num_matches": 20, "min_inliers": 25})
    pipeline = types.ModuleType("fixture_pipeline")
    pipeline.options = {"doppelgangers": {}, "mapper": {}, "retrieval": {"num_pairs_retrieval": 100}}
    (tmp_path / "data").mkdir()
    (tmp_path / "workspace").mkdir()
    (tmp_path / "data/image_list.txt").write_text("a.jpg\nb.jpg\nc.jpg\n")
    def run_pipeline(workspace, images, image_list):
        assert active == [argparse.Namespace]
        assert workspace == tmp_path / "workspace"
        assert images == tmp_path / "data/images"
        assert image_list == tmp_path / "data/image_list.txt"
        assert pipeline.options == {"doppelgangers": {"weights": str(model_weights)},
                                    "mapper": {"min_num_matches": 20, "abs_pose_min_num_inliers": 25},
                                    "retrieval": {"num_pairs_retrieval": 2}}
        events.append("run")
        if fails:
            raise RuntimeError("fixture failure")
    pipeline.run_pipeline = run_pipeline
    reconstruction = types.ModuleType("historic_reconstruction_pipeline.reconstruction")
    reconstruction.pipeline = pipeline
    monkeypatch.setitem(sys.modules, "historic_reconstruction_pipeline", types.ModuleType("historic_reconstruction_pipeline"))
    monkeypatch.setitem(sys.modules, "historic_reconstruction_pipeline.reconstruction", reconstruction)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(serialization=types.SimpleNamespace(safe_globals=SafeGlobals)))
    monkeypatch.setattr(sys, "argv", ["-c", *command[3:]])
    if fails:
        with pytest.raises(RuntimeError, match="fixture failure"):
            exec(command[2], {})
    else:
        exec(command[2], {})
    assert events == ["enter", "run", "exit"]
    assert active == []
    assert json.loads((tmp_path / "workspace/adapter-settings.json").read_text()) == {
        "retrieval_neighbors_requested": 100, "retrieval_neighbors_effective": 2}


@pytest.mark.parametrize("network", [False, True])
def test_network_environment_uses_operator_trust_and_only_enabled_proxy(tmp_path, monkeypatch, network):
    bundle = tmp_path / "operator-ca.pem"
    bundle.write_text("test-only CA path fixture")
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "0")
    monkeypatch.setenv("HTTPS_PROXY", "http://cluster-proxy.example:3128")
    monkeypatch.setenv("no_proxy", "localhost")
    monkeypatch.setenv("SSL_CERT_FILE", "/untrusted/inherited.pem")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "/untrusted/inherited.pem")
    config = {"_source": tmp_path / "source", "_dependencies": [],
              "_assets": {"tls_ca_bundle": bundle}, "allow_network": network}
    env = u._environment(config, tmp_path)
    if network:
        assert env["HTTPS_PROXY"] == "http://cluster-proxy.example:3128"
        assert env["no_proxy"] == "localhost"
        assert env["SSL_CERT_FILE"] == env["REQUESTS_CA_BUNDLE"] == str(bundle)
    else:
        assert not ({"HTTPS_PROXY", "no_proxy", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"} & env.keys())
    assert env["HF_HUB_OFFLINE"] == env["TRANSFORMERS_OFFLINE"] == "1"
    assert env["ORT_DISABLE_TELEMETRY"] == "1"


@pytest.mark.parametrize("fails", [False, True])
def test_geolocation_launcher_scopes_checkpoint_global_and_preserves_cli(tmp_path, monkeypatch, fails):
    import argparse
    import runpy
    events = []
    active = []
    class SafeGlobals:
        def __init__(self, values):
            assert values == [argparse.Namespace]
        def __enter__(self):
            active.append(argparse.Namespace)
            events.append("enter")
        def __exit__(self, *args):
            active.clear()
            events.append("exit")
    weights = tmp_path / "operator-pinned.pth"
    config = {"_python": Path(sys.executable), "_assets": {"doppelgangers_weights": weights},
              "allow_network": True}
    command = u.build_command("geolocalization", config, tmp_path, tmp_path / "work", {},
                              ("--gps-json", tmp_path / "gps.json"))
    def run_module(module, *, run_name, alter_sys):
        assert active == [argparse.Namespace]
        assert module == "historic_reconstruction_pipeline.geolocalization.geoloc_pipeline"
        assert run_name == "__main__" and alter_sys is True
        assert sys.argv[sys.argv.index("--dg-weights") + 1] == str(weights)
        assert sys.argv[sys.argv.index("--gps-json") + 1] == str(tmp_path / "gps.json")
        events.append("run")
        if fails:
            raise RuntimeError("fixture failure")
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(serialization=types.SimpleNamespace(safe_globals=SafeGlobals)))
    monkeypatch.setattr(runpy, "run_module", run_module)
    monkeypatch.setattr(sys, "argv", ["-c", *command[3:]])
    if fails:
        with pytest.raises(RuntimeError, match="fixture failure"):
            exec(command[2], {})
    else:
        exec(command[2], {})
    assert events == ["enter", "run", "exit"] and active == []
    skipped = u.build_command("geolocalization", config, tmp_path, tmp_path / "work",
                              {"skip_doppelgangers": True}, ("--gps-json", tmp_path / "gps.json"))
    assert skipped[1:3] == ["-m", "historic_reconstruction_pipeline.geolocalization.geoloc_pipeline"]


def test_pin_detects_source_and_config_drift(tmp_path, monkeypatch):
    config, path, source = configured(tmp_path, monkeypatch)
    assert u.load_config("segmentation")["_source"] == source
    (source / "marker.py").write_text("VALUE = 2\n")
    with pytest.raises(ValueError, match="checksum mismatch"):
        u.load_config("segmentation")
    config["source"]["sha256"] = u.tree_sha256(source)
    config["enabled_stages"] = ["segmentation"]
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="not enabled"):
        u.load_config("mvs")


def test_pins_ignore_bytecode_but_reject_source_symlinks(tmp_path):
    root = tmp_path / "source"
    root.mkdir()
    (root / "main.py").write_text("print('source')")
    before = u.tree_sha256(root)
    (root / "__pycache__").mkdir()
    (root / "__pycache__/main.pyc").write_bytes(b"compiled")
    assert u.tree_sha256(root) == before
    (root / "injected.py").symlink_to(root / "main.py")
    with pytest.raises(ValueError, match="symlink"):
        u.tree_sha256(root)


@pytest.mark.parametrize("stage,parameters", [
    ("segmentation", {"command": "anything"}),
    ("original_sfm", {"min_num_matches": True}),
    ("original_sfm", {"num_retrieval": 0}),
    ("refine_keypoints", {"max_refine_num": 0}),
    ("refine_keypoints", {"run_ba": "false"}),
    ("mvs", {"batch_size": 5}),
    ("geolocalization", {"skip_doppelgangers": "true"}),
])
def test_public_parameters_cannot_select_commands_or_invalid_resources(tmp_path, stage, parameters):
    config = {"_python": Path(sys.executable), "_source": tmp_path, "_assets": {"doppelgangers_weights": tmp_path,
              "mvs_model_config": tmp_path, "mvs_data_config": tmp_path, "mvs_checkpoint": tmp_path}, "allow_network": True}
    with pytest.raises(ValueError):
        u.build_command(stage, config, tmp_path / "data", tmp_path / "workspace", parameters, ("--gps-json", tmp_path / "gps.json"))


def test_geolocation_requires_explicit_network_runtime(tmp_path):
    config = {"_python": Path(sys.executable), "_assets": {}}
    with pytest.raises(ValueError, match="network acquisition disabled"):
        u.build_command("geolocalization", config, tmp_path, tmp_path / "work", {"skip_doppelgangers": True}, ("--gps-json", tmp_path / "gps.json"))


@pytest.mark.parametrize("compiled,onnx,error", [(False, True, "lacks a compiled CASPAR backend"),
                                                (True, False, "compiled LoMa/ONNX support"), (True, True, None)])
def test_caspar_preflight_checks_compiled_backend_not_only_enum(tmp_path, monkeypatch, compiled, onnx, error):
    import importlib
    commands = []
    backend = object()
    checked = []
    def options(**values):
        assert values == {"ba_local_backend": backend, "ba_global_backend": backend}
        return types.SimpleNamespace(check=lambda: checked.append(True) or compiled)
    colmap = types.SimpleNamespace(
        BundleAdjustmentBackend=types.SimpleNamespace(CASPAR=backend), IncrementalPipelineOptions=options,
        FeatureExtractorType=types.SimpleNamespace(LOMA_B=object()))
    if onnx:
        colmap.LomaExtractionOptions = object
    monkeypatch.setitem(sys.modules, "pycolmap", colmap)
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(__version__="fixture",
        cuda=types.SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setattr(importlib, "import_module", lambda name: None)
    monkeypatch.setattr(u, "_execute", lambda command, *args: commands.append(command))
    config = {"_python": Path(sys.executable), "_assets": {"model_cache": tmp_path, "torch_cache": tmp_path}}
    u._preflight("geolocalization", config, {}, tmp_path, {"skip_doppelgangers": True})
    command = commands[0]
    monkeypatch.setattr(sys, "argv", ["-c", *command[3:]])
    if error is None:
        exec(command[2], {})
    else:
        with pytest.raises(RuntimeError, match=error):
            exec(command[2], {})
    assert checked == [True]


def test_geolocation_operator_seed_bounds_ids_without_changing_inference(tmp_path):
    seed = tmp_path / "selected-panoramas.json"
    seed.write_text(json.dumps({"actual-pano_A": {"lat": 47.4886, "lon": 19.0612},
                                "actual-pano_B": {"lat": 47.4887, "lon": 19.0613}}))
    config = {"_python": Path(sys.executable), "_assets": {"pano_metadata": seed},
              "allow_network": True, "geolocation_acquisition": {"max_panoramas": 2,
                  "bounds_margin": 20, "zoom": 2, "cubemap_width": 512, "download_workers": 1}}
    command = u.build_command("geolocalization", config, tmp_path, tmp_path / "work",
                              {"skip_doppelgangers": True}, ("--gps-json", tmp_path / "gps.json"))
    for flag, value in {"--pano-meta-json": str(seed), "--bounds-margin": "20", "--zoom": "2",
                        "--cubemap-width": "512", "--download-workers": "1"}.items():
        assert command[command.index(flag) + 1] == value
    assert "--no-caspar" not in command
    config["geolocation_acquisition"]["max_panoramas"] = 1
    with pytest.raises(ValueError, match="panorama count"):
        u._geolocation_acquisition_args(config)


def test_dense_intrinsics_does_not_require_unused_caspar_or_loma(tmp_path, monkeypatch):
    """The source uses RoMa correspondences and explicitly caspar=False triangulation."""
    import importlib
    commands = []
    imported = []
    monkeypatch.setitem(sys.modules, "pycolmap", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "torch", types.SimpleNamespace(__version__="fixture",
        cuda=types.SimpleNamespace(is_available=lambda: True)))
    monkeypatch.setattr(importlib, "import_module", lambda name: imported.append(name))
    monkeypatch.setattr(u, "_execute", lambda command, *args: commands.append(command))
    config = {"_python": Path(sys.executable), "_assets": {"romav2_hub": tmp_path}}
    u._preflight("dense_intrinsics", config, {}, tmp_path, {})
    monkeypatch.setattr(sys, "argv", ["-c", *commands[0][3:]])
    exec(commands[0][2], {})
    assert "romav2" in imported
    assert "historic_reconstruction_pipeline.geolocalization.dense_intrinsics" in imported


@pytest.mark.parametrize("settings", [{"max_panoramas": True}, {"zoom": 5}, {"download_workers": 0},
                                     {"bounds_margin": float("inf")}, {"command": "other"}])
def test_geolocation_operator_acquisition_rejects_unbounded_or_untyped_settings(tmp_path, settings):
    with pytest.raises(ValueError):
        u._geolocation_acquisition_args({"geolocation_acquisition": settings, "_assets": {}})


@pytest.mark.parametrize("seed", [{"../../outside": {"lat": 47, "lon": 19}},
                                 {"pano": {"lat": float("nan"), "lon": 19}},
                                 {"pano": {"lat": 47, "lon": 181}}, {}])
def test_geolocation_operator_seed_checks_paths_coordinates_and_nonempty_count(tmp_path, seed):
    path = tmp_path / "seed.json"
    path.write_text(json.dumps(seed))
    with pytest.raises(ValueError):
        u._geolocation_acquisition_args({"geolocation_acquisition": {}, "_assets": {"pano_metadata": path}})


@pytest.mark.parametrize("name", ["workspace/rig_config.pkl", "workspace/object.npy", "checkpoint.pth", "module.py"])
def test_input_bundle_never_loads_untrusted_executable_caches(tmp_path, monkeypatch, name):
    configured(tmp_path, monkeypatch)
    inputs = dataset_zip(tmp_path, monkeypatch, {name: "not trusted"})
    with pytest.raises(ValueError, match="pickle caches"):
        u.run("segmentation", inputs, {}, tmp_path / "out")


@pytest.mark.parametrize("stage", ["segmentation", "original_sfm", "geolocalization"])
def test_same_stem_images_cannot_overwrite_each_others_masks(tmp_path, monkeypatch, stage):
    configured(tmp_path, monkeypatch)
    inputs = dataset_zip(tmp_path, monkeypatch)
    content = (tmp_path / "inputs/image.jpg").read_bytes()
    with zipfile.ZipFile(inputs["input_file"], "a") as archive:
        archive.writestr("images/same.jpg", content)
        archive.writestr("images/same.png", content)
    monkeypatch.setattr(u, "_preflight", lambda *args: pytest.fail("Collision must fail before inference"))
    with pytest.raises(ValueError, match="collide.*mask filenames"):
        u.run(stage, inputs, {}, tmp_path / "out")


def test_coordinate_schema_is_checked_before_processing(tmp_path):
    path = tmp_path / "coords.json"
    path.write_text(json.dumps({"a.jpg": [91, 13]}))
    with pytest.raises(ValueError, match="outside"):
        u._validate_geo(path, ["a.jpg"])
    path.write_text(json.dumps({"different.jpg": [51, 13]}))
    with pytest.raises(ValueError, match="matching image names"):
        u._validate_geo(path, ["a.jpg"])
    path.write_text(json.dumps([[51, 13], [51.1, 13], [51, 13.1]]))
    u._validate_geo(path, [], bounds=True)


def test_segmentation_subprocess_contract_retains_dataset_and_checks_all_masks(tmp_path, monkeypatch):
    config, config_file, package = configured(tmp_path, monkeypatch)
    prep = package / "preprocess"
    prep.mkdir()
    (prep / "__init__.py").write_text("")
    # This deterministic child is a file-contract harness, not Mask2Former inference.
    (prep / "generate_segmask.py").write_text('''import argparse
from pathlib import Path
from PIL import Image
p=argparse.ArgumentParser()
for name in ('image_dir','image_list_path','output_path_mask'): p.add_argument('--'+name,required=True)
a=p.parse_args()
for name in Path(a.image_list_path).read_text().splitlines():
 with Image.open(Path(a.image_dir)/name) as image:
  target=(Path(a.output_path_mask)/name).with_suffix('.png'); target.parent.mkdir(parents=True,exist_ok=True)
  Image.new('L',image.size,255).save(target)
''')
    config["source"]["sha256"] = u.tree_sha256(package)
    config_file.write_text(json.dumps(config))
    inputs = dataset_zip(tmp_path, monkeypatch)
    monkeypatch.setattr(u, "_preflight", lambda *args: None)
    files, metrics = u.run("segmentation", inputs, {}, tmp_path / "out")
    assert metrics["masks"] == 3
    assert files["dataset_bundle"] == files["workspace_bundle"]
    with zipfile.ZipFile(files["dataset_bundle"]) as archive:
        assert "dataset.json" in archive.namelist()
        assert len([name for name in archive.namelist() if name.startswith("masks/")]) == 3
        manifest = json.loads(archive.read("dataset.json"))
        assert manifest["schema"] == "webhdp.historic-dataset/1"
    receipt = json.loads(files["report"].read_text())
    assert receipt["source_sha256"] == config["source"]["sha256"]
    assert receipt["runtime_pins"]["python_sha256"]


def test_zero_exit_without_masks_is_not_success(tmp_path, monkeypatch):
    configured(tmp_path, monkeypatch)
    inputs = dataset_zip(tmp_path, monkeypatch)
    monkeypatch.setattr(u, "_preflight", lambda *args: None)
    monkeypatch.setattr(u, "_execute", lambda *args: None)
    with pytest.raises(ValueError, match="mask for every image"):
        u.run("segmentation", inputs, {}, tmp_path / "out")


def test_generated_python_launchers_are_syntactically_valid(tmp_path, monkeypatch):
    config = {"_python": Path(sys.executable), "_source": tmp_path, "_dependencies": [],
              "_assets": {"doppelgangers_weights": tmp_path, "model_cache": tmp_path, "torch_cache": tmp_path}, "timeout_seconds": 60}
    command = u.build_command("original_sfm", config, tmp_path / "data", tmp_path / "out", {})
    ast.parse(command[2])
    commands = []
    monkeypatch.setattr(u, "_execute", lambda command, *args: commands.append(command))
    u._preflight("original_sfm", config, {}, tmp_path, {})
    ast.parse(commands[0][2])
    # Every fixed child source constant, including the MVS tuple generator, must parse.
    tree = ast.parse(Path(u.__file__).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in {"script", "launcher"} for target in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                ast.parse(node.value.value)


def test_child_failure_is_reported_without_fabricated_outputs(tmp_path):
    config = {"timeout_seconds": 60}
    with pytest.raises(ValueError, match="exit code 7"):
        u._execute([sys.executable, "-c", "raise SystemExit(7)"], config, os.environ.copy(), tmp_path, tmp_path / "log")


def test_proxy_log_redaction_handles_chunk_boundaries_and_preserves_other_bytes(tmp_path):
    log = tmp_path / "child.log"
    proxy = b"http://dummy-user:dummy-password@proxy.example:3128"
    second = b"https://another-proxy.example:8080"
    prefix = b"a" * (64 * 1024 - 11)
    original = prefix + proxy + b"\xff\x00 * .example " + second + b"\n" + proxy
    log.write_bytes(original)
    u._redact_proxy_log(log, {"HTTPS_PROXY": proxy.decode(), "http_proxy": second.decode(),
                             "ALL_PROXY": "", "NO_PROXY": "*", "no_proxy": ".example"})
    assert log.read_bytes() == original.replace(proxy, b"[REDACTED_PROXY]").replace(second, b"[REDACTED_PROXY]")
    assert not list(tmp_path.glob("*.redacted-*"))


def test_execute_sets_pwd_to_actual_per_call_working_directory(tmp_path):
    cwd = tmp_path / "actual-stage-directory"
    cwd.mkdir()
    env = {"PWD": "/stale/host/directory"}
    log = tmp_path / "pwd.log"
    u._execute([sys.executable, "-c", "import json,os;print(json.dumps([os.getcwd(),os.environ['PWD']]))"],
               {"timeout_seconds": 5}, env, cwd, log)
    assert json.loads(log.read_text()) == [str(cwd.resolve()), str(cwd.resolve())]
    assert env["PWD"] == "/stale/host/directory"


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_execute_redacts_persisted_proxy_before_success_failure_or_timeout_tail(tmp_path, capsys, outcome):
    proxy = "http://dummy-user:dummy-password@proxy.example:3128"
    command = [sys.executable, "-c",
               "import os,time;print('child says '+os.environ['HTTPS_PROXY'],flush=True);" +
               ("time.sleep(10)" if outcome == "timeout" else "raise SystemExit(" + ("7" if outcome == "failure" else "0") + ")")]
    log = tmp_path / "child.log"
    if outcome == "success":
        u._execute(command, {"timeout_seconds": 5}, {"HTTPS_PROXY": proxy}, tmp_path, log)
    else:
        with pytest.raises(ValueError, match="configured time limit" if outcome == "timeout" else "exit code 7"):
            u._execute(command, {"timeout_seconds": 0.2 if outcome == "timeout" else 5},
                       {"HTTPS_PROXY": proxy}, tmp_path, log)
    assert proxy not in log.read_text()
    assert "child says [REDACTED_PROXY]" in log.read_text()
    diagnostics = capsys.readouterr().err
    assert proxy not in diagnostics
    if outcome != "success":
        assert "child says [REDACTED_PROXY]" in diagnostics


def test_pinned_native_libraries_precede_inherited_runtime_paths(tmp_path, monkeypatch):
    libraries = tmp_path / "checked-libraries"
    libraries.mkdir()
    monkeypatch.setenv("LD_LIBRARY_PATH", "/cluster/driver-libraries")
    config = {"_source": tmp_path / "source", "_dependencies": [], "_assets": {"native_libraries": libraries}}
    env = u._environment(config, tmp_path)
    assert env["LD_LIBRARY_PATH"] == str(libraries) + ":/cluster/driver-libraries"
    libraries.rmdir()
    libraries.write_text("not a directory")
    with pytest.raises(ValueError, match="native_libraries must be a directory"):
        u._environment(config, tmp_path)
