# ADR 0001 — Configure Prompt on Launch through existing MCP tools with AWX API-driven validation

- **Status:** Accepted (design decision; implementation not yet complete)
- **Decision date:** 2026-10-16
- **Scope:** AWX MCP job-template and workflow-template configuration
- **Context:** [Root engineering context](../../CONTEXT.md)
- **Supersedes:** None

## Context and problem

The AWX MCP server has tools to create and update job templates and workflow job templates. The current `awx_mcp/tools/job_templates.py` API exposes normal template defaults and the `launch_job` API can submit runtime overrides, but the creation/update tools do not expose the AWX Prompt on Launch configuration flags, such as `ask_variables_on_launch`.

The existing `awx_mcp/tools/workflow_templates.py` interface also offers general workflow configuration, including a separate `survey_enabled` setting, but not a comprehensive, explicit interface for the native Prompt on Launch flags supported by a given workflow-template resource.

As a result an AI client cannot reliably configure these flags using the existing MCP tool arguments. A runtime launch call accepting `extra_vars` does not itself grant permission for launch-time overrides; AWX controls that through its template configuration and API.

The intended users operate small AWX instances. The solution should be simple and avoid additional infrastructure, while keeping the existing caller credentials, AWX RBAC, read-only restrictions, API adapter and JSON tool response patterns.

The AWX API is the authority on the fields accepted by the connected controller. Job templates and workflow job templates must be treated as distinct resource types: not every field exposed by one is necessarily applicable to the other.

## Decision

**Extend the four existing MCP template creation/update tools with optional, typed, tri-state Prompt on Launch Boolean arguments, and use AWX API metadata to validate explicitly requested settings before writing.**

### 1. Configuration-only feature

- Extend `create_job_template` and `update_job_template` in `awx_mcp/tools/job_templates.py`.
- Extend `create_workflow_template` and `update_workflow_template` in `awx_mcp/tools/workflow_templates.py`.
- Do **not** introduce a separate Prompt on Launch MCP tool.
- Do **not** change `launch_job`, `launch_workflow`, surveys, credential-management flows, workflow nodes or child job templates as part of this feature.
- Launching a job must **never** implicitly enable or disable template flags.

### 2. Explicit configuration semantics

Each newly exposed toggle is optional:

| Input | Meaning |
| --- | --- |
| `True` | Explicitly enable this Prompt on Launch setting |
| `False` | Explicitly disable this Prompt on Launch setting |
| Omitted / `None` | Do not send this setting |

On create, AWX determines defaults for omitted flags. On update, omitted settings retain their existing value. Do not confuse an explicit `False` with absence.

The interfaces should cover all native Prompt on Launch toggles supported by the relevant AWX template resource, not just variable prompting. Examples include variable, inventory, credential, host limit, tag, skip-tag, SCM branch, verbosity, and diff-mode flags **where actually supported**. Tool signatures need explicit known fields; this design does not assume MCP schemas can dynamically add arguments at runtime. API support and write permission must still be checked per requested field.

### 3. Discover capabilities from the connected AWX instance

When and **only when** at least one new Prompt on Launch argument is explicitly supplied:

1. Issue an AWX `OPTIONS` request using the existing `AnsibleClient.request` path.
2. For creation, inspect the collection endpoint's create-action metadata (for example `/api/v2/job_templates/` or `/api/v2/workflow_job_templates/`).
3. For an update, inspect the detail endpoint's applicable update-action metadata (for example `/api/v2/job_templates/{id}/` or `/api/v2/workflow_job_templates/{id}/`). Read the AWX-provided action metadata carefully rather than assuming a fixed `OPTIONS.actions.PATCH` response shape across installations.
4. Require affirmative evidence that **every requested** Prompt on Launch field is accepted as a writable Boolean input for that resource and operation.
5. If metadata cannot be retrieved or interpreted unambiguously, or a field is not permitted, **reject the entire requested operation before any write** with a precise explanation.
6. Once validated, submit the normal single create/update API request through the existing client.

No separate compatibility table, field emulation, cache, database, or periodic discovery job is permitted. Do not infer support from an earlier call, a different resource type, or a different AWX version.

Regular calls with **no** new Prompt on Launch arguments bypass these additional checks and preserve the existing API-request path and return behaviour.

### 4. Verify the write without rollback

When a requested configuration write succeeds:

1. Determine the resulting template's ID (existing ID for update; response ID for create).
2. GET the same template resource through AWX.
3. Compare each requested Boolean against the persisted value; ignore unrelated fields.
4. On success, return AWX template data containing the persisted settings.
5. On mismatch, missing ID, failed GET or unverifiable persistence, return an explicit error/report identifying requested and observed values where available, and indicating that the original write **may already have taken effect**.

