"""Outbound URL policy rejects local addresses and unsafe redirect hops."""
import socket

import httpcore
import httpx
import pytest
import respx

from fmaj_agent.tools import impl


def test_only_http_schemes_and_standard_ports_are_allowed() -> None:
    assert not impl._safe_destination("file:///etc/passwd")[0]
    assert not impl._safe_destination("http://user:pass@example.com")[0]
    assert not impl._safe_destination("http://example.com:8080")[0]


def test_literal_loopback_private_and_link_local_are_rejected() -> None:
    for address in ("127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fc00::1"):
        assert not impl._safe_destination(f"http://{address}")[0]


def test_dns_rejects_a_host_with_any_non_public_answer(monkeypatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_a, **_kw: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443)),
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443)),
        ],
    )
    assert not impl._safe_destination("https://mixed.example")[0]


@respx.mock
def test_redirect_to_loopback_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_a, **_kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    monkeypatch.setattr(
        impl, "_send_pinned_request",
        lambda method, url, _addresses, timeout: getattr(httpx, method.lower())(
            url, headers={"User-Agent": impl.USER_AGENT}, timeout=timeout,
            follow_redirects=False,
        ),
    )
    respx.get("https://public.example/").mock(
        return_value=httpx.Response(302, headers={"Location": "http://127.0.0.1/admin"})
    )
    with pytest.raises(ValueError, match="private"):
        impl._request_public("https://public.example/")


def test_pinned_backend_connects_to_the_validated_address(monkeypatch) -> None:
    monkeypatch.setattr(httpcore.SyncBackend, "connect_tcp",
                        lambda _self, host, *_a, **_kw: host)
    backend = impl._PinnedBackend("public.example", ["8.8.8.8"])
    assert backend.connect_tcp("public.example", 443) == "8.8.8.8"
    with pytest.raises(ValueError, match="host changed"):
        backend.connect_tcp("other.example", 443)


def test_job_board_listing_bodies_are_blocked() -> None:
    assert impl._board_listing_url("https://www.linkedin.com/jobs/view/123")
    assert impl._board_listing_url("https://au.seek.com/job/123")
    assert not impl._board_listing_url("https://au.seek.com/Acme-jobs/at-this-company")
    assert not impl._board_listing_url("https://company.example/careers")


def test_robots_wildcards_block_disallowed_listing_paths() -> None:
    body = "User-agent: *\nDisallow: */job/"
    assert not impl._robots_can_fetch(body, "https://au.seek.com/company/job/123")
    assert impl._robots_can_fetch(body, "https://au.seek.com/company/careers")


def test_robots_fetch_failure_is_not_permission_to_crawl(monkeypatch) -> None:
    impl._robot_cache.clear()

    def unavailable(*_args, **_kwargs):
        raise TimeoutError("robots host timed out")

    monkeypatch.setattr(impl, "_request_public", unavailable)
    assert not impl._allowed("https://company.example/careers")
