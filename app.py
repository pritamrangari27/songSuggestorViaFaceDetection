import os, time, base64, json, secrets, threading, random
import numpy as np, cv2
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, render_template, redirect, url_for, jsonify, make_response
from werkzeug.security import generate_password_hash, check_password_hash
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required, get_jwt_identity, set_access_cookies, unset_jwt_cookies
)
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from tensorflow.keras.models import load_model

# ---------------------------
# Config / App init
# ---------------------------
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
USERS_FILE = os.path.join(PROJECT_DIR, "users.json")
MESSAGES_FILE = os.path.join(PROJECT_DIR, "messages.json")
MODEL_PATH = os.path.join(PROJECT_DIR, "emotion_model.h5")

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
model = load_model(MODEL_PATH)
emotion_labels = ['Angry', 'Disgust', 'Fear', 'Happy', 'Sad', 'Surprise', 'Neutral']

# ---------------------------
# Spotify Setup
# ---------------------------
SPOTIFY_CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "dfae3d26fe9b430daebf6bedae6f1320")
SPOTIFY_CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "982424fd187b404d9e604a2b1b4cbd54")
auth_manager = SpotifyClientCredentials(client_id=SPOTIFY_CLIENT_ID, client_secret=SPOTIFY_CLIENT_SECRET)
sp = spotipy.Spotify(auth_manager=auth_manager)

# ---------------------------
# Users storage helpers
# ---------------------------
_users_lock = threading.Lock()
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_users(users: dict):
    with _users_lock:
        tmp = USERS_FILE + ".tmp"
        with open(tmp,"w",encoding="utf-8") as f:
            json.dump(users,f,indent=2)
        os.replace(tmp, USERS_FILE)

if not os.path.exists(USERS_FILE):
    default_users = {
        "pritam":{"password":generate_password_hash("pritam123"),"gender":"","age":""},
        "testuser":{"password":generate_password_hash("test123"),"gender":"","age":""}
    }
    save_users(default_users)

# ---------------------------
# Messages helpers
# ---------------------------
if not os.path.exists(MESSAGES_FILE):
    with open(MESSAGES_FILE,"w",encoding="utf-8") as f:
        json.dump([],f)

def load_messages():
    if not os.path.exists(MESSAGES_FILE) or os.path.getsize(MESSAGES_FILE)==0:
        return []
    try:
        with open(MESSAGES_FILE,"r",encoding="utf-8") as f:
            return json.load(f)
    except:
        return []

def save_messages(messages):
    with open(MESSAGES_FILE,"w",encoding="utf-8") as f:
        json.dump(messages,f,indent=2)

