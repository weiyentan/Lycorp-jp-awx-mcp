# AWX MCP — Engineering Context

> Status: Initial context baseline, reviewed 2026-10-16.
> Scope: This document describes the existing codebase and agreed behaviour. It is **not** a specification, issue breakdown, or evidence that planned functionality has shipped.
> Decision record: [ADR 0001](docs/adr/0001-configure-prompt-on-launch-through-existing-tools.md).

## Purpose and audience

This repository is a fork of [lycorp-jp/awx-mcp](https://github.com/lycorp-jp/awx-mcp). It provides an MCP interface to the AWX / Ansible Automation Platform controller REST API v2, allowing AI clients to inspect and manage AWX resources using the permissions of their AWX identity.

The intended deployment profile for our enhancements is **small AWX instances**. Prefer clear interfaces, bounded API calls, straightforward Python code, and existing facilities over caches, databases, new services, or generic compatibility frameworks.

Domain terminology:

- **MCP tool** — an operation exposed to an AI client by this Python MCP server.
- **AWX job template** — a reusable configuration for running a single playbook.
- **AWX workflow job template** — a multi-node execution definition; its top-level configuration is not identical to a job template's configuration.
- **Prompt on Launch** — AWX *template configuration flags* such as `ask_variables_on_launch` that permit selected launch-time inputs. These are **not** MCP interactive elicitation and are **not** an AWX survey.
- **Survey** — AWX's distinct mechanism for defining named launch-time questions; existing survey tools remain separate.
- **Launch operation** — a runtime request to start a job or workflow; it must never silently modify template settings.
- **Supported setting** — a field confirmed as writable for the relevant AWX resource/action by that instance's REST API metadata, not merely a field known to the Python tool schema.

## Current codebase — inspected baseline

The Python package is `awx_mcp` (entry point `awx-mcp` in `pyproject.toml`), with Python >=3.10 and the MCP Python SDK 2.x. The project README currently describes 145 tools across 20 domain modules (141 enabled by default, plus four opt-in credential/user-write tools).

| Area | Key files | Responsibility |
| --- | --- | --- |
| Entry point and transports | `awx_mcp/__init__.py`, `awx_mcp/proxy.py` | Local stdio, central `--serve` (Streamable HTTP/SSE), remote stdio proxy |
| MCP server and tool registration | `awx_mcp/server.py`, `awx_mcp/tools/__init__.py` | MCP server, read/write decorators, request-context headers, read-only gates, error surfacing, module imports |
| AWX API adapter | `awx_mcp/client.py`, `awx_mcp/exceptions.py`, `awx_mcp/utils.py` | `AnsibleClient.request(method, endpoint, params, data)`, authentication, retries, API errors, JSON validation, pagination |
| Job templates | `awx_mcp/tools/job_templates.py` | Create/update/read/delete templates, launch, copy, survey, credential association |
| Workflow templates | `awx_mcp/tools/workflow_templates.py` | Create/update/read/delete workflow templates, launch, survey, nodes and node links |
| Other AWX domains | `awx_mcp/tools/` | Inventories/sources, hosts, groups, projects, jobs, workflow jobs, RBAC, credentials, users, schedules, execution environments, system operations and related resources |
| Security and observability | `awx_mcp/server.py`, `awx_mcp/usage.py`, `awx_mcp/access_log.py`, `awx_mcp/tls_config.py`, `SECURITY.md` | Per-caller auth, read-only restrictions, redact sensitive parameters, structured usage/access logs, TLS |
| Build, quality and tests | `pyproject.toml`, `uv.lock`, `Dockerfile`, `tests/`, `.github/workflows/ci.yml`, `.github/workflows/lint.yml` | Dependency locking, package/container build, pytest/mocks, Ruff and Python-version CI |

The repository's separate container publishing work is tracked independently of Prompt on Launch; do not treat a planned publishing workflow as part of this enhancement.

### Existing behaviour relevant to Prompt on Launch

- `create_job_template` and `update_job_template` currently expose general template configuration but **do not expose** `ask_*_on_launch` parameters.
- `launch_job` already submits selected runtime overrides, including `extra_vars`, to AWX. Its presence **does not** guarantee a template is configured to allow arbitrary overrides.
- `create_workflow_template` and `update_workflow_template` expose general workflow settings (including `survey_enabled`) but not a comprehensive, explicit Prompt on Launch interface.
- `launch_workflow` accepts runtime overrides. Workflow nodes and their own settings are distinct.
- The generic AWX client supports arbitrary HTTP methods via `request`; the agreed capability-discovery design should reuse this client for `OPTIONS`.
- Existing methods generally return JSON-encoded AWX responses and use decorators for permissions/error presentation. Extend these patterns rather than creating a parallel protocol.
- Existing pytest fixtures in `tests/conftest.py` provide a fake AWX client, and `tests/test_client.py` uses mocked HTTP behaviour. Use those patterns for the new functionality.

These are observations about the inspected source on `main`, **not** proof of runtime behaviour against a live controller.

## Agreed change: configure AWX Prompt on Launch

The Grill-with-Docs decisions from 2026-10-16 are binding context for subsequent specification work:

1. **Configuration only.** Add the ability to set Prompt on Launch flags. Do not add interactive prompting, implicit enablement, or execution-time template mutations.
2. **Extend existing tools.** Add optional Boolean parameters to `create_job_template`, `update_job_template`, `create_workflow_template`, and `update_workflow_template`. Do not introduce a dedicated Prompt on Launch MCP tool.
3. **All natively supported settings, per template type.** Cover the applicable AWX `ask_*_on_launch` flags, including variables, inventory, credentials, limits, tags, skip tags, SCM branch, verbosity, diff mode and any other flags actually supported by the target resource. A workflow template must **not** be assumed to support every job-template flag. Any required extension of the static MCP tool schema is considered during specification.
4. **Tri-state input semantics.** `true` enables; `false` disables; omitted/`None` does not submit that setting. Creation leaves omitted fields to AWX defaults; updates leave omitted fields unchanged. Preserve existing positional arguments and defaults.
5. **Capability checks for explicitly requested flags.** Before a configuration write containing new Prompt on Launch parameters, query the appropriate AWX `OPTIONS` metadata for the create/update endpoint and confirm that each requested field is writable for that operation.
6. **Fail closed.** If requested fields are unsupported, the metadata is missing/ambiguous, or `OPTIONS` fails, reject **before** writing. Do not filter out unsupported fields, apply a partial requested configuration intentionally, or guess based on a different AWX version.
7. **No capability cache.** Query `OPTIONS` on each explicit Prompt on Launch configuration operation. Small-instance operation favours simplicity and fresh metadata.
8. **No extra discovery on legacy operations.** Calls that omit all new Prompt on Launch fields follow the existing code path and response behaviour without mandatory `OPTIONS`.
9. **Read-after-write verification.** After successful create/update with explicitly requested settings, re-fetch the resulting template, compare each supplied Boolean against the persisted value, and report discrepancies.
10. **Verification errors are not transaction rollbacks.** A write may have succeeded even if verification fails. Report expected/actual fields and the potentially applied state; do not automatically retry, revert or modify further.
11. **Preserve successful response compatibility.** Unmodified calls retain their existing response shape; successful Prompt on Launch operations return the AWX template data, including persisted flag values. Added error information applies to the new validation/verification failure cases.
12. **Keep runtime launching unchanged.** `launch_job` and `launch_workflow` must not enable flags, create surveys, or reconfigure templates. AWX continues to enforce whether submitted launch inputs are allowed.
13. **Preserve AWX security boundaries.** Keep the caller's existing AWX identity and RBAC, the MCP read-only gate, existing credential opt-in protections and explicit 401/403 errors. No credential switching or privilege escalation.
14. **Workflow isolation.** Change only top-level job/workflow template configuration. Do not rewrite workflow nodes, child job templates, links or inherited behaviour.
15. **No compatibility workarounds.** Use capabilities of the connected AWX instance as returned by its API. Do not emulate missing settings for older releases.
16. **Mocked testing only.** Use pytest and mocked AWX API responses (including `OPTIONS`, write and GET); do not require live-controller integration testing or create temporary real resources.
17. **Documentation is required.** Document how to set and unset configuration flags, examples for each template type, the difference from surveys, and failure behaviour.

See [ADR 0001](docs/adr/0001-configure-prompt-on-launch-through-existing-tools.md) for rationale, alternatives, and consequences.

## Expected interaction and invariants

Example **conceptual** call (not yet available in the deployed MCP):

```python
update_job_template(
    template_id=238,
    ask_variables_on_launch=True,
    ask_inventory_on_launch=False,
)
```

The MCP validates only the explicitly supplied flags, issues one AWX configuration write if validation passes, reads the saved template back, and reports the result. A non-Prompt-on-Launch update such as `update_job_template(template_id=238, description="new description")` continues to use its existing path.

An explicit `False` must never be mistaken for omission. Unsupported or unverifiable settings must not produce a success result. A validation rejection means **no write attempted**; a verification mismatch means **a write may already have occurred**.

Do not conflate:
- `extra_vars` stored as defaults on a template, launch-time `extra_vars` supplied to a run, and `ask_variables_on_launch` authorisation;
- `survey_enabled` and Prompt on Launch toggles;
- a workflow template's own configuration and the settings on its nodes/child job templates;
- MCP elicitation used by certain opt-in credential tools and AWX Prompt on Launch.

## Quality, test and documentation constraints

Mock responses should cover both template resource types; supported/unsupported/ambiguous `OPTIONS` metadata; `True`, `False`, omitted and mixed-field requests; no-write fail-closed behaviour; GET verification match/mismatch; API authentication/permission errors; unchanged legacy calls; read-only mode; and preservation of unrelated template/workflow fields. Do not claim real-controller validation from these tests.

Documentation should be consistent with the actual implemented signatures and only enumerate flags confirmed by code and API metadata. Existing lint, tests and container build checks should remain intact.

## Decisions, boundaries and handoff

- The decisions above arose from **Grill-with-Docs**, used to understand the domain and capture requirements.
- This baseline is input to the repository's later specification and issue-management skills; it must not pre-decide the count, dependencies or scope of implementation issues/PRs.
- Detailed parameter signatures, shared helper shapes, error envelope schemas and implementation slicing belong to subsequent specification work.
- Any new architectural decision should be recorded under [docs/adr](docs/adr/README.md), with accepted decisions distinguishable from implemented behaviour.
- Review/update this context as code changes; do not silently turn prospective design into a statement about deployed capability.
