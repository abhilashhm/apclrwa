"""Python Worker entrypoint: FastAPI API first, Vite assets as the fallback."""

from fastapi import Request
from fastapi.responses import Response
from workers import asgi

from app import app


@app.get("/{path:path}")
async def frontend(path: str, request: Request) -> Response:
    env = request.scope.get("env")
    assets = getattr(env, "ASSETS", None) if env is not None else None
    if assets is None and isinstance(env, dict):
        assets = env.get("ASSETS")
    if assets is None:
        return Response(content="Static asset binding is not configured.", status_code=503, media_type="text/plain")
    asset_url = f"https://assets.local/{path}"
    response = await assets.fetch(asset_url)
    body = await response.bytes()
    return Response(content=body, status_code=response.status, headers=dict(response.headers))


Default = asgi.entrypoint(app)
