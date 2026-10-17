# SPDX-License-Identifier: Apache-2.0

"""AWX MCP Server - MCP server for Ansible Tower/AWX."""

import argparse
import os
import sys


def _resolve_serve_auth_mode(value: str | None, host: str) -> str:
    """Choose network auth without silently exposing a shared AWX credential.

    Normal --serve uses per-caller passthrough. Explicit static is reserved for
    a single-tenant, loopback-bound server (e.g. a trusted same-pod MCP tunnel).
    """
    mode = "passthrough" if value is None else value.strip().lower()
    if mode not in ("static", "passthrough"):
        raise ValueError(
            "AWX_MCP_AUTH_MODE must be 'static' or 'passthrough' for --serve."
        )
    if mode == "static" and host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(
            "Static --serve authentication requires a loopback bind "
            "(--host 127.0.0.1 or AWX_MCP_HOST=127.0.0.1); refusing "
            "to expose the shared AWX credential on the network."
        )
    return mode


def main():
    """Entry point for the awx-mcp command.

    Three mutually exclusive running modes, selected by CLI flags:

    * (no flags)         local stdio server using this process's own AWX
                         credentials (``ANSIBLE_TOKEN`` / USERNAME+PASSWORD).
    * ``--remote <URL>`` client proxy: no local server; relays stdio to a
                         central awx-mcp, injecting the caller's ``ANSIBLE_TOKEN``
                         as an ``Authorization: Bearer`` header.
    * ``--serve``        network server (streamable-http, or sse with ``--sse``).
                         Passthrough is the default (per-caller AWX token).
                         Explicit ``AWX_MCP_AUTH_MODE=static`` is supported
                         only when bound to loopback for a trusted tunnel.

    Heavy imports (``server``/``tools``/``proxy``) are deferred into the branch
    that needs them: proxy mode must not import ``server`` (which requires
    ``ANSIBLE_BASE_URL``, deliberately absent for proxy users).
    """
    parser = argparse.ArgumentParser(
        prog="awx-mcp",
        description="MCP server for Ansible Tower/AWX.",
    )
    parser.add_argument(
        "--remote",
        metavar="URL",
        default=None,
        help=(
            "Client proxy mode: connect to a central awx-mcp at URL instead of "
            "running a local server (env: AWX_MCP_REMOTE_URL)."
        ),
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help="Run the central multi-user server (streamable-http; --sse for sse).",
    )
    parser.add_argument(
        "--sse",
        action="store_true",
        help="With --serve, serve the sse transport instead of streamable-http.",
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Bind host for --serve (env: AWX_MCP_HOST, default 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Bind port for --serve (env: AWX_MCP_PORT, default 8000).",
    )
    args = parser.parse_args()

    remote_url = args.remote or os.environ.get("AWX_MCP_REMOTE_URL")

    # --- Mutual exclusivity -------------------------------------------------
    if args.remote and args.serve:
        parser.error("--remote and --serve are mutually exclusive.")
    if remote_url and (args.serve or args.host or args.port is not None or args.sse):
        parser.error(
            "--remote runs no server; it cannot be combined with "
            "--serve/--host/--port/--sse."
        )
    if args.sse and not args.serve:
        parser.error("--sse is only valid together with --serve.")

    # --- Proxy mode ---------------------------------------------------------
    if remote_url:
        # Import only the proxy; never touch server (no ANSIBLE_BASE_URL here).
        from .proxy import run_proxy

        run_proxy(remote_url)
        return

    # --- Server modes: set the internal channels BEFORE importing server ----
    if args.serve:
        effective_host = (
            args.host if args.host is not None
            else os.environ.get("AWX_MCP_HOST", "127.0.0.1")
        )
        try:
            mode = _resolve_serve_auth_mode(
                os.environ.get("AWX_MCP_AUTH_MODE"), effective_host
            )
        except ValueError as exc:
            parser.error(str(exc))
        os.environ["AWX_MCP_AUTH_MODE"] = mode
        transport = "sse" if args.sse else "streamable-http"
    else:
        # Guard: a stray AWX_MCP_AUTH_MODE env cannot turn on passthrough
        # without --serve. Modes are flag-decided.
        os.environ["AWX_MCP_AUTH_MODE"] = "static"
        transport = "stdio"
    os.environ["AWX_MCP_EFFECTIVE_TRANSPORT"] = transport

    from . import tools  # noqa: F401 — registers all tools on import
    from .access_log import AccessLogMiddleware
    from .server import (
        MCP_HOST,
        MCP_PORT,
        STATELESS_HTTP,
        logger,
        mcp,
        resolve_tls_kwargs,
        warn_if_exposed,
    )

    if transport == "stdio":
        logger.info("Starting awx-mcp (local stdio server)")
        mcp.run(transport="stdio")
        return

    # Central server (--serve). Resolve the effective bind address (CLI flag wins
    # over the env default), then optionally serve over TLS. resolve_tls_kwargs
    # validates the cert/key and raises on misconfiguration. mcp 2.x takes the
    # bind host per transport at the app factory instead of on the server object,
    # so the resolved values are threaded through explicitly.
    host = args.host if args.host is not None else MCP_HOST
    port = args.port if args.port is not None else MCP_PORT

    tls_kwargs = resolve_tls_kwargs(transport)
    warn_if_exposed(host, tls_enabled=bool(tls_kwargs))
    logger.info(
        "Starting awx-mcp --serve (transport=%s, %s) on %s:%s",
        transport,
        "https" if tls_kwargs else "http",
        host,
        port,
    )

    # Drive uvicorn directly (MCPServer.run() cannot pass TLS options or wrap the
    # app in middleware). log_config=None routes uvicorn's own loggers through
    # the root logging config (JSON in --serve, see server.py); access_log=False
    # drops uvicorn's plain-text access lines — the JSON access log
    # (AccessLogMiddleware) is the access record.
    import uvicorn

    app = (
        mcp.sse_app(host=host)
        if transport == "sse"
        else mcp.streamable_http_app(host=host, stateless_http=STATELESS_HTTP)
    )
    app = AccessLogMiddleware(app)
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_config=None,
        access_log=False,
        **(tls_kwargs or {}),
    )


if __name__ == "__main__":
    sys.exit(main())
