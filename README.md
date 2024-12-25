Flask Backend for Music App

This repository contains the Flask server that powers the backend of the Premier Music App. The server provides API endpoints to handle various functionalities such as searching YouTube videos, streaming audio, managing recently played tracks, and handling liked songs. The backend is hosted on Render for global accessibility.

Features

YouTube Integration: Search for videos and stream their audio using the YouTube Data API and yt_dlp.

Caching: Integrated with Redis (Upstash) to cache audio URLs, recently played tracks, and liked songs for improved performance.

API Endpoints:

/search - Search for YouTube videos.

/stream - Stream audio for a given video ID.

/recently-played - Manage and fetch recently played tracks.

/liked-songs - Manage and fetch liked songs.

CORS Support: Configured to accept requests from any origin, enabling cross-origin API access.

Prerequisites

Python 3.7 or higher.

Redis (configured with Upstash).

Flask and required dependencies (see Requirements).

Render account for hosting.