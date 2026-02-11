"""
Database module for Daiso Category Search
SQLite database operations
"""
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional

# Database path - relative to this file's location
DB_PATH = os.path.join(os.path.dirname(__file__), 'products.db')

def get_connection():
    """Get SQLite connection"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Initialize database tables"""
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rank INTEGER,
            name TEXT NOT NULL,
            price INTEGER,
            image_url TEXT,
            image_name TEXT,
            image_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_utterances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            utterance TEXT NOT NULL,
            difficulty TEXT CHECK(difficulty IN ('normal', 'hard')),
            expected_product_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (expected_product_id) REFERENCES products(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS product_embeddings (
            product_id INTEGER PRIMARY KEY,
            text_embedding BLOB,
            image_embedding BLOB,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (product_id) REFERENCES products(id)
        )
    ''')
    
    conn.commit()
    conn.close()
    print(f"✅ Database initialized: {DB_PATH}")

def insert_product(rank: int, name: str, price: int, image_url: str, 
                   image_name: str = None, image_path: str = None) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute('''
            INSERT OR IGNORE INTO products (rank, name, price, image_url, image_name, image_path)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (rank, name, price, image_url, image_name, image_path))
        conn.commit()
        return cursor.rowcount > 0
    except Exception as e:
        print(f"❌ Insert error: {e}")
        return False
    finally:
        conn.close()

def get_product_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM products')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def get_all_products() -> List[Dict]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM products ORDER BY rank')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def product_exists(name: str) -> bool:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT 1 FROM products WHERE name = ?', (name,))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def get_utterance_count() -> int:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM test_utterances')
    count = cursor.fetchone()[0]
    conn.close()
    return count

def search_products(keyword: str) -> List[Dict]:
    """Search products by name (simple LIKE query)"""
    conn = get_connection()
    cursor = conn.cursor()
    # Split keyword by spaces to support multiple terms "blue pen" -> "%blue%" AND "%pen%"
    terms = keyword.split()
    query = "SELECT * FROM products WHERE " + " AND ".join(["name LIKE ?"] * len(terms))
    params = [f"%{term}%" for term in terms]
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def get_related_products_for_context(keyword: str, limit: int = 5) -> str:
    """
    Search products and return a formatted string for LLM context.
    Example: "- Plastic Box (1000 won)\n- Paper Box (2000 won)"
    """
    products = search_products(keyword)
    if not products:
        return ""
    
    # Take top N matching products
    context_list = []
    for p in products[:limit]:
        context_list.append(f"- {p['name']} ({p.get('price', 'N/A')}원)")
    
    return "\n".join(context_list)


if __name__ == "__main__":
    init_database()
    print(f"Products: {get_product_count()}")
    print(f"Utterances: {get_utterance_count()}")
