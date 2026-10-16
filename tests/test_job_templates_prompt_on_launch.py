# SPDX-License-Identifier: Apache-2.0

"""Tests for tri-state ``ask_variables_on_launch`` Prompt on Launch support.

Job-template create/update with an explicitly supplied flag performs an AWX
OPTIONS capability check, exactly one write, and a read-after-write GET
verification. Omitted flags keep the legacy single-write path. Metadata that is
missing, ambiguous or does not confirm the field is writable fails closed with
zero writes. Mocked AWX responses only - no live controller.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from awx_mcp.exceptions import AnsibleAuthError, AnsibleHTTPError
from awx_mcp.tools import job_templates as jt_mod
from tests.conftest import fake_client_factory

CREATE_ENDPOINT = "/api/v2/job_templates/"
CREATE_ARGS = dict(name="n", inventory_id=1, project_id=2, playbook="p.yml")


def _options(action=None, field_spec=None, actions=None):
    """Build AWX OPTIONS metadata for the requested action."""
    if actions is None:
        if field_spec is None:
            field_spec = {"type": "boolean", "required": False, "read_only": False}
        actions = {action: {"ask_variables_on_launch": field_spec}}
    return {"name": "Job Template", "actions": actions}


def _routed(responses):
    """Route mocked ``client.request`` calls by (method, endpoint)."""

    def _request(method, endpoint, params=None, data=None):
        key = (method, endpoint)
        assert key in responses, f"unexpected request: {key}"
        result = responses[key]
        if isinstance(result, Exception):
            raise result
        return result

    return _request


def _patch(fake_client):
    return patch.object(
        jt_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    )


def _calls(fake_client):
    return [c.args for c in fake_client.request.call_args_list]


def test_create_true_checks_options_single_write_and_verifies(fake_client):
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", CREATE_ENDPOINT): _options("POST"),
            ("POST", CREATE_ENDPOINT): {
                "id": 99,
                "name": "n",
                "ask_variables_on_launch": True,
            },
            ("GET", f"{CREATE_ENDPOINT}99/"): {
                "id": 99,
                "ask_variables_on_launch": True,
            },
        }
    )
    with _patch(fake_client):
        out = jt_mod.create_job_template(**CREATE_ARGS, ask_variables_on_launch=True)

    assert _calls(fake_client) == [
        ("OPTIONS", CREATE_ENDPOINT),
        ("POST", CREATE_ENDPOINT),
        ("GET", f"{CREATE_ENDPOINT}99/"),
    ]
    body = fake_client.request.call_args_list[1].kwargs["data"]
    assert body["ask_variables_on_launch"] is True
    assert json.loads(out) == {"id": 99, "ask_variables_on_launch": True}


def test_create_false_is_sent_explicitly(fake_client):
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", CREATE_ENDPOINT): _options("POST"),
            ("POST", CREATE_ENDPOINT): {"id": 1, "ask_variables_on_launch": False},
            ("GET", f"{CREATE_ENDPOINT}1/"): {
                "id": 1,
                "ask_variables_on_launch": False,
            },
        }
    )
    with _patch(fake_client):
        out = jt_mod.create_job_template(**CREATE_ARGS, ask_variables_on_launch=False)

    assert (
        fake_client.request.call_args_list[1].kwargs["data"]["ask_variables_on_launch"]
        is False
    )
    assert json.loads(out)["ask_variables_on_launch"] is False


def test_update_true_checks_detail_options_and_patches_with_other_fields(fake_client):
    detail = f"{CREATE_ENDPOINT}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, "name": "new", "ask_variables_on_launch": True},
        }
    )
    with _patch(fake_client):
        out = jt_mod.update_job_template(
            template_id=7, name="new", ask_variables_on_launch=True
        )

    assert _calls(fake_client) == [
        ("OPTIONS", detail),
        ("PATCH", detail),
        ("GET", detail),
    ]
    assert fake_client.request.call_args_list[1].kwargs["data"] == {
        "name": "new",
        "ask_variables_on_launch": True,
    }
    assert json.loads(out)["ask_variables_on_launch"] is True


def test_update_false_is_sent_explicitly(fake_client):
    detail = f"{CREATE_ENDPOINT}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, "ask_variables_on_launch": False},
        }
    )
    with _patch(fake_client):
        jt_mod.update_job_template(template_id=7, ask_variables_on_launch=False)

    assert fake_client.request.call_args_list[1].kwargs["data"] == {
        "ask_variables_on_launch": False
    }


def test_update_uses_put_metadata_when_patch_absent(fake_client):
    detail = f"{CREATE_ENDPOINT}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options(
                actions={"PUT": {"ask_variables_on_launch": {"type": "boolean"}}}
            ),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, "ask_variables_on_launch": True},
        }
    )
    with _patch(fake_client):
        out = jt_mod.update_job_template(template_id=7, ask_variables_on_launch=True)

    assert json.loads(out)["ask_variables_on_launch"] is True


def test_create_without_flag_keeps_legacy_single_write(fake_client):
    fake_client.request.return_value = {"id": 5, "name": "n"}
    with _patch(fake_client):
        out = jt_mod.create_job_template(**CREATE_ARGS)

    assert _calls(fake_client) == [("POST", CREATE_ENDPOINT)]
    assert json.loads(out) == {"id": 5, "name": "n"}


def test_update_without_flag_keeps_legacy_single_write(fake_client):
    fake_client.request.return_value = {"id": 7, "name": "x"}
    with _patch(fake_client):
        out = jt_mod.update_job_template(template_id=7, name="x")

    assert _calls(fake_client) == [("PATCH", f"{CREATE_ENDPOINT}7/")]
    assert json.loads(out) == {"id": 7, "name": "x"}


def test_unwritable_field_fails_closed_with_zero_writes(fake_client):
    fake_client.request.return_value = _options("POST", actions={"POST": {}})
    with _patch(fake_client):
        out = jt_mod.create_job_template(**CREATE_ARGS, ask_variables_on_launch=True)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert "ask_variables_on_launch" in data["message"]
    assert _calls(fake_client) == [("OPTIONS", CREATE_ENDPOINT)]


def test_missing_actions_metadata_fails_closed(fake_client):
    fake_client.request.return_value = {"name": "Job Template"}
    with _patch(fake_client):
        out = jt_mod.update_job_template(template_id=7, ask_variables_on_launch=True)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert _calls(fake_client) == [("OPTIONS", f"{CREATE_ENDPOINT}7/")]


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "string"},
        {"type": "boolean", "read_only": True},
    ],
    ids=["non-boolean", "read-only"],
)
def test_non_writable_metadata_fails_closed(fake_client, spec):
    detail = f"{CREATE_ENDPOINT}7/"
    fake_client.request.return_value = _options("PATCH", field_spec=spec)
    with _patch(fake_client):
        out = jt_mod.update_job_template(template_id=7, ask_variables_on_launch=True)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert _calls(fake_client) == [("OPTIONS", detail)]


def test_verification_mismatch_reports_write_may_have_occurred(fake_client):
    detail = f"{CREATE_ENDPOINT}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, "ask_variables_on_launch": False},
        }
    )
    with _patch(fake_client):
        out = jt_mod.update_job_template(template_id=7, ask_variables_on_launch=True)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is True
    assert data["write_may_have_occurred"] is True
    assert data["verification"]["ask_variables_on_launch"] == {
        "expected": True,
        "actual": False,
    }
    assert "may already have taken effect" in data["message"]


def test_verification_read_back_failure_reports_write_may_have_occurred(fake_client):
    detail = f"{CREATE_ENDPOINT}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): AnsibleHTTPError(
                "Ansible API error: 502", status_code=502
            ),
        }
    )
    with _patch(fake_client):
        out = jt_mod.update_job_template(template_id=7, ask_variables_on_launch=True)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is True
    assert data["write_may_have_occurred"] is True
    assert "502" in json.dumps(data)


def test_create_missing_id_in_write_response_reports_write_may_have_occurred(
    fake_client,
):
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", CREATE_ENDPOINT): _options("POST"),
            ("POST", CREATE_ENDPOINT): {"name": "n"},
        }
    )
    with _patch(fake_client):
        out = jt_mod.create_job_template(**CREATE_ARGS, ask_variables_on_launch=True)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is True
    assert data["write_may_have_occurred"] is True


def test_options_auth_error_propagates_with_zero_writes(fake_client):
    fake_client.request.side_effect = _routed(
        {("OPTIONS", CREATE_ENDPOINT): AnsibleAuthError("Forbidden", status_code=403)}
    )
    with _patch(fake_client):
        with pytest.raises((AnsibleAuthError, ToolError), match="Forbidden"):
            jt_mod.create_job_template(**CREATE_ARGS, ask_variables_on_launch=True)

    assert _calls(fake_client) == [("OPTIONS", CREATE_ENDPOINT)]
