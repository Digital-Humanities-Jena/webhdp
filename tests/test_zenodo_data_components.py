"""Real-file integrity and HDPC export checks, including hostile inputs."""
import csv
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import stat
import struct
import sys
import wave
import zipfile

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "external_code/zenodo_component_runtime"
sys.path.insert(0, str(RUNTIME))
spec = importlib.util.spec_from_file_location("zenodo_data_runner", RUNTIME / "component_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
from common import safe_unpack, staged_file


@pytest.fixture
def staging(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBHDP_INPUT_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def database(staging):
    source = staging / "project.hdpc"
    with sqlite3.connect(source) as connection:
        connection.executescript('''
          CREATE TABLE project_info (project_id INTEGER PRIMARY KEY, project_name TEXT, project_short_code TEXT);
          CREATE TABLE source_files (file_id INTEGER PRIMARY KEY, project_id INTEGER, filename TEXT, status TEXT, added_timestamp TEXT);
          CREATE TABLE zenodo_records (record_id INTEGER PRIMARY KEY, project_id INTEGER, record_status TEXT, created_timestamp TEXT);
          CREATE TABLE metadata_values (value_id INTEGER PRIMARY KEY, project_id INTEGER, value TEXT, extracted_timestamp TEXT);
          CREATE TABLE api_log (log_id INTEGER PRIMARY KEY, project_id INTEGER, status TEXT, timestamp TEXT);
          CREATE TABLE batches (batch_id INTEGER PRIMARY KEY, project_id INTEGER);
          CREATE TABLE strange ("=HEADER()" TEXT, "quote""column" TEXT, binary BLOB);
        ''')
        connection.executemany("INSERT INTO project_info VALUES (?,?,?)", [(1,"Measured project","A"),(2,"Other project","B")])
        connection.executemany("INSERT INTO source_files VALUES (?,?,?,?,?)", [(1,1,"photo.jpg","ready","2026-11-01 10:00:00"),(2,1,"=HYPERLINK(\"https://example.invalid\")","pending","2026-11-02 10:00:00"),(3,2,"mesh.glb","ready","2026-11-03 10:00:00")])
        connection.executemany("INSERT INTO zenodo_records VALUES (?,?,?,?)", [(1,1,"published","2026-11-01"),(2,2,"draft","2026-11-03")])
        connection.execute("INSERT INTO metadata_values VALUES (1,1,'name','2026-11-01')")
        connection.execute("INSERT INTO api_log VALUES (1,1,'success','2026-11-01')")
        connection.execute("INSERT INTO batches VALUES (1,1)")
        connection.execute("INSERT INTO strange VALUES (?,?,?)", (" @SUM(1)", "ordinary", b"\x00\xff"))
    return source


def invoke(staging, key, source, parameters=None, out="output"):
    return runner.run_component(key, {"inputs":{"input_file":str(source)},"parameters":parameters or {}}, staging / out)


def report(result, role):
    return json.loads(Path(result["outputs"][role]).read_text())


def rows(result):
    with Path(result["outputs"]["csv_file"]).open(encoding="utf-8-sig",newline="") as stream:
        return list(csv.reader(stream))


def test_integrity_real_image_and_unchanged_input(staging):
    source = staging / "photo.png"
    Image.new("RGB",(8,12),"red").save(source)
    source.chmod(0o444)
    before, mode = source.read_bytes(), source.stat().st_mode
    result = invoke(staging,"validate_file_integrity",source)
    metadata = report(result,"validation_report")
    assert metadata["is_valid"] is True
    assert metadata["validation_details"]["width"] == 8
    assert metadata["sha256"] == hashlib.sha256(before).hexdigest()
    assert source.read_bytes() == before and source.stat().st_mode == mode
    assert result["status"] == "completed" and result["artifacts"][0]["metadata"]["sha256"]


@pytest.mark.parametrize("name,content",[("bad.png",b"not image"),("bad.json",b'{"a":NaN}'),("bad.gltf",b'{"asset":{"version":"1.0"}}'),("bad.glb",b"glTF"),("bad.hdpc",b"not database"),("empty.txt",b"")])
def test_integrity_invalid_files_return_negative_verdict(staging,name,content):
    source=staging/name; source.write_bytes(content)
    result=invoke(staging,"validate_file_integrity",source)
    metadata=report(result,"validation_report")
    assert result["success"] is True  # The validator ran; its verdict is false.
    assert metadata["is_valid"] is False and metadata["errors"]
    assert result["summary"]["is_valid"] is False


def test_integrity_valid_json_zip_sqlite_and_readability_coverage(staging,database):
    json_file=staging/"valid.json"; json_file.write_text('{"ok":true}')
    archive=staging/"valid.zip"
    with zipfile.ZipFile(archive,"w") as opened:
        opened.writestr("nested/data.txt","fixture")
    text=staging/"unknown.dat"; text.write_bytes(b"readable arbitrary bytes")
    for index,source in enumerate((json_file,archive,database,text)):
        metadata=report(invoke(staging,"validate_file_integrity",source,out=f"out{index}"),"validation_report")
        assert metadata["is_valid"]
        if source==text:
            assert metadata["warnings"] and metadata["validation_details"]["validation_coverage"]=="readability only"
        if source==database:
            assert metadata["validation_details"]["quick_check"]=="ok"


def test_integrity_wav_detects_truncation(staging):
    source=staging/"sound.wav"
    with wave.open(str(source),"wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000); audio.writeframes(b"\0\0"*100)
    assert report(invoke(staging,"validate_file_integrity",source),"validation_report")["is_valid"]
    source.write_bytes(source.read_bytes()[:-8])
    invalid=report(invoke(staging,"validate_file_integrity",source,out="bad"),"validation_report")
    assert not invalid["is_valid"] and "truncated" in invalid["errors"][0]


def test_integrity_glb_real_chunk_structure_and_declared_lengths(staging):
    source=staging/"model.glb"
    document=json.dumps({"asset":{"version":"2.0"},"buffers":[{"byteLength":4}]}).encode()
    document+=b" "*(-len(document)%4)
    chunks=struct.pack("<I4s",len(document),b"JSON")+document+struct.pack("<I4s",4,b"BIN\0")+b"\0\0\0\0"
    original=struct.pack("<4sII",b"glTF",2,12+len(chunks))+chunks
    source.write_bytes(original)
    metadata=report(invoke(staging,"validate_file_integrity",source),"validation_report")
    assert metadata["is_valid"] and metadata["validation_details"]["chunks"]==2
    source.write_bytes(original[:-1])
    assert not report(invoke(staging,"validate_file_integrity",source,out="truncated"),"validation_report")["is_valid"]
    duplicate=chunks+struct.pack("<I4s",4,b"BIN\0")+b"\0\0\0\0"
    source.write_bytes(struct.pack("<4sII",b"glTF",2,12+len(duplicate))+duplicate)
    metadata=report(invoke(staging,"validate_file_integrity",source,out="duplicate"),"validation_report")
    assert not metadata["is_valid"] and "Duplicate binary" in metadata["errors"][0]


def test_integrity_zip_checks_payload_crc(staging):
    source=staging/"archive.zip"
    with zipfile.ZipFile(source,"w",compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("fixture.txt",b"measured payload")
    source.write_bytes(source.read_bytes().replace(b"measured payload",b"damaged! payload"))
    metadata=report(invoke(staging,"validate_file_integrity",source),"validation_report")
    assert not metadata["is_valid"] and "checksum" in metadata["errors"][0]


def test_integrity_real_flac_headers_and_unchanged_source(staging):
    # Generated 440 Hz, 0.1 s, 8 kHz mono FLAC with ffmpeg; padding removed.
    # Embedding this measured 485-byte fixture keeps tests independent of ffmpeg.
    source = staging / "tone.flac"
    source.write_bytes(base64.b64decode("ZkxhQwAAACICQAJAAACUAAEKAfQA8AAAAyAQwjlZxu/PiF5P0MPupVblBAAAFQ0AAABMYXZmNjIuMTIuMTAxAAAAAIEAAAD/+CQIAMpOAAAFawoyDcUPtg/NDgUKlOYxEodSqSsgGVrN6gL4fa+ANlSiwjFiGEalFhMS0WWllpSSRZZapMIxZQslEYRqWWlFSliMqi0TC0WlLIwmTBGFKWRicVllRZUqrLLKShGEy0y5YRhSiypaUomFpLKxGVlSiwjFiGEalFhMS0WWllpSSRZZapMIxZQslEYRqWWlFSliMqi0TC0WlLIwmTBGFKWRicVllRZUqrLLKShGEy0y5YRhSiypaUomFpLKxGVlSiwjFiGEalFhMS0WWllpSSRZZapMIxZQslEYRqWWlFSliMqi0TC0WlLIwmTBGFKWRicVllRZUqrLLKShGEy0y5bA8P/4ZAgB3+VO8YfwE/CB8sX2mfuJAQEGWuWZcrtyck9SeQzefqHQ/siAISU5ntGFiEEgihDTPfQoCwKBGCHNvMRgkggkFFOPbpEEgSCi/GQMQygoEQgmCGnnHSEhBEKCMmzj0wUIIhEk0GQaGEMEhCEQTCHRnGtCQRCElZw41kRAsBMFo0PZiGChEEgkpzPaMLEIYu4="))
    before = source.read_bytes()
    metadata = report(invoke(staging, "validate_file_integrity", source), "validation_report")
    assert metadata["is_valid"]
    assert metadata["validation_details"]["format"] == "FLAC"
    assert metadata["validation_details"]["duration_seconds"] == pytest.approx(0.1)
    assert metadata["validation_details"]["sample_rate"] == 8000
    assert metadata["validation_details"]["channels"] == 1
    assert "not decoded" in metadata["validation_details"]["validation_coverage"]
    assert metadata["validation_dispatch"] == "filename extension"
    assert source.read_bytes() == before


@pytest.mark.parametrize("extension", ["mp3", "flac", "ogg", "opus", "m4a", "aac", "aiff"])
def test_integrity_corrupt_audio_has_negative_verdict(staging, extension):
    source = staging / ("corrupt." + extension)
    source.write_bytes(b"not an audio stream")
    metadata = report(invoke(staging, "validate_file_integrity", source), "validation_report")
    assert metadata["is_valid"] is False and metadata["errors"]


@pytest.mark.parametrize("mode,count",[("files_overview",3),("zenodo_records",2),("metadata_export",1),("project_summary",2),("api_log",1),("custom",3)])
def test_real_hdpc_export_modes_source_unchanged(staging,database,mode,count):
    before=database.read_bytes()
    result=invoke(staging,"hdpc_exporter",database,{"export_mode":mode})
    metadata=report(result,"export_report")
    assert metadata["rows_exported"]==count and not metadata["truncated"]
    assert database.read_bytes()==before and metadata["source_modified"] is False
    assert len(rows(result))==count+1
    if mode=="project_summary":
        values=list(csv.DictReader(io.StringIO(Path(result["outputs"]["csv_file"]).read_text(encoding="utf-8-sig"))))
        assert values[0]["total_files"]=="2" and values[1]["total_files"]=="1"
        assert values[0]["total_batches"]=="1" and values[1]["total_batches"]=="0"


def test_hdpc_filters_dates_columns_and_limit(staging,database):
    result=invoke(staging,"hdpc_exporter",database,{"filter_status":"ready","date_range_start":"2026-11-02","date_range_end":"2026-11-03","columns":"file_id,filename","include_project_info":False})
    assert rows(result)==[["file_id","filename"],["3","mesh.glb"]]
    limited=invoke(staging,"hdpc_exporter",database,{"max_rows":1},out="limited")
    assert report(limited,"export_report")["truncated"] is True and len(rows(limited))==2


def test_hdpc_sql_values_parameterized_and_identifiers_allowlisted(staging,database):
    result=invoke(staging,"hdpc_exporter",database,{"filter_status":"ready' OR 1=1 --"})
    assert len(rows(result))==1
    for parameters in ({"export_mode":"custom","table":"source_files; DROP TABLE project_info;--"},{"columns":"filename,(SELECT sqlite_version())"},{"columns":"filename,filename"},{"date_range_start":"2026-11-05","date_range_end":"2026-11-01"}):
        with pytest.raises(ValueError):
            invoke(staging,"hdpc_exporter",database,parameters,out="bad")
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT COUNT(*) FROM source_files").fetchone()==(3,)


def test_csv_formula_headers_cells_blobs_and_quoted_identifiers(staging,database):
    result=invoke(staging,"hdpc_exporter",database,{"export_mode":"custom","table":"strange"})
    assert rows(result)==[["'=HEADER()",'quote"column',"binary"],["' @SUM(1)","ordinary","hex:00ff"]]


def test_hdpc_requires_real_project_schema(staging):
    source=staging/"empty.sqlite"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
    with pytest.raises(ValueError,match="project_info"):
        invoke(staging,"hdpc_exporter",source)


def test_contract_refuses_paths_outside_staging_and_existing_outputs(staging,database):
    outside=staging.parent/"outside.txt"; outside.write_text("outside")
    with pytest.raises(ValueError):
        staged_file({"input_file":str(outside)})
    linked=staging/"linked.hdpc"; linked.symlink_to(database)
    with pytest.raises(ValueError):
        staged_file({"input_file":str(linked)})
    invoke(staging,"hdpc_exporter",database)
    with pytest.raises(ValueError,match="already exists"):
        invoke(staging,"hdpc_exporter",database)


@pytest.mark.parametrize("name",["../escape","/absolute","C:/absolute","nested\\bad","a/../bad"])
def test_unpack_rejects_traversal(staging,name):
    source=staging/"unsafe.zip"
    with zipfile.ZipFile(source,"w") as archive:
        archive.writestr(name,b"payload")
    with pytest.raises(ValueError,match="Unsafe"):
        safe_unpack(source,staging/"unpacked")


def test_unpack_rejects_symlinks_and_duplicate_case(staging):
    source=staging/"unsafe.zip"
    item=zipfile.ZipInfo("link"); item.external_attr=(stat.S_IFLNK | 0o777)<<16
    with zipfile.ZipFile(source,"w") as archive:
        archive.writestr(item,b"../outside")
    with pytest.raises(ValueError,match="linked"):
        safe_unpack(source,staging/"links")
    with zipfile.ZipFile(source,"w") as archive:
        archive.writestr("model.obj",b"one"); archive.writestr("MODEL.obj",b"two")
    with pytest.raises(ValueError,match="duplicate"):
        safe_unpack(source,staging/"duplicates")
