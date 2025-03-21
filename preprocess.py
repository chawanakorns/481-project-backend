import sqlite3
import re
import pickle
import nltk
from nltk import bigrams, word_tokenize
from collections import Counter

# Ensure NLTK data is downloaded
nltk.download('punkt', quiet=True)

# Database connection
FOOD_DB = "../481-project-database/food.db"  # Adjust path as needed
OUTPUT_PICKLE = "../481-project-database/preprocessed_recipes.pkl"  # Output file for recipes
WORD_FREQ_FILE = "../481-project-database/word_freq.pkl"  # Output file for unigram frequencies
BIGRAM_FREQ_FILE = "../481-project-database/bigram_freq.pkl"  # Output file for bigram frequencies


def get_db_connection():
    conn = sqlite3.connect(FOOD_DB, timeout=10)
    conn.row_factory = sqlite3.Row  # Returns rows as dictionaries
    return conn


# Function to parse 'c("item1", "item2", ...)' format into a list
def parse_array_string(array_string):
    if not array_string or not isinstance(array_string, str):
        return []
    if array_string.startswith('c(') and array_string.endswith(')'):
        content = array_string[2:-1]
        items = re.findall(r'"([^"]*)"(?:,|$)', content)
        return [item.strip() for item in items if item.strip()]
    return [array_string]  # Treat non-c() strings as a single-item list


# Function to parse ISO 8601 duration (e.g., "PT24H45M") into minutes
def parse_duration(duration):
    if not duration or not isinstance(duration, str) or not duration.startswith('PT'):
        return duration  # Return as-is if not a valid duration
    hours = 0
    minutes = 0
    match_hours = re.search(r'(\d+)H', duration)
    match_minutes = re.search(r'(\d+)M', duration)
    if match_hours:
        hours = int(match_hours.group(1))
    if match_minutes:
        minutes = int(match_minutes.group(1))
    return hours * 60 + minutes  # Convert to total minutes


# Function to preprocess a single recipe row
def preprocess_recipe(row):
    preprocessed = dict(row)

    # Columns that might need parsing as arrays
    array_columns = [
        "RecipeInstructions",
        "RecipeIngredientQuantities",
        "RecipeIngredientParts",
        "Keywords",
        "Images"
    ]

    # Parse array-like columns
    for col in array_columns:
        if col in preprocessed and preprocessed[col]:
            preprocessed[col] = parse_array_string(preprocessed[col])

    # Convert numeric columns to proper types
    numeric_columns = [
        "Calories", "FatContent", "SaturatedFatContent", "CholesterolContent",
        "SodiumContent", "CarbohydrateContent", "FiberContent", "SugarContent",
        "ProteinContent", "AggregatedRating", "ReviewCount"
    ]
    for col in numeric_columns:
        if preprocessed[col] is not None:
            try:
                preprocessed[col] = float(preprocessed[col]) if "." in str(preprocessed[col]) else int(
                    preprocessed[col])
            except (ValueError, TypeError):
                preprocessed[col] = None

    # Handle time fields (convert ISO 8601 durations to minutes)
    time_columns = ["CookTime", "PrepTime", "TotalTime"]
    for col in time_columns:
        if preprocessed[col] and isinstance(preprocessed[col], str):
            preprocessed[col] = parse_duration(preprocessed[col])

    # Handle Images field for image_url and all_image_urls
    if preprocessed['Images']:
        # Ensure Images is always a list, even for single URLs
        if isinstance(preprocessed['Images'], str):
            preprocessed['Images'] = [preprocessed['Images']]
        preprocessed['image_url'] = preprocessed['Images'][0] if preprocessed['Images'] else ''
        preprocessed['all_image_urls'] = preprocessed['Images']
    else:
        preprocessed['image_url'] = ''
        preprocessed['all_image_urls'] = []

    return preprocessed


# Function to generate unigram and bigram frequencies
def generate_frequencies(preprocessed_recipes):
    print("Building recipe-specific corpus for frequency analysis...")
    corpus_words = []
    corpus_bigrams = []

    for recipe in preprocessed_recipes.values():
        name = recipe.get('Name', '').lower()
        keywords = ' '.join(recipe.get('Keywords', [])) if recipe.get('Keywords') else ''
        # Tokenize the combined name and keywords
        tokens = word_tokenize(name + ' ' + keywords)
        corpus_words.extend(tokens)
        # Generate bigrams from tokens
        recipe_bigrams = list(bigrams(tokens))
        corpus_bigrams.extend(recipe_bigrams)

    # Calculate frequencies
    word_freq = Counter(corpus_words)
    bigram_freq = Counter(corpus_bigrams)

    return word_freq, bigram_freq


# Main preprocessing function
def preprocess_recipes():
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Fetch and preprocess recipes
        cursor.execute("SELECT * FROM recipes")
        recipes = cursor.fetchall()
        preprocessed_recipes = {row["RecipeId"]: preprocess_recipe(row) for row in recipes}

        # Generate unigram and bigram frequencies
        word_freq, bigram_freq = generate_frequencies(preprocessed_recipes)

        # Save preprocessed recipes to pickle file
        with open(OUTPUT_PICKLE, "wb") as f:
            pickle.dump(preprocessed_recipes, f)
        print(f"Preprocessed {len(preprocessed_recipes)} recipes and saved to {OUTPUT_PICKLE}")

        # Save word frequencies
        with open(WORD_FREQ_FILE, 'wb') as f:
            pickle.dump(word_freq, f)
        print(f"Saved unigram frequencies to {WORD_FREQ_FILE}")

        # Save bigram frequencies
        with open(BIGRAM_FREQ_FILE, 'wb') as f:
            pickle.dump(bigram_freq, f)
        print(f"Saved bigram frequencies to {BIGRAM_FREQ_FILE}")

    finally:
        conn.close()


if __name__ == "__main__":
    preprocess_recipes()