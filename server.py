from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_caching import Cache
from googleapiclient.discovery import build
from yt_dlp import YoutubeDL
import logging
import requests
import redis
from dotenv import load_dotenv
import os
import json

app = Flask(__name__)
load_dotenv()

# Setup logging with more detailed formatting
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

CORS(app, resources={
    r"/*": {
        "origins": ["*"],
        "methods": ["GET", "POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    }
})

app.config['CACHE_TYPE'] = 'RedisCache'
app.config['CACHE_REDIS_URL'] = os.getenv('CACHE_REDIS_URL')
app.config['CACHE_REDIS_SSL'] = True
cache = Cache(app)

YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)

@app.route('/stream', methods=['POST'])
def stream_audio():
    data = request.get_json()
    video_id = data.get('videoId')

    if not video_id:
        return jsonify({'error': 'Video ID is required'}), 400

    # Check cache with validation
    cached_audio_url = cache.get(f"audio_url:{video_id}")
    if cached_audio_url:
        try:
            # Use GET instead of HEAD to properly validate the URL
            response = requests.get(cached_audio_url, stream=True, timeout=5)
            response.close()  # Close the connection immediately after validation
            
            if response.status_code == 200:
                logger.info(f'Valid cached URL found for video ID: {video_id}')
                return jsonify({'audioUrl': cached_audio_url})
            else:
                logger.warning(f'Cached URL invalid for video ID {video_id}, status: {response.status_code}')
                cache.delete(f"audio_url:{video_id}")
        except Exception as e:
            logger.warning(f'Error validating cached URL: {str(e)}')
            cache.delete(f"audio_url:{video_id}")

    # Parse cookies from environment variable
    try:
        cookie_data = os.getenv('YOUTUBE_COOKIES', '')
        cookies = {}
        if cookie_data:
            for cookie in cookie_data.split(';'):
                cookie = cookie.strip()
                if '=' in cookie:
                    key, value = cookie.split('=', 1)
                    cookies[key.strip()] = value.strip()
    except Exception as e:
        logger.error(f'Cookie parsing error: {str(e)}')
        cookies = {}

    try:
        video_url = f'https://www.youtube.com/watch?v={video_id}'
        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',  # Prefer m4a format
            'cookies': cookies,
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
        }

        with YoutubeDL(ydl_opts) as ydl:
            try:
                info_dict = ydl.extract_info(video_url, download=False)
                
                # Ensure we have a valid audio URL
                if 'url' not in info_dict:
                    raise Exception('No audio URL found in extracted info')
                
                audio_url = info_dict['url']
                
                # Validate the extracted URL
                validation_response = requests.get(audio_url, stream=True, timeout=5)
                validation_response.close()
                
                if validation_response.status_code != 200:
                    raise Exception(f'Invalid audio URL (Status: {validation_response.status_code})')
                
                # Cache the valid URL
                cache.set(f"audio_url:{video_id}", audio_url, timeout=60 * 60)  # Cache for 1 hour
                logger.info(f'Successfully cached new audio URL for video ID: {video_id}')
                
                return jsonify({
                    'audioUrl': audio_url,
                    'format': info_dict.get('format', 'unknown'),
                    'ext': info_dict.get('ext', 'unknown')
                })
                
            except Exception as e:
                logger.error(f'Error extracting video info: {str(e)}')
                error_message = str(e)
                if 'confirm you\'re not a bot' in error_message:
                    return jsonify({
                        'error': 'YouTube authentication required. Please update cookies.'
                    }), 403
                elif 'Private video' in error_message:
                    return jsonify({'error': 'This video is private'}), 403
                elif 'Copyright' in error_message:
                    return jsonify({'error': 'This video is not available due to copyright restrictions'}), 403
                else:
                    return jsonify({'error': f'Failed to extract video info: {error_message}'}), 500

    except Exception as e:
        logger.error(f'Unexpected error: {str(e)}')
        return jsonify({'error': 'An unexpected error occurred'}), 500



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
    app.run(host='0.0.0.0', port=port, debug=True)
