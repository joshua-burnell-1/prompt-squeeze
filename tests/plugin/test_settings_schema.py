# ABOUTME: Validates the settings JSON Schema is well-formed and accepts/rejects expected payloads.
# ABOUTME: Contract for settings.schema.json.

import json
from pathlib import Path

import jsonschema
import pytest

REPO = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO / "settings.schema.json"


@pytest.fixture()
def schema():
    return json.loads(SCHEMA_PATH.read_text())


def test_schema_is_valid_draft_2020_12(schema):
    jsonschema.Draft202012Validator.check_schema(schema)


def test_schema_accepts_defaults(schema):
    valid = {
        "prompt-squeeze.mode": "advise",
        "prompt-squeeze.warn_threshold": 800,
        "prompt-squeeze.notify_threshold": 0.25,
        "prompt-squeeze.hard_limit": 4000,
        "prompt-squeeze.interactive": False,
        "prompt-squeeze.telemetry": "local",
    }
    jsonschema.Draft202012Validator(schema).validate(valid)


def test_schema_rejects_invalid_mode(schema):
    invalid = {"prompt-squeeze.mode": "panic"}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)


def test_schema_rejects_negative_threshold(schema):
    invalid = {"prompt-squeeze.warn_threshold": -1}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)


def test_schema_rejects_notify_above_one(schema):
    invalid = {"prompt-squeeze.notify_threshold": 1.5}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)


def test_schema_rejects_unknown_keys(schema):
    invalid = {"prompt-squeeze.unknown_key": True}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(invalid)


def test_schema_telemetry_enum(schema):
    for ok in ("local", "team", "off"):
        jsonschema.Draft202012Validator(schema).validate(
            {"prompt-squeeze.telemetry": ok}
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.Draft202012Validator(schema).validate(
            {"prompt-squeeze.telemetry": "cloud"}
        )
