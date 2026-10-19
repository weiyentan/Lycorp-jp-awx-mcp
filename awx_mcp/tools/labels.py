# SPDX-License-Identifier: Apache-2.0

"""
Ansible MCP Server - Label Tools
"""

import json
from typing import Any

from ..client import get_ansible_client, handle_pagination
from ..server import read_tool, write_tool


@read_tool
def list_labels(
    label_name: str = None,
    limit: int = 20,
    offset: int = 0,
) -> str:
    """List AWX labels.

    Use this to discover reusable tags applied across AWX resources for
    grouping and filtering. Returns label IDs and organization linkage for
    follow-up resource association workflows.

    Label name searches are performed server-side using AWX's case-insensitive
    partial-name filter. Prefer this over paging through the whole collection
    when resolving a name to an ID.

    Returns a JSON envelope {count, returned, offset, results}. count is the
    server-side total; if offset + returned < count, call again with
    offset=offset+returned to page through.

    Args:
        label_name: Optional full or partial label name, matched
            case-insensitively.
        limit: Maximum number of label results to return
        offset: Number of label results to skip
    """
    with get_ansible_client() as client:
        params: dict[str, Any] = {"limit": limit, "offset": offset}

        if label_name and label_name.strip():
            params["name__icontains"] = label_name.strip()

        labels = handle_pagination(client, "/api/v2/labels/", params, with_meta=True)
        return json.dumps(labels, indent=2)


@write_tool()
def create_label(name: str, organization_id: int) -> str:
    """Create an AWX label in an organization.

    Use this to define a tag that can be attached to resources such as job
    templates and inventories for organization-level categorization. Returns
    the created label object, including id and organization.

    Args:
        name: Label name (for example, "production" or "pci")
        organization_id: Owning organization ID (from list_organizations)
    """
    with get_ansible_client() as client:
        data = {"name": name, "organization": organization_id}
        response = client.request("POST", "/api/v2/labels/", data=data)
        return json.dumps(response, indent=2)


# =============================================================================
# Job Template Label Associations
# =============================================================================


@read_tool
def list_template_labels(
    template_id: int, limit: int = 20, offset: int = 0
) -> str:
    """List labels attached to an AWX job template.

    Unlike list_labels (the organization-wide label catalog), this returns
    only labels on the specified job template. Use returned label IDs when
    removing an association.

    Returns a JSON envelope {count, returned, offset, results}. If more
    results exist, call again with offset=offset+returned.

    Args:
        template_id: Job template ID (from list_job_templates)
        limit: Maximum number of labels to return
        offset: Number of labels to skip
    """
    with get_ansible_client() as client:
        labels = handle_pagination(
            client,
            f"/api/v2/job_templates/{template_id}/labels/",
            {"limit": limit, "offset": offset},
            with_meta=True,
        )
        return json.dumps(labels, indent=2)


@write_tool(idempotent=True)
def associate_label_with_template(template_id: int, label_id: int) -> str:
    """Attach an existing AWX label to a job template.

    Resolve a label ID with list_labels first, or create it with create_label.
    This assigns a resource label, not an Ansible job_tags execution filter.

    Args:
        template_id: ID of the job template
        label_id: ID of an existing label (from list_labels or create_label)
    """
    with get_ansible_client() as client:
        response = client.request(
            "POST",
            f"/api/v2/job_templates/{template_id}/labels/",
            data={"id": label_id},
        )
        return json.dumps(response, indent=2)


@write_tool(destructive=True)
def disassociate_label_from_template(template_id: int, label_id: int) -> str:
    """Remove a label association from an AWX job template.

    Does not delete the job template. AWX may garbage-collect a label when
    its final resource association is removed, so inspect existing uses
    before removing the final association.

    Args:
        template_id: ID of the job template
        label_id: ID of a label attached to it (from list_template_labels)
    """
    with get_ansible_client() as client:
        client.request(
            "POST",
            f"/api/v2/job_templates/{template_id}/labels/",
            data={"id": label_id, "disassociate": True},
        )
        return json.dumps(
            {
                "status": "success",
                "message": (
                    f"Label {label_id} disassociated from job template {template_id}"
                ),
            },
            indent=2,
        )
