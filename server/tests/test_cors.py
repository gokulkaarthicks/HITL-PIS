import httpx
import pytest
from app.config import settings
from app.main import app


@pytest.mark.asyncio
async def test_cors_reads_current_runtime_settings() -> None:
    previous = settings.cors_allow_origins
    settings.cors_allow_origins = "https://reviewer.pages.dev"
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.options(
                "/health",
                headers={
                    "Origin": "https://reviewer.pages.dev",
                    "Access-Control-Request-Method": "GET",
                },
            )
    finally:
        settings.cors_allow_origins = previous

    assert response.status_code == 204
    assert response.headers["access-control-allow-origin"] == (
        "https://reviewer.pages.dev"
    )


@pytest.mark.asyncio
async def test_cors_rejects_an_unconfigured_origin() -> None:
    previous = settings.cors_allow_origins
    settings.cors_allow_origins = "https://reviewer.pages.dev"
    transport = httpx.ASGITransport(app=app)

    try:
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test"
        ) as client:
            response = await client.options(
                "/health",
                headers={
                    "Origin": "https://other.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
    finally:
        settings.cors_allow_origins = previous

    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
