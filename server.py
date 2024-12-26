from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import yt_dlp
import redis
import json
import os
from googleapiclient.discovery import build
from functools import lru_cache

app = FastAPI()

origins = [
    "http://localhost:3000",
    "*"  # During development. Remove in production
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    max_age=3600,
)

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
REDIS_URL = os.getenv('CACHE_REDIS_URL')

redis_client = redis.from_url(REDIS_URL, decode_responses=True)
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

class VideoRequest(BaseModel):
    videoId: str

@app.options("/{path:path}")
async def options_route(path: str):
    return JSONResponse(
        content="OK",
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        }
    )

@lru_cache(maxsize=100)
def get_stream_url(video_id: str) -> str:
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            return info.get('url', '')
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))

@app.get("/search")
async def search_videos(q: str):
    cache_key = f"search:{q}"
    cached_result = redis_client.get(cache_key)
    
    if cached_result:
        return JSONResponse(content=json.loads(cached_result))
    
    try:
        search_response = youtube.search().list(
            q=q,
            part='snippet',
            maxResults=10,
            type='video'
        ).execute()
        
        results = []
        for item in search_response.get('items', []):
            video_data = {
                'videoId': item['id']['videoId'],
                'title': item['snippet']['title'],
                'thumbnail': item['snippet']['thumbnails']['default']['url']
            }
            results.append(video_data)
        
        redis_client.setex(cache_key, 3600, json.dumps(results))
        return JSONResponse(content=results)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/stream")
async def get_stream(video: VideoRequest):
    try:
        stream_url = get_stream_url(video.videoId)
        return JSONResponse(
            content={"audioUrl": stream_url},
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
                "Access-Control-Allow-Headers": "*",
            }
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
