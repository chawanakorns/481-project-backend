import os
import pickle
import sqlite3
from Levenshtein import distance as levenshtein_distance

BASE_DIR = os.path.abspath("../481-project-database")
USERS_DB = os.path.join(BASE_DIR, 'users.db')
FOOD_DB = os.path.join(BASE_DIR, 'food.db')
PREPROCESSED_RECIPES_FILE = "../481-project-database/preprocessed_recipes.pkl"
WORD_FREQ_FILE = "../481-project-database/word_freq.pkl"
BIGRAM_FREQ_FILE = "../481-project-database/bigram_freq.pkl"

# Load preprocessed data
with open(PREPROCESSED_RECIPES_FILE, "rb") as f:
    PREPROCESSED_RECIPES = pickle.load(f)

with open(WORD_FREQ_FILE, 'rb') as f:
    word_freq = pickle.load(f)

with open(BIGRAM_FREQ_FILE, 'rb') as f:
    bigram_freq = pickle.load(f)

total_words = sum(word_freq.values())
total_bigrams = sum(bigram_freq.values())

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
        dist = levenshtein_distance(misspelled_bigram, bigram)
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