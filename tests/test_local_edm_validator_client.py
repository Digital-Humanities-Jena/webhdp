from flask import Flask

from services.local_edm_validator_client import LocalEdmValidatorClient
from services.edm_service import EdmService


def test_local_edm_validator_request_uses_fast_report_contract(monkeypatch):
    app = Flask(__name__)
    app.config.update(
        LOCAL_EDM_VALIDATOR_URL="http://validator.local",
        LOCAL_EDM_VALIDATOR_CONTINUE_ON_ERROR=True,
        API_TIMEOUT=12,
    )

    captured = {}

    class FakeResponse:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {
                "validationResults": [
                    {
                        "step": "VALIDATE_EXTERNAL",
                        "status": "PASSED",
                        "messages": [{"messageType": "INFO", "message": "external ok"}],
                    },
                    {
                        "step": "VALIDATE_INTERNAL",
                        "status": "FAILED",
                        "messages": [{"messageType": "ERROR", "message": "missing edm:rights"}],
                    },
                    {
                        "step": "PROBLEM_PATTERNS",
                        "status": "PASSED",
                        "messages": [{"messageType": "WARN", "message": "short description"}],
                    },
                ],
                "problemPatternList": [
                    {
                        "problemPatternDescription": {
                            "problemPatternId": "P9",
                            "problemPatternTitle": "Very short description",
                        }
                    }
                ],
                "stepTimings": [
                    {"step": "VALIDATE_EXTERNAL", "durationMillis": 5},
                    {"step": "VALIDATE_INTERNAL", "durationMillis": 8},
                ],
                "totalDurationMillis": 21,
            }

    def fake_post(url, data=None, files=None, timeout=None):
        captured["url"] = url
        captured["data"] = data
        captured["files"] = files
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("requests.Session.post", lambda self, *args, **kwargs: fake_post(*args, **kwargs))

    with app.app_context():
        result = EdmService().validate_with_local_edm_validator(
            "<rdf:RDF/>",
            metadata={"country": "NL", "language": "en"},
        )

    assert captured["url"] == "http://validator.local/record/validation"
    assert captured["data"] == {
        "country": "Netherlands",
        "language": "English",
        "continueOnError": "true",
    }
    assert captured["files"]["recordToValidate"][2] == "application/xml"
    assert captured["timeout"] == 12

    assert result["valid"] is False
    assert result["validator"] == "local-edm-validator"
    assert result["total_duration_millis"] == 21
    assert result["validation_results"][0]["duration_millis"] == 5
    assert "[VALIDATE_INTERNAL] missing edm:rights" in result["errors"]
    assert "[PROBLEM_PATTERNS] short description" in result["warnings"]
    assert "[Problem Pattern] Very short description (P9)" in result["warnings"]
    assert "[VALIDATE_EXTERNAL] external ok" in result["infos"]


def test_local_edm_validator_health_reports_actuator_status(monkeypatch):
    app = Flask(__name__)
    app.config["LOCAL_EDM_VALIDATOR_URL"] = "http://validator.local"

    captured = {}

    class FakeResponse:
        status_code = 200
        text = '{"status":"UP"}'

        def json(self):
            return {"status": "UP"}

    def fake_get(url, timeout=None):
        captured["url"] = url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("requests.Session.get", lambda self, *args, **kwargs: fake_get(*args, **kwargs))

    with app.app_context():
        status = LocalEdmValidatorClient().check_health(timeout=1.5)

    assert captured == {
        "url": "http://validator.local/actuator/health",
        "timeout": 1.5,
    }
    assert status["ok"] is True
    assert status["status"] == "UP"


def test_local_edm_validator_info_summarizes_build_and_git_metadata(monkeypatch):
    app = Flask(__name__)
    app.config["LOCAL_EDM_VALIDATOR_URL"] = "http://validator.local"

    class FakeResponse:
        status_code = 200
        text = "{}"

        def json(self):
            return {
                "app": {
                    "title": "Local EDM Validator",
                    "version": "1.0.0-local",
                    "repository": "https://github.com/Digital-Humanities-Jena/local-edm-validator",
                    "source": {
                        "ref": "b1ba678",
                    },
                    "image-tag": "local-edm-validator:test",
                },
                "build": {
                    "version": "12-SNAPSHOT",
                    "time": "2026-04-30T13:12:00Z",
                },
                "git": {
                    "branch": "main",
                    "commit": {
                        "id": "b1ba67890123456789012345678901234567890",
                        "id.abbrev": "b1ba678",
                        "time": "2026-04-29T10:00:00Z",
                    },
                },
            }

    monkeypatch.setattr("requests.Session.get", lambda self, *args, **kwargs: FakeResponse())

    with app.app_context():
        info = LocalEdmValidatorClient().get_info(timeout=1.5)

    assert info["ok"] is True
    assert info["summary"] == {
        "title": "Local EDM Validator",
        "description": None,
        "version": "1.0.0-local",
        "repository": "https://github.com/Digital-Humanities-Jena/local-edm-validator",
        "source_ref": "b1ba678",
        "image_tag": "local-edm-validator:test",
        "build_time": "2026-04-30T13:12:00Z",
        "git_branch": "main",
        "git_commit": "b1ba67890123456789012345678901234567890",
        "git_commit_short": "b1ba678",
        "git_commit_time": "2026-04-29T10:00:00Z",
    }
