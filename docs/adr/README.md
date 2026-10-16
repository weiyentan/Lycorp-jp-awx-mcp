# Architecture Decision Records (ADRs)

This directory records durable architectural decisions for the AWX MCP fork.

**Start with [CONTEXT.md](../../CONTEXT.md)** for the current codebase, domain language, requirements and boundaries. ADRs explain significant decisions and trade-offs, not implementation steps.

## Decision register

| ADR | Decision | Status | Date |
| --- | --- | --- | --- |
| [0001](0001-configure-prompt-on-launch-through-existing-tools.md) | Configure Prompt on Launch through existing MCP tools with AWX API-driven validation | Accepted (design; not yet implemented) | 2026-10-16 |

## Conventions

1. Add one numbered Markdown file per architectural decision. Use `NNNN-short-description.md` and keep existing identifiers stable.
2. Use [template.md](template.md) for new decisions, adding: context, decision, alternatives, consequences, and references.
3. Distinguish **Proposed**, **Accepted**, **Superseded** and **Deprecated**. Acceptance of a design does not imply its code has shipped.
4. Reference relevant code paths and the root `CONTEXT.md`. Link superseding ADRs rather than rewriting a decision's historical reasoning.
5. Use Grill-with-Docs to understand and capture decisions. Specifications, issue breakdown and AFK execution belong to subsequent skills/workflows.
6. When implementing an ADR, keep its status and implementation evidence accurate; update `CONTEXT.md` to distinguish observed source behaviour from planned work.
