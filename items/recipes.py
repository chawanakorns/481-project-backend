# items/recipes.py
from flask import Blueprint, request, jsonify
import re
from utils.utils import PREPROCESSED_RECIPES, clean_image_url, generate_candidates, generate_bigrams, \
    calculate_p_w, calculate_p_x_given_w, calculate_p_bigram, word_freq, bigram_freq, PHRASE_MAP, token_required, \
    generate_bigram_candidates

recipes_bp = Blueprint('recipes', __name__)

def correct_spelling(query):
    """
    Correct spelling in the given query using Levenshtein distance and bigram probabilities.
    Returns a tuple of (corrected_query, suggestions).
    """
    try:
        # Handle empty or invalid queries
        if not query or not query.strip():
            return query, []

        query = query.lower().strip()
        words = query.split()

        # Single-word query
        if len(words) == 1:
            word = words[0]
            if word in word_freq:
                return word, []
            candidates = generate_candidates(word, max_distance=2)
            if not candidates:
                return word, []
            candidate_scores = []
            for cand, dist in candidates:
                p_w = calculate_p_w(cand)
                p_x_given_w = calculate_p_x_given_w(word, cand, dist)
                score = p_x_given_w * p_w
                candidate_scores.append((cand, score, dist))
            candidate_scores.sort(key=lambda x: (-x[1], x[2]))
            top_candidates = [cand[0] for cand in candidate_scores[:5]]
            corrected_query = top_candidates[0] if top_candidates else word
            suggestions = top_candidates if corrected_query != word else []
            return corrected_query, suggestions

        # Multi-word query
        corrected_words = []
        suggestions = []

        # Correct individual words
        for word in words:
            if word in word_freq:
                corrected_words.append(word)
                suggestions.append([word])
                continue
            candidates = generate_candidates(word, max_distance=2)
            if not candidates:
                corrected_words.append(word)
                suggestions.append([word])
                continue
            candidate_scores = []
            for cand, dist in candidates:
                p_w = calculate_p_w(cand)
                p_x_given_w = calculate_p_x_given_w(word, cand, dist)
                score = p_x_given_w * p_w
                candidate_scores.append((cand, score, dist))
            candidate_scores.sort(key=lambda x: (-x[1], x[2]))
            top_candidates = [cand[0] for cand in candidate_scores[:5]]
            corrected_word = top_candidates[0] if top_candidates else word
            corrected_words.append(corrected_word)
            suggestions.append(top_candidates if corrected_word != word else [word])

        # Join corrected words
        corrected_query = " ".join(corrected_words)

        # Bigram correction
        if len(words) >= 2:
            bigrams = generate_bigrams(corrected_words)
            for i, bigram in enumerate(bigrams):
                bigram_tuple = tuple(bigram.split())
                if bigram_tuple in bigram_freq:
                    continue
                bigram_candidates = generate_bigram_candidates(bigram, max_distance=3)
                if not bigram_candidates:
                    continue
                bigram_scores = []
                for cand_bigram, dist in bigram_candidates:
                    cand_bigram_str = ' '.join(cand_bigram)
                    p_bigram = calculate_p_bigram(cand_bigram)
                    p_x_given_w = calculate_p_x_given_w(bigram, cand_bigram_str, dist)
                    score = p_x_given_w * p_bigram
                    bigram_scores.append((cand_bigram, score, dist))
                bigram_scores.sort(key=lambda x: (-x[1], x[2]))
                top_bigram_candidates = [cand[0] for cand in bigram_scores[:3]]
                if top_bigram_candidates:
                    best_bigram = top_bigram_candidates[0]
                    # Replace the two words in corrected_words
                    corrected_words[i] = best_bigram[0]
                    corrected_words[i + 1] = best_bigram[1]
                    # Update suggestions
                    suggestions[i] = [best_bigram[0]]
                    suggestions[i + 1] = [best_bigram[1]]

        # Join corrected words after bigram correction
        corrected_query = " ".join(corrected_words)

        # Phrase correction using PHRASE_MAP
        corrected_query_lower = corrected_query.lower()
        if corrected_query_lower in PHRASE_MAP:
            corrected_query = PHRASE_MAP[corrected_query_lower]
            # Update suggestions to reflect the phrase correction
            suggestions = [[corrected_query]]

        return corrected_query, suggestions

    except Exception as e:
        print(f"Error in spell correction: {e}")
        return query, []

def search_recipes(query, recipes_list):
    filtered_recipes = []
    query_terms = query.lower().strip().split()
    for recipe in recipes_list:
        name = recipe.get('Name', '').lower()
        desc = recipe.get('Description', '').lower() if recipe.get('Description') else ''
        keywords_list = [kw.strip('"').lower() for kw in recipe.get('Keywords', []) if kw and not re.match(r'^\d+$', kw.strip('"'))]
        ingredients_list = [ing.strip('"').lower() for ing in recipe.get('RecipeIngredientParts', []) if ing and not re.match(r'^\d+$', ing.strip('"'))]
        instructions = ' '.join(recipe.get('RecipeInstructions', [])).lower()
        recipe_text = ' '.join([name, desc, ' '.join(keywords_list), ' '.join(ingredients_list), instructions])
        if all(term in recipe_text for term in query_terms):
            filtered_recipes.append(recipe)
    return filtered_recipes

@recipes_bp.route('/recipes', methods=['GET'])
@token_required
def get_recipes():
    limit = request.args.get('limit', default=20, type=int)
    page = request.args.get('page', default=1, type=int)
    search_query = request.args.get('search', default='', type=str).strip()
    recipes_list = list(PREPROCESSED_RECIPES.values())
    start = (page - 1) * limit
    end = start + limit
    if search_query:
        corrected_query, suggestions = correct_spelling(search_query)
        filtered_recipes = search_recipes(corrected_query, recipes_list)
        total_results = len(filtered_recipes)
        paginated_recipes = filtered_recipes[start:end]
        total_pages = (total_results + limit - 1) // limit
        response = {
            'recipes': [{**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))} for recipe in paginated_recipes],
            'original_query': search_query,
            'corrected_query': corrected_query if corrected_query != search_query else None,
            'suggestions': suggestions,
            'total_results': total_results,
            'total_pages': total_pages,
            'current_page': page
        }
    else:
        total_results = len(recipes_list)
        paginated_recipes = recipes_list[start:end]
        total_pages = (total_results + limit - 1) // limit
        response = {
            'recipes': [{**recipe, 'image_url': clean_image_url(recipe.get('image_url', ''))} for recipe in paginated_recipes],
            'original_query': '',
            'corrected_query': None,
            'suggestions': [],
            'total_results': total_results,
            'total_pages': total_pages,
            'current_page': page
        }
    return jsonify(response)