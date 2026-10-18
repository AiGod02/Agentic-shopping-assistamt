import asyncio
import httpx
from agent_server.config import settings

async def test():
    print('Configured WEAVIATE_URL:', settings.weaviate_url)
    raw_url = settings.weaviate_url
    if not raw_url.startswith('http://') and not raw_url.startswith('https://'):
        url = 'https://' + raw_url
    else:
        url = raw_url
    headers = {'Authorization': f'Bearer {settings.weaviate_api_key}'}
    print(f"Connecting to {url}/v1/meta ...")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f'{url}/v1/meta', headers=headers)
            print("Status Code:", r.status_code)
            print("Response:", r.text)
    except Exception as e:
        print("Connection Error:", type(e).__name__, str(e))

if __name__ == '__main__':
    asyncio.run(test())