No automatic retries, compensating writes, rollbacks or additional template changes. In particular, “validation rejected before write” and “write accepted but verification failed” are **different states** that must be distinguishable to an autonomous client.

Do not promise all-or-nothing persistence from AWX merely because the MCP sent one API request; the post-write GET is authoritative for what can be observed.

### 5. Preserve security and existing contracts

- Continue using the same AWX authentication and user identity as the existing request. AWX permissions remain authoritative.
- Respect `AWX_MCP_READ_ONLY` and the existing per-request read-only gate.
- Surface AWX `401`/`403` and other expected errors using established exception/tool patterns; never elevate or switch credentials.
- Maintain the established JSON response shape for calls that do not use the new feature.
- Keep `survey_enabled` and the survey management endpoints separate from Prompt on Launch configuration.
- Do not propagate parent workflow template settings to workflow nodes.

### 6. Tests and documentation

Use mocked AWX API responses only. Tests should cover:

- Both template resource types; correct create/detail `OPTIONS` endpoint selection.
- Supported and unsupported metadata; unavailable, malformed and ambiguous metadata.
- `True`, `False`, omission/`None`, and mixed settings; no accidental reset of unspecified flags.
- Early fail-closed rejection with **zero writes**, successful single writes, GET verification success and mismatch, and read-back failure after an accepted write.
- AWX `401`/`403` propagation and existing read-only handling.
- Existing operations without new flags skipping `OPTIONS`, retaining their outputs and call patterns.
- Confirmation that launch calls, surveys, workflow nodes and unrelated data are unaffected.

There is **no** requirement for real AWX integration tests, creating temporary real templates, or running playbooks. Mock tests validate implementation logic, **not** compatibility with a particular live AWX controller.

Update the repository README/tool documentation with concrete examples and unsupported-setting/verification-failure explanations.

## Alternatives considered

| Alternative | Decision and rationale |
| --- | --- |
| Add a dedicated `configure_prompt_on_launch` tool | Rejected: duplicates existing create/update responsibilities and expands the MCP surface unnecessarily |
| Automatically enable prompting when launching | Rejected: job execution must not silently mutate persistent, potentially shared templates |
| Require an AWX survey to pass `extra_vars` | Rejected: surveys are a separate AWX feature and not a substitute for a native template toggle |
| Hardcode a supported-field list as final validation | Rejected: cannot reliably establish capabilities of the connected AWX instance |
| Cache `OPTIONS` metadata | Rejected: configuration is infrequent in small installations; freshness/simplicity are preferred |
| Apply supported fields and skip unsupported ones | Rejected: misleading partial success for autonomous callers |
| Roll back automatically after verification mismatches | Rejected: risks additional mutations and rollback failure |
| Require tests against live AWX | Rejected for this phase: mocked REST API tests are the agreed testing boundary |

## Consequences

### Benefits

- Existing MCP clients can configure native AWX Prompt on Launch settings through familiar create/update calls.
- Optional fields preserve old call sites and avoid accidental resets of unrelated template settings.
- Dynamic per-resource validation prevents unsupported settings from being silently ignored.
- Read-after-write checks make observed persistence explicit.
- No new service, dependency, storage, cache or launch-time behaviour change is required.

### Costs and limitations

- Explicit Prompt on Launch configuration performs an `OPTIONS`, a write, and a subsequent GET, so it costs extra REST calls. This is accepted for small-instance workloads.
- `OPTIONS` metadata may differ or be incomplete. The feature then fails closed rather than attempting compatibility workarounds.
- The static MCP tool signature still needs explicit field definitions; discovering additional fields in the runtime API does **not** automatically add new callable MCP arguments.
- Once AWX accepts a write, a read-back failure cannot guarantee rollback or unchanged state.
- Mock-only tests cannot prove behaviour against every real AWX version.
- Workflow templates may support only a subset of job-template flags; this is expected and must be communicated as a resource-specific limitation.

## Out of scope

This ADR does not prescribe specification structure, implementation issue count, dependency graph, PR count, AFK labels, deployment timing, GHCR publishing, Kubernetes changes, or changes to AWX instances. Those belong to subsequent skills and delivery processes.

## References

- [CONTEXT.md](../../CONTEXT.md)
- [Job-template MCP tools](../../awx_mcp/tools/job_templates.py)
- [Workflow-template MCP tools](../../awx_mcp/tools/workflow_templates.py)
- [AWX REST API client](../../awx_mcp/client.py)
- [MCP server permission/error handling](../../awx_mcp/server.py)
- [AWX 24.6.1 user guide — Job Templates](https://docs.ansible.com/projects/awx/en/24.6.1/userguide/job_templates.html)
