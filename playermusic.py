from flask import Flask, request, jsonify, send_from_directory, render_template_string
from flask_cors import CORS
import yt_dlp
import os
import uuid
import requests
import librosa
import numpy as np
import sqlite3
from pydub import AudioSegment
from g4f.client import Client
import lyricsgenius

app = Flask(__name__)
CORS(app)

LASTFM_API_KEY = "09ee8b5d3fb10929d2909a29aa1a18b8"
DOWNLOAD_FOLDER = 'downloads'
if not os.path.exists(DOWNLOAD_FOLDER):
    os.makedirs(DOWNLOAD_FOLDER)

GENIUS_API_TOKEN = "nEcfhIt8pJUhkoPtGccbflVWQLcPVp8Q8nGdFhqoOPl6UWUcQJI-wiOzkBCp81-m"
genius = lyricsgenius.Genius(GENIUS_API_TOKEN, skip_non_songs=True, excluded_terms=["(Remix)", "(Live)"])

db_path = "music.db"
conn = sqlite3.connect(db_path, check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_uuid TEXT UNIQUE,
    title TEXT,
    artist TEXT,
    thumbnail TEXT,
    file_url TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS favorites (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    track_id INTEGER,
    FOREIGN KEY(track_id) REFERENCES tracks(id)
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS playlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS playlist_tracks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    playlist_id INTEGER,
    track_id INTEGER,
    FOREIGN KEY(playlist_id) REFERENCES playlists(id),
    FOREIGN KEY(track_id) REFERENCES tracks(id)
)
""")

conn.commit()

def get_or_create_track(track_uuid, title, artist, thumbnail, file_url):
    cursor.execute("SELECT id, track_uuid, title, artist, thumbnail, file_url FROM tracks WHERE track_uuid = ?", (track_uuid,))
    row = cursor.fetchone()
    if row:
        return {
            'id': row[0],
            'track_uuid': row[1],
            'title': row[2],
            'artist': row[3],
            'thumbnail': row[4],
            'file_url': row[5],
        }
    else:
        cursor.execute(
            "INSERT INTO tracks (track_uuid, title, artist, thumbnail, file_url) VALUES (?, ?, ?, ?, ?)",
            (track_uuid, title, artist, thumbnail, file_url)
        )
        conn.commit()
        new_id = cursor.lastrowid
        return {
            'id': new_id,
            'track_uuid': track_uuid,
            'title': title,
            'artist': artist,
            'thumbnail': thumbnail,
            'file_url': file_url,
        }

def add_favorite(track_id):
    cursor.execute("SELECT 1 FROM favorites WHERE track_id = ?", (track_id,))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO favorites (track_id) VALUES (?)", (track_id,))
        conn.commit()

def get_all_favorites():
    cursor.execute("""
        SELECT tracks.id, tracks.track_uuid, tracks.title, tracks.artist, tracks.thumbnail, tracks.file_url
        FROM favorites
        JOIN tracks ON favorites.track_id = tracks.id
    """)
    rows = cursor.fetchall()
    favorites = []
    for row in rows:
        favorites.append({
            'id': row[0],
            'track_uuid': row[1],
            'title': row[2],
            'artist': row[3],
            'thumbnail': row[4],
            'file_url': row[5]
        })
    return favorites

def create_playlist(name):
    cursor.execute("SELECT id FROM playlists WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    else:
        cursor.execute("INSERT INTO playlists (name) VALUES (?)", (name,))
        conn.commit()
        return cursor.lastrowid

def get_all_playlists():
    cursor.execute("SELECT id, name FROM playlists")
    rows = cursor.fetchall()
    playlists_list = []
    for row in rows:
        p_id = row[0]
        p_name = row[1]
        cursor.execute("""
            SELECT tracks.id, tracks.track_uuid, tracks.title, tracks.artist, tracks.thumbnail, tracks.file_url
            FROM playlist_tracks
            JOIN tracks ON playlist_tracks.track_id = tracks.id
            WHERE playlist_tracks.playlist_id = ?
        """, (p_id,))
        tracks_rows = cursor.fetchall()
        track_list = []
        for trow in tracks_rows:
            track_list.append({
                'id': trow[0],
                'track_uuid': trow[1],
                'title': trow[2],
                'artist': trow[3],
                'thumbnail': trow[4],
                'file_url': trow[5]
            })
        playlists_list.append({
            'id': p_id,
            'name': p_name,
            'tracks': track_list
        })
    return playlists_list

def add_track_to_playlist(playlist_id, track_id):
    cursor.execute("SELECT 1 FROM playlist_tracks WHERE playlist_id = ? AND track_id = ?", (playlist_id, track_id))
    row = cursor.fetchone()
    if not row:
        cursor.execute("INSERT INTO playlist_tracks (playlist_id, track_id) VALUES (?, ?)", (playlist_id, track_id))
        conn.commit()

def get_top_tracks():
    url = f"http://ws.audioscrobbler.com/2.0/?method=chart.gettoptracks&api_key={LASTFM_API_KEY}&format=json&limit=10"
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception("Errore nel recupero dei top tracks da Last.fm")
    data = response.json()
    top_tracks = data['tracks']['track']
    return [{
        'name': track['name'],
        'artist': track['artist']['name'],
        'thumbnail': track['image'][-1]['#text'] if track['image'] else '/static/default_cover.png',
        'url': track['url']
    } for track in top_tracks]

def get_music_recommendations(artist_name):
    if not artist_name:
        return []
    try:
        url = f"http://ws.audioscrobbler.com/2.0/?method=artist.getsimilar&artist={artist_name}&api_key={LASTFM_API_KEY}&format=json"
        response = requests.get(url)
        data = response.json()
        similar_artists = data['similarartists']['artist'][:5]
        return [artist['name'] for artist in similar_artists]
    except:
        return []

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="it">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Bubble Music Player</title>
  <link href="https://fonts.googleapis.com/css2?family=Sour+Gummy:ital,wght@0,100..900;1,100..900&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=DynaPuff:wght@400..700&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@100..900&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Itim&display=swap" rel="stylesheet">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Varela+Round&display=swap" rel="stylesheet">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Tsukimi+Rounded&display=swap" rel="stylesheet">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Montserrat+Alternates:ital,wght@0,100;0,200;0,300;0,400;0,500;0,600;0,700;0,800;0,900;1,100;1,200;1,300;1,400;1,500;1,600;1,700;1,800;1,900&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Playwrite+AU+SA:wght@100..400&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Fredoka+One&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Pacifico&display=swap" rel="stylesheet">
  <link href="https://fonts.googleapis.com/css2?family=Quicksand:wght@400;500;600&family=Poppins:wght@400;500;600&family=Fredoka+One&display=swap" rel="stylesheet">
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/animate.css/4.1.1/animate.min.css">
  <link rel="manifest" href="/manifest.json">
  <meta name="theme-color" content="#A18CD1">
  <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
  <script src="https://cdn.jsdelivr.net/npm/canvas-confetti@1.5.1/dist/confetti.browser.min.js"></script>
  <style>
    * {
      margin: 0;
      padding: 0;
      box-sizing: border-box;
      -webkit-tap-highlight-color: transparent;
    }
    :root {
      --pastel-pink: #FFD6E0;
      --pastel-purple: #E5D4F1;
      --pastel-blue: #D4E5F1;
      --pastel-green: #D4F1E5;
      --pastel-yellow: #F1EED4;
      /* Nuove variabili pastello */
      --pastel-lavender: #E6E6FA;
      --pastel-peach: #FFE5B4;
      --pastel-mint: #C5FAD5;
      --pastel-sky: #CDF0FF;
      --pastel-lemon:  #FFF9C4; /* Giallino delicato */
      --pastel-rose:   #FFDDE4; /* Rosa soffice */
      --pastel-lime:   #D7FCD4; /* Verde lime leggero */
      --pastel-red:    #FFC6C7; /* Rosso-pesca molto tenue */
      --pastel-peach:  #FFE5CC; /* Arancione chiaro pastellato */
      --pastel-water:  #CDF0FF; /* Azzurro “acquoso” e tenue */

      --primary-color: #A18CD1;
      --pastel-mycolor: #F6E5F5;
      --secondary-color: #FBC2EB;
      --background-color: #F8F9FE;
      --text-color: #6C7293;
      --card-background: #FFFFFF;
      --accent-color: #A18CD1;
      --bubble-shadow: 0 8px 32px 0 rgba(31, 38, 135, 0.15);
      --soft-shadow: 0 4px 20px rgba(161, 140, 209, 0.15);
      --glass-background: rgba(255, 255, 255, 0.85);
      --glass-border: 1px solid rgba(255, 255, 255, 0.18);
      --glass-radius: 24px;
      --transition-speed: 0.3s;
      --font-family-primary: 'Quicksand', sans-serif;
      --font-family-secondary: 'Poppins', sans-serif;
      --font-family-cute: 'Fredoka One', cursive;
      --ai-spinner-color: #a18cd1;
      --ai-overlay-bg: rgba(0, 0, 0, 0.6);
    }
    [data-theme="dark"] {
      --background-color: #2F3346;
      --text-color: #B4BBDA;
      --card-background: #3A3F58;
      --glass-background: rgba(58, 63, 88, 0.85);
      --ai-spinner-color: #eee;
      --ai-overlay-bg: rgba(0, 0, 0, 0.8);
    }
    [data-theme="christmas"] {
      --background-color: #FAF8F0;
      --text-color: #B23A48;
      --card-background: #FFFFFF;
      --glass-background: rgba(255, 255, 255, 0.95);
      --ai-spinner-color: #b23a48;
      --ai-overlay-bg: rgba(255, 0, 0, 0.3);
    }
    [data-theme="newyear"] {
      --background-color: #1E1E1E;
      --text-color: #FFD700;
      --card-background: #2C2C2C;
      --glass-background: rgba(44, 44, 44, 0.85);
      --accent-color: #FF4500;
      --ai-spinner-color: #FFD700;
      --ai-overlay-bg: rgba(0, 0, 0, 0.8);
    }
    /* Nuovi Temi */
    [data-theme="spring"] {
      --background-color: #FFF5F3;
      --text-color: #4B3832;
      --card-background: #FFF9F3;
      --glass-background: rgba(255, 249, 243, 0.85);
      --accent-color: #FFB6B9;
      --ai-spinner-color: #FFD1DC;
      --ai-overlay-bg: rgba(255, 182, 193, 0.6);
    }
    [data-theme="ocean"] {
      --background-color: #E0F7FA;
      --text-color: #01579B;
      --card-background: #FFFFFF;
      --glass-background: rgba(224, 247, 250, 0.85);
      --accent-color: #80DEEA;
      --ai-spinner-color: #4DD0E1;
      --ai-overlay-bg: rgba(0, 150, 136, 0.6);
    }
    body {
      font-family: var(--font-family-primary);
      background-color: var(--background-color);
      color: var(--text-color);
      transition: all var(--transition-speed);
      min-height: 100vh; CiaoCiaoCiaoCiao90@
      overflow-x: hidden;
      padding-bottom: 60px; 
      /* Animazione background con più colori pastel/cute */
      animation: pastelBackground 20s infinite alternate ease-in-out;
    }

    .background-bubbles {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      z-index: -1;
      overflow: hidden;
    }
    .bubble {
      position: absolute;
      border-radius: 50%;
      opacity: 0.3;
      filter: blur(10px);
      animation: float 20s infinite ease-in-out;
    }
    .bubble:nth-child(1) {
      width: 300px;
      height: 300px;
      background: var(--pastel-pink);
      top: -150px;
      left: -150px;
      animation-delay: 0s;
    }
    .bubble:nth-child(2) {
      width: 200px;
      height: 200px;
      background: var(--pastel-purple);
      top: 50%;
      right: -100px;
      animation-delay: -5s;
    }
    .bubble:nth-child(3) {
      width: 250px;
      height: 250px;
      background: var(--pastel-blue);
      bottom: -125px;
      left: 30%;
      animation-delay: -10s;
    }
    @keyframes float {
      0%, 100% { transform: translate(0, 0) scale(1); }
      50% { transform: translate(30px, -30px) scale(1.1); }
    }

    [data-theme="christmas"] .snow-container,
    [data-theme="newyear"] .firework-container,
    [data-theme="spring"] .rain-container,
    [data-theme="ocean"] .wave-container {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      pointer-events: none;
      z-index: 9999;
    }
    .snowflake {
      position: absolute;
      top: -10%;
      font-size: 1.2rem;
      color: #fff;
      opacity: 0.8;
      animation: snow 10s linear infinite;
      user-select: none;
    }
    @keyframes snow {
      0% { transform: translateY(0) rotate(0deg); }
      100% { transform: translateY(110vh) rotate(360deg); }
    }

    /* Nuova Animazione Fuochi d'Artificio Migliorata */
    .firework {
      position: absolute;
      bottom: 0;
      width: 3px;
      height: 15px;
      background: var(--accent-color);
      border-radius: 2px;
      animation: fireworkRise 1s ease-out forwards;
      opacity: 0.8;
    }
    .firework::after {
      content: '';
      position: absolute;
      top: -5px;
      left: -5px;
      width: 13px;
      height: 13px;
      background: var(--accent-color);
      border-radius: 50%;
      opacity: 0.6;
      animation: fireworkSparkle 1.2s ease-out forwards;
    }
    @keyframes fireworkRise {
      0% { transform: translateX(0) translateY(0); opacity: 1; }
      100% { transform: translateX(var(--firework-x)) translateY(-100vh); opacity: 0; }
    }
    @keyframes fireworkSparkle {
      0% { transform: scale(1); opacity: 0.6; }
      100% { transform: scale(0.5); opacity: 0; }
    }

    /* Nuove Animazioni per i Nuovi Temi */
    .rain-container {
      display: none;
    }
    .rain {
      position: absolute;
      width: 2px;
      height: 15px;
      background: var(--pastel-blue);
      opacity: 0.5;
      animation: rainFall 1s linear infinite;
    }
    @keyframes rainFall {
      0% { transform: translateY(-100px); }
      100% { transform: translateY(100vh); }
    }

    .wave-container {
      display: none;
    }
    .wave {
      position: absolute;
      bottom: -100px;
      width: 200px;
      height: 100px;
      background: var(--pastel-blue);
      border-radius: 100px 100px 0 0;
      opacity: 0.5;
      animation: waveRise 5s linear infinite;
    }
    @keyframes waveRise {
      0% { transform: translateX(0) scaleY(1); opacity: 0.5; }
      50% { transform: translateX(50px) scaleY(1.2); opacity: 0.7; }
      100% { transform: translateX(100px) scaleY(1); opacity: 0.5; }
    }

    .side-menu {
      position: fixed;
      top: 0;
      left: -320px;
      width: 320px;
      height: 100%;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border-right: var(--glass-border);
      z-index: 1000;
      transition: left var(--transition-speed) cubic-bezier(0.4, 0, 0.2, 1);
      padding: 30px;
      box-shadow: var(--bubble-shadow);
    }
    .side-menu.open {
      left: 0;
    }
    .menu-toggle {
      position: fixed;
      top: 20px;
      left: 20px;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-radius: 50%;
      width: 50px;
      height: 50px;
      display: flex;
      align-items: center;
      justify-content: center;
      color: var(--accent-color);
      font-size: 24px;
      z-index: 1001;
      cursor: pointer;
      box-shadow: var(--soft-shadow);
      transition: transform var(--transition-speed);
    }
    .menu-toggle:active {
      transform: scale(0.95);
    }
    .menu-toggle img.menu-icon {
      width: 20px;
      height: 20px;
      object-fit: contain;
      transition: transform 0.3s ease;
    }
    .menu-toggle.active img.menu-icon {
      transform: rotate(90deg);
    }
    .menu-header {
      display: flex;
      align-items: center;
      margin-bottom: 40px;
      padding-top: 20px;
    }
    .logo {
      font-size: 28px;
      font-weight: 600;
      background: linear-gradient(45deg, var(--primary-color), var(--secondary-color));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      text-align: center;
      width: 100%;
      font-family: var(--font-family-secondary);
    }
    .menu-items {
      list-style: none;
      margin-top: 30px;
    }
    .menu-items li {
      margin: 25px 0;
    }
    .menu-items a {
      color: var(--text-color);
      text-decoration: none;
      display: flex;
      align-items: center;
      gap: 15px;
      font-size: 16px;
      padding: 15px 20px;
      border-radius: var(--glass-radius);
      transition: all var(--transition-speed);
      background: transparent;
      cursor: pointer;
      font-family: var(--font-family-secondary);
    }
    .menu-items a:hover {
      background: var(--glass-background);
      transform: translateX(5px);
      box-shadow: var(--soft-shadow);
    }
    .menu-items img {
      width: 20px;
      height: 20px;
      object-fit: contain;
    }
    .theme-switcher {
      position: fixed;
      top: 20px;
      right: 20px;
      width: 50px;
      height: 50px;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: var(--soft-shadow);
      transition: all var(--transition-speed);
      z-index: 1001;
    }
    .theme-switcher img {
      width: 24px;
      height: 24px;
      object-fit: contain;
      transition: transform 0.3s ease;
    }
    .theme-switcher:hover img {
      transform: scale(1.1);
    }

    .settings-switcher {
      position: fixed;
      top: 80px;
      right: 20px;
      width: 50px;
      height: 50px;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: var(--soft-shadow);
      transition: all var(--transition-speed);
      z-index: 1001;
    }
    .settings-switcher img {
      width: 24px;
      height: 24px;
      object-fit: contain;
      transition: transform 0.3s ease;
    }
    .settings-switcher:hover img {
      transform: scale(1.1);
    }

    /* Stili per il pulsante combinato */
    .combined-switcher {
      position: fixed;
      top: 20px;
      right: 20px;
      width: 50px;
      height: 50px;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      box-shadow: var(--soft-shadow);
      transition: all var(--transition-speed);
      z-index: 1001;
    }

    .combined-switcher img#combinedIcon {
      width: 24px;
      height: 24px;
      object-fit: contain;
      transition: transform 0.3s ease;
    }

    .combined-switcher:hover img#combinedIcon {
      transform: scale(1.1);
    }

    /* Stili per la tendina combinata */
    .combined-dropdown {
      position: absolute;
      top: 60px;
      right: 0;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-radius: var(--glass-radius);
      box-shadow: var(--soft-shadow);
      display: none;
      flex-direction: column;
      padding: 10px;
      gap: 10px;
    }

    .combined-switcher.open .combined-dropdown {
      display: flex;
    }

    .combined-dropdown a {
      display: flex;
      align-items: center;
      gap: 10px;
      text-decoration: none;
      color: var(--text-color);
      padding: 8px 12px;
      border-radius: var(--glass-radius);
      transition: background var(--transition-speed), transform var(--transition-speed);
    }

    .combined-dropdown a:hover {
      background: var(--glass-background);
      transform: translateX(5px);
      box-shadow: var(--soft-shadow);
    }

    .combined-dropdown img.dropdown-icon {
      width: 20px;
      height: 20px;
      object-fit: contain;
    }


    .results-grid {
      width: 100%;
      min-height: 200px;
      margin: 0 auto;
      padding: 20px;
      margin-bottom: 120px;
      position: relative;
      animation: fadeInUp 1s ease-in-out;
    }
    @keyframes fadeInUp {
      from { opacity: 0; transform: translateY(20px); }
      to { opacity: 1; transform: translateY(0); }
    }

    .download-list {
      display: flex;
      flex-direction: column;
      gap: 15px;
      margin: 0 auto;
      max-width: 800px;
      margin-top: 30px;
    }

    @keyframes gradientAnimation {
        0% {
            background-position: 0% 50%;
            background-image: linear-gradient(135deg,
                var(--pastel-pink) 0%,
                var(--pastel-purple) 20%,
                var(--pastel-blue) 40%,
                var(--pastel-green) 60%,
                var(--pastel-yellow) 80%,
                var(--pastel-red) 100%
            );
        }

        50% {
            background-position: 100% 50%;
        }

        100% {
            background-position: 0% 50%;
        }
    }



    @keyframes floatingBubble1 {
        0%, 100% {
            transform: translate(10%, -20px) scale(1);
            opacity: 0.3;
        }
        50% {
            transform: translate(15%, -40px) scale(1.1);
            opacity: 0.5;
        }
    }

    @keyframes floatingBubble2 {
        0%, 100% {
            transform: translate(80%, 40%) scale(1);
            opacity: 0.3;
        }
        50% {
            transform: translate(85%, 30%) scale(1.1);
            opacity: 0.5;
        }
    }

    @keyframes floatingBubble3 {
        0%, 100% {
            transform: translate(30%, 90%) scale(1);
            opacity: 0.3;
        }
        50% {
            transform: translate(35%, 80%) scale(1.1);
            opacity: 0.5;
        }
    }
    .download-item {
        display: flex;
        align-items: center;
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(var(--glass-blur));
        -webkit-backdrop-filter: blur(var(--glass-blur));
        border: var(--glass-border);
        border-radius: var(--glass-radius);
        padding: 20px;
        box-shadow: var(--soft-shadow);
        cursor: pointer;
        transition: all var(--transition-speed);
        position: relative;
        color: var(--text-color);
        overflow: hidden;
    }


    .download-item::before {
        content: '';
        position: absolute;
        inset: 0;
        background: linear-gradient(135deg,
            var(--pastel-pink) 0%,
            var(--pastel-purple) 20%,
            var(--pastel-blue) 40%,
            var(--pastel-green) 60%,
            var(--pastel-yellow) 80%,
            var(--pastel-red) 100%
        );
        background-size: 400% 400%;
        animation: gradientAnimation 15s ease infinite;
        opacity: 0.3;
        z-index: -2;
    }

    .download-item::after {
        content: '';
        position: absolute;
        inset: 0;
        background: rgba(255, 255, 255, 0.1);
        backdrop-filter: blur(5px);
        -webkit-backdrop-filter: blur(5px);
        z-index: -1;
    }


    .download-item > * + *::before {
        ontent: '';
        position: absolute;
        width: 60px;
        height: 60px;
        background: rgba(255, 255, 255, 0.1);
        border-radius: 50%;
        pointer-events: none;
        animation: floatingBubble1 8s ease-in-out infinite;
        z-index: -1;
    }


    .download-item > * + *::after {
        content: '';
        position: absolute;
        width: 40px;
        height: 40px;
        background: rgba(255, 255, 255, 0.1);
        border-radius: 50%;
        pointer-events: none;
        animation: floatingBubble2 8s ease-in-out infinite;
        z-index: -1;
    }


    .download-item > *:first-child::before {
        content: '';
        position: absolute;
        width: 30px;
        height: 30px;
        background: rgba(255, 255, 255, 0.1);
        border-radius: 50%;
        pointer-events: none;
        animation: floatingBubble3 8s ease-in-out infinite;
        z-index: -1;
    }

    .download-item:hover {
        transform: translateY(-5px) scale(1.02);
        box-shadow: 0 15px 45px rgba(161, 140, 209, 0.4);
    }

    .download-item:hover::after {
        background: rgba(255, 255, 255, 0.15);
    }

    .download-item:active {
        transform: scale(0.98);
        box-shadow: 0 5px 15px rgba(161, 140, 209, 0.2);
    }



    @media (prefers-reduced-motion: reduce) {
        .download-item,
        .download-item::before,
        .download-item > * + *::before,
        .download-item > * + *::after,
        .download-item > *:first-child::before {
        animation: none;
        }

    .download-item:hover {
        transform: none;
    }
}

    .download-item:hover::before {
        background: rgba(0, 0, 0, 0.05);
    }

    @media (prefers-reduced-motion: reduce) {
      .download-item {
        animation: none;
        background: var(--glass-background); /* Ritorna al background statico */
      }
  
      .download-item::before {
        background: rgba(255, 255, 255, 0.15); /* Riduci l'overlay */
      }
    }
    .download-item-cover {
      width: 60px;
      height: 60px;
      border-radius: 12px;
      object-fit: cover;
      margin-right: 15px;
    }
    .download-item-info {
      flex: 1;
      display: flex;
      flex-direction: column;
      justify-content: center;
    }
    .download-item-title {
      font-weight: 600;
      font-family: Varela Round;
      font-size: 16px;
      margin-bottom: 5px;
      color: var(--text-color);
    }
    .download-item-artist {
      font-size: 14px;
      font-family: Outfit;
      color: var(--accent-color);
      opacity: 0.8;
    }
    .download-item-duration {
      font-size: 12px;
      color: var(--text-color);
      font-family: Fredoka One;
      opacity: 0.7;
      margin-top: 5px;
      display: flex;  
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
    }
    .delete-btn {
      background: transparent;
      border: none;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: transform 0.2s;
      overflow: hidden;
    }
    .delete-btn img {
      width: 24px;
      height: 24px;
      object-fit: contain;
    }
    .delete-btn:hover {
      transform: scale(1.2);
    }

    .favorite-btn {
      background: transparent;
      border: none;
      width: 40px;
      height: 40px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: transform var(--transition-speed);
      overflow: hidden;
    }
    .favorite-btn img {
      width: 20px;
      height: 20px;
      object-fit: contain;
    }
    .favorite-btn:hover {
      transform: scale(1.2);
    }

    .overlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(255, 255, 255, 0.2);
      backdrop-filter: blur(5px);
      opacity: 0;
      visibility: hidden;
      transition: all var(--transition-speed);
      z-index: 999;
    }
    .overlay.show {
      opacity: 1;
      visibility: visible;
    }

    .loading-spinner {
      display: none;
      margin-top: 20px;
      text-align: center;
    }
    .loading-spinner .spinner {
      width: 60px;
      height: 60px;
      background: linear-gradient(45deg, var(--pastel-pink), var(--pastel-purple));
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      animation: rotateSpinner 1s linear infinite;
      box-shadow: var(--soft-shadow);
      margin: 0 auto;
    }
    @keyframes rotateSpinner {
      from { transform: rotate(0deg); }
      to { transform: rotate(360deg); }
    }
    .spinner::after {
      content: '';
      width: 30px;
      height: 30px;
      background: rgba(255, 255, 255, 0.7);
      border-radius: 50%;
      animation: pulse 1.5s infinite;
    }
    @keyframes pulse {
      0%, 100% { transform: scale(1); opacity: 0.7; }
      50% { transform: scale(1.2); opacity: 1; }
    }

    .player-sheet {
      position: fixed;
      left: 0;
      right: 0;
      bottom: 0;
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-top-left-radius: var(--glass-radius);
      border-top-right-radius: var(--glass-radius);
      box-shadow: var(--bubble-shadow);
      overflow: hidden;
      z-index: 100;
      display: flex;
      flex-direction: column;
      transition: transform 0.3s ease;
      height: 80px;
      max-height: 90vh;
      color: white;
    }
    .player-sheet.collapsed {
      height: 92px;
    }
    .player-sheet.half {
      height: 50vh;
    }
    .player-sheet.expanded {
      height: 90vh;
    }
    .player-background {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background-size: cover;
      background-position: center;
      filter: blur(20px);
      transition: background-image 0.5s ease-in-out;
      z-index: -1;
    }
    .sheet-header {
      position: relative;
      padding: 10px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: grab;
    }
    .sheet-handle {
      width: 40px;
      height: 4px;
      background: var(--pastel-peach);
      border-radius: 2px;
      margin: 8px auto;
    }
    .sheet-compact {
      display: flex;
      align-items: center;
      padding: 0 15px;
      gap: 10px;
    }
    .sheet-compact img {
      width: 40px; 
      height: 40px; 
      object-fit: cover;
      border-radius: 8px;
      box-shadow: var(--soft-shadow);
    }
    .sheet-compact .player-info-compact {
      display: flex;
      flex-direction: column;
      overflow: hidden;
      color: white;
    }
    .sheet-compact .player-info-compact .song-title {
      font-size: 14px;
      font-family: 'Fredoka One';
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      animation: smooth-color-change 3s linear infinite;
    }

    @keyframes smooth-color-change {
      0% { color: #ffe6e6; }
      20% { color: #ffd7be; }
      40% { color: #ffb3b3; }
      60% { color: #ffc5c5; }
      80% { color: #ffb3b3; }
      100% { color: #ffe6e6; }
    }

    .sheet-compact .player-info-compact .song-artist {
      font-size: 12px;
      font-family: 'DynaPuff';
      color: white;
      opacity: 0.8;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .sheet-compact-controls {
      margin-left: auto;
      display: flex;
      align-items: center;
      gap: 15px;
    }
    .sheet-compact-controls button {
      background: transparent;
      border: none;
      width: 32px;
      height: 32px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
    }
    .sheet-compact-controls button img {
      width: 18px;
      height: 18px;
      object-fit: contain;
    }
    .sheet-expanded {
      padding: 15px 20px;
      overflow-y: auto;
      display: none;
    }
    .sheet-expanded img.player-image-expanded {
      width: 150px;
      height: 150px;
      border-radius: 20px;
      object-fit: cover;
      margin: 0 auto 10px;
      display: block;
      box-shadow: var(--soft-shadow);
    }
    .sheet-expanded .player-info-expanded {
      text-align: center;
      margin-bottom: 15px;
      color: white;
    }
    .sheet-expanded .player-info-expanded .song-title {
      font-size: 18px;
      font-family: 'Tsukimi Rounded';
      font-weight: 600;
      margin-bottom: 5px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      animation: smooth-color-change 3s linear infinite;
    }

    @keyframes smooth-color-change {
      0% { color: #ffe6e6; }
      20% { color: #ffd7be; }
      40% { color: #ffb3b3; }
      60% { color: #ffc5c5; }
      80% { color: #ffb3b3; }
      100% { color: #ffe6e6; }
    }

    .sheet-expanded .player-info-expanded .song-artist {
      font-size: 17px;
      font-family: 'Sour Gummy';
      color: white;
      opacity: 0.9;
    }

    .expanded-controls {
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: 10px;
      margin-top: 15px;
    }
    .time-slider-container {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 10px;
      justify-content: center;
    }
    .time-label {
      font-size: 12px;
      opacity: 0.7;
    }
    .time-slider {
      -webkit-appearance: none;
      width: 100%;
      height: 6px;
      background: var(--glass-background);
      border-radius: 3px;
      outline: none;
      margin: 0;
    }
    .time-slider::-webkit-slider-thumb {
      -webkit-appearance: none;
      width: 16px;
      height: 16px;
      background: linear-gradient(45deg, var(--primary-color), var(--secondary-color));
      border-radius: 50%;
      cursor: pointer;
      box-shadow: var(--soft-shadow);
      transition: transform 0.2s;
    }
    .time-slider::-webkit-slider-thumb:hover {
      transform: scale(1.2);
    }

    .animated-text {
      display: inline-block;
      white-space: nowrap;
      color: var(--pastel-yellow);
      font-size: 30px;
      font-family: 'Fredoka One', sans-serif;
      overflow: hidden;
      animation: blink-caret 0.75s step-end infinite, color-change 7s infinite;
    }

    @keyframes color-change {
  0%   { color: #FFCCC9; }   /* Soft Peach */
  7%   { color: #FFB3BA; }   /* Light Rose */
  14%  { color: #FF6F61; }   /* Coral Red */
  21%  { color: #FF9AA2; }   /* Vibrant Pink */
  28%  { color: #FFB6B9; }   /* Pastel Red */
  35%  { color: #FF8C94; }   /* Soft Pink Red */
  42%  { color: #FF704D; }   /* Warm Coral */
  49%  { color: #FF8DAA; }   /* Bright Pink */
  56%  { color: #FF6F61; }   /* Coral Red */
  63%  { color: #FF5E57; }   /* Strong Coral */
  70%  { color: #FF7F50; }   /* Coral */
  77%  { color: #FFB07C; }   /* Soft Apricot */
  84%  { color: #FFD1BA; }   /* Soft Coral Peach */
  91%  { color: #FFE5D9; }   /* Light Pastel Peach */
  100% { color: #FFCCC9; }   /* Soft Peach */
}



    @keyframes blink-caret {
      from, to { border-color: transparent; }
      50% { border-color: orange; }
    }



    .player-buttons {
      display: flex;
      align-items: center;
      gap: 15px;
    }
    .player-buttons button {
      background: transparent;
      border: none;
      width: 40px;
      height: 40px;
      display: flex;
      align-items: center;
      justify-content: center;
      cursor: pointer;
      transition: all var(--transition-speed);
    }
    .player-buttons button:hover {
      transform: scale(1.1);
      color: var(--accent-color);
    }
    .player-buttons button img {
      width: 24px;
      height: 24px;
      object-fit: contain;
    }
    .player-sheet.half .sheet-expanded,
    .player-sheet.expanded .sheet-expanded {
      display: block;
    }
    .player-sheet.half .sheet-compact,
    .player-sheet.expanded .sheet-compact {
      display: none; 
    }
    .download-progress {
      background: var(--glass-background);
      border-radius: 20px;
      height: 10px;
      width: 100%;
      overflow: hidden;
      position: relative;
      margin: 10px 0;
      box-shadow: inset 0 2px 8px rgba(0, 0, 0, 0.1);
    }
    .progress-fill {
      background: linear-gradient(45deg, var(--primary-color), var(--secondary-color));
      height: 100%;
      border-radius: 20px;
      width: 0%;
      transition: width 0.3s ease;
      position: relative;
      overflow: hidden;
    }
    .progress-fill::after {
      content: '';
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: linear-gradient(
        90deg,
        rgba(255, 255, 255, 0) 0%,
        rgba(255, 255, 255, 0.3) 50%,
        rgba(255, 255, 255, 0) 100%
      );
      animation: shine 1.5s infinite;
    }
    @keyframes shine {
      0% { transform: translateX(-100%); }
      100% { transform: translateX(100%); }
    }
    .success-icon {
      display: none;
      width: 20px;
      height: 20px;
      object-fit: contain;
      transition: transform 0.3s ease, opacity 0.3s ease;
      margin-left: 10px;
    }
    .success-icon.show {
      display: inline-block;
      animation: popIn 0.5s cubic-bezier(0.68, -0.55, 0.265, 1.55);
    }
    @keyframes popIn {
      0% {
        transform: scale(0) rotate(-180deg);
        opacity: 0;
      }
      70% {
        transform: scale(1.2) rotate(10deg);
        opacity: 1;
      }
      100% {
        transform: scale(1) rotate(0deg);
        opacity: 1;
      }
    }

    #analysisOverlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      display: none;
      background: rgba(255,255,255,0.4);
      backdrop-filter: blur(6px);
      z-index: 2000;
      align-items: center;
      justify-content: center;
      text-align: center;
      flex-direction: column;
      color: #333;
      font-family: var(--font-family-primary);
      padding: 20px;
    }
    #analysisOverlay.show {
      display: flex;
    }
    #analysisOverlay .analysis-text {
      background: var(--glass-background);
      border: var(--glass-border);
      border-radius: var(--glass-radius);
      padding: 20px 30px;
      box-shadow: var(--soft-shadow);
      color: var(--text-color);
      margin-bottom: 20px;
      font-size: 18px;
    }
    #analysisSpinnerOverlay {
      width: 80px;
      height: 80px;
      border: 8px solid var(--pastel-purple);
      border-top: 8px solid var(--pastel-pink);
      border-radius: 50%;
      animation: cuteSpin 0.8s linear infinite;
      box-shadow: var(--soft-shadow);
    }
    @keyframes cuteSpin {
      0% { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }

    #analysisPanel {
      max-height: 0;
      overflow: hidden;
      transition: max-height 0.4s ease;
    }
    #analysisPanel.open {
      max-height: 400px;
    }
    .analysis-chart {
      background: linear-gradient(135deg, #FAD0C4, #FFD1FF);
      border-radius: 20px;
      padding: 20px;
      box-shadow: 0 8px 16px rgba(161, 140, 209, 0.2);
    }
    .chart-container {
      position: relative;
      height: 300px;
      width: 100%;
      background: var(--glass-background);
      border-radius: var(--glass-radius);
      box-shadow: var(--soft-shadow);
      padding: 20px;
    }
    .analysis-toggle-btn {
      background: var(--pastel-blue);
      border: none;
      border-radius: 20px;
      padding: 6px 12px;
      font-size: 12px;
      cursor: pointer;
      font-family: var(--font-family-primary);
      transition: transform 0.2s;
      margin: 10px 0 0 0;
    }
    .analysis-toggle-btn:hover {
      transform: scale(1.05);
    }
    .describe-analysis-btn {
      background: transparent;
      border: none;
      color: var(--text-color);
      font-size: 22px;
      cursor: pointer;
      transition: all var(--transition-speed);
      width: 45px;
      height: 45px;
      display: flex;
      align-items: center;
      justify-content: center;
      margin-left: 10px;
    }
    .describe-analysis-btn:hover {
      color: var(--accent-color);
      transform: scale(1.1);
    }
    .describe-analysis-btn img {
      width: 24px;
      height: 24px;
      object-fit: contain;
    }

    #aiDescriptionModal {
      position: fixed;
      top: 0; 
      left: 0;
      right: 0; 
      bottom: 0;
      background: var(--ai-overlay-bg);
      backdrop-filter: blur(10px);
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
      z-index: 2001;
      opacity: 0;
      visibility: hidden;
      transition: all var(--transition-speed);
    }
    #aiDescriptionModal.show {
      opacity: 1;
      visibility: visible;
    }
    .ai-description-content {
      background: var(--glass-background);
      border: var(--glass-border);
      border-radius: var(--glass-radius);
      max-width: 600px;
      width: 100%;
      max-height: 80vh;
      overflow-y: auto;
      padding: 30px;
      box-shadow: var(--soft-shadow);
      animation: fadeInModal 0.3s ease-in-out;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: flex-start;
      position: relative;
    }
    @keyframes fadeInModal {
      0% {
        opacity: 0;
        transform: translateY(20px);
      }
      100% {
        opacity: 1;
        transform: translateY(0);
      }
    }
    #aiDescriptionTitle {
      font-size: 20px;
      font-family: var(--font-family-secondary);
      font-weight: 600;
      margin-bottom: 10px;
      text-align: center;
      color: var(--accent-color);
    }
    #aiDescriptionText {
      font-size: 16px;
      line-height: 1.6;
      margin-bottom: 20px;
      color: var(--text-color);
      width: 100%;
    }
    #closeAiDescriptionBtn {
      background: var(--primary-color);
      color: #fff;
      border: none;
      border-radius: var(--glass-radius);
      padding: 10px 20px;
      cursor: pointer;
      font-family: var(--font-family-primary);
      transition: transform 0.2s;
      width: 100%;
      text-align: center;
      font-size: 16px;
      margin-top: auto;
    }
    #closeAiDescriptionBtn:hover {
      transform: scale(1.05);
    }

    #aiLoadingOverlay {
      position: fixed;
      top: 0; left: 0;
      width: 100%; 
      height: 100%;
      display: none;
      z-index: 3000;
      background: var(--ai-overlay-bg);
      backdrop-filter: blur(10px);
      align-items: center;
      justify-content: center;
      flex-direction: column;
      transition: opacity var(--transition-speed);
    }
    #aiLoadingOverlay.show {
      display: flex;
    }
    #aiLoadingText {
      margin-top: 15px;
      color: var(--text-color);
      font-family: var(--font-family-secondary);
      font-size: 18px;
      text-align: center;
    }
    #aiSpinner {
      width: 70px;
      height: 70px;
      border: 8px solid var(--ai-spinner-color);
      border-top: 8px solid transparent;
      border-radius: 50%;
      animation: spinAi 1s linear infinite;
    }
    @keyframes spinAi {
      0%   { transform: rotate(0deg); }
      100% { transform: rotate(360deg); }
    }

    .home-container {
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      height: calc(100vh - 200px);
      background: linear-gradient(135deg, var(--pastel-yellow), var(--pastel-red));
      border-radius: var(--glass-radius);
      box-shadow: var(--soft-shadow);
      padding: 40px;
      text-align: center;
      animation: fadeInUp 1s ease-in-out;
      font-family: var(--font-family-cute);
      color: var(--text-color);
      position: relative;
    }
    .home-hero h1 {
      font-size: 48px;
      margin-bottom: 20px;
      color: var(--primary-color);
      text-shadow: 2px 2px 4px rgba(0,0,0,0.1);
    }
    .home-hero p {
      font-size: 20px;
      margin-bottom: 30px;
      color: var(--text-color);
    }
    .home-search {
      position: relative;
      width: 100%;
      max-width: 500px;
    }
    .home-search .search-input {
      padding: 15px 50px 15px 20px;
      font-size: 18px;
      border-radius: 30px;
      border: none;
      width: 100%;
      box-shadow: var(--soft-shadow);
      transition: all var(--transition-speed);
    }
    .home-search .search-input::placeholder {
      color: var(--text-color);
      opacity: 0.7;
    }
    .home-search .search-input:focus {
      outline: none;
      box-shadow: 0 8px 25px rgba(161, 140, 209, 0.25);
      transform: translateY(-2px);
    }
    .home-search .search-icon {
      position: absolute;
      right: 15px;
      top: 50%;
      transform: translateY(-50%);
      cursor: pointer;
      transition: transform 0.3s ease;
    }
    .home-search .search-icon img {
      width: 25px;
      height: 25px;
    }
    .home-search .search-icon:hover img {
      transform: scale(1.2);
    }

    #homeRedirectOverlay {
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(255, 255, 255, 0.75);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 9999;
      flex-direction: column;
      text-align: center;
      font-family: var(--font-family-primary);
    }
    #homeRedirectOverlay.show {
      display: flex;
    }
    #homeRedirectSpinner {
      width: 70px;
      height: 70px;
      background: linear-gradient(45deg, var(--pastel-pink), var(--pastel-purple));
      border-radius: 35px;
      animation: bounce2 1.5s infinite ease-in-out;
      position: relative;
      margin-bottom: 20px;
    }
    #homeRedirectSpinner::after {
      content: '';
      position: absolute;
      top: 20px;
      left: 20px;
      width: 30px;
      height: 30px;
      background: rgba(255, 255, 255, 0.7);
      border-radius: 15px;
      filter: blur(5px);
    }
    @keyframes bounce2 {
      0%, 100% {
        transform: scale(0.3);
        background: var(--pastel-pink);
      }
      50% {
        transform: scale(1);
        background: var(--pastel-purple);
      }
    }
    .empty-state {
      text-align: center;
      padding:50px;
      color: var(--text-color);
      opacity:0.9;
      font-size: 16px;
      display:flex;
      flex-direction:column;
      align-items:center;
      justify-content:center;
      animation: fadeIn 1s ease-in-out;
    }
    .empty-state-box {
      background: linear-gradient(135deg, var(--pastel-purple), var(--pastel-pink));
      padding: 40px;
      border-radius: 20px;
      box-shadow: var(--soft-shadow);
      max-width: 600px;
      animation: fadeInUp 0.8s ease;
      font-family: var(--font-family-secondary);
      text-align: left;
      transition: all var(--transition-speed);
    }
    .empty-state .empty-state-box img {
      width:60px;
      height:60px;
      object-fit: contain;
      margin-bottom:20px;
      animation: bounceIcon 2s infinite;
    }
    @keyframes bounceIcon {
      0%, 100% { transform: translateY(0); }
      50% { transform: translateY(-10px); }
    }
    .empty-state .empty-state-box p {
      color: #fff;
      font-size: 18px;
      line-height: 1.6;
    }

    .modal {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%) scale(0.9);
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      border: var(--glass-border);
      border-radius: var(--glass-radius);
      padding: 30px;
      width: 90%;
      max-width: 400px;
      opacity: 0;
      visibility: hidden;
      transition: all var(--transition-speed);
      z-index: 1001;
      font-family: var(--font-family-primary);
    }
    .modal.show {
      opacity: 1;
      visibility: visible;
      transform: translate(-50%, -50%) scale(1);
    }
    .modal-header {
      text-align: center;
      margin-bottom: 20px;
    }
    .modal-title {
      font-size: 24px;
      font-weight: 600;
      background: linear-gradient(45deg, var(--primary-color), var(--secondary-color));
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
      font-family: var(--font-family-secondary);
    }
    .modal-content {
      max-height: 300px;
      overflow-y: auto;
    }
    .quality-option {
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px;
      cursor: pointer;
      transition: background var(--transition-speed);
    }
    .playlist-item, .quality-option, .favorite-item {
      display: flex;
      align-items: center;
      padding: 15px;
      border-radius: var(--glass-radius);
      margin-bottom: 10px;
      cursor: pointer;
      transition: all var(--transition-speed);
      font-family: var(--font-family-primary);
    }
    .playlist-item:hover, .quality-option:hover, .favorite-item:hover {
      background: var(--glass-background);
      transform: translateX(5px);
    }
    .quality-option img.quality-icon {
      width: 20px;
      height: 20px;
      object-fit: contain;
    }
    .create-playlist-form {
      display: flex;
      gap: 10px;
      margin-bottom: 10px;
    }
    .create-playlist-form input {
      flex:1;
      padding:8px;
      border: none;
      border-radius: var(--glass-radius);
      background: var(--glass-background);
      backdrop-filter: blur(10px);
      color: var(--text-color);
      font-family: var(--font-family-primary);
    }
    .create-playlist-form button {
      background: var(--primary-color);
      border: none;
      border-radius: var(--glass-radius);
      color: #fff;
      padding: 8px 12px;
      cursor: pointer;
      font-family: var(--font-family-primary);
      transition: transform 0.2s;
    }
    .create-playlist-form button:hover {
      transform: scale(1.05);
    }
    #afterDownloadModal button {
      background: var(--primary-color);
      border:none;
      padding:10px 15px;
      border-radius:var(--glass-radius);
      margin:5px;
      color:#fff;
      transition: transform 0.3s;
      font-family: var(--font-family-primary);
      cursor: pointer;
    }
    #afterDownloadModal button:hover {
      transform: scale(1.05);
    }
    #addToPlaylistBtn {
      background: var(--secondary-color) !important;
    }
    .lyrics-search-input {
      width: 100%;
      padding: 12px;
      border-radius: 30px;
      border: none;
      margin-bottom: 10px;
      font-size: 16px;
      font-family: var(--font-family-cute);
      color: var(--text-color);
  /* Gradiente delicato e morbido */
      background: linear-gradient(
        135deg,
        var(--pastel-rose),
        var(--pastel-lemon)
      );
      box-shadow: var(--soft-shadow);
      transition: transform 0.2s ease,
                  box-shadow var(--transition-speed),
                  background 0.3s ease;
      outline: none;
    }

    .lyrics-search-input::placeholder {
      color: var(--text-color);
      opacity: 0.7;
    }

    .lyrics-search-input:focus {
  /* Aggiunge profondità e un gradiente leggermente diverso per il focus */
      box-shadow: 0 8px 25px rgba(161, 140, 209, 0.25);
      transform: translateY(-2px);
      background: linear-gradient(
        135deg,
        var(--pastel-lime),
        var(--pastel-sky)
      );
    }

    .lyrics-search-button {
      background: linear-gradient(135deg, var(--pastel-peach), var(--pastel-lavender));
      color: var(--text-color);
      border: none;
      border-radius: 30px;
      padding: 12px 20px;
      cursor: pointer;
      font-family: var(--font-family-cute);
      font-size: 16px;
      box-shadow: var(--soft-shadow);
      transition: transform 0.2s ease, box-shadow var(--transition-speed), background 0.3s ease;
      outline: none;
    }
    .lyrics-search-button:hover {
      transform: scale(1.05);
      box-shadow: 0 8px 25px rgba(161, 140, 209, 0.25);
    }

    /* Notification Styles */
    #notification-container {
      position: fixed;
      top: 20px;
      right: 20px;
      z-index: 10000;
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-width: 300px;
      width: 90%;
    }
    .notification {
      background-color: var(--primary-color);
      color: white;
      padding: 10px 15px;
      border-radius: 8px;
      box-shadow: var(--soft-shadow);
      opacity: 0;
      transform: translateX(100%);
      transition: opacity 0.3s ease, transform 0.3s ease;
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 14px;
    }
    .notification.show {
      opacity: 1;
      transform: translateX(0);
    }
    .notification.error {
      background-color: #e74c3c;
    }
    .notification.success {
      background-color: #2ecc71;
    }
    .notification.info {
      background-color: var(--primary-color);
    }
    .notification .icon {
      width: 20px;
      height: 20px;
      flex-shrink: 0;
    }
    .notification .close-btn {
      background: transparent;
      border: none;
      color: white;
      font-size: 16px;
      cursor: pointer;
      margin-left: auto;
      padding: 0;
      line-height: 1;
    }

    @media (max-width: 600px) {
      #notification-container {
        right: 10px;
        top: 10px;
      }
      .notification {
        padding: 8px 12px;
        font-size: 12px;
        gap: 8px;
      }
      .notification .icon {
        width: 16px;
        height: 16px;
      }
      .notification .close-btn {
        font-size: 14px;
      }
    }

    /* Keyframe esteso con più colori pastel/cute */
    @keyframes pastelBackground {
      0%    { background-color: var(--pastel-pink); }
      10%   { background-color: var(--pastel-rose); }
      20%   { background-color: var(--pastel-lavender); }
      30%   { background-color: var(--pastel-purple); }
      40%   { background-color: var(--pastel-sky); }
      50%   { background-color: var(--pastel-blue); }
      60%   { background-color: var(--pastel-lime); }
      70%   { background-color: var(--pastel-mint); }
      80%   { background-color: var(--pastel-green); }
      90%   { background-color: var(--pastel-peach); }
      95%   { background-color: var(--pastel-lemon); }
      100%  { background-color: var(--pastel-red); }
    }

  </style>
</head>
<body data-theme="light">
  <div class="background-bubbles">
    <div class="bubble"></div>
    <div class="bubble"></div>
    <div class="bubble"></div>
  </div>

  <div class="snow-container" id="snowContainer" style="display:none;"></div>
  <div class="firework-container" id="fireworkContainer" style="display:none;"></div>
  <div class="rain-container" id="rainContainer" style="display:none;"></div>
  <div class="wave-container" id="waveContainer" style="display:none;"></div>

  <div id="homeRedirectOverlay">
    <div id="homeRedirectSpinner"></div>
    <div id="homeRedirectText">
      Stai per essere reindirizzato, attendi...
    </div>
  </div>

  <div id="analysisOverlay">
    <div class="analysis-text">Stiamo analizzando la canzone...</div>
    <div id="analysisSpinnerOverlay"></div>
  </div>

  <button class="menu-toggle">
    <img src="/static/book.png" alt="book-icon" class="menu-icon">
  </button>

  <div class="side-menu">
    <div class="menu-header">
      <div class="logo">DØRTUBE</div>
    </div>
    <ul class="menu-items">
      <li><a id="menuHome"><img src="/static/home.png" alt="home-icon">Home</a></li>
      <li><a id="menuTopTracks"><img src="/static/top_tracks.png" alt="top-tracks-icon">Top Brani</a></li>
      <li><a id="menuProposals"><img src="/static/recommend.png" alt="proposals-icon">Proposte brani</a></li>
      <li><a id="menuCerca"><img src="/static/search.png" alt="search-icon">Cerca</a></li>
      <li><a id="menuFav"><img src="/static/heart.png" alt="heart-icon">Preferiti</a></li>
      <li><a id="menuPlaylist"><img src="/static/list.png" alt="list-icon">Playlist</a></li>
      <li><a id="menuDownloads"><img src="/static/download.png" alt="download-icon">Download</a></li>
      <li><a id="menuLyrics"><img src="/static/lyrics.png" alt="lyrics-icon">Testi</a></li>
    </ul>
  </div>

  <div class="combined-switcher" id="combinedSwitcher">
    <img src="/static/combined_icon.png" alt="combined-icon" id="combinedIcon">
    <div class="combined-dropdown" id="combinedDropdown">
      <a href="#" id="menuTheme" style="font-family: 'DynaPuff'">
        <img src="/static/sun.png" alt="Theme Icon" class="dropdown-icon"> Cambia Tema
      </a>
      <a href="#" id="menuSettings" style="font-family: 'DynaPuff'">
        <img src="/static/sliders.png" alt="Settings Icon" class="dropdown-icon"> Impostazioni
      </a>
    </div>
  </div>


  <div class="overlay"></div>

  <div id="notification-container"></div>

  <div class="modal" id="settingsModal">
    <div class="modal-header">
      <div class="modal-title">Impostazioni YT-DLP</div>
    </div>
    <div class="modal-content">
      <div class="quality-option" data-quality="bestaudio">
        <img src="/static/bestaudio.png" alt="Icona Best Audio" class="quality-icon">
        Qualità Migliore (bestaudio)
      </div>
      <div class="quality-option" data-quality="128k">
        <img src="/static/bad.png" alt="Icona 128k" class="quality-icon">
        Qualità 128k
      </div>
      <div class="quality-option" data-quality="192k">
        <img src="/static/good.png" alt="Icona 192k" class="quality-icon">
        Qualità 192k
      </div>
    </div>
  </div>

  <div class="modal" id="favoritesModal">
    <div class="modal-header">
      <div class="modal-title">⭐ Brani Preferiti</div>
    </div>
    <div class="modal-content" id="favoritesList">
    </div>
  </div>

  <div class="modal" id="playlistsModal">
    <div class="modal-header">
      <div class="modal-title">Playlist</div>
    </div>
    <div class="modal-content" id="playlistsContent">
      <form class="create-playlist-form" id="createPlaylistForm">
        <input type="text" id="newPlaylistName" placeholder="Nuova Playlist...">
        <button type="submit">Crea</button>
      </form>
    </div>
  </div>

  <div class="modal" id="afterDownloadModal">
    <div class="modal-header">
      <div class="modal-title">Aggiungi a...</div>
    </div>
    <div class="modal-content" style="text-align:center;">
      <button id="addToFavoritesBtn">Aggiungi ai Preferiti</button>
      <button id="addToPlaylistBtn">Aggiungi a Playlist</button>
    </div>
  </div>

  <div class="modal" id="lyricsModal">
    <div class="modal-header">
      <div class="modal-title">✏️ Cerca Testi</div>
    </div>
    <div class="modal-content" style="text-align:center;">
      <input type="text" id="lyricsTitle" class="lyrics-search-input" placeholder="Titolo brano...">
      <input type="text" id="lyricsArtist" class="lyrics-search-input" placeholder="Artista...">
      <button id="searchLyricsBtn" class="lyrics-search-button">Cerca Testi</button>
      <hr style="margin:15px 0;">
      <pre id="lyricsResult" style="text-align:left;white-space:pre-wrap;"></pre>
    </div>
  </div>

  <div id="aiDescriptionModal">
    <div class="ai-description-content">
      <div id="aiDescriptionTitle">Descrizione AI</div>
      <div id="aiDescriptionText">Qui apparirà la descrizione fornita dall'AI...</div>
      <button id="closeAiDescriptionBtn">Chiudi</button>
    </div>
  </div>

  <div id="aiLoadingOverlay">
    <div id="aiSpinner"></div>
    <div id="aiLoadingText">Caricamento risposta AI...</div>
  </div>

  <div class="results-grid" id="resultsGrid">
    <div class="home-container">
      <div class="home-hero">
        <h1><img src="/static/loghetto.png" alt="bolla di sapone" style="width: 47px; height: 47px; vertical-align: middle;"><span class="animated-text" id="animatedText"></span></h1>

        <p>Trova e ascolta i tuoi brani preferiti in un attimo!</p>
        <div class="home-search">
          <input type="text" class="search-input" placeholder="Cerca una canzone...">
          <div class="search-icon">
            <img src="/static/search.png" alt="search-icon">
          </div>
        </div>
      </div>
      <div class="loading-spinner" id="searchSpinner">
        <div class="spinner"></div>
      </div>
    </div>
  </div>

  <div class="player-sheet collapsed" id="playerSheet">
    <div class="player-background" id="playerBackground"></div>
    <div class="sheet-header" id="sheetHeader">
      <div class="sheet-handle"></div>
    </div>
    <div class="sheet-compact" id="sheetCompact">
      <img src="/static/default_cover.png" alt="Cover" id="playerCoverCompact">
      <div class="player-info-compact">
        <div class="song-title" id="playerTitleCompact">Nessun brano...</div>
        <div class="song-artist" id="playerArtistCompact"></div>
      </div>
      <div class="sheet-compact-controls">
        <button class="prev-btn"><img src="/static/step-backward.png" alt="prev-icon"></button>
        <button class="play-btn"><img src="/static/play.png" alt="play-icon"></button>
        <button class="next-btn"><img src="/static/step-forward.png" alt="next-icon"></button>
      </div>
      <img src="/static/check-circle.png" alt="success-icon" class="success-icon">
    </div>
    <div class="sheet-expanded" id="sheetExpanded">
      <img src="/static/default_cover.png" alt="Cover" class="player-image-expanded" id="playerCoverExpanded">
      <div class="player-info-expanded">
        <div class="song-title" id="playerTitleExpanded">Nessun brano in riproduzione...</div>
        <div class="song-artist" id="playerArtistExpanded">👻 ATTENDO UN BRANO!</div>
      </div>

      <div class="download-progress">
        <div class="progress-fill" id="progressBar"></div>
      </div>

      <div class="expanded-controls">
        <div class="time-slider-container">
          <span class="time-label" id="currentTimeLabel">00:00</span>
          <input type="range" class="time-slider" id="timeSlider" min="0" max="100" step="0.1" value="0">
          <span class="time-label" id="durationLabel">00:00</span>
        </div>

        <div class="player-buttons">
          <button class="prev-btn"><img src="/static/step-backward.png" alt="prev-icon"></button>
          <button class="play-btn"><img src="/static/play.png" alt="play-icon"></button>
          <button class="next-btn"><img src="/static/step-forward.png" alt="next-icon"></button>
          <button class="fav-player-btn"><img src="/static/heart-outline.png" alt="heart-outline-icon"></button>
          <button class="analyze-btn"><img src="/static/analyze.png" alt="analyze-icon"></button>
          <button class="describe-analysis-btn"><img src="/static/ai.png" alt="ai-icon"></button>
          <button class="download-again-btn"><img src="/static/download.png" alt="download-icon" style="width:24px;height:24px;"></button>
        </div>
        <img src="/static/check-circle.png" alt="success-icon" class="success-icon">
      </div>

      <div id="analysisPanel">
        <div class="chart-container">
          <canvas id="analysisChart" class="analysis-chart"></canvas>
        </div>
      </div>
      <button class="analysis-toggle-btn" id="analysisToggleBtn" style="display:none;">
        👻 Nascondi Analisi
      </button>
    </div>
  </div>

  <audio id="audioPlayer" controls style="display:none;"></audio>

  <script>
    function showNotification(message, type='info') {
      const container = document.getElementById('notification-container');
      const notif = document.createElement('div');
      notif.classList.add('notification', type);

      let iconSrc = '';
      if (type === 'error') {
        iconSrc = '/static/error.png';
      } else if (type === 'success') {
        iconSrc = '/static/success.png';
      } else {
        iconSrc = '/static/info.png';
      }

      notif.innerHTML = `
        <img src="${iconSrc}" alt="${type}-icon" class="icon">
        <span>${message}</span>
        <button class="close-btn">&times;</button>
      `;
      container.appendChild(notif);
      setTimeout(() => {
          notif.classList.add('show');
      }, 100);
      setTimeout(() => {
          notif.classList.remove('show');
          notif.addEventListener('transitionend', () => {
              notif.remove();
          });
      }, 3000);
      notif.querySelector('.close-btn').addEventListener('click', () => {
          notif.classList.remove('show');
          notif.addEventListener('transitionend', () => {
              notif.remove();
          });
      });
    }

    let isPlaying = false;
    let currentQuality = 'bestaudio';
    let favorites = [];
    let playlists = {};
    let lastDownloadedTrack = null;
    let downloadedTracks = [];
    let currentTrack = null;
    let currentTrackIndex = -1;
    let lastAnalysisData = null;

    const menuToggle = document.querySelector('.menu-toggle');
    const sideMenu = document.querySelector('.side-menu');
    const overlay = document.querySelector('.overlay');
    const resultsGrid = document.getElementById('resultsGrid');
    const playBtn = document.querySelectorAll('.play-btn');
    const audioPlayer = document.getElementById('audioPlayer');

    const playerCoverCompact = document.getElementById('playerCoverCompact');
    const playerTitleCompact = document.getElementById('playerTitleCompact');
    const playerArtistCompact = document.getElementById('playerArtistCompact');

    const playerCoverExpanded = document.getElementById('playerCoverExpanded');
    const playerTitleExpanded = document.getElementById('playerTitleExpanded');
    const playerArtistExpanded = document.getElementById('playerArtistExpanded');

    const progressBar = document.getElementById('progressBar');
    const favPlayerBtn = document.querySelector('.fav-player-btn');
    const snowContainer = document.getElementById('snowContainer');
    const fireworkContainer = document.getElementById('fireworkContainer');
    const rainContainer = document.getElementById('rainContainer');
    const waveContainer = document.getElementById('waveContainer');
    const timeSlider = document.getElementById('timeSlider');
    const currentTimeLabel = document.getElementById('currentTimeLabel');
    const durationLabel = document.getElementById('durationLabel');
    const homeRedirectOverlay = document.getElementById('homeRedirectOverlay');
    const themeSwitcher = document.getElementById('themeSwitcher');
    const body = document.body;
    const analysisOverlay = document.getElementById('analysisOverlay');
    const analysisPanel = document.getElementById('analysisPanel');
    const analysisToggleBtn = document.getElementById('analysisToggleBtn');
    const analyzeBtn = document.querySelector('.analyze-btn');
    const describeAnalysisBtn = document.querySelector('.describe-analysis-btn');
    const downloadAgainBtn = document.querySelector('.download-again-btn');

    const settingsSwitcher = document.getElementById('settingsSwitcher');
    const playerSheet = document.getElementById('playerSheet');
    const sheetHeader = document.getElementById('sheetHeader');
    const playerBackground = document.getElementById('playerBackground');

    const lyricsModal = document.getElementById('lyricsModal');
    const lyricsTitle = document.getElementById('lyricsTitle');
    const lyricsArtist = document.getElementById('lyricsArtist');
    const lyricsResult = document.getElementById('lyricsResult');
    const searchLyricsBtn = document.getElementById('searchLyricsBtn');

    const aiDescriptionModal = document.getElementById('aiDescriptionModal');
    const aiDescriptionText = document.getElementById('aiDescriptionText');
    const closeAiDescriptionBtn = document.getElementById('closeAiDescriptionBtn');
    const aiLoadingOverlay = document.getElementById('aiLoadingOverlay');

    let chartInstance = null;
    const analysisContext = document.getElementById('analysisChart').getContext('2d');

    function triggerConfetti() {
  const duration = 1500;
  const end = Date.now() + duration;

  // Definisci le gamme di tonalità per i colori desiderati
  const colorRanges = {
    yellow: { min: 50, max: 60 },    // Giallo
    pink: { min: 300, max: 330 },    // Rosa
    peach: { min: 20, max: 30 },     // Pesca
    green: { min: 90, max: 150 },    // Verde
    red: { min: 0, max: 15 }         // Rosso
  };

  // Funzione per generare un colore pastellato casuale all'interno delle gamme specificate
  function getRandomPastelColor() {
    // Seleziona casualmente una delle categorie di colore
    const categories = Object.keys(colorRanges);
    const randomCategory = categories[Math.floor(Math.random() * categories.length)];
    const range = colorRanges[randomCategory];

    // Genera una tonalità casuale all'interno della gamma selezionata
    const hue = Math.floor(Math.random() * (range.max - range.min + 1)) + range.min;

    const saturation = Math.floor(Math.random() * 20) + 70; // Saturazione tra 70% e 90%
    const lightness = Math.floor(Math.random() * 10) + 80;  // Luminosità tra 80% e 90%

    return hslToHex(hue, saturation, lightness);
  }

  // Funzione per convertire HSL in HEX
  function hslToHex(h, s, l) {
    l /= 100;
    const a = s * Math.min(l, 1 - l) / 100;
    const f = n => {
      const k = (n + h / 30) % 12;
      const color = l - a * Math.max(Math.min(k - 3, 9 - k, 1), -1);
      return Math.round(255 * color).toString(16).padStart(2, '0');
    };
    return `#${f(0)}${f(8)}${f(4)}`;
  }

  // Genera un array di colori pastellati casuali limitati alle categorie specificate
  const pastelColors = Array.from({ length: 30 }, getRandomPastelColor); // Aumentato a 30 per maggiore varietà

  (function frame() {
    confetti({
      particleCount: 4,
      angle: 60,
      spread: 60,
      origin: { x: 0 },
      colors: pastelColors
    });
    confetti({
      particleCount: 4,
      angle: 120,
      spread: 60,
      origin: { x: 1 },
      colors: pastelColors
    });
    if (Date.now() < end) {
      requestAnimationFrame(frame);
    }
  })();
}


    /* Funzione Migliorata per i Fuochi d'Artificio */
    function triggerFirework() {
      const firework = document.createElement('div');
      firework.classList.add('firework');
      // Random horizontal position
      firework.style.left = Math.random() * 100 + '%';
      // Random horizontal movement
      firework.style.setProperty('--firework-x', (Math.random() * 100 - 50) + 'px');
      fireworkContainer.appendChild(firework);
      // Rimuove il fuoco d'artificio dopo l'animazione
      firework.addEventListener('animationend', () => {
        firework.remove();
      });
    }

    function triggerRain() {
      rainContainer.style.display = 'block';
      rainContainer.innerHTML = '';
      for (let i = 0; i < 50; i++) {
        const drop = document.createElement('div');
        drop.className = 'rain';
        drop.style.left = Math.random() * 100 + '%';
        drop.style.animationDuration = (1 + Math.random() * 1) + 's';
        drop.style.animationDelay = Math.random() * 2 + 's';
        rainContainer.appendChild(drop);
      }
    }

    function triggerWaves() {
      waveContainer.style.display = 'block';
      waveContainer.innerHTML = '';
      for (let i = 0; i < 5; i++) {
        const wave = document.createElement('div');
        wave.className = 'wave';
        wave.style.left = (i * 200) + 'px';
        waveContainer.appendChild(wave);
      }
    }

    function initPlayerSheetDrag() {
      let startY = 0;
      let currentY = 0;
      let dragging = false;
      const minHeight = 92;
      const midHeight = 0.5;
      const maxHeight = 0.9;

      sheetHeader.addEventListener('mousedown', startDrag);
      sheetHeader.addEventListener('touchstart', startDrag, { passive: false });

      function startDrag(e) {
        dragging = true;
        startY = (e.touches && e.touches[0]) ? e.touches[0].clientY : e.clientY;
        document.addEventListener('mousemove', onDrag);
        document.addEventListener('touchmove', onDrag, { passive: false });
        document.addEventListener('mouseup', stopDrag);
        document.addEventListener('touchend', stopDrag);
      }
      function onDrag(e) {
        if (!dragging) return;
        e.preventDefault();
        currentY = (e.touches && e.touches[0]) ? e.touches[0].clientY : e.clientY;
        let delta = startY - currentY;

        let sheetRect = playerSheet.getBoundingClientRect();
        let currentHeight = sheetRect.height;
        let newHeight = currentHeight + delta;
        let maxPixel = Math.round(window.innerHeight * maxHeight);
        if (newHeight < minHeight) newHeight = minHeight;
        if (newHeight > maxPixel) newHeight = maxPixel;

        playerSheet.style.height = newHeight + 'px';
        updatePlayerBackground(currentTrack);
        startY = currentY;
      }
      function stopDrag(e) {
        dragging = false;
        document.removeEventListener('mousemove', onDrag);
        document.removeEventListener('touchmove', onDrag);
        document.removeEventListener('mouseup', stopDrag);
        document.removeEventListener('touchend', stopDrag);

        let sheetRect = playerSheet.getBoundingClientRect();
        let finalHeight = sheetRect.height;
        let windowHeight = window.innerHeight;

        let collapsedThreshold = minHeight + (windowHeight * 0.1);
        let halfThreshold = windowHeight * (midHeight + 0.1);
        let expandThreshold = windowHeight * (maxHeight - 0.1);

        let halfPx = windowHeight * midHeight; 
        let expandPx = windowHeight * maxHeight; 

        if (finalHeight <= collapsedThreshold) {
          playerSheet.classList.remove('half');
          playerSheet.classList.remove('expanded');
          playerSheet.classList.add('collapsed');
          playerSheet.style.height = minHeight + 'px';
        } else if (finalHeight >= expandThreshold) {
          playerSheet.classList.remove('collapsed');
          playerSheet.classList.remove('half');
          playerSheet.classList.add('expanded');
          playerSheet.style.height = expandPx + 'px';
        } else {
          playerSheet.classList.remove('collapsed');
          playerSheet.classList.remove('expanded');
          playerSheet.classList.add('half');
          playerSheet.style.height = halfPx + 'px';
        }
      }
    }

    window.startDownload = async function startDownload(url, title, artist, thumbnail) {
      const progressFill = document.querySelector('.progress-fill');
      const successIcon = document.querySelector('.sheet-expanded .success-icon');
      progressFill.style.width = '0%';
      successIcon.classList.remove('show');

      let fakeProgress = 0;
      const fakeInterval = setInterval(() => {
        fakeProgress += 3;
        if (fakeProgress >= 90) fakeProgress = 90;
        progressFill.style.width = fakeProgress + '%';
      }, 200);

      try {
        const resp = await fetch('/download', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({url, quality: currentQuality})
        });
        const data = await resp.json();
        clearInterval(fakeInterval);
        if (data.error) {
          progressFill.style.width = '100%';
          progressFill.style.background = 'red';
          showNotification(`Errore nel download: ${data.error}`, 'error');
          return;
        }
        progressFill.style.width = '100%';
        successIcon.classList.add('show');

        const trackInfo = {
          title: data.title,
          artist: data.artist || 'Sconosciuto',
          thumbnail: data.thumbnail,
          file_url: data.file_url,
          webpage_url: url
        };
        downloadedTracks.push(trackInfo);
        currentTrackIndex = downloadedTracks.length - 1;
        playTrack(trackInfo);
        lastDownloadedTrack = trackInfo;

        document.getElementById('afterDownloadModal').classList.add('show');
        overlay.classList.add('show');

        setTimeout(() => {
          successIcon.classList.remove('show');
          progressFill.style.width = '0%';
          progressFill.style.background = 'linear-gradient(45deg, var(--primary-color), var(--secondary-color))';
        }, 2000);

      } catch (error) {
        clearInterval(fakeInterval);
        progressFill.style.width = '100%';
        progressFill.style.background = 'red';
        showNotification(`Errore nel download: ${error.message}`, 'error');
      }
    };

    function downloadCurrentTrack() {
      if (!currentTrack) {
        showNotification('Nessun brano selezionato o in riproduzione!', 'error');
        return;
      }
      startDownload(currentTrack.webpage_url, currentTrack.title, currentTrack.artist, currentTrack.thumbnail);
    }
    downloadAgainBtn.addEventListener('click', downloadCurrentTrack);

    function setupHomeSearch() {
      const si = document.querySelector('.home-search .search-input');
      const sp = document.getElementById('searchSpinner');
      if (!si || !sp) return;

      si.removeEventListener('input', handleInput);
      si.addEventListener('input', handleInput);

      function handleInput() {
        let query = si.value.trim();
        if (query.length > 0) {
          sp.style.display = 'block';
          clearTimeout(window.searchTimeout);

          window.searchTimeout = setTimeout(async () => {
            try {
              let resp = await fetch(`/search?q=${encodeURIComponent(query)}`);
              let data = await resp.json();
              sp.style.display = 'none';
              resultsGrid.innerHTML = '';

              if (data.error) {
                showNotification(data.error, 'error');
              } else {
                if (data.results.length === 0) {
                  showNotification('Nessun risultato trovato.', 'info');
                } else {
                  triggerConfetti();
                  setTimeout(() => {
                    let hc = document.querySelector('.home-container');
                    if (hc) hc.style.display = 'none';

                    let container = document.createElement('div');
                    container.classList.add('download-list');

                    data.results.forEach((track) => {
                      let item = document.createElement('div');
                      item.classList.add('download-item');
                      item.setAttribute('data-url', track.webpage_url);

                      let durSec = track.duration || 0;
                      let mm = Math.floor(durSec / 60);
                      let ss = durSec % 60;
                      let durFormatted = (mm < 10 ? "0"+mm : mm) + ":" + (ss < 10 ? "0"+ss : ss);

                      let uploadDate = track.upload_date ? track.upload_date : '---';
                      let views = track.view_count ? track.view_count.toLocaleString() : '---';

                      item.innerHTML = `
                        <img src="${track.thumbnail}" alt="Cover" class="download-item-cover">
                        <div class="download-item-info">
                          <div class="download-item-title">${track.title}</div>
                          <div class="download-item-artist">${track.uploader || 'Sconosciuto'}</div>
                          <div class="download-item-duration">
                            Durata: ${durSec > 0 ? durFormatted : '--:--'}
                            | Visual: ${views}
                            | Pubbl.: ${uploadDate}
                            <button class="delete-btn"><img src="/static/trash.png" alt="trash-icon"></button>
                            <button class="favorite-btn"><img src="/static/heart-outline.png" alt="heart-outline-icon"></button>
                          </div>
                        </div>
                      `;

                      item.addEventListener('click', async (e) => {
                        if (e.target.closest('.delete-btn')) {
                          e.stopPropagation();
                          showNotification('Prima scarica il brano, poi potrai eventualmente eliminarlo dal DB.', 'info');
                          return;
                        }
                        if (e.target.closest('.favorite-btn')) {
                          e.stopPropagation();
                          showNotification('Devi prima scaricare il brano per aggiungerlo ai preferiti!', 'info');
                          return;
                        }

                        await startDownload(track.webpage_url, track.title, track.uploader, track.thumbnail);
                      });

                      container.appendChild(item);
                    });

                    resultsGrid.appendChild(container);
                  }, 700);
                }
              }
            } catch (error) {
              sp.style.display = 'none';
              showNotification(`Errore nella ricerca: ${error.message}`, 'error');
            }
          }, 800);
        } else {
          sp.style.display = 'none';
          resultsGrid.innerHTML = `
            <div class="home-container">
              <div class="home-hero">
                <h1><img src="/static/loghetto.png" alt="largehz-icon" width="45" height="45"></h1>
                <p>Trova e ascolta i tuoi brani preferiti in un attimo!</p>
                <div class="home-search">
                  <input type="text" class="search-input" placeholder="Cerca una canzone...">
                  <div class="search-icon">
                    <img src="/static/search.png" alt="search-icon">
                  </div>
                </div>
              </div>
              <div class="loading-spinner" id="searchSpinner">
                <div class="spinner"></div>
              </div>
            </div>
          `;
          setupHomeSearch();
        }
      }
    }

    document.addEventListener('DOMContentLoaded', async () => {
      setupHomeSearch();
      initPlayerSheetDrag();

      try {
        let respFav = await fetch('/api/favorites');
        let dataFav = await respFav.json();
        favorites = dataFav.favorites || [];

        let respPl = await fetch('/api/playlists');
        let dataPl = await respPl.json();
        playlists = {};
        dataPl.playlists.forEach(pl => {
          playlists[pl.name] = pl.tracks;
        });

        let respDown = await fetch('/api/tracks');
        let dataDown = await respDown.json();
        downloadedTracks = dataDown.tracks || [];
      } catch (err) {
        console.error('Errore nel caricamento dati dal DB:', err);
        showNotification('Errore nel caricamento dati dal DB.', 'error');
      }
    });

    if ('serviceWorker' in navigator) {
      window.addEventListener('load', function() {
        navigator.serviceWorker.register('/service-worker.js');
      });
    }

    document.addEventListener("DOMContentLoaded", function() {
      const texts = ["DORTUBE", "PLAYER ", "MUSIC "]; // Array di nomi
      const animatedText = document.getElementById("animatedText");
      let textIndex = 0; // Indice del testo corrente nell'array
      let charIndex = 0; // Indice del carattere corrente nel testo
      let isDeleting = false; // Stato di cancellazione
      const typingSpeed = 150; // Velocità di digitazione (ms)
      const deletingSpeed = 100; // Velocità di cancellazione (ms)
      const pause = 1000; // Pausa tra digitazione e cancellazione (ms)

      function type() {
        const currentText = texts[textIndex]; // Testo corrente da visualizzare

        if (isDeleting) {
          // Cancellazione del testo
          animatedText.textContent = currentText.substring(0, charIndex--);
          if (charIndex < 0) {
            isDeleting = false;
            textIndex = (textIndex + 1) % texts.length; // Passa al prossimo testo in loop
            setTimeout(type, typingSpeed);
          } else {
            setTimeout(type, deletingSpeed);
          }
        } else {
          // Digitazione del testo
          animatedText.textContent = currentText.substring(0, charIndex++);
          if (charIndex > currentText.length) {
            isDeleting = true;
            setTimeout(type, pause);
          } else {
            setTimeout(type, typingSpeed);
          }
        }
      }

      type(); // Avvia l'animazione
    });

    function closeAllModals() {
      sideMenu.classList.remove('open');
      overlay.classList.remove('show');
      menuToggle.classList.remove('active');
      document.getElementById('settingsModal').classList.remove('show');
      document.getElementById('favoritesModal').classList.remove('show');
      document.getElementById('playlistsModal').classList.remove('show');
      document.getElementById('afterDownloadModal').classList.remove('show');
      lyricsModal.classList.remove('show');
      aiDescriptionModal.classList.remove('show');
    }

    function playTrack(track) {
      currentTrack = track;
      updatePlayerBackground(track);

      playerCoverCompact.src = track.thumbnail;
      playerTitleCompact.textContent = track.title;
      playerArtistCompact.textContent = track.artist;

      playerCoverExpanded.src = track.thumbnail;
      playerTitleExpanded.textContent = track.title;
      playerArtistExpanded.textContent = track.artist;

      audioPlayer.src = track.file_url;
      audioPlayer.play();
      isPlaying = true;

      playBtn.forEach(btn => {
        const icon = btn.querySelector('img');
        icon.src = '/static/pause.png';
      });
    }

    function updatePlayerBackground(track) {
      if (track && track.thumbnail) {
        playerBackground.style.backgroundImage = `url('${track.thumbnail}')`;
      } else {
        playerBackground.style.backgroundImage = `url('/static/default_cover.png')`;
      }
    }

    playBtn.forEach(btn => {
      btn.addEventListener('click', () => {
        if (!currentTrack) {
          showNotification('Nessun brano selezionato!', 'error');
          return;
        }
        isPlaying = !isPlaying;
        playBtn.forEach(b => {
          const icon = b.querySelector('img');
          if (isPlaying) {
            icon.src = '/static/pause.png';
            audioPlayer.play();
          } else {
            icon.src = '/static/play.png';
            audioPlayer.pause();
          }
        });
      });
    });

    audioPlayer.addEventListener('ended', () => {
      nextTrack();
    });

    function nextTrack() {
      if (downloadedTracks.length === 0) {
        return;
      }
      currentTrackIndex++;
      if (currentTrackIndex >= downloadedTracks.length) {
        currentTrackIndex = 0;
      }
      const track = downloadedTracks[currentTrackIndex];
      playTrack(track);
    }

    document.querySelectorAll('.prev-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        if (downloadedTracks.length === 0) {
          return;
        }
        currentTrackIndex--;
        if (currentTrackIndex < 0) {
          currentTrackIndex = downloadedTracks.length - 1;
        }
        const track = downloadedTracks[currentTrackIndex];
        playTrack(track);
      });
    });

    document.querySelectorAll('.next-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        nextTrack();
      });
    });

    audioPlayer.addEventListener('timeupdate', () => {
      if (!isNaN(audioPlayer.duration) && currentTrack) {
        const progress = (audioPlayer.currentTime / audioPlayer.duration) * 100;
        progressBar.style.width = `${progress}%`;
        timeSlider.value = progress.toFixed(1);
        currentTimeLabel.textContent = formatTime(audioPlayer.currentTime);
        durationLabel.textContent = formatTime(audioPlayer.duration);
      }
    });

    timeSlider.addEventListener('input', () => {
      if (!currentTrack) return;
      const newPercent = parseFloat(timeSlider.value);
      if (!isNaN(audioPlayer.duration)) {
        audioPlayer.currentTime = (newPercent / 100) * audioPlayer.duration;
      }
    });

    function formatTime(seconds) {
      if (isNaN(seconds)) return "00:00";
      const m = Math.floor(seconds / 60);
      const s = Math.floor(seconds % 60);
      return (m<10?"0"+m:m)+":"+(s<10?"0"+s:s);
    }

    favPlayerBtn.addEventListener('click', async () => {
      if (!currentTrack) {
        showNotification('Nessun brano in riproduzione da aggiungere ai preferiti!', 'error');
        return;
      }
      try {
        let resp = await fetch('/api/favorites', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ file_url: currentTrack.file_url })
        });
        let data = await resp.json();
        if (data.error) {
          showNotification(data.error, 'error');
        } else {
          showNotification(`Aggiunto "${currentTrack.title}" ai preferiti!`, 'success');
          favPlayerBtn.querySelector('img').src = '/static/heart-filled.png';
          favorites.push(currentTrack);
        }
      } catch (err) {
        showNotification(`Errore durante l'aggiunta ai preferiti: ${err}`, 'error');
      }
    });

    menuToggle.addEventListener('click', () => {
      sideMenu.classList.toggle('open');
      overlay.classList.toggle('show');
      menuToggle.classList.toggle('active');
    });

    overlay.addEventListener('click', () => {
      closeAllModals();
    });

    // Ottieni riferimenti agli elementi
    const combinedSwitcher = document.getElementById('combinedSwitcher');
    const combinedDropdown = document.getElementById('combinedDropdown');
    const menuTheme = document.getElementById('menuTheme');
    const menuSettings = document.getElementById('menuSettings');

    // Funzione per chiudere la tendina se si clicca fuori
    document.addEventListener('click', (event) => {
      if (!combinedSwitcher.contains(event.target)) {
        combinedSwitcher.classList.remove('open');
      }
    });

    // Toggle della tendina combinata
    combinedSwitcher.addEventListener('click', (e) => {
      e.stopPropagation(); // Previene la chiusura immediata
      combinedSwitcher.classList.toggle('open');
    });

    // Gestione del cambio tema tramite la tendina combinata
    menuTheme.addEventListener('click', () => {
      const currentTheme = body.getAttribute('data-theme');
      let newTheme;
      let newIconSrc;

      if (currentTheme === 'light') {
        newTheme = 'dark';
        newIconSrc = '/static/moon.png';
        removeSnow();
        removeFireworks();
        removeRain();
        removeWaves();
    } else if (currentTheme === 'dark') {
        newTheme = 'christmas';
        newIconSrc = '/static/snowflake.png';
        startSnow();
        removeFireworks();
        removeRain();
        removeWaves();
    } else if (currentTheme === 'christmas') {
        newTheme = 'newyear';
        newIconSrc = '/static/firework.png';
        startFireworks();
        removeSnow();
        removeRain();
        removeWaves();
    } else if (currentTheme === 'newyear') {
        newTheme = 'spring';
        newIconSrc = '/static/rain.png';
        startRain();
        removeFireworks();
        removeSnow();
        removeWaves();
    } else if (currentTheme === 'spring') {
        newTheme = 'ocean';
        newIconSrc = '/static/wave.png';
        startWaves();
        removeFireworks();
        removeSnow();
        removeRain();
    } else {
        newTheme = 'light';
        newIconSrc = '/static/sun.png';
        removeSnow();
        removeFireworks();
        removeRain();
        removeWaves();
    }

    body.setAttribute('data-theme', newTheme);
    const combinedIcon = document.getElementById('combinedIcon');
    combinedIcon.src = newIconSrc;

    // Aggiorna l'icona nel link "Cambia Tema" nella tendina combinata
    const dropdownIcon = menuTheme.querySelector('.dropdown-icon');
    if (dropdownIcon) {
      dropdownIcon.src = newIconSrc;
    }

    // Chiudi la tendina dopo l'azione
      combinedSwitcher.classList.remove('open');
    });

    function startSnow() {
      snowContainer.style.display = 'block';
      snowContainer.innerHTML = '';
      for (let i = 0; i < 20; i++) {
        const flake = document.createElement('div');
        flake.className = 'snowflake';
        flake.innerHTML = '❄';
        flake.style.left = Math.random() * 100 + '%';
        flake.style.animationDuration = (8 + Math.random() * 5) + 's';
        snowContainer.appendChild(flake);
      }
    }

    function removeSnow() {
      snowContainer.style.display = 'none';
      snowContainer.innerHTML = '';
    }

    function startFireworks() {
      fireworkContainer.style.display = 'block';
      // Generate firework periodically
      const interval = setInterval(() => {
        triggerFirework();
      }, 1000);
      fireworkContainer.setAttribute('data-interval', interval);
    }

    function removeFireworks() {
      fireworkContainer.style.display = 'none';
      fireworkContainer.innerHTML = '';
      const interval = fireworkContainer.getAttribute('data-interval');
      if (interval) {
        clearInterval(interval);
        fireworkContainer.removeAttribute('data-interval');
      }
    }

    function startRain() {
      rainContainer.style.display = 'block';
      rainContainer.innerHTML = '';
      for (let i = 0; i < 50; i++) {
        const drop = document.createElement('div');
        drop.className = 'rain';
        drop.style.left = Math.random() * 100 + '%';
        drop.style.animationDuration = (1 + Math.random() * 1) + 's';
        drop.style.animationDelay = Math.random() * 2 + 's';
        rainContainer.appendChild(drop);
      }
    }

    function removeRain() {
      rainContainer.style.display = 'none';
      rainContainer.innerHTML = '';
    }

    function startWaves() {
      waveContainer.style.display = 'block';
      waveContainer.innerHTML = '';
      for (let i = 0; i < 5; i++) {
        const wave = document.createElement('div');
        wave.className = 'wave';
        wave.style.left = (i * 200) + 'px';
        waveContainer.appendChild(wave);
      }
    }

    function removeWaves() {
      waveContainer.style.display = 'none';
      waveContainer.innerHTML = '';
    }

    // Gestione delle Impostazioni tramite la tendina combinata
    menuSettings.addEventListener('click', () => {
      document.getElementById('settingsModal').classList.add('show');
      overlay.classList.add('show');
  
      // Chiudi la tendina dopo l'azione
      combinedSwitcher.classList.remove('open');
    });

    document.getElementById('menuHome').addEventListener('click', () => {
      closeAllModals();
      resultsGrid.innerHTML = `
        <div class="home-container">
          <div class="home-hero">
            <h1><img src="/static/loghetto.png" alt="bolla di sapone" style="width: 47px; height: 47px; vertical-align: middle;">DORTUBE <span class="animated-text" id="animatedText"></span></h1>
            <p>Trova e ascolta i tuoi brani preferiti in un attimo!</p>
            <div class="home-search">
              <input type="text" class="search-input" placeholder="Cerca una canzone...">
              <div class="search-icon">
                <img src="/static/search.png" alt="search-icon">
              </div>
            </div>
          </div>
          <div class="loading-spinner" id="searchSpinner">
            <div class="spinner"></div>
          </div>
        </div>
      `;
      setupHomeSearch();
    });

    document.getElementById('menuTopTracks').addEventListener('click', async () => {
      closeAllModals();
      let si = document.querySelector('.home-search .search-input');
      if (si) si.value = '';
      resultsGrid.innerHTML = '';
      homeRedirectOverlay.classList.add('show');
      try {
        const resp = await fetch('/top_tracks');
        const data = await resp.json();
        homeRedirectOverlay.classList.remove('show');
        if (data.error) {
          showNotification(data.error, 'error');
          return;
        }
        if (data.top_tracks.length > 0) {
          let html = `
            <div style="text-align:center; margin-bottom:20px;">
              <h2 style="margin-bottom:10px; font-family: var(--font-family-secondary); font-size:28px;">🏆 Top 10 Brani</h2>
              <p style="color:var(--text-color); font-family: var(--font-family-secondary); opacity:0.8;">Scopri i 10 brani più popolari!</p>
            </div>
            <div class="download-list">
          `;
          data.top_tracks.forEach((song) => {
            html += `
              <div class="download-item" data-url="${song.url}">
                <img src="${song.thumbnail}" alt="Cover" class="download-item-cover">
                <div class="download-item-info">
                  <div class="download-item-title">${song.name}</div>
                  <div class="download-item-artist">${song.artist}</div>
                  <div class="download-item-duration">Cancella brano ➡️
                    <button class="delete-btn"><img src="/static/trash.png" alt="trash-icon"></button>
                  </div>
                </div>
                <button class="favorite-btn"><img src="/static/heart-outline.png" alt="heart-outline-icon"></button>
              </div>
            `;
          });
          html += `</div>`;
          resultsGrid.innerHTML = html;

          document.querySelectorAll('.download-item').forEach(item => {
            item.addEventListener('click', async (e) => {
              if (e.target.closest('.favorite-btn')) return;
              if (e.target.closest('.delete-btn')) return;
              const url = item.getAttribute('data-url');
              const title = item.querySelector('.download-item-title').textContent;
              const artist = item.querySelector('.download-item-artist').textContent;
              const thumbnail = item.querySelector('.download-item-cover').src;
              await startDownload(url, title, artist, thumbnail);
            });
          });

          document.querySelectorAll('.delete-btn').forEach(delBtn => {
            delBtn.addEventListener('click', (ev) => {
              ev.stopPropagation();
              showNotification('Questi brani top sono solo un elenco, prima scaricali per poterli poi cancellare.', 'info');
            });
          });

        } else {
          resultsGrid.innerHTML = `
            <div style="text-align:center; margin-bottom:20px;">
              <h2 style="margin-bottom:10px; font-family: var(--font-family-secondary); font-size:28px;">Top 10 Brani</h2>
              <p style="opacity:0.8;">Nessun brano trovato.</p>
            </div>
          `;
        }
      } catch(err) {
        homeRedirectOverlay.classList.remove('show');
        showNotification(`Errore durante il recupero dei top brani: ${err}`, 'error');
      }
    });

    document.getElementById('menuProposals').addEventListener('click', async () => {
      closeAllModals();
      let si = document.querySelector('.home-search .search-input');
      if (si) si.value = '';
      resultsGrid.innerHTML = '';
      homeRedirectOverlay.classList.add('show');
      if (!lastDownloadedTrack || !lastDownloadedTrack.artist) {
        await new Promise(r => setTimeout(r, 1000));
        homeRedirectOverlay.classList.remove('show');
        resultsGrid.innerHTML = `
          <div style="text-align:center; margin-bottom:20px;">
            <h2 style="margin-bottom:10px; font-family: var(--font-family-secondary); font-size:28px;">📅 Proposte Brano</h2>
            <p style="opacity:0.8;">Nessun brano scaricato di recente. Scarica qualcosa per ottenere proposte mirate!</p>
          </div>
        `;
        return;
      }
      try {
        const artistName = encodeURIComponent(lastDownloadedTrack.artist);
        const resp = await fetch(`/recommendations?artist=${artistName}`);
        const recData = await resp.json();
        homeRedirectOverlay.classList.remove('show');
        if (recData.error) {
          showNotification(recData.error, 'error');
          return;
        }
        if (recData.length > 0) {
          let html = `
            <div style="text-align:center; margin-bottom:20px;">
              <h2 style="margin-bottom:10px; font-family: var(--font-family-secondary); font-size:28px;">Proposte per te</h2>
              <p style="opacity:0.8;">Basate sull'ultimo artista scaricato: <strong>${lastDownloadedTrack.artist}</strong></p>
            </div>
            <div class="download-list">
          `;
          recData.forEach((track) => {
            html += `
              <div class="download-item" data-url="${track.webpage_url}">
                <img src="${track.thumbnail}" alt="Proposta" class="download-item-cover">
                <div class="download-item-info">
                  <div class="download-item-title">${track.title}</div>
                  <div class="download-item-artist">Cancella brano ➡️
                    <button class="delete-btn"><img src="/static/trash.png" alt="trash-icon"></button>
                  </div>
                </div>
                <button class="favorite-btn"><img src="/static/heart-outline.png" alt="heart-outline-icon"></button>
              </div>
            `;
          });
          html += `</div>`;
          resultsGrid.innerHTML = html;

          document.querySelectorAll('.download-item').forEach(item => {
            item.addEventListener('click', async (e) => {
              if (e.target.closest('.favorite-btn')) return;
              if (e.target.closest('.delete-btn')) return;
              const url = item.getAttribute('data-url');
              const title = item.querySelector('.download-item-title').textContent;
              const artist = item.querySelector('.download-item-artist').textContent;
              const thumbnail = item.querySelector('.download-item-cover').src;
              await startDownload(url, title, artist, thumbnail);
            });
          });

          document.querySelectorAll('.delete-btn').forEach(delBtn => {
            delBtn.addEventListener('click', (ev) => {
              ev.stopPropagation();
              showNotification('Questi brani consigliati non sono ancora nel DB, scaricali prima se vuoi cancellarli.', 'info');
            });
          });

        } else {
          resultsGrid.innerHTML = `
            <div style="text-align:center; margin-bottom:20px;">
              <h2 style="margin-bottom:10px; font-family: var(--font-family-secondary); font-size:28px;">Proposte del giorno</h2>
              <p style="opacity:0.8;">Non ci sono raccomandazioni al momento. Prova con altri brani!</p>
            </div>
          `;
        }
      } catch(err) {
        homeRedirectOverlay.classList.remove('show');
        showNotification(`Errore durante il recupero delle proposte: ${err}`, 'error');
      }
    });

    document.getElementById('menuCerca').addEventListener('click', () => {
      closeAllModals();
      let si = document.querySelector('.home-search .search-input');
      if (si) si.focus();
    });

    document.getElementById('menuFav').addEventListener('click', () => {
      updateFavoritesModal();
      document.getElementById('favoritesModal').classList.add('show');
      overlay.classList.add('show');
    });

    document.getElementById('menuPlaylist').addEventListener('click', () => {
      updatePlaylistsModal();
      document.getElementById('playlistsModal').classList.add('show');
      overlay.classList.add('show');
    });

    document.getElementById('menuDownloads').addEventListener('click', async () => {
      closeAllModals();
      let si = document.querySelector('.home-search .search-input');
      if (si) si.value = '';
      resultsGrid.innerHTML = '';
      homeRedirectOverlay.classList.add('show');

      try {
        let resp = await fetch('/api/tracks');
        let data = await resp.json();
        homeRedirectOverlay.classList.remove('show');

        if (!data.tracks || data.tracks.length === 0) {
          resultsGrid.innerHTML = `
            <div style="text-align:center; margin-bottom:20px;">
              <h2 style="margin-bottom:10px; font-family: var(--font-family-secondary); font-size:28px;">Download</h2>
              <p style="opacity:0.8;">Nessun brano scaricato</p>
            </div>
          `;
          return;
        }
        let html = `
          <div style="text-align:center; margin-bottom:20px;">
            <h2 style="margin-bottom:10px; font-family: Fredoka One; font-size:28px;">📂 Download</h2>
            <p style="color:var(--text-color); font-family: Fredoka One; font-size:18px; opacity:0.8;">🎵 Brani che hai scaricato in precedenza</p>
          </div>
          <div class="download-list">
        `;
        data.tracks.forEach((track, idx) => {
          html += `
            <div class="download-item" data-idx="${idx}">
              <img src="${track.thumbnail}" alt="Cover" class="download-item-cover">
              <div class="download-item-info">
                <div class="download-item-title">${track.title}</div>
                <div class="download-item-artist">${track.artist}</div>
                <div class="download-item-duration">Cancella brano ➡️
                  <button class="delete-btn"><img src="/static/trash.png" alt="trash-icon"></button>
                </div>
              </div>
              <button class="favorite-btn"><img src="/static/heart-outline.png" alt="heart-outline-icon"></button>
            </div>
          `;
        });
        html += `</div>`;
        resultsGrid.innerHTML = html;

        downloadedTracks = data.tracks;

        document.querySelectorAll('.download-item').forEach(item => {
          item.addEventListener('click', (e) => {
            if (e.target.closest('.favorite-btn')) return;
            if (e.target.closest('.delete-btn')) return;
            const idx = parseInt(item.getAttribute('data-idx'), 10);
            currentTrackIndex = idx;
            playTrack(downloadedTracks[idx]);
          });
        });

        document.querySelectorAll('.delete-btn').forEach((delBtn, delIndex) => {
          delBtn.addEventListener('click', async (ev) => {
            ev.stopPropagation();
            const idx = parseInt(delBtn.parentNode.parentNode.parentNode.getAttribute('data-idx'));
            const trackToDelete = downloadedTracks[idx];
            if (!trackToDelete) return;
            try {
              const delResp = await fetch(`/api/tracks/${trackToDelete.id}`, {
                method: 'DELETE'
              });
              const delData = await delResp.json();
              if (delData.status === 'ok') {
                showNotification(`Brano "${trackToDelete.title}" rimosso!`, 'success');
                delBtn.parentNode.parentNode.parentNode.remove();
                downloadedTracks.splice(idx, 1);
              } else {
                showNotification('Errore nella rimozione del brano.', 'error');
              }
            } catch (err) {
              showNotification('Errore di rete nella rimozione del brano.', 'error');
            }
          });
        });

      } catch(err) {
        homeRedirectOverlay.classList.remove('show');
        showNotification(`Errore durante il recupero dei download: ${err}`, 'error');
      }
    });

    document.getElementById('menuLyrics').addEventListener('click', () => {
      closeAllModals();
      lyricsModal.classList.add('show');
      overlay.classList.add('show');
    });

    document.querySelectorAll('.quality-option').forEach(option => {
      option.addEventListener('click', () => {
        currentQuality = option.dataset.quality;
        showNotification(`Qualità impostata a: ${currentQuality}`, 'info');
        document.getElementById('settingsModal').classList.remove('show');
        overlay.classList.remove('show');
      });
    });

    document.getElementById('addToFavoritesBtn').addEventListener('click', async () => {
      if (lastDownloadedTrack) {
        try {
          let resp = await fetch('/api/favorites', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ file_url: lastDownloadedTrack.file_url })
          });
          let data = await resp.json();
          if (data.error) {
            showNotification(data.error, 'error');
          } else {
            showNotification(`Aggiunto "${lastDownloadedTrack.title}" ai preferiti!`, 'success');
            favorites.push(lastDownloadedTrack);
          }
        } catch (err) {
          showNotification(`Errore durante l'aggiunta ai preferiti: ${err}`, 'error');
        }
      }
      document.getElementById('afterDownloadModal').classList.remove('show');
      overlay.classList.remove('show');
    });

    document.getElementById('addToPlaylistBtn').addEventListener('click', () => {
      if (lastDownloadedTrack) {
        updatePlaylistsModal();
        document.getElementById('playlistsModal').classList.add('show');
      }
      document.getElementById('afterDownloadModal').classList.remove('show');
    });

    function updateFavoritesModal() {
      const favList = document.getElementById('favoritesList');
      favList.innerHTML = '';
      if (favorites.length === 0) {
        favList.innerHTML = '<p style="text-align:center;opacity:0.8;">Nessun brano tra i preferiti</p>';
      } else {
        favorites.forEach(track => {
          const item = document.createElement('div');
          item.className = 'favorite-item';
          item.innerHTML = `<img src="/static/heart-filled.png" alt="heart-filled-icon" style="width:20px; height:20px; margin-right:10px;"> ${track.title} - ${track.artist}`;
          item.addEventListener('click', () => {
            playTrack(track);
            closeAllModals();
          });
          favList.appendChild(item);
        });
      }
    }

    const playlistsContent = document.getElementById('playlistsContent');
    const createPlaylistForm = document.getElementById('createPlaylistForm');

    createPlaylistForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const name = document.getElementById('newPlaylistName').value.trim();
      if (name) {
        try {
          let resp = await fetch('/api/playlists', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ name })
          });
          let data = await resp.json();
          if (data.error) {
            showNotification(data.error, 'error');
          } else {
            showNotification(`Playlist "${name}" creata!`, 'success');
            document.getElementById('newPlaylistName').value = '';
            resp = await fetch('/api/playlists');
            data = await resp.json();
            playlists = {};
            data.playlists.forEach(pl => {
              playlists[pl.name] = pl.tracks;
            });
            updatePlaylistsModal();
          }
        } catch (err) {
          showNotification(`Errore creazione playlist: ${err}`, 'error');
        }
      }
    });

    function updatePlaylistsModal() {
      while (playlistsContent.children.length > 1) {
        if (playlistsContent.lastChild !== createPlaylistForm) {
          playlistsContent.removeChild(playlistsContent.lastChild);
        } else {
          break;
        }
      }
      const names = Object.keys(playlists);
      if (names.length === 0) {
        const p = document.createElement('p');
        p.style.textAlign = 'center';
        p.style.opacity = '0.8';
        p.textContent = 'Nessuna playlist creata';
        playlistsContent.appendChild(p);
      } else {
        names.forEach(name => {
          const item = document.createElement('div');
          item.className = 'playlist-item';
          item.innerHTML = `<img src="/static/list.png" alt="list-icon" style="width:20px; height:20px; margin-right:10px;"> ${name} (${playlists[name].length} brani)`;
          item.addEventListener('click', async () => {
            if (lastDownloadedTrack) {
              try {
                let resp = await fetch('/api/playlists/add', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({ playlist_name: name, file_url: lastDownloadedTrack.file_url })
                });
                let data = await resp.json();
                if (data.error) {
                  showNotification(data.error, 'error');
                } else {
                  showNotification(`Aggiunto "${lastDownloadedTrack.title}" alla playlist "${name}"!`, 'success');
                  lastDownloadedTrack = null;
                  closeAllModals();
                }
              } catch (err) {
                showNotification(`Errore durante l'aggiunta alla playlist: ${err}`, 'error');
              }
            } else {
              showPlaylistTracks(name);
            }
          });
          playlistsContent.appendChild(item);
        });
      }
    }

    function showPlaylistTracks(playlistName) {
      playlistsContent.innerHTML = '';
      const h = document.createElement('div');
      h.className = 'modal-header';
      h.innerHTML = `<div class="modal-title">Brani in ${playlistName}</div>`;
      playlistsContent.appendChild(h);

      const backBtn = document.createElement('div');
      backBtn.textContent = '← Indietro';
      backBtn.style.cursor = 'pointer';
      backBtn.style.textAlign = 'right';
      backBtn.style.marginBottom = '10px';
      backBtn.style.fontFamily = 'var(--font-family-primary)';
      backBtn.addEventListener('click', () => {
        updatePlaylistsModal();
      });
      playlistsContent.appendChild(backBtn);

      if (!playlists[playlistName] || playlists[playlistName].length === 0) {
        const p = document.createElement('p');
        p.style.textAlign = 'center';
        p.style.opacity = '0.8';
        p.textContent = 'Nessun brano in questa playlist.';
        playlistsContent.appendChild(p);
      } else {
        playlists[playlistName].forEach(track => {
          const item = document.createElement('div');
          item.className = 'playlist-item';
          item.innerHTML = `<img src="/static/music.png" alt="music-icon" style="width:20px; height:20px; margin-right:10px;"> ${track.title} - ${track.artist}`;
          item.addEventListener('click', () => {
            playTrack(track);
            closeAllModals();
          });
          playlistsContent.appendChild(item);
        });
      }
    }

    analyzeBtn.addEventListener('click', async () => {
      if (!currentTrack) {
        showNotification('Nessun brano in riproduzione da analizzare!', 'error');
        return;
      }
      analysisOverlay.classList.add('show');
      try {
        const resp = await fetch('/analyze', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ file_url: currentTrack.file_url })
        });
        const data = await resp.json();
        analysisOverlay.classList.remove('show');

        if (data.error) {
          showNotification(`Errore nell'analisi: ${data.error}`, 'error');
          return;
        }
        lastAnalysisData = data.emotions;
        analysisPanel.classList.add('open');
        analysisToggleBtn.style.display = 'inline-block';
        analysisToggleBtn.textContent = '👻 Nascondi Analisi';

        if (chartInstance) {
          chartInstance.destroy();
        }

        const labels = Object.keys(data.emotions);
        const values = Object.values(data.emotions);

        const backgroundColors = [
          'rgba(255, 182, 193, 0.6)',
          'rgba(135, 206, 250, 0.6)',
          'rgba(144, 238, 144, 0.6)',
          'rgba(255, 228, 181, 0.6)',
          'rgba(250, 128, 114, 0.6)',
          'rgba(221, 160, 221, 0.6)',
          'rgba(176, 224, 230, 0.6)',
          'rgba(152, 251, 152, 0.6)'
        ];
        const borderColors = [
          'rgba(255, 182, 193, 1)',
          'rgba(135, 206, 250, 1)',
          'rgba(144, 238, 144, 1)',
          'rgba(255, 228, 181, 1)',
          'rgba(250, 128, 114, 1)',
          'rgba(221, 160, 221, 1)',
          'rgba(176, 224, 230, 1)',
          'rgba(152, 251, 152, 1)'
        ];

        chartInstance = new Chart(analysisContext, {
          type: 'bar',
          data: {
            labels: labels,
            datasets: [{
              label: 'Valori',
              data: values,
              backgroundColor: backgroundColors.slice(0, labels.length),
              borderColor: borderColors.slice(0, labels.length),
              borderWidth: 2,
              borderRadius: 15,
              hoverBackgroundColor: backgroundColors.slice(0, labels.length).map(c => c.replace('0.6', '0.8')),
              hoverBorderColor: borderColors.slice(0, labels.length)
            }]
          },
          options: {
            plugins: {
              legend: {
                labels: {
                  font: {
                    family: 'Poppins, sans-serif',
                    size: 14,
                    weight: '500'
                  },
                  color: '#6C7293'
                }
              },
              tooltip: {
                backgroundColor: 'rgba(255, 255, 255, 0.9)',
                titleColor: '#A18CD1',
                bodyColor: '#6C7293',
                borderColor: '#A18CD1',
                borderWidth: 1,
                borderRadius: 10,
                padding: 10,
                displayColors: false
              }
            },
            scales: {
              y: {
                beginAtZero: true,
                grid: {
                  color: 'rgba(161, 140, 209, 0.1)'
                },
                ticks: {
                  color: '#6C7293',
                  font: {
                    family: 'Poppins, sans-serif',
                    size: 12
                  }
                }
              },
              x: {
                grid: {
                  display: false
                },
                ticks: {
                  color: '#6C7293',
                  font: {
                    family: 'Poppins, sans-serif',
                    size: 12
                  }
                }
              }
            },
            responsive: true,
            maintainAspectRatio: false
          }
        });
      } catch (err) {
        analysisOverlay.classList.remove('show');
        showNotification(`Errore nell'analisi: ${err}`, 'error');
      }
    });

    analysisToggleBtn.addEventListener('click', () => {
      if (analysisPanel.classList.contains('open')) {
        analysisPanel.classList.remove('open');
        analysisToggleBtn.textContent = '⬆️ Mostra Analisi';
      } else {
        analysisPanel.classList.add('open');
        analysisToggleBtn.textContent = '⬇️ Nascondi Analisi';
      }
    });

    function parseMarkdown(text) {
      let parsed = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
      parsed = parsed.replace(/\*(.*?)\*/g, '<em>$1</em>');
      return parsed;
    }

    describeAnalysisBtn.addEventListener('click', async () => {
      if (!lastAnalysisData) {
        showNotification('Prima esegui l\'analisi del brano per avere dei dati da descrivere!', 'error');
        return;
      }
      aiLoadingOverlay.classList.add('show');
      try {
        const resp = await fetch('/describe_analysis', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ analysisData: lastAnalysisData })
        });
        const data = await resp.json();
        aiLoadingOverlay.classList.remove('show');

        if (data.error) {
          showNotification(`Errore nella descrizione AI: ${data.error}`, 'error');
          return;
        }
        const formatted = parseMarkdown(data.description);
        aiDescriptionText.innerHTML = formatted;
        aiDescriptionModal.classList.add('show');
      } catch (err) {
        aiLoadingOverlay.classList.remove('show');
        showNotification(`Errore nella descrizione AI: ${err}`, 'error');
      }
    });

    closeAiDescriptionBtn.addEventListener('click', () => {
      aiDescriptionModal.classList.remove('show');
    });

    searchLyricsBtn.addEventListener('click', async () => {
      const t = lyricsTitle.value.trim();
      const a = lyricsArtist.value.trim();
      if (!t || !a) {
        showNotification('Inserisci titolo e artista per cercare i testi!', 'error');
        return;
      }
      lyricsResult.textContent = 'Caricamento...';
      try {
        const resp = await fetch(`/api/lyrics?title=${encodeURIComponent(t)}&artist=${encodeURIComponent(a)}`);
        const data = await resp.json();
        if (data.error) {
          lyricsResult.textContent = `Errore: ${data.error}`;
          showNotification(`Errore: ${data.error}`, 'error');
        } else if (data.lyrics) {
          lyricsResult.textContent = data.lyrics;
        } else {
          lyricsResult.textContent = 'Testo non trovato.';
          showNotification('Testo non trovato.', 'info');
        }
      } catch (err) {
        lyricsResult.textContent = `Errore nella richiesta: ${err}`;
        showNotification(`Errore nella richiesta: ${err}`, 'error');
      }
    });
  </script>
</body>
</html>
"""
@app.route('/')
def index():
    return render_template_string(HTML_PAGE)

@app.route('/manifest.json')
def manifest():
    manifest_data = {
        "short_name": "BubbleMusic",
        "name": "Bubble Music Player",
        "icons": [
            {
                "src": "/static/icons/icon-192x192.png",
                "type": "image/png",
                "sizes": "192x192"
            },
            {
                "src": "/static/icons/icon-512x512.png",
                "type": "image/png",
                "sizes": "512x512"
            }
        ],
        "start_url": "/",
        "background_color": "#A18CD1",
        "display": "standalone",
        "scope": "/",
        "theme_color": "#A18CD1"
    }
    return jsonify(manifest_data)

@app.route('/service-worker.js')
def service_worker():
    sw_js = """
    const CACHE_NAME = 'bubble-music-cache-v2';
    const urlsToCache = [
      '/',
      '/static/book.png',
      '/static/home.png',
      '/static/top_tracks.png',
      '/static/recommend.png',
      '/static/search.png',
      '/static/heart.png',
      '/static/list.png',
      '/static/sliders.png',
      '/static/moon.png',
      '/static/snowflake.png',
      '/static/sun.png',
      '/static/firework.png',
      '/static/rain.png',
      '/static/wave.png',
      '/static/bestaudio.png',
      '/static/bad.png',
      '/static/good.png',
      '/static/heart-outline.png',
      '/static/play.png',
      '/static/pause.png',
      '/static/step-backward.png',
      '/static/step-forward.png',
      '/static/check-circle.png',
      '/static/music.png',
      '/static/default_cover.png',
      '/static/heart-filled.png',
      '/static/icons/icon-192x192.png',
      '/static/icons/icon-512x512.png',
      '/manifest.json',
      '/static/analyze.png',
      '/static/ai.png',
      '/static/download.png',
      '/static/lyrics.png',
      '/static/trash.png',
      '/static/error.png',
      '/static/success.png',
      '/static/info.png'
    ];

    self.addEventListener('install', function(event) {
      event.waitUntil(
        caches.open(CACHE_NAME)
          .then(function(cache) {
            return cache.addAll(urlsToCache);
          })
      );
    });

    self.addEventListener('fetch', function(event) {
      event.respondWith(
        caches.match(event.request)
          .then(function(response) {
            if (response) {
              return response;
            }
            return fetch(event.request);
          })
      );
    });

    self.addEventListener('activate', function(event) {
      const cacheWhitelist = [CACHE_NAME];
      event.waitUntil(
        caches.keys().then(function(cacheNames) {
          return Promise.all(
            cacheNames.map(function(cacheName) {
              if (!cacheWhitelist.includes(cacheName)) {
                return caches.delete(cacheName);
              }
            })
          );
        })
      );
    });
    """
    return sw_js, 200, {'Content-Type': 'application/javascript'}

@app.route('/icons/<path:filename>')
def icons(filename):
    return send_from_directory(os.path.join('static', 'icons'), filename)

@app.route('/search', methods=['GET'])
def search():
    query = request.args.get('q')
    if not query:
        return jsonify({'error': 'Nessuna query fornita'}), 400

    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch5',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(query, download=False)
            if 'entries' in info:
                results = []
                for entry in info['entries'][:5]:
                    if entry is None:
                        continue
                    results.append({
                        'id': entry.get('id'),
                        'title': entry.get('title'),
                        'uploader': entry.get('uploader'),
                        'thumbnail': entry.get('thumbnail'),
                        'webpage_url': entry.get('webpage_url'),
                        'duration': entry.get('duration', 0),
                        'view_count': entry.get('view_count', 0),
                        'upload_date': entry.get('upload_date', '')
                    })
                return jsonify({'results': results})
            else:
                single = {
                    'id': info.get('id'),
                    'title': info.get('title'),
                    'uploader': info.get('uploader'),
                    'thumbnail': info.get('thumbnail'),
                    'webpage_url': info.get('webpage_url'),
                    'duration': info.get('duration', 0),
                    'view_count': info.get('view_count', 0),
                    'upload_date': info.get('upload_date', '')
                }
                return jsonify({'results': [single]})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    data = request.get_json()
    url = data.get('url')
    quality = data.get('quality', 'bestaudio')
    if not url:
        return jsonify({'error': 'Nessun URL fornito'}), 400

    file_id = str(uuid.uuid4())
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(DOWNLOAD_FOLDER, f'{file_id}.%(ext)s'),
        'quiet': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, ext = os.path.splitext(filename)
            mp3_file = f'{base}.mp3'
            if not os.path.exists(mp3_file):
                return jsonify({'error': 'File audio non trovato dopo il download'}), 500

            # Ottimizzazione Audio
            optimized_mp3 = f'{base}_optimized.mp3'
            audio = AudioSegment.from_mp3(mp3_file)
            normalized_audio = audio.normalize()
            normalized_audio.export(optimized_mp3, format="mp3", bitrate="320k")

            if not os.path.exists(optimized_mp3):
                return jsonify({'error': 'File audio ottimizzato non trovato'}), 500

            os.remove(mp3_file)
            os.rename(optimized_mp3, mp3_file)

            track_uuid = file_id
            title = info.get('title')
            artist = info.get('uploader')
            thumbnail = info.get('thumbnail')
            file_url = f'/files/{file_id}.mp3'
            track_data = get_or_create_track(track_uuid, title, artist, thumbnail, file_url)

            return jsonify({
                'title': track_data['title'],
                'artist': track_data['artist'],
                'thumbnail': track_data['thumbnail'],
                'file_url': track_data['file_url']
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/files/<filename>', methods=['GET'])
def serve_file(filename):
    return send_from_directory(DOWNLOAD_FOLDER, filename)

@app.route('/recommendations', methods=['GET'])
def recommendations():
    artist = request.args.get('artist', '')
    if not artist:
        return jsonify({'error': 'Nessun artista specificato'}), 400

    sim_artists = get_music_recommendations(artist)
    if not sim_artists:
        return jsonify([])

    recommended_tracks = []
    ydl_opts = {
        'format': 'bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'default_search': 'ytsearch1',
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        for similar_artist in sim_artists:
            try:
                info = ydl.extract_info(similar_artist, download=False)
                if 'entries' in info and info['entries']:
                    entry = info['entries'][0]
                else:
                    entry = info
                recommended_tracks.append({
                    'title': entry.get('title'),
                    'artist': entry.get('uploader') or similar_artist,
                    'thumbnail': entry.get('thumbnail'),
                    'webpage_url': entry.get('webpage_url')
                })
            except:
                pass

    return jsonify(recommended_tracks)

@app.route('/top_tracks', methods=['GET'])
def top_tracks():
    try:
        tracks = get_top_tracks()
        return jsonify({'top_tracks': tracks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    file_url = data.get('file_url')
    if not file_url:
        return jsonify({'error': 'Nessun file fornito'}), 400

    file_path = os.path.join(DOWNLOAD_FOLDER, os.path.basename(file_url))
    if not os.path.exists(file_path):
        return jsonify({'error': 'File non trovato'}), 404
    try:
        y, sr = librosa.load(file_path)
        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        chroma = librosa.feature.chroma_stft(y=y, sr=sr)
        spectral_centroid = librosa.feature.spectral_centroid(y=y, sr=sr)
        spectral_bandwidth = librosa.feature.spectral_bandwidth(y=y, sr=sr)
        rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr)
        zcr = librosa.feature.zero_crossing_rate(y)
        rmse = librosa.feature.rms(y=y)

        emotions = {
            'Tempo': float(tempo),
            'ChromaMean': float(np.mean(chroma)),
            'ChromaVar': float(np.var(chroma)),
            'SpectralCentroidMean': float(np.mean(spectral_centroid)),
            'SpectralBandwidthMean': float(np.mean(spectral_bandwidth)),
            'RolloffMean': float(np.mean(rolloff)),
            'ZeroCrossingRateMean': float(np.mean(zcr)),
            'RMSMean': float(np.mean(rmse))
        }
        return jsonify({'emotions': emotions})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/describe_analysis', methods=['POST'])
def describe_analysis():
    data = request.get_json()
    analysis_data = data.get('analysisData')
    if not analysis_data:
        return jsonify({'error': 'Nessun dato di analisi inviato'}), 400

    prompt = f"""Ciao! Ho analizzato un brano con librosa e ho ottenuto questi valori:
{analysis_data}

Potresti fornirmi una descrizione dettagliata di questi risultati e spiegare quali emozioni la canzone potrebbe suscitare?
Usa un po' di **grassetto** e *corsivo* dove pensi sia più utile.
"""
    try:
        client = Client()
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            web_search=False
        )
        ai_description = response.choices[0].message.content
        return jsonify({'description': ai_description})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/favorites', methods=['GET', 'POST'])
def api_favorites():
    if request.method == 'GET':
        favs = get_all_favorites()
        return jsonify({'favorites': favs})
    else:
        data = request.get_json()
        file_url = data.get('file_url')
        if not file_url:
            return jsonify({'error': 'Nessun file_url fornito'}), 400

        filename = os.path.basename(file_url)
        track_uuid, _ = os.path.splitext(filename)
        cursor.execute("SELECT id FROM tracks WHERE track_uuid = ?", (track_uuid,))
        row = cursor.fetchone()
        if not row:
            return jsonify({'error': 'Traccia non trovata in DB per i preferiti'}), 404
        track_id = row[0]
        add_favorite(track_id)
        return jsonify({'status': 'ok'})

@app.route('/api/playlists', methods=['GET', 'POST'])
def api_playlists():
    if request.method == 'GET':
        pls = get_all_playlists()
        return jsonify({'playlists': pls})
    else:
        data = request.get_json()
        name = data.get('name')
        if not name:
            return jsonify({'error': 'Nessun nome di playlist fornito'}), 400
        create_playlist(name)
        return jsonify({'status': 'ok'})

@app.route('/api/playlists/add', methods=['POST'])
def api_playlists_add():
    data = request.get_json()
    playlist_name = data.get('playlist_name')
    file_url = data.get('file_url')
    if not playlist_name or not file_url:
        return jsonify({'error': 'Parametri mancanti'}), 400

    cursor.execute("SELECT id FROM playlists WHERE name = ?", (playlist_name,))
    row = cursor.fetchone()
    if not row:
        return jsonify({'error': 'Playlist non trovata'}), 404
    playlist_id = row[0]

    filename = os.path.basename(file_url)
    track_uuid, _ = os.path.splitext(filename)
    cursor.execute("SELECT id FROM tracks WHERE track_uuid = ?", (track_uuid,))
    row2 = cursor.fetchone()
    if not row2:
        return jsonify({'error': 'Traccia non trovata'}), 404
    track_id = row2[0]

    add_track_to_playlist(playlist_id, track_id)
    return jsonify({'status': 'ok'})

@app.route('/api/tracks', methods=['GET'])
def api_tracks():
    cursor.execute("SELECT id, track_uuid, title, artist, thumbnail, file_url FROM tracks")
    rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append({
            'id': row[0],
            'track_uuid': row[1],
            'title': row[2],
            'artist': row[3],
            'thumbnail': row[4],
            'file_url': row[5]
        })
    return jsonify({'tracks': result})

@app.route('/api/tracks/<int:track_id>', methods=['DELETE'])
def api_delete_track(track_id):
    cursor.execute("SELECT track_uuid FROM tracks WHERE id = ?", (track_id,))
    row = cursor.fetchone()
    if not row:
        return jsonify({'error': 'Brano non trovato'}), 404

    track_uuid = row[0]
    cursor.execute("DELETE FROM tracks WHERE id = ?", (track_id,))
    conn.commit()

    cursor.execute("DELETE FROM favorites WHERE track_id = ?", (track_id,))
    conn.commit()

    cursor.execute("DELETE FROM playlist_tracks WHERE track_id = ?", (track_id,))
    conn.commit()

    file_path = os.path.join(DOWNLOAD_FOLDER, f"{track_uuid}.mp3")
    if os.path.exists(file_path):
        os.remove(file_path)

    return jsonify({'status': 'ok'})

@app.route('/api/lyrics', methods=['GET'])
def get_lyrics():
    title = request.args.get('title', '')
    artist = request.args.get('artist', '')

    if not title or not artist:
        return jsonify({'error': 'Parametri mancanti: titolo e artista'}), 400

    try:
        song = genius.search_song(title, artist)
        if song and song.lyrics:
            return jsonify({'lyrics': song.lyrics})
        else:
            return jsonify({'lyrics': 'Testo non trovato'}), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port = 5000, debug=True)
