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
import ffmpeg
import io

app = Flask(__name__)

load_dotenv()

# Setup logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Configure CORS to accept requests from any origin
CORS(app, resources={r"/*": {"origins": "*"}})

# Setup caching (Upstash Redis as cache backend)
app.config['CACHE_TYPE'] = 'RedisCache'
app.config['CACHE_REDIS_URL'] = os.getenv('CACHE_REDIS_URL')  # Load from .env
app.config['CACHE_REDIS_SSL'] = True
cache = Cache(app)

# YouTube API setup
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')  # Load from .env
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

# Check Redis connection
try:
    cache.get('test_key')  # Test Redis connection
except ConnectionError as e:
    logger.error(f'Redis connection error: {e}')
    exit(1)  # Exit if Redis is unavailable

@app.route('/')
def home():
    return "Welcome to deployed Flask server and it's running successfully!"

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
    except Exception as e:
        logger.error(f'Error fetching search results: {e}')
        return jsonify({'error': 'Failed to fetch search results'}), 500

    results = [
        {'videoId': item['id']['videoId'], 'title': item['snippet']['title']}
        for item in search_response.get('items', [])
    ]

    return jsonify(results)

@app.route('/stream', methods=['POST'])
def stream_audio():
    data = request.get_json()
    video_id = data.get('videoId')

    if not video_id:
        return jsonify({'error': 'Video ID is required'}), 400

    video_url = f'https://www.youtube.com/watch?v={video_id}'
    
    try:
        # Use yt-dlp to fetch video info and audio URL
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/70.0.3538.110 Safari/537.36'
            }
        }

        with YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(video_url, download=False)
            audio_url = info_dict['url']  # Get the URL for the audio stream
            
            # Fetch audio via requests
            audio_stream = requests.get(audio_url, stream=True)

            # Create a BytesIO buffer to store the converted audio
            output_stream = io.BytesIO()

            # Use ffmpeg to convert the audio stream directly to MP3 and store it in the output buffer
            ffmpeg.input('pipe:0').output(output_stream, format='mp3').run(input=audio_stream.raw)

            output_stream.seek(0)  # Rewind to the beginning of the stream
            
            # Return the converted audio stream with CORS headers
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Content-Type': 'audio/mp3',
            }

            return Response(output_stream, content_type='audio/mp3', headers=headers)
    except Exception as e:
        logger.error(f'Error in streaming or converting audio: {str(e)}')
        return jsonify({'error': 'Failed to stream or convert audio'}), 500


@app.route('/recently-played', methods=['POST'])
def add_recently_played():
    """Add a song to the recently played list."""
    data = request.get_json()
    video_id = data.get('videoId')
    title = data.get('title')

    if not video_id or not title:
        return jsonify({'error': 'Video ID and title are required'}), 400

    # Fetch existing recently played songs
    recently_played = cache.get('recently_played')
    recently_played = eval(recently_played) if recently_played else []

    # Add the new song to the list and limit to last 10 songs
    recently_played.append({'videoId': video_id, 'title': title})
    recently_played = recently_played[-10:]

    # Cache the updated list
    cache.set('recently_played', recently_played, timeout=60 * 60 * 24 * 2)  # Cache for 7 days
    return jsonify({'message': 'Song added to recently played'})

@app.route('/recently-played', methods=['GET'])
def get_recently_played():
    """Get the list of recently played songs."""
    recently_played = cache.get('recently_played')
    recently_played = eval(recently_played) if recently_played else []
    return jsonify(recently_played)

@app.route('/liked-songs', methods=['POST'])
def like_song():
    """Add a song to the liked songs list."""
    data = request.get_json()
    video_id = data.get('videoId')
    title = data.get('title')

    if not video_id or not title:
        return jsonify({'error': 'Video ID and title are required'}), 400

    # Fetch existing liked songs
    liked_songs = cache.get('liked_songs')
    liked_songs = eval(liked_songs) if liked_songs else []

    # Add the new song to the list if it's not already liked
    if {'videoId': video_id, 'title': title} not in liked_songs:
        liked_songs.append({'videoId': video_id, 'title': title})

    # Cache the updated list
    cache.set('liked_songs', liked_songs, timeout=60 * 60 * 24 * 120)  # Cache for 120 days
    return jsonify({'message': 'Song added to liked songs'})

@app.route('/liked-songs', methods=['GET'])
def get_liked_songs():
    """Get the list of liked songs."""
    liked_songs = cache.get('liked_songs')
    liked_songs = eval(liked_songs) if liked_songs else []
    return jsonify(liked_songs)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)

