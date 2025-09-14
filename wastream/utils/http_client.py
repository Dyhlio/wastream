import httpx
from typing import Optional, Dict, Any
from wastream.core.config import PROXY_URL

# HTTP client singleton with proxy support
class HTTPClient:
    
    _instance: Optional['HTTPClient'] = None
    _client: Optional[httpx.AsyncClient] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    async def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            proxies = {"all://": PROXY_URL} if PROXY_URL else None
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(15.0),
                proxies=proxies,
                follow_redirects=True,
                limits=httpx.Limits(max_connections=None, max_keepalive_connections=None)
            )
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

http_client = HTTPClient()