# ---------------------------
# CAPTCHA generator
# ---------------------------
def generate_captcha():
    captcha_text = ''.join(secrets.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") for _ in range(6))
    image = Image.new("RGB",(150,60),color=(0,0,0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default()
    bbox = draw.textbbox((0,0),captcha_text,font=font)
    w,h = bbox[2]-bbox[0], bbox[3]-bbox[1]
    draw.text(((150-w)/2,(60-h)/2),captcha_text,font=font,fill=(255,255,255))
    buffer = BytesIO()
    image.save(buffer,format="PNG")
    buffer.seek(0)
    captcha_image = "data:image/png;base64,"+base64.b64encode(buffer.read()).decode()
    return captcha_text,captcha_image

# ---------------------------
# Mood → Spotify
# ---------------------------
def mood_to_query(mood):
    mapping = {
        "neutral":"chill","angry":"rock","surprise":"party",
        "happy":"upbeat","sad":"melancholy","fear":"intense","disgust":"grunge"
    }
    return mapping.get(mood.lower(),mood.lower())

FALLBACK_TRACK = {"name":"Fallback Chill Song","artist":"Unknown","url":"https://open.spotify.com/embed/track/6rqhFgbbKwnb9MLmUQDhG6"}
_song_cache = {}
CACHE_TTL_SECONDS = 10*60
last_mood = None

def get_songs_spotify(mood):
    """Return 5 unique Spotify tracks (songs only) for a given mood."""
    global _song_cache
    mood_key = (mood or "chill").lower()
    now = time.time()
    
    # Use cache if valid
    cached = _song_cache.get(mood_key)
    if cached and now - cached[0] < CACHE_TTL_SECONDS:
        tracks = cached[1]
    else:
        query = f"{mood_to_query(mood)} bollywood"
        tracks=[]
        try:
            results = sp.search(q=query, type="track", limit=50)
            seen=set()
            for t in results.get("tracks", {}).get("items", []):
                tid = t.get("id")
                if not tid or tid in seen: continue
                tracks.append({
                    "name": t.get("name","Unknown"),
                    "artist": t.get("artists",[{}])[0].get("name","Unknown"),
                    "url": f"https://open.spotify.com/embed/track/{tid}"
                })
                seen.add(tid)
            if len(tracks)<5:
                while len(tracks)<5:
                    tracks.append(FALLBACK_TRACK.copy())
        except Exception as e:
            print("Spotify error:", e)
            tracks = [FALLBACK_TRACK.copy() for _ in range(5)]
        _song_cache[mood_key]=(now,tracks)
    
    if len(tracks) <= 5:
        return tracks
    return random.sample(tracks,5)

# ---------------------------
# Routes
# ---------------------------
@app.route("/")
def root(): return redirect(url_for("login"))

@app.route("/register",methods=["GET","POST"])
def register():
    users = load_users(); error=None; success=None
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        captcha_input=request.form.get("captcha","")
        captcha_code=request.form.get("captcha_code","")
        if not username or not password:
            error="Username/password required"
        elif captcha_input.upper()!=captcha_code.upper():
            error="Captcha incorrect!"
        elif username in users:
            error="Username already exists!"
        else:
            users[username]={"password":generate_password_hash(password),"gender":"","age":""}
            save_users(users)
            success="Registration successful!"
    captcha_code,captcha_image=generate_captcha()
    return render_template("register.html",captcha_image=captcha_image,captcha_code=captcha_code,error=error,success=success)

@app.route("/login",methods=["GET","POST"])
def login():
    users=load_users(); error=None
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        captcha_input=request.form.get("captcha","")
        captcha_code=request.form.get("captcha_code","")
        if captcha_input.upper()!=captcha_code.upper():
            error="Captcha incorrect!"
        elif username in users and check_password_hash(users[username]["password"],password):
            access_token=create_access_token(identity=username)
            resp=make_response(redirect(url_for("dashboard")))
            set_access_cookies(resp,access_token)
            return resp
        else:
            error="Invalid credentials!"
    captcha_code,captcha_image=generate_captcha()
    return render_template("login.html",captcha_image=captcha_image,captcha_code=captcha_code,error=error)

@app.route("/logout")
def logout():
    resp=make_response(redirect(url_for("login")))
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

@app.route("/update_profile",methods=["POST"])
@jwt_required()
def update_profile():
    username=get_jwt_identity()
    users=load_users()
    users[username]["gender"]=request.form.get("gender","").strip()
    users[username]["age"]=request.form.get("age","").strip()
    users[username]["email"]=request.form.get("email","").strip()
    save_users(users)
    return redirect(url_for("dashboard"))

@app.route("/predict",methods=["POST"])
@jwt_required()
def predict():
    global last_mood
    body=request.get_json(silent=True)
    if not body or "image" not in body:
        return jsonify({"error":"No image","emotion":"None"}),400
    try:
        data_url=body["image"]
        img_data=base64.b64decode(data_url.split(",",1)[1])
        arr = np.frombuffer(img_data,np.uint8)
        frame = cv2.imdecode(arr,cv2.IMREAD_COLOR)
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        faces=cv2.CascadeClassifier(cv2.data.haarcascades+"haarcascade_frontalface_default.xml").detectMultiScale(gray,1.3,5)
        if len(faces)==0: return jsonify({"emotion":"No face detected"})
        (x,y,w,h)=faces[0]; face=gray[y:y+h,x:x+w]
        face_resized=cv2.resize(face,(48,48)).astype("float32")/255.0
        face_resized=np.expand_dims(face_resized,axis=(0,-1))
        emotion=emotion_labels[int(np.argmax(model.predict(face_resized)))]
        last_mood=emotion
        return jsonify({"emotion":emotion})
    except Exception as e:
        return jsonify({"error":str(e),"emotion":"None"}),500

@app.route("/songs",methods=["POST"])
def songs():
    global last_mood
    body=request.get_json(silent=True)
    mood=last_mood
    if body and "mood" in body: mood=body["mood"]
    safe_mood=(mood or "chill").strip()
    if safe_mood.lower() in ("no face detected","not detected","none",""): safe_mood="chill"
    tracks=get_songs_spotify(safe_mood)
    return jsonify({"mood":safe_mood,"songs":tracks})

# ---------------------------
# Chat routes
# ---------------------------
@app.route("/chat/send", methods=["POST"])
@jwt_required()  # require login
def chat_send():
    body = request.get_json()
    if not body or "to" not in body or "text" not in body:
        return jsonify({"error": "Missing fields"}), 400
    
    username = get_jwt_identity()  # guaranteed to be logged in
    msg = {
        "from": username,
        "to": body["to"],
        "text": body["text"],
        "ts": int(time.time())
    }
    msgs = load_messages()
    msgs.append(msg)
    save_messages(msgs)
    return jsonify({"status": "ok"})


@app.route("/chat/fetch", methods=["GET"])
@jwt_required()  # require login
def chat_fetch():
    chat_with = request.args.get("user")
    if not chat_with:
        return jsonify({"error": "Missing user"}), 400
    
    username = get_jwt_identity()  # guaranteed to be logged in

    msgs = load_messages()
    convo = [m for m in msgs if (m["from"] == username and m["to"] == chat_with) or
                             (m["from"] == chat_with and m["to"] == username)]
    convo.sort(key=lambda x: x["ts"])
    return jsonify(convo)

@app.route("/users/list", methods=["GET"])
@jwt_required()  # require login
def users_list():
    users = load_users()
    username = get_jwt_identity()
    others = [u for u in users if u != username]
    return jsonify(others)



# ---------------------------
# Run app
# ---------------------------
if __name__=="__main__":
    app.run(debug=True,use_reloader=False)
