# SPDX-License-Identifier: Apache-2.0

"""Tests for workflow-template tri-state ``ask_variables_on_launch`` support.

Workflow-template create/update with an explicitly supplied flag performs an
AWX OPTIONS capability check against the workflow resource endpoints, exactly
one write, and a read-after-write GET verification of the top-level workflow
template. Omitted flags keep the legacy single-write path. Metadata that is
missing, ambiguous or does not confirm the field is writable fails closed with
zero writes; job-template metadata is never substituted. Mocked AWX responses
only - no live controller.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from awx_mcp.exceptions import AnsibleAuthError, AnsibleHTTPError
from awx_mcp.tools import workflow_templates as wt_mod
from tests.conftest import fake_client_factory

COLLECTION = "/api/v2/workflow_job_templates/"
CREATE_ARGS = dict(name="wf", organization_id=1)
JOB_TEMPLATE_COLLECTION = "/api/v2/job_templates/"


def _options(action=None, field_spec=None, actions=None):
    """Build AWX workflow OPTIONS metadata for the requested action."""
    if actions is None:
        if field_spec is None:
            field_spec = {"type": "boolean", "required": False, "read_only": False}
        actions = {action: {"ask_variables_on_launch": field_spec}}
    return {"name": "Workflow Job Template", "actions": actions}


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
        wt_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    )


def _calls(fake_client):
    return [c.args for c in fake_client.request.call_args_list]


def test_create_true_checks_workflow_options_single_write_and_verifies(fake_client):
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", COLLECTION): _options("POST"),
            ("POST", COLLECTION): {
                "id": 99,
                "name": "wf",
                "ask_variables_on_launch": True,
            },
            ("GET", f"{COLLECTION}99/"): {
                "id": 99,
                "ask_variables_on_launch": True,
            },
        }
    )
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS, ask_variables_on_launch=True
        )

    assert _calls(fake_client) == [
        ("OPTIONS", COLLECTION),
        ("POST", COLLECTION),
        ("GET", f"{COLLECTION}99/"),
    ]
    body = fake_client.request.call_args_list[1].kwargs["data"]
    assert body["ask_variables_on_launch"] is True
    assert json.loads(out) == {"id": 99, "ask_variables_on_launch": True}


def test_create_sends_mixed_workflow_flags_in_one_validated_write(fake_client):
    requested = {
        "ask_variables_on_launch": True,
        "ask_inventory_on_launch": False,
        "ask_limit_on_launch": True,
        "ask_scm_branch_on_launch": False,
        "ask_labels_on_launch": True,
        "ask_skip_tags_on_launch": False,
        "ask_tags_on_launch": True,
    }
    options = {field: {"type": "boolean"} for field in requested}
    persisted = {"id": 99, **requested}
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", COLLECTION): {"actions": {"POST": options}},
            ("POST", COLLECTION): persisted,
            ("GET", f"{COLLECTION}99/"): persisted,
        }
    )
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(**CREATE_ARGS, **requested)

    assert _calls(fake_client) == [
        ("OPTIONS", COLLECTION),
        ("POST", COLLECTION),
        ("GET", f"{COLLECTION}99/"),
    ]
    body = fake_client.request.call_args_list[1].kwargs["data"]
    for field, value in requested.items():
        assert body[field] is value
    assert json.loads(out) == persisted


def test_create_false_is_sent_explicitly(fake_client):
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", COLLECTION): _options("POST"),
            ("POST", COLLECTION): {"id": 1, "ask_variables_on_launch": False},
            ("GET", f"{COLLECTION}1/"): {"id": 1, "ask_variables_on_launch": False},
        }
    )
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS, ask_variables_on_launch=False
        )

    body = fake_client.request.call_args_list[1].kwargs["data"]
    assert body["ask_variables_on_launch"] is False
    assert json.loads(out)["ask_variables_on_launch"] is False


def test_update_true_checks_detail_options_and_patches_with_other_fields(fake_client):
    detail = f"{COLLECTION}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {
                "id": 7,
                "name": "new",
                "ask_variables_on_launch": True,
            },
        }
    )
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
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
    detail = f"{COLLECTION}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, "ask_variables_on_launch": False},
        }
    )
    with _patch(fake_client):
        wt_mod.update_workflow_template(template_id=7, ask_variables_on_launch=False)

    assert fake_client.request.call_args_list[1].kwargs["data"] == {
        "ask_variables_on_launch": False
    }


def test_update_uses_put_metadata_when_patch_absent(fake_client):
    detail = f"{COLLECTION}7/"
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
        out = wt_mod.update_workflow_template(
            template_id=7, ask_variables_on_launch=True
        )

    assert json.loads(out)["ask_variables_on_launch"] is True


def test_create_without_flag_keeps_legacy_single_write(fake_client):
    fake_client.request.return_value = {"id": 5, "name": "wf"}
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(**CREATE_ARGS)

    assert _calls(fake_client) == [("POST", COLLECTION)]
    assert json.loads(out) == {"id": 5, "name": "wf"}


def test_update_without_flag_keeps_legacy_single_write(fake_client):
    detail = f"{COLLECTION}7/"
    fake_client.request.return_value = {"id": 7, "name": "x"}
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(template_id=7, name="x")

    assert _calls(fake_client) == [("PATCH", detail)]
    assert json.loads(out) == {"id": 7, "name": "x"}


def test_workflow_metadata_without_flag_fails_closed_never_uses_job_metadata(
    fake_client,
):
    # Workflow templates may support other ask_* flags but not variables; the
    # job-template metadata must not be consulted or substituted.
    fake_client.request.return_value = _options(
        actions={"POST": {"ask_inventory_on_launch": {"type": "boolean"}}}
    )
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS, ask_variables_on_launch=True
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert "ask_variables_on_launch" in data["message"]
    assert _calls(fake_client) == [("OPTIONS", COLLECTION)]
    assert all(
        endpoint != JOB_TEMPLATE_COLLECTION for _, endpoint in _calls(fake_client)
    )


def test_unwritable_field_fails_closed_with_zero_writes(fake_client):
    fake_client.request.return_value = _options("POST", actions={"POST": {}})
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS, ask_variables_on_launch=True
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert "ask_variables_on_launch" in data["message"]
    assert _calls(fake_client) == [("OPTIONS", COLLECTION)]


def test_missing_actions_metadata_fails_closed(fake_client):
    fake_client.request.return_value = {"name": "Workflow Job Template"}
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
            template_id=7, ask_variables_on_launch=True
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert _calls(fake_client) == [("OPTIONS", f"{COLLECTION}7/")]


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "string"},
        {"type": "boolean", "read_only": True},
    ],
    ids=["non-boolean", "read-only"],
)
def test_non_writable_metadata_fails_closed(fake_client, spec):
    detail = f"{COLLECTION}7/"
    fake_client.request.return_value = _options("PATCH", field_spec=spec)
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
            template_id=7, ask_variables_on_launch=True
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert _calls(fake_client) == [("OPTIONS", detail)]


def test_verification_mismatch_reports_write_may_have_occurred(fake_client):
    detail = f"{COLLECTION}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): _options("PATCH"),
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, "ask_variables_on_launch": False},
        }
    )
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
            template_id=7, ask_variables_on_launch=True
        )

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
    detail = f"{COLLECTION}7/"
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
        out = wt_mod.update_workflow_template(
            template_id=7, ask_variables_on_launch=True
        )

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
            ("OPTIONS", COLLECTION): _options("POST"),
            ("POST", COLLECTION): {"name": "wf"},
        }
    )
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS, ask_variables_on_launch=True
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is True
    assert data["write_may_have_occurred"] is True


def test_options_auth_error_propagates_with_zero_writes(fake_client):
    fake_client.request.side_effect = _routed(
        {("OPTIONS", COLLECTION): AnsibleAuthError("Forbidden", status_code=403)}
    )
    with _patch(fake_client):
        with pytest.raises((AnsibleAuthError, ToolError), match="Forbidden"):
            wt_mod.create_workflow_template(**CREATE_ARGS, ask_variables_on_launch=True)

    assert _calls(fake_client) == [("OPTIONS", COLLECTION)]


def test_update_sends_mixed_workflow_flags_and_leaves_omitted_unchanged(fake_client):
    detail = f"{COLLECTION}7/"
    requested = {
        "ask_inventory_on_launch": False,
        "ask_limit_on_launch": True,
        "ask_scm_branch_on_launch": False,
        "ask_labels_on_launch": True,
        "ask_skip_tags_on_launch": False,
        "ask_tags_on_launch": True,
    }
    options = {field: {"type": "boolean"} for field in requested}
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): {"actions": {"PATCH": options}},
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {"id": 7, **requested},
        }
    )
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(template_id=7, **requested)

    body = fake_client.request.call_args_list[1].kwargs["data"]
    assert body == requested
    assert "ask_variables_on_launch" not in body
    assert json.loads(out) == {"id": 7, **requested}


def test_create_rejects_whole_request_when_any_requested_flag_unsupported(fake_client):
    # ask_variables_on_launch is affirmatively writable, but the presence of a
    # single unconfirmed flag must reject the entire request before any write.
    fake_client.request.return_value = {
        "actions": {"POST": {"ask_variables_on_launch": {"type": "boolean"}}}
    }
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS,
            ask_variables_on_launch=True,
            ask_inventory_on_launch=True,
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert "ask_inventory_on_launch" in data["message"]
    assert _calls(fake_client) == [("OPTIONS", COLLECTION)]


def test_update_rejects_whole_request_when_any_flag_not_writable_boolean(fake_client):
    detail = f"{COLLECTION}7/"
    fake_client.request.return_value = {
        "actions": {
            "PATCH": {
                "ask_variables_on_launch": {"type": "boolean"},
                "ask_scm_branch_on_launch": {"type": "string"},
            }
        }
    }
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
            template_id=7,
            ask_variables_on_launch=True,
            ask_scm_branch_on_launch=True,
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert "ask_scm_branch_on_launch" in data["message"]
    assert _calls(fake_client) == [("OPTIONS", detail)]


def test_job_template_only_metadata_does_not_authorise_workflow_flags(fake_client):
    # Metadata listing job-template-only switches must not be treated as
    # workflow capabilities or substituted for the missing workflow flag.
    fake_client.request.return_value = {
        "actions": {
            "POST": {
                "ask_credential_on_launch": {"type": "boolean"},
                "ask_verbosity_on_launch": {"type": "boolean"},
                "ask_diff_mode_on_launch": {"type": "boolean"},
            }
        }
    }
    with _patch(fake_client):
        out = wt_mod.create_workflow_template(
            **CREATE_ARGS, ask_inventory_on_launch=True
        )

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is False
    assert "ask_inventory_on_launch" in data["message"]
    assert _calls(fake_client) == [("OPTIONS", COLLECTION)]


@pytest.mark.parametrize(
    "flag",
    [
        "ask_credential_on_launch",
        "ask_verbosity_on_launch",
        "ask_diff_mode_on_launch",
        "ask_job_type_on_launch",
        "ask_forks_on_launch",
    ],
)
def test_job_template_only_flags_are_not_workflow_arguments(flag):
    with pytest.raises(TypeError):
        wt_mod.create_workflow_template(**CREATE_ARGS, **{flag: True})
    with pytest.raises(TypeError):
        wt_mod.update_workflow_template(template_id=7, **{flag: True})


def test_update_verification_ignores_unrequested_workflow_flags(fake_client):
    detail = f"{COLLECTION}7/"
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): {
                "actions": {"PATCH": {"ask_inventory_on_launch": {"type": "boolean"}}}
            },
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {
                "id": 7,
                "ask_inventory_on_launch": True,
                "ask_limit_on_launch": False,
            },
        }
    )
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
            template_id=7, ask_inventory_on_launch=True
        )

    data = json.loads(out)
    assert data["ask_inventory_on_launch"] is True
    assert data["ask_limit_on_launch"] is False


def test_verification_reports_every_mismatched_requested_flag(fake_client):
    detail = f"{COLLECTION}7/"
    requested = {
        "ask_inventory_on_launch": True,
        "ask_limit_on_launch": False,
    }
    fake_client.request.side_effect = _routed(
        {
            ("OPTIONS", detail): {
                "actions": {
                    "PATCH": {field: {"type": "boolean"} for field in requested}
                }
            },
            ("PATCH", detail): {"id": 7},
            ("GET", detail): {
                "id": 7,
                "ask_inventory_on_launch": False,
                "ask_limit_on_launch": True,
            },
        }
    )
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(template_id=7, **requested)

    data = json.loads(out)
    assert data["status"] == "error"
    assert data["write_attempted"] is True
    assert data["write_may_have_occurred"] is True
    assert data["verification"]["ask_inventory_on_launch"] == {
        "expected": True,
        "actual": False,
    }
    assert data["verification"]["ask_limit_on_launch"] == {
        "expected": False,
        "actual": True,
    }


def test_legacy_update_with_defaults_and_no_flags_is_single_write(fake_client):
    detail = f"{COLLECTION}7/"
    fake_client.request.return_value = {"id": 7}
    with _patch(fake_client):
        out = wt_mod.update_workflow_template(
            template_id=7, inventory=3, limit="prod", scm_branch="main"
        )

    assert _calls(fake_client) == [("PATCH", detail)]
    assert fake_client.request.call_args.kwargs["data"] == {
        "inventory": 3,
        "limit": "prod",
        "scm_branch": "main",
    }
    assert json.loads(out) == {"id": 7}


def test_survey_and_node_helpers_are_untouched_by_prompt_configuration(fake_client):
    # Survey updates and launch_workflow remain single-call operations and must
    # not mutate top-level Prompt on Launch configuration implicitly.
    fake_client.request.side_effect = _routed(
        {
            ("POST", f"{COLLECTION}7/survey_spec/"): {"id": 1},
        }
    )
    with _patch(fake_client):
        wt_mod.set_workflow_template_survey(template_id=7, survey_spec='{"name": "s"}')

    assert _calls(fake_client) == [("POST", f"{COLLECTION}7/survey_spec/")]

    fake_client.request.reset_mock()
    fake_client.request.side_effect = _routed(
        {
            ("POST", f"{COLLECTION}7/launch/"): {"id": 42},
        }
    )
    with _patch(fake_client):
        out = wt_mod.launch_workflow(template_id=7, extra_vars='{"x": 1}')

    assert _calls(fake_client) == [("POST", f"{COLLECTION}7/launch/")]
    assert json.loads(out) == {"id": 42}
