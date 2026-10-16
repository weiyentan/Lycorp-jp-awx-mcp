# SPDX-License-Identifier: Apache-2.0

import json
import re
from typing import Any

# --- Secret masking -----------------------------------------------------------
# Shared by the usage instrumentation and the API client so that bearer tokens /
# token=... / password=... never reach a log sink, the usage JSONL, an exception
# message propagated to the MCP client, or the diagnostic log.
_SECRET_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"Bearer\s+\S+", re.IGNORECASE), "Bearer ***"),
    (re.compile(r"(token[\"']?\s*[:=]\s*)\S+", re.IGNORECASE), r"\1***"),
    (re.compile(r"(password[\"']?\s*[:=]\s*)\S+", re.IGNORECASE), r"\1***"),
]


def mask_secrets(text: str) -> str:
    """Redact bearer tokens, token=... and password=... occurrences from text."""
    if not text:
        return text
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def validate_json_str(value: str, param_name: str) -> str | None:
    """Validate a JSON string parameter.

    Returns MCP error response if invalid, None if valid.
    """
    try:
        json.loads(value)
        return None
    except json.JSONDecodeError:
        return json.dumps(
            {"status": "error", "message": f"Invalid JSON in {param_name}"}
        )


def parse_json_str(value: str, param_name: str) -> tuple:
    """Parse a JSON string.

    Returns (parsed_data, None) on success, (None, error_response) on failure.
    """
    try:
        return json.loads(value), None
    except json.JSONDecodeError:
        return None, json.dumps(
            {"status": "error", "message": f"Invalid JSON in {param_name}"}
        )


def interpret_prompt_on_launch_metadata(
    metadata: Any,
    action: str,
    fields: list[str],
) -> str | None:
    """Check AWX OPTIONS metadata confirms every field is writable.

    ``action`` is the HTTP action the caller will use (``POST`` on a collection
    endpoint, ``PATCH`` on a detail endpoint). Installations that publish only
    a ``PUT`` action mapping for an update are accepted, because AWX/DRF treats
    both actions as accepting the same writable field set.

    Returns ``None`` when every requested field is affirmatively writable,
    otherwise a human-readable reason. Missing, malformed or ambiguous metadata
    is a failure so callers can reject before writing.
    """
    if not isinstance(metadata, dict):
        return "the OPTIONS response was not a JSON object"
    actions = metadata.get("actions")
    if not isinstance(actions, dict) or not actions:
        return "the OPTIONS response contains no action metadata"
    action_meta = actions.get(action)
    if action_meta is None and action == "PATCH":
        action_meta = actions.get("PUT")
    if not isinstance(action_meta, dict):
        return f"the OPTIONS response contains no writable '{action}' action metadata"
    for field in fields:
        spec = action_meta.get(field)
        if not isinstance(spec, dict):
            return f"field '{field}' is not present in the '{action}' action metadata"
        if spec.get("read_only"):
            return f"field '{field}' is marked read-only"
        if spec.get("type") != "boolean":
            return (
                f"field '{field}' is not confirmed as a writable Boolean field "
                f"(metadata type: {spec.get('type')!r})"
            )
    return None
