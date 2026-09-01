from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_only_frontend_defaults_to_lan_binding() -> None:
    compose = (PROJECT_ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert '"${WEBNOVEL_FRONTEND_HOST:-0.0.0.0}' in compose
    assert '"${WEBNOVEL_BACKEND_HOST:-127.0.0.1}' in compose
    assert '"${WEBNOVEL_POSTGRES_HOST:-127.0.0.1}' in compose
    assert '"${WEBNOVEL_REDIS_HOST:-127.0.0.1}' in compose
    assert '"${WEBNOVEL_STORAGE_HOST:-127.0.0.1}' in compose


def test_browser_code_has_no_loopback_backend_dependency() -> None:
    browser_files = [
        *sorted((PROJECT_ROOT / "frontend").glob("*.html")),
        *sorted((PROJECT_ROOT / "frontend").glob("*.js")),
    ]

    for path in browser_files:
        content = path.read_text(encoding="utf-8")
        assert "localhost" not in content, path.name
        assert "127.0.0.1" not in content, path.name
        assert ":8270" not in content, path.name


def test_nginx_proxies_same_origin_api_and_health() -> None:
    nginx = (PROJECT_ROOT / "frontend" / "nginx.conf").read_text(encoding="utf-8")

    assert "location /api/" in nginx
    assert "location = /api/health" in nginx
    assert "proxy_pass http://backend:8270" in nginx
    assert "proxy_set_header Host $http_host" in nginx
