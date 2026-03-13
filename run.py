"""
Script de desenvolvimento: sobe o Flask com debug e hot reload.
Uso: python run.py
"""
from app import app

if __name__ == "__main__":
    app.run(debug=True)
