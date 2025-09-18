# Mood Detection & Song Suggestor Dashboard

A Flask web application that detects user mood from images and suggests songs using Spotify. Includes user authentication, chat, profile management, and Google Drive integration for image uploads.
U can check it at https://songsuggestor.site/

## Features
- Mood detection from webcam or uploaded images
- Song suggestions based on detected mood (Spotify API)
- User authentication (login/register)
- Profile and settings management
- Chat with other users
- Responsive dashboard and modals
- Google Drive integration for image uploads

## Technologies Used
- Python (Flask, OpenCV, scikit-learn, skimage)
- HTML, CSS, JavaScript
- Spotipy (Spotify API)
- Google Drive API (OAuth)

## Setup Instructions

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/mood-song-dashboard.git
   cd mood-song-dashboard
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   - Create a `.env` file or set variables in your environment:
     - `SECRET_KEY` (Flask secret)
     - `SPOTIPY_CLIENT_ID`, `SPOTIPY_CLIENT_SECRET`, `SPOTIPY_REDIRECT_URI` (Spotify API)
     - Google Drive OAuth credentials (see Google API docs)

4. **Run the app locally**
   ```bash
   python app.py
   ```
   The app will be available at `http://localhost:5000`


## Folder Structure
```
app.py
requirements.txt
messages.json
train_model.py
static/
    css/
    js/
templates/
    dashboard.html
    login.html
    register.html
test/
    angry/
    ...
train/
    angry/
    ...
```
