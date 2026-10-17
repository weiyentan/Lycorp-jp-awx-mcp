# SPDX-License-Identifier: Apache-2.0

"""Regression tests for loopback-only static authentication in --serve mode."""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from awx_mcp import _resolve_serve_auth_mode, main
from awx_mcp.client import get_ansible_client
from awx_mcp.exceptions import AnsibleAuthError


@pytest.mark.parametrize("value", [None, "passthrough", " PASSTHROUGH "])
def test_shared_server_defaults_to_passthrough(value):
    assert _resolve_serve_auth_mode(value, "0.0.0.0") == "passthrough"


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_explicit_static_only_accepted_on_loopback(host):
    assert _resolve_serve_auth_mode("static", host) == "static"


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.10", "mcp.internal"])
def test_static_denies_network_listener_even_with_env_flag(host):
    with pytest.raises(ValueError, match="loopback bind"):
        _resolve_serve_auth_mode("static", host)


def test_invalid_serve_mode_fails_closed():
    with pytest.raises(ValueError, match="must be"):
        _resolve_serve_auth_mode("fallback", "127.0.0.1")


def test_serve_static_writes_mode_before_server_start(monkeypatch):
    from awx_mcp import server

    monkeypatch.setenv("AWX_MCP_AUTH_MODE", "static")
    # main() mutates this global channel; register its original value for cleanup.
    monkeypatch.setenv("AWX_MCP_EFFECTIVE_TRANSPORT", "stdio")
    monkeypatch.setattr(sys, "argv", ["awx-mcp", "--serve", "--host", "127.0.0.1"])
    monkeypatch.setattr(server.mcp, "streamable_http_app", lambda **_: MagicMock())
    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)

    main()

    assert os.environ["AWX_MCP_AUTH_MODE"] == "static"
    assert run.call_args.kwargs["host"] == "127.0.0.1"


def test_serve_without_explicit_mode_stays_passthrough(monkeypatch):
    from awx_mcp import server

    # Track the original values even though main() writes directly to os.environ.
    monkeypatch.setenv("AWX_MCP_AUTH_MODE", "static")
    monkeypatch.delenv("AWX_MCP_AUTH_MODE")
    monkeypatch.setenv("AWX_MCP_EFFECTIVE_TRANSPORT", "stdio")
    monkeypatch.setattr(sys, "argv", ["awx-mcp", "--serve", "--host", "0.0.0.0"])
    monkeypatch.setattr(server.mcp, "streamable_http_app", lambda **_: MagicMock())
    run = MagicMock()
    monkeypatch.setattr("uvicorn.run", run)

    main()

    assert os.environ["AWX_MCP_AUTH_MODE"] == "passthrough"
    assert run.call_args.kwargs["host"] == "0.0.0.0"


def test_serve_static_non_loopback_fails_before_start(monkeypatch, capsys):
    monkeypatch.setenv("AWX_MCP_AUTH_MODE", "static")
    monkeypatch.setattr(sys, "argv", ["awx-mcp", "--serve", "--host", "0.0.0.0"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2
    assert "refusing to expose" in capsys.readouterr().err


def test_static_client_uses_server_token_without_caller_header():
    with (
        patch("awx_mcp.client.AUTH_MODE", "static"),
        patch("awx_mcp.client.ANSIBLE_TOKEN", "static-test-token"),
        patch("awx_mcp.client.get_request_token", return_value=None),
        patch("awx_mcp.client._get_shared_session"),
        patch("awx_mcp.client.AnsibleClient") as client_cls,
    ):
        with get_ansible_client():
            pass
        assert client_cls.call_args.kwargs["token"] == "static-test-token"


def test_passthrough_requires_caller_token_even_if_server_has_one():
    with (
        patch("awx_mcp.client.AUTH_MODE", "passthrough"),
        patch("awx_mcp.client.ANSIBLE_TOKEN", "static-test-token"),
        patch("awx_mcp.client.get_request_token", return_value=None),
    ):
        with pytest.raises(AnsibleAuthError, match="An AWX token is required"):
            with get_ansible_client():
                pass
