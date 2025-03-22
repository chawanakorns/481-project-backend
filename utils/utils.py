# utils/utils.py
import os
import pickle
import sqlite3
from functools import wraps
from flask import request, jsonify
import jwt
from Levenshtein import distance as levenshtein_distance
import lightgbm as lgb

# Define the base directory relative to utils.py
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "481-project-database"))

USERS_DB = os.path.join(BASE_DIR, 'users.db')
FOOD_DB = os.path.join(BASE_DIR, 'food.db')
PREPROCESSED_RECIPES_FILE = os.path.join(BASE_DIR, 'preprocessed_recipes.pkl')
WORD_FREQ_FILE = os.path.join(BASE_DIR, 'word_freq.pkl')
BIGRAM_FREQ_FILE = os.path.join(BASE_DIR, 'bigram_freq.pkl')
RANKING_MODEL_PATH = os.path.join(BASE_DIR, 'ranking_model.txt')

SECRET_KEY = ""

# Load preprocessed data with error handling
try:
    with open(PREPROCESSED_RECIPES_FILE, "rb") as f:
        PREPROCESSED_RECIPES = pickle.load(f)
except FileNotFoundError as e:
    print(f"Error: Could not find preprocessed_recipes.pkl at {PREPROCESSED_RECIPES_FILE}. Please ensure the file exists.")
    raise e

try:
    with open(WORD_FREQ_FILE, 'rb') as f:
        word_freq = pickle.load(f)
except FileNotFoundError as e:
    print(f"Error: Could not find word_freq.pkl at {WORD_FREQ_FILE}. Please ensure the file exists.")
    raise e

try:
    with open(BIGRAM_FREQ_FILE, 'rb') as f:
        bigram_freq = pickle.load(f)
except FileNotFoundError as e:
    print(f"Error: Could not find bigram_freq.pkl at {BIGRAM_FREQ_FILE}. Please ensure the file exists.")
    raise e

# Load the LightGBM ranking model with fallback
ranking_model = None
try:
    if os.path.exists(RANKING_MODEL_PATH):
        ranking_model = lgb.Booster(model_file=RANKING_MODEL_PATH)
        print(f"Successfully loaded ranking model from {RANKING_MODEL_PATH}")
    else:
        print(f"Warning: Ranking model file not found at {RANKING_MODEL_PATH}. Run train_ranking_model.py to generate the model.")
except Exception as e:
    print(f"Error: Failed to load ranking model from {RANKING_MODEL_PATH}: {str(e)}")

total_words = sum(word_freq.values())
total_bigrams = sum(bigram_freq.values())

# Define a phrase map for common recipe phrases
PHRASE_MAP = {
    "chicken beads": "chicken breasts",
    "chiken beads": "chicken breasts",
    "chiken breasts": "chicken breasts",
    "chicken brests": "chicken breasts",
    "oliv oil": "olive oil",
    "garlic power": "garlic powder",
    "tamoto": "tomato",
    "brown suger": "brown sugar",
    "wheat flower": "wheat flour",
    "soi sauce": "soy sauce",
    "backed chicken": "baked chicken",
}

def get_user_db_connection():
    conn = sqlite3.connect(USERS_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def get_food_db_connection():
    conn = sqlite3.connect(FOOD_DB, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn

def clean_image_url(url):
    if url and isinstance(url, str):
        return url.strip('"')
    return url

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({"message": "Token is missing"}), 401
        try:
            if token.startswith("Bearer "):
                token = token.split(" ")[1]
            jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
        except jwt.ExpiredSignatureError:
            return jsonify({"message": "Token has expired"}), 401
        except jwt.InvalidTokenError:
            return jsonify({"message": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

def generate_candidates(misspelled_word, max_distance=2):
    candidates = []
    misspelled_word = misspelled_word.lower()
    for word in word_freq.keys():
        dist = levenshtein_distance(misspelled_word, word)
        if dist <= max_distance:
            candidates.append((word, dist))
    return candidates

def generate_bigram_candidates(misspelled_bigram, max_distance=3):
    candidates = []
    misspelled_bigram = misspelled_bigram.lower()
    for bigram in bigram_freq.keys():
        bigram_str = ' '.join(bigram)
        dist = levenshtein_distance(misspelled_bigram, bigram_str)
        if dist <= max_distance:
            candidates.append((bigram, dist))
    return candidates

def calculate_p_w(word):
    return word_freq.get(word, 1) / total_words

def calculate_p_bigram(bigram):
    return bigram_freq.get(bigram, 1) / total_bigrams

def calculate_p_x_given_w(misspelled, candidate, edit_dist):
    if misspelled == candidate:
        return 1.0
    elif edit_dist == 1:
        return 0.8
    elif edit_dist == 2:
        return 0.2
    elif edit_dist == 3:
        return 0.05
    return 0.0

def generate_bigrams(words):
    return [' '.join(words[i:i+2]) for i in range(len(words) - 1)]

def parse_image_urls(image_string):
    import re
    pattern = r'"(https?://[^"]+)"'
    matches = re.findall(pattern, image_string)
    return matches if matches else []