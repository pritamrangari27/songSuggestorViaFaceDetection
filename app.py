import os, time, base64, json, secrets, random, datetime
import numpy as np
import cv2
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, render_template, redirect, url_for, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity,
    set_access_cookies, unset_jwt_cookies
)
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from joblib import load
from skimage.feature import hog

# ---------------------------
# App Config
# ---------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(PROJECT_DIR, "users.json")
MESSAGES_FILE = os.path.join(PROJECT_DIR, "messages.json")
MODEL_PATH = os.path.join(PROJECT_DIR, "svm_emotion_model.joblib")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", secrets.token_hex(32))
app.config["JWT_SECRET_KEY"] = os.environ.get("JWT_SECRET_KEY", secrets.token_hex(32))
app.config["JWT_TOKEN_LOCATION"] = ["cookies"]
app.config["JWT_COOKIE_SECURE"] = False
app.config["JWT_ACCESS_COOKIE_PATH"] = "/"
app.config["JWT_COOKIE_SAMESITE"] = "Lax"
app.config["JWT_COOKIE_CSRF_PROTECT"] = False

jwt = JWTManager(app)

# ---------------------------
# Load ML model
# ---------------------------
if not os.path.exists(MODEL_PATH):
    raise FileNotFoundError(f"Model file not found at {MODEL_PATH}.")
model = load(MODEL_PATH)

train_dir = os.path.join(PROJECT_DIR, "train")
emotion_labels = sorted(os.listdir(train_dir)) if os.path.isdir(train_dir) else []

# ---------------------------
# Spotify Setup
# ---------------------------
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "Your Credentials")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "Your Credentials")
auth_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
sp = spotipy.Spotify(auth_manager=auth_manager)

# ---------------------------
# Users Helpers
# ---------------------------
def load_users():
    if not os.path.exists(USERS_FILE): return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(users: dict):
    tmp = USERS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)
    os.replace(tmp, USERS_FILE)

if not os.path.exists(USERS_FILE):
    default_users = {
        "Pritam": {"password": generate_password_hash("1234"), "gender": "", "age": "", "email": ""},
        
    }
    save_users(default_users)

