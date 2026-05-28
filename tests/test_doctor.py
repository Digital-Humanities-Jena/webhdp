from scripts.doctor import _meets_min_version, _parse_semver


def test_parse_semver_accepts_common_tool_outputs():
    assert _parse_semver("v22.22.2") == (22, 22, 2)
    assert _parse_semver("Python 3.11.15") == (3, 11, 15)
    assert _parse_semver("uv 0.11.8 (aarch64-unknown-linux-gnu)") == (0, 11, 8)


def test_meets_min_version_compares_numeric_parts():
    assert _meets_min_version("v22.22.2", "22.12.0")
    assert _meets_min_version("3.11", "3.11.0")
    assert not _meets_min_version("v20.19.0", "22.12.0")
