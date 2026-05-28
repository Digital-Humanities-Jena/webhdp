import pandas as pd

from services.msf_service import MSFService


def test_validate_msf_marks_obj_dependencies_as_implicitly_included(tmp_path):
    glb_path = tmp_path / "test_model.glb"
    obj_path = tmp_path / "test_model.obj"
    mtl_path = tmp_path / "test_model.mtl"
    texture_path = tmp_path / "albedo.jpg"

    glb_path.write_bytes(b"glb")
    obj_path.write_text("mtllib test_model.mtl\n", encoding="utf-8")
    mtl_path.write_text("map_Kd albedo.jpg\n", encoding="utf-8")
    texture_path.write_bytes(b"jpg")

    df = pd.DataFrame({"Filename": ["test_model.glb"]})
    service = MSFService()
    result = service.validate_msf_against_directory(
        df=df,
        directory_files=[path.name for path in tmp_path.iterdir()],
        filename_column="Filename",
        directory_root=str(tmp_path),
    )

    assert result.is_valid is True
    assert result.matched_files == ["test_model.glb"]
    assert result.unmapped_files == []
    assert sorted(result.implicitly_included_files) == [
        "albedo.jpg",
        "test_model.mtl",
        "test_model.obj",
    ]
