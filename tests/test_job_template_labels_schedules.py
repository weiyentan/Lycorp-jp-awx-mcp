# SPDX-License-Identifier: Apache-2.0

"""Mocked AWX API tests for job-template labels and schedule activation."""

import json
from unittest.mock import patch

import pytest

from awx_mcp.tools import labels as labels_mod
from awx_mcp.tools import schedules as schedules_mod
from tests.conftest import fake_client_factory


def _paged(rows):
    return {"count": len(rows), "next": None, "previous": None, "results": rows}


def test_list_template_labels_scoped_and_paginated(fake_client):
    fake_client.request.return_value = _paged([{"id": 17, "name": "maintenance"}])
    with patch.object(
        labels_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        result = json.loads(labels_mod.list_template_labels(44, limit=5, offset=10))

    fake_client.request.assert_called_once_with(
        "GET",
        "/api/v2/job_templates/44/labels/",
        params={"page_size": 5, "page": 3},
    )
    assert result == {
        "count": 1,
        "returned": 1,
        "offset": 10,
        "results": [{"id": 17, "name": "maintenance"}],
    }


def test_associate_label_with_template_uses_related_endpoint(fake_client):
    with patch.object(
        labels_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        result = json.loads(labels_mod.associate_label_with_template(44, 17))

    fake_client.request.assert_called_once_with(
        "POST", "/api/v2/job_templates/44/labels/", data={"id": 17}
    )
    assert result == {"id": 99, "name": "ok"}


def test_disassociate_label_does_not_delete_resource(fake_client):
    with patch.object(
        labels_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        result = json.loads(labels_mod.disassociate_label_from_template(44, 17))

    fake_client.request.assert_called_once_with(
        "POST",
        "/api/v2/job_templates/44/labels/",
        data={"id": 17, "disassociate": True},
    )
    assert result["status"] == "success"


@pytest.mark.parametrize("enabled", [True, False])
def test_create_schedule_explicit_enabled_state(fake_client, enabled):
    with patch.object(
        schedules_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        schedules_mod.create_schedule(
            name="cleanup",
            unified_job_template_id=44,
            rrule="DTSTART:20261024T090000Z RRULE:FREQ=WEEKLY",
            extra_data='{"dry_run": true}',
            enabled=enabled,
        )

    method, endpoint = fake_client.request.call_args.args
    body = fake_client.request.call_args.kwargs["data"]
    assert (method, endpoint) == ("POST", "/api/v2/schedules/")
    assert body["unified_job_template"] == 44
    assert body["extra_data"] == {"dry_run": True}
    assert body["enabled"] is enabled


def test_create_schedule_omitted_enabled_uses_awx_default(fake_client):
    with patch.object(
        schedules_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        schedules_mod.create_schedule(
            name="cleanup",
            unified_job_template_id=44,
            rrule="DTSTART:20261024T090000Z RRULE:FREQ=WEEKLY",
        )
    assert "enabled" not in fake_client.request.call_args.kwargs["data"]


@pytest.mark.parametrize("enabled", [True, False])
def test_update_schedule_resumes_or_pauses(fake_client, enabled):
    with patch.object(
        schedules_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        schedules_mod.update_schedule(schedule_id=33, enabled=enabled)

    fake_client.request.assert_called_once_with(
        "PATCH", "/api/v2/schedules/33/", data={"enabled": enabled}
    )


def test_update_schedule_does_not_touch_enabled_when_omitted(fake_client):
    with patch.object(
        schedules_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        schedules_mod.update_schedule(schedule_id=33, description="weekly cleanup")

    fake_client.request.assert_called_once_with(
        "PATCH", "/api/v2/schedules/33/", data={"description": "weekly cleanup"}
    )


def test_schedule_lookup_filter_remains_available(fake_client):
    fake_client.request.return_value = _paged([{"id": 33}])
    with patch.object(
        schedules_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        result = json.loads(schedules_mod.list_schedules(unified_job_template_id=44))

    assert fake_client.request.call_args.args == ("GET", "/api/v2/schedules/")
    assert fake_client.request.call_args.kwargs["params"]["unified_job_template"] == 44
    assert result["results"] == [{"id": 33}]


@pytest.mark.parametrize("operation", ["create", "update"])
def test_invalid_schedule_extra_data_does_not_write(fake_client, operation):
    with patch.object(
        schedules_mod, "get_ansible_client", new=fake_client_factory(fake_client)
    ):
        if operation == "create":
            output = schedules_mod.create_schedule(
                name="cleanup",
                unified_job_template_id=44,
                rrule="DTSTART:20261024T090000Z RRULE:FREQ=WEEKLY",
                extra_data="not-json{",
                enabled=False,
            )
        else:
            output = schedules_mod.update_schedule(
                schedule_id=33, extra_data="not-json{", enabled=False
            )

    assert json.loads(output)["status"] == "error"
    fake_client.request.assert_not_called()
