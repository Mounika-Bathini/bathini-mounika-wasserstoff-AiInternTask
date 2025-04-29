import redis
import uuid
from flask import Flask, request, jsonify
from flask_ngrok import run_with_ngrok
from collections import deque
import fakeredis
import re
import nest_asyncio
import openai  

nest_asyncio.apply()  # Allows Flask+asyncio in Jupyter

# === CONFIG ===
openai.api_key = "sk-<USE_YOUR_KEY>"  # Replace with your OpenAI key
USE_FAKE_REDIS = True  # Set False if using real Redis locally

# === CACHE ===
cache = fakeredis.FakeStrictRedis() if USE_FAKE_REDIS else redis.Redis()

# === MODERATION ===
def is_clean(text):
    return not re.search(r"(damn|hell|shit|fuck|badword)", text, re.IGNORECASE)

# === LINKED LIST PER SESSION ===
sessions = {}
global_counter = {}

class GameSession:
    def __init__(self, seed):
        self.words = deque([seed])
        self.score = 0

    def add_word(self, word):
        self.words.append(word)
        self.score += 1

    def exists(self, word):
        return word in self.words

    def history(self):
        return list(self.words)

# === FLASK SETUP ===
app = Flask(__name__)

# === Initialize ngrok with Flask ===
run_with_ngrok(app)  

# === MOCK LLM CALL (can replace with real openai.ChatCompletion) ===
def ask_ai_if_beats(guess, current):
    key = f"{guess}:{current}"
    cached = cache.get(key)
    if cached:
        return cached.decode()
    # Prompt
    prompt = f"Does '{guess}' beat '{current}' in a creative sense?"
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=10,
    )
    verdict = response.choices[0].message.content.strip()
    cache.set(key, verdict)
    return verdict

# === ROUTES ===
@app.route("/v1/guess", methods=["POST"])
def guess():
    data = request.get_json()
    session_id = data.get("session_id") or str(uuid.uuid4())
    word = data.get("word", "").strip().lower()

    if not is_clean(word):
        return jsonify({"error": "Inappropriate word"}), 400

    if session_id not in sessions:
        sessions[session_id] = GameSession("rock")

    session = sessions[session_id]

    if session.exists(word):
        return jsonify({"game_over": True, "message": "Duplicate guess!"})

    current = session.words[-1]
    verdict = ask_ai_if_beats(word, current)

    if "yes" in verdict.lower():
        session.add_word(word)
        global_counter[word] = global_counter.get(word, 0) + 1
        return jsonify({
            "game_over": False,
            "message": f"✅ Nice! '{word}' beats '{current}'. {word} has been guessed {global_counter[word]} times.",
            "score": session.score,
            "session_id": session_id
        })
    else:
        return jsonify({"game_over": True, "message": f"'{word}' does not beat '{current}'."})

@app.route("/v1/history/<session_id>")
def history(session_id):
    session = sessions.get(session_id)
    if not session:
        return jsonify({"error": "Session not found"}), 404
    return jsonify({"history": session.history(), "score": session.score})

@app.route("/")
def home():
    return "Game server is running. POST to /v1/guess with JSON: {\"session_id\":..., \"word\":...}"

# === RUN FLASK APP ===
app.run()  # This will run your Flask app
