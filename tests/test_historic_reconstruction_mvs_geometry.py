"""Real PLY decoding at the MVS output boundary; no neural inference claim."""
import pytest

pytest.importorskip("trimesh")
from external_code.historic_reconstruction_runtime import upstream as u


def ply(tmp_path, coordinates, face="3 0 1 2"):
    path = tmp_path / "mesh.ply"
    path.write_text("ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n"
                    "element face 1\nproperty list uchar int vertex_indices\nend_header\n"
                    + coordinates + "\n" + face + "\n")
    return path


def test_real_ply_triangle_has_expected_surface_area(tmp_path):
    assert u._mvs_mesh_metrics(ply(tmp_path, "0 0 0\n1 0 0\n0 1 0")) == {
        "vertices": 3, "faces": 1, "surface_area": 0.5}


@pytest.mark.parametrize("coordinates,face,error", [
    ("nan 0 0\n1 0 0\n0 1 0", "3 0 1 2", "non-finite"),
    ("0 0 0\n1 0 0\n0 1 0", "3 0 1 9", "face indices"),
    ("0 0 0\n1 0 0\n2 0 0", "3 0 1 2", "surface area"),
])
def test_mvs_rejects_malformed_or_degenerate_ply(tmp_path, coordinates, face, error):
    with pytest.raises(ValueError, match=error):
        u._mvs_mesh_metrics(ply(tmp_path, coordinates, face))
