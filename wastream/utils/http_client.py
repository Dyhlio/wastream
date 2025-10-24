from typing import Optional, Dict, Any

import httpx

from wastream.core.config import settings

# ===========================
# HTTP Client Singleton
# ===========================
class HTTPClient:

    _instance: Optional['HTTPClient'] = None
    _client: Optional[httpx.AsyncClient] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            client_args = {
                "timeout": httpx.Timeout(float(settings.HTTP_TIMEOUT)),
                "follow_redirects": True,
                "limits": httpx.Limits(max_connections=None, max_keepalive_connections=None)
            }
            if settings.PROXY_URL:
                client_args["proxy"] = settings.PROXY_URL
            self._client = httpx.AsyncClient(**client_args)
        return self._client

    async def get(self, url: str, **kwargs) -> httpx.Response:
        client = await self.get_client()
        return await client.get(url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        client = await self.get_client()
        return await client.post(url, **kwargs)

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

# ===========================
# Global HTTP Client Instance
# ===========================
http_client = HTTPClient()