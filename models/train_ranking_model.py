# train_ranking_model.py
import os
import re
import sqlite3
import pickle
import pandas as pd
import numpy as np
import lightgbm as lgb
from sklearn.model_selection import train_test_split
import random
from utils.utils import PREPROCESSED_RECIPES, get_food_db_connection

# Paths for saving the model
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "481-project-database"))
MODEL_PATH = os.path.join(BASE_DIR, 'ranking_model.txt')

# Maximum number of recipes per group (to stay under LightGBM's limit)
MAX_RECIPES_PER_GROUP = 5000  # Set to a value less than 10,000

def load_data():
    # Load preprocessed recipes
    recipes = PREPROCESSED_RECIPES

    # Load user bookmarks and ratings
    conn = get_food_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.UserId, b.RecipeId, b.Rating, f.FolderId
        FROM bookmarks b
        JOIN folders f ON b.FolderId = f.FolderId
    """)
    bookmarks = cursor.fetchall()
    conn.close()

    # Convert to DataFrame
    bookmark_data = pd.DataFrame([dict(b) for b in bookmarks])
    return recipes, bookmark_data

def extract_features(user_id, folder_id, recipe, user_keywords, avg_user_rating):
    # Extract keywords from the recipe
    recipe_keywords = set(
        kw.strip('"').lower() for kw in recipe.get('Keywords', [])
        if kw and not re.match(r'^\d+$', kw.strip('"'))
    )

    # Feature 1: Keyword overlap
    keyword_overlap = len(recipe_keywords.intersection(user_keywords))

    # Feature 2: Rating similarity
    recipe_rating = recipe.get('AggregatedRating', 0) or 0
    rating_diff = abs(avg_user_rating - recipe_rating)

    # Feature 3: Category match (binary: 1 if matches user's preferred category, 0 otherwise)
    # For simplicity, assume user's preferred category is the most common in their bookmarks
    category_match = 0  # Placeholder; we'll compute this in the training loop

    # Feature 4: Recipe popularity (based on ReviewCount)
    review_count = recipe.get('ReviewCount', 0) or 0

    # Feature 5: Cooking time (TotalTime in minutes)
    total_time = recipe.get('TotalTime', 0) or 0
    if isinstance(total_time, str):
        total_time = 0  # Handle cases where TotalTime wasn't parsed correctly

    return [keyword_overlap, rating_diff, category_match, review_count, total_time]

def train_ranking_model():
    print("Training LightGBM ranking model...")

    # Load data
    recipes, bookmark_data = load_data()

    # Determine user preferences (e.g., preferred categories)
    user_category_prefs = bookmark_data.merge(
        pd.DataFrame(list(recipes.values())), on='RecipeId'
    ).groupby('UserId')['RecipeCategory'].agg(lambda x: x.mode()[0]).to_dict()

    # Convert recipes to a list for sampling
    all_recipe_ids = list(recipes.keys())
    print(f"Total number of recipes: {len(all_recipe_ids)}")

    # Prepare training data
    X = []
    y = []
    groups = []  # For ranking: group by user_id and folder_id
    group_counts = []

    for (user_id, folder_id), group in bookmark_data.groupby(['UserId', 'FolderId']):
        print(f"Processing user {user_id}, folder {folder_id}...")

        # Get user-specific data
        user_bookmarks = group['RecipeId'].tolist()
        user_ratings = group['Rating'].tolist()
        avg_user_rating = np.mean(user_ratings) if user_ratings else 0

        # Get user keywords from bookmarked recipes
        user_keywords = set()
        for recipe_id in user_bookmarks:
            recipe = recipes.get(recipe_id, {})
            keywords = [
                kw.strip('"').lower() for kw in recipe.get('Keywords', [])
                if kw and not re.match(r'^\d+$', kw.strip('"'))
            ]
            user_keywords.update(keywords)

        # Sample recipes for this group
        # Ensure we include all bookmarked recipes
        bookmarked_recipe_ids = set(user_bookmarks)
        non_bookmarked_recipe_ids = [rid for rid in all_recipe_ids if rid not in bookmarked_recipe_ids]

        # Sample non-bookmarked recipes to keep total under MAX_RECIPES_PER_GROUP
        num_non_bookmarked = max(0, MAX_RECIPES_PER_GROUP - len(bookmarked_recipe_ids))
        sampled_non_bookmarked = random.sample(
            non_bookmarked_recipe_ids,
            min(num_non_bookmarked, len(non_bookmarked_recipe_ids))
        )

        # Combine bookmarked and sampled non-bookmarked recipes
        sampled_recipe_ids = list(bookmarked_recipe_ids) + sampled_non_bookmarked
        print(f"User {user_id}, Folder {folder_id}: {len(sampled_recipe_ids)} recipes after sampling")

        if len(sampled_recipe_ids) > MAX_RECIPES_PER_GROUP:
            print(f"Warning: Group size {len(sampled_recipe_ids)} exceeds limit {MAX_RECIPES_PER_GROUP}. Truncating...")
            sampled_recipe_ids = sampled_recipe_ids[:MAX_RECIPES_PER_GROUP]

        # Generate features for the sampled recipes
        group_features = []
        group_labels = []
        for recipe_id in sampled_recipe_ids:
            recipe = recipes.get(recipe_id, {})
            features = extract_features(user_id, folder_id, recipe, user_keywords, avg_user_rating)
            # Add category match feature
            user_preferred_category = user_category_prefs.get(user_id, None)
            features[2] = 1 if recipe.get('RecipeCategory') == user_preferred_category else 0

            group_features.append(features)
            # Label: 1 if bookmarked, 0 otherwise
            label = 1 if recipe_id in bookmarked_recipe_ids else 0
            group_labels.append(label)

        X.extend(group_features)
        y.extend(group_labels)
        group_counts.append(len(group_features))
        groups.extend([f"{user_id}_{folder_id}"] * len(group_features))

    # Convert to numpy arrays
    X = np.array(X)
    y = np.array(y)

    # Split data (for validation)
    train_indices, val_indices = train_test_split(
        range(len(group_counts)), test_size=0.2, random_state=42
    )

    # Prepare training and validation data
    train_X = []
    train_y = []
    train_group = []
    val_X = []
    val_y = []
    val_group = []

    current_idx = 0
    for i, count in enumerate(group_counts):
        group_data = X[current_idx:current_idx + count]
        group_labels = y[current_idx:current_idx + count]
        current_idx += count

        if i in train_indices:
            train_X.extend(group_data)
            train_y.extend(group_labels)
            train_group.append(count)
        else:
            val_X.extend(group_data)
            val_y.extend(group_labels)
            val_group.append(count)

    train_X = np.array(train_X)
    train_y = np.array(train_y)
    val_X = np.array(val_X)
    val_y = np.array(val_y)

    # Create LightGBM dataset
    train_data = lgb.Dataset(train_X, label=train_y, group=train_group)
    val_data = lgb.Dataset(val_X, label=val_y, group=val_group, reference=train_data)

    # Define LightGBM parameters for ranking
    params = {
        'objective': 'lambdarank',
        'metric': 'ndcg',
        'ndcg_at': [5, 10],
        'learning_rate': 0.05,
        'num_leaves': 31,
        'min_data_in_leaf': 20,
        'feature_fraction': 0.8,
        'bagging_fraction': 0.8,
        'bagging_freq': 5,
        'random_state': 42
    }

    # Train the model
    model = lgb.train(
        params,
        train_data,
        num_boost_round=100,
        valid_sets=[train_data, val_data],
        valid_names=['train', 'val'],
        callbacks=[lgb.early_stopping(stopping_rounds=10)]
    )

    # Save the model
    model.save_model(MODEL_PATH)
    print(f"Ranking model saved to {MODEL_PATH}")

if __name__ == "__main__":
    train_ranking_model()