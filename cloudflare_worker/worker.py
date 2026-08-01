"""Cloudflare Python Worker entrypoint for the existing FastAPI application."""

import asgi
from workers import WorkerEntrypoint

from server.app.config import settings
from server.app.main import app


class Default(WorkerEntrypoint):
    async def fetch(self, request):
        settings.bind_worker_env(self.env)
        return await asgi.fetch(app, request, self.env)