# ---------------------------
# Messages Helpers
# ---------------------------
if not os.path.exists(MESSAGES_FILE):
    with open(MESSAGES_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

def load_messages():
    try:
        with open(MESSAGES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_messages(messages):
    tmp = MESSAGES_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2)
    os.replace(tmp, MESSAGES_FILE)

# ---------------------------
# Spotify Songs Fetch
# ---------------------------
FALLBACK_TRACK = {"name": "Fallback Chill Song", "artist": "Unknown",
                  "url": "https://open.spotify.com/embed/track/6rqhFgbbKwnb9MLmUQDhG6"}

def mood_to_query(mood):
    mapping = {
        "neutral": "chill",
        "angry": "rock",
        "surprise": "party",
        "happy": "upbeat",
        "sad": "melancholy",
        "fear": "intense",
        "disgust": "grunge"
    }
    return mapping.get((mood or "").lower(), (mood or "").lower() or "chill")

last_mood = None

def get_songs_spotify(mood):
    query = f"{mood_to_query(mood)} bollywood"
    tracks = []
    try:
        results = sp.search(q=query, type="track", limit=50)
        seen = set()
        for t in results.get("tracks", {}).get("items", []):
            tid = t.get("id")
            if not tid or tid in seen: continue
            tracks.append({"name": t.get("name","Unknown"),
                           "artist": t.get("artists",[{}])[0].get("name","Unknown"),
                           "url": f"https://open.spotify.com/embed/track/{tid}"})
            seen.add(tid)
        while len(tracks) < 5: tracks.append(FALLBACK_TRACK.copy())
    except Exception as e:
        print("Spotify error:", e)
        tracks = [FALLBACK_TRACK.copy() for _ in range(5)]
    return random.sample(tracks, 5) if len(tracks) > 5 else tracks

# ---------------------------
# Routes
# ---------------------------
@app.route("/")
def root(): return redirect(url_for("login"))

@app.route("/register", methods=["GET","POST"])
def register():
    users = load_users()
    error = success = None
    if request.method == "POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        email = request.form.get("email","").strip()
        gender = request.form.get("gender","").strip()
        age = request.form.get("age","").strip()
        if not username or not password: error="Username/password required"
        elif username in users: error="Username already exists!"
        else:
            users[username] = {"password": generate_password_hash(password),
                               "email": email, "gender": gender, "age": age}
            save_users(users)
            success="Registration successful!"
    return render_template("register.html", error=error, success=success)

@app.route("/login", methods=["GET","POST"])
def login():
    users = load_users()
    error=None
    if request.method=="POST":
        username = request.form.get("username","").strip()
        password = request.form.get("password","")
        if username in users and check_password_hash(users[username]["password"], password):
            access_token = create_access_token(identity=username)
            resp = make_response(redirect(url_for("dashboard")))
            set_access_cookies(resp, access_token)
            return resp
        else: error="Invalid credentials!"
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    resp = make_response(redirect(url_for("login")))
    unset_jwt_cookies(resp)
    return resp

@app.route("/dashboard")
@jwt_required()
def dashboard():
    username = get_jwt_identity()
    users = load_users()
    user_info = users.get(username,{})
    return render_template("dashboard.html",
                           username=username,
                           email=user_info.get("email","None"),
                           gender=user_info.get("gender","None"),
                           age=user_info.get("age","None"))

@app.route("/get_user_info")
@jwt_required()
def get_user_info():
    username = get_jwt_identity()
    users = load_users()
    return jsonify(users.get(username, {}))

@app.route("/update_profile", methods=["POST"])
@jwt_required()
def update_profile():
    username = get_jwt_identity()
    users = load_users()
    if username not in users: return jsonify({"error":"User not found"}),404
    payload = request.get_json(silent=True)
    users[username]["gender"] = payload.get("gender","").strip() if payload else request.form.get("gender","").strip()
    users[username]["age"] = payload.get("age","").strip() if payload else request.form.get("age","").strip()
    users[username]["email"] = payload.get("email","").strip() if payload else request.form.get("email","").strip()
    save_users(users)
    return jsonify({"status":"ok", "user":users[username]}) if payload else redirect(url_for("dashboard"))

@app.route("/predict", methods=["POST"])
@jwt_required()
def predict():
    global last_mood
    body = request.get_json(silent=True)
    if not body or "image" not in body:
        return jsonify({"error": "No image", "emotion": "None"}), 400
    try:
        # Decode base64 image
        data_url = body["image"]
        img_data = base64.b64decode(data_url.split(",", 1)[1]) if "," in data_url else base64.b64decode(data_url)
        arr = np.frombuffer(img_data, np.uint8)
        frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if frame is None:
            return jsonify({"error": "Failed to decode image", "emotion": "None"}), 400
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5)
        if len(faces) == 0:
            last_mood = None
            return jsonify({"emotion": "No face detected"})
        # Use largest face
        x, y, w, h = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)[0]
        face_img = gray[y:y+h, x:x+w]
        face_img = cv2.resize(face_img, (48, 48))
        hog_features = hog(face_img, pixels_per_cell=(8, 8), cells_per_block=(2, 2))
        pred_raw = model.predict([hog_features])[0]
        # Map prediction to label
        if not emotion_labels or int(pred_raw) >= len(emotion_labels):
            print("Error: emotion_labels misalignment or empty.")
            return jsonify({"error": "Invalid model output", "emotion": "None"}), 500
        emotion = emotion_labels[int(pred_raw)]
        last_mood = emotion
        # Save the full image locally
        save_dir = os.path.join(PROJECT_DIR, "captured_faces")
        os.makedirs(save_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        local_path = os.path.join(save_dir, f"full_image_{timestamp}.jpg")
        cv2.imwrite(local_path, frame)
        return jsonify({"emotion": emotion})
    except Exception as e:
        print("Predict error:", e)
        return jsonify({"error": str(e), "emotion": "None"}), 500

@app.route("/songs", methods=["POST"])
@jwt_required()
def songs():
    global last_mood
    body = request.get_json(silent=True)
    mood = last_mood
    if body and "mood" in body: mood=body["mood"]
    safe_mood = (mood or "chill").strip()
    if safe_mood.lower() in ("no face detected","none",""): safe_mood="chill"
    tracks = get_songs_spotify(safe_mood)
    return jsonify({"mood":safe_mood,"songs":tracks})

# ---------------------------
# Chat
# ---------------------------
@app.route("/chat/send", methods=["POST"])
@jwt_required()
def chat_send():
    body = request.get_json(silent=True)
    if not body or "to" not in body or "text" not in body:
        return jsonify({"error":"Missing fields"}),400
    username=get_jwt_identity()
    ts=int(time.time())
    msg={"from":username,"to":body["to"],"text":body["text"],"ts":ts}
    msgs=load_messages()
    msgs.append(msg)
    save_messages(msgs)
    return jsonify({"status":"ok","message":msg})

@app.route("/chat/fetch", methods=["GET"])
@jwt_required()
def chat_fetch():
    chat_with=request.args.get("user")
    if not chat_with: return jsonify({"error":"Missing user"}),400
    username=get_jwt_identity()
    msgs=load_messages()
    convo=[m for m in msgs if (m.get("from")==username and m.get("to")==chat_with) or
                         (m.get("from")==chat_with and m.get("to")==username)]
    convo.sort(key=lambda x:x.get("ts",0))
    return jsonify(convo)

@app.route("/chat/updates", methods=["GET"])
@jwt_required()
def chat_updates():
    chat_with=request.args.get("user")
    since=request.args.get("since",type=int,default=0)
    if not chat_with: return jsonify({"error":"Missing user"}),400
    username=get_jwt_identity()
    msgs=load_messages()
    new=[m for m in msgs if m.get("ts",0)>since and ((m.get("from")==username and m.get("to")==chat_with) or
                                                   (m.get("from")==chat_with and m.get("to")==username))]
    new.sort(key=lambda x:x.get("ts",0))
    return jsonify(new)

@app.route("/users/list", methods=["GET"])
@jwt_required()
def users_list():
    users=load_users()
    username=get_jwt_identity()
    return jsonify([u for u in users if u!=username])

# ---------------------------
# Run App
# ---------------------------
if __name__=="__main__":
    app.run(debug=True,use_reloader=False)
