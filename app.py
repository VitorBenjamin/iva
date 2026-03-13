# Entry point Flask
from flask import Flask, jsonify

from core.projetos import listar_projetos

app = Flask(__name__)


@app.get("/")
def index():
    """Lista projetos existentes em JSON (padrão R3)."""
    projetos = listar_projetos()
    dados = [p.model_dump(mode="json") for p in projetos]
    return jsonify({"success": True, "message": "Projetos listados.", "data": dados})
