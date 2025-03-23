# 953481 - TERM PROJECT<br>

## Overview
This project focuses on building an information retrieval system for recipe recommendations and bookmarking, with a backend in Python (Flask) and a frontend in Vue.js.

## Setup Instructions

### <u>Database Setup</u>
1. **Database Schema**:
   - Ensure the following tables are created in the `recipes` database:
     ```sql
     CREATE TABLE bookmarks (
         BookmarkId INTEGER PRIMARY KEY AUTOINCREMENT,
         UserId INTEGER,
         FolderId INTEGER,
         RecipeId INTEGER,
         Rating INTEGER,
         FOREIGN KEY (UserId) REFERENCES users(id),
         FOREIGN KEY (FolderId) REFERENCES folders(FolderId),
         FOREIGN KEY (RecipeId) REFERENCES recipes(RecipeId)
     );

     CREATE TABLE folders (
         FolderId INTEGER PRIMARY KEY AUTOINCREMENT,
         UserId INTEGER,
         Name TEXT NOT NULL,
         FOREIGN KEY (UserId) REFERENCES users(id)
     );
     ```

2. **User Authentication**:
   - Create a new database for user management and authentication:
     ```sql
     CREATE TABLE users (
         id INTEGER NOT NULL, 
         username VARCHAR, 
         hashed_password VARCHAR, 
         PRIMARY KEY (id)
     );

     CREATE INDEX ix_users_id ON users (id);
     CREATE UNIQUE INDEX ix_users_username ON users (username);
     ```

### <u>Preprocessing Data</u>
3. **Preprocessing Data**: 
   - Run `preprocess.py` to preprocess data in the database.
   - Specify the path to save the preprocessed data.

### <u>Training the Ranking Model</u>
4. **Training the Ranking Model**: 
   - Run `train_ranking_model.py` to train the learn-to-rank model.
   - Specify the path to save the trained model.

### <u>Configuring Base Directory</u>
5. **Configuring Base Directory**:
   - Update `BASE_DIR` in `utils.py` with paths for preprocessed data, model, and database files.

### <u>Running the Backend Server</u>
6. **Running the Backend**:
   - Execute `backend.py` to start the Flask server.

## Getting Started
- Ensure Python, Flask, Vue.js, and necessary dependencies are installed.
- Configure paths and database connections as per instructions above.
- Start the backend server and launch the Vue.js frontend to interact with the application.

## Additional Notes
- Customize folder structure, file paths, and database connections based on your environment and project requirements.
