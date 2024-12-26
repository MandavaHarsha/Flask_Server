from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
from flask_caching import Cache
from googleapiclient.discovery import build
from yt_dlp import YoutubeDL
import logging
import requests
import redis
from dotenv import load_dotenv
from urllib.parse import quote
import os
import tempfile
import json

app = Flask(__name__)

load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configure CORS to accept requests from any origin
CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

# Setup Redis caching (Upstash Redis or local Redis)
redis_url = os.getenv('CACHE_REDIS_URL')
if not redis_url:
    raise ValueError("CACHE_REDIS_URL environment variable is required")

app.config['CACHE_TYPE'] = 'RedisCache'
app.config['CACHE_REDIS_URL'] = redis_url
app.config['CACHE_REDIS_SSL'] = True
cache = Cache(app)

# Test Redis connection
try:
    cache.get('test_key')
except redis.exceptions.AuthenticationError as e:
    logger.error(f"Redis authentication error: {e}")
    exit(1)
except Exception as e:
    logger.error(f"Error connecting to Redis: {e}")
    exit(1)

# YouTube API setup
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
if not YOUTUBE_API_KEY:
    raise ValueError("YOUTUBE_API_KEY environment variable is required")

youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

@app.route('/')
def home():
    return "Flask server is running successfully!"

@app.route('/search', methods=['GET'])
def search_videos():
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Query parameter "q" is required'}), 400

    try:
        search_response = youtube.search().list(
            q=query,
            part='id,snippet',
            maxResults=5,
            type='video'
        ).execute()
        
        results = [
            {'videoId': item['id']['videoId'], 'title': item['snippet']['title']}
            for item in search_response.get('items', [])
        ]
        return jsonify(results)
    except Exception as e:
        logger.error(f"Error fetching search results: {e}")
        return jsonify({'error': 'Failed to fetch search results'}), 500

@app.route('/proxy-stream', methods=['GET'])
def proxy_stream():
    url = request.args.get('url')
    if not url:
        return jsonify({'error': 'URL parameter is required'}), 400

    try:
        response = requests.get(url, stream=True, timeout=10)

        headers = {
            'Content-Type': response.headers.get('Content-Type', 'audio/webm'),
            'Content-Length': response.headers.get('Content-Length', ''),
            'Accept-Ranges': 'bytes',
            'Access-Control-Allow-Origin': '*',
            'Connection': 'keep-alive'
        }

        return Response(stream_with_context(response.iter_content(chunk_size=8192)), headers=headers, status=response.status_code)

    except Exception as e:
        logger.error(f"Proxy streaming error: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/stream', methods=['POST'])
def stream_audio():
    data = request.get_json()
    video_id = data.get('videoId')

    if not video_id:
        return jsonify({'error': 'Video ID is required'}), 400

    cached_audio_url = cache.get(f"audio_url:{video_id}")
    if cached_audio_url:
        return jsonify({'audioUrl': cached_audio_url})

    try:
        cookie_data = os.getenv('YOUTUBE_COOKIES')
        if not cookie_data:
            logger.error("YOUTUBE_COOKIES environment variable not set")
            return jsonify({'error': 'Cookie configuration missing'}), 500

        with tempfile.NamedTemporaryFile(mode='w+', delete=True) as temp_cookie_file:
            temp_cookie_file.write(cookie_data)
            temp_cookie_file.flush()

            video_url = f"https://www.youtube.com/watch?v={video_id}"
            ydl_opts = {
                'format': 'bestaudio/best',
                'cookiefile': temp_cookie_file.name,
                'quiet': True,
                'no_warnings': True,
                'nocheckcertificate': True
            }

            with YoutubeDL(ydl_opts) as ydl:
                info_dict = ydl.extract_info(video_url, download=False)
                audio_url = info_dict['url']
                cache.set(f"audio_url:{video_id}", audio_url, timeout=3600)
                return jsonify({'audioUrl': audio_url})

    except Exception as e:
        logger.error(f"Error in stream endpoint: {str(e)}")
        return jsonify({'error': 'Failed to process video request'}), 500

@app.route('/recently-played', methods=['GET', 'POST'])
def recently_played():
    if request.method == 'POST':
        data = request.get_json()
        video_id = data.get('videoId')
        title = data.get('title')

        if not video_id or not title:
            return jsonify({'error': 'Video ID and title are required'}), 400

        recently_played = json.loads(cache.get('recently_played') or '[]')
        recently_played.append({'videoId': video_id, 'title': title})
        recently_played = recently_played[-10:]
        cache.set('recently_played', json.dumps(recently_played), timeout=604800)
        return jsonify({'message': 'Song added to recently played'})

    recently_played = json.loads(cache.get('recently_played') or '[]')
    return jsonify(recently_played)

@app.route('/liked-songs', methods=['GET', 'POST'])
def liked_songs():
    if request.method == 'POST':
        data = request.get_json()
        video_id = data.get('videoId')
        title = data.get('title')

        if not video_id or not title:
            return jsonify({'error': 'Video ID and title are required'}), 400

        liked_songs = json.loads(cache.get('liked_songs') or '[]')
        if {'videoId': video_id, 'title': title} not in liked_songs:
            liked_songs.append({'videoId': video_id, 'title': title})
        cache.set('liked_songs', json.dumps(liked_songs), timeout=10368000)
        return jsonify({'message': 'Song added to liked songs'})

    liked_songs = json.loads(cache.get('liked_songs') or '[]')
    return jsonify(liked_songs)

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
