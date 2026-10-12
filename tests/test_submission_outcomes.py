from types import SimpleNamespace

import pytest

from services.submission_outcomes import summarize_outcomes


SESSION = SimpleNamespace(id=27, hdpc_path=None)


def test_effective_selection_marks_disabled_steps_skipped_without_hiding_a_failure():
    result = {"success": True, "effective_steps": [
        {"id": "fast_renderer", "enabled": True}, {"id": "any_to_usdz", "enabled": False},
    ], "details": [{"record_id": 1, "step_results": {"fast_renderer": {"success": True}}}]}
    config = {"steps": [{"id": "fast_renderer"}, {"id": "any_to_usdz"}]}

    outcome = summarize_outcomes(result, SESSION, config=config)
    assert outcome["summary"]["completed"] == 1
    assert outcome["summary"]["needs_attention"] == 0
    assert outcome["records"][0]["steps"][1]["status"] == "skipped"

    result["details"][0]["step_results"]["any_to_usdz"] = {"success": False, "status": "failed", "error": "Conversion failed"}
    outcome = summarize_outcomes(result, SESSION, config=config)
    assert outcome["summary"]["needs_attention"] == 1
    assert outcome["records"][0]["steps"][1]["issue"] == "Conversion failed"


def test_historical_success_uses_explicit_skipped_builtin_status_without_current_settings():
    result = {"success": True, "details": [{"record_id": 1,
        "render": {"success": True, "status": "completed"}, "usdz": {"success": False, "status": "skipped"},
        "step_results": {"fast_renderer": {"success": True}},
    }]}
    outcome = summarize_outcomes(result, SESSION, config={"steps": [{"id": "fast_renderer"}, {"id": "any_to_usdz"}]})
    assert outcome["summary"]["completed"] == 1
    assert outcome["records"][0]["steps"][1]["status"] == "skipped"


@pytest.mark.parametrize("step_id", ["custom_export", "lod_generation", "any_to_usdz"])
def test_missing_required_steps_remain_attention_with_an_effective_snapshot(step_id):
    result = {"success": True, "effective_steps": [{"id": step_id, "enabled": True}], "details": [{
        "record_id": 1, "usdz": {"status": "skipped"}, "edm": {"status": "skipped"}, "step_results": {},
    }]}
    outcome = summarize_outcomes(result, SESSION)
    assert outcome["summary"]["needs_attention"] == 1
    assert outcome["records"][0]["steps"][0]["status"] == "not_started"


def test_historical_missing_metadata_step_remains_attention():
    result = {"success": True, "details": [{"record_id": 1, "edm": {"status": "skipped"}, "step_results": {}}]}
    outcome = summarize_outcomes(result, SESSION, config={"steps": [{"id": "lod_generation"}]})
    assert outcome["summary"]["needs_attention"] == 1


def test_recorded_custom_failure_is_visible_even_if_missing_from_pinned_config():
    result = {"success": False, "details": [{"record_id": 1, "step_results": {
        "custom_export": {"status": "failed", "success": False, "error": "Invalid output"},
    }}]}
    outcome = summarize_outcomes(result, SESSION, config={"steps": [{"id": "any_to_usdz", "enabled": False}]})
    assert outcome["summary"]["needs_attention"] == 1
    assert outcome["records"][0]["steps"][1]["status"] == "failed"


def test_failed_record_does_not_infer_missing_enabled_converter_was_disabled():
    result = {"success": False, "details": [{"record_id": 1, "error": "Renderer failed",
        "usdz": {"status": "skipped"}, "step_results": {},
    }]}
    outcome = summarize_outcomes(result, SESSION, config={"steps": [{"id": "any_to_usdz"}]})
    assert outcome["summary"]["needs_attention"] == 1
    assert outcome["records"][0]["steps"][0]["status"] == "not_started"
