# Entry point Flask
from datetime import date

from flask import Flask, jsonify, render_template, request
from loguru import logger
from pydantic import BaseModel, Field

from core.financeiro.modelos import DadosFinanceiros
from core.projetos import (
    PROJECTS_DIR,
    Projeto,
    gerar_id_projeto,
    listar_projetos,
    salvar_projeto,
)

app = Flask(__name__)


class CriarProjetoBody(BaseModel):
    """Payload para POST /projeto."""

    nome: str = Field(min_length=1)
    url_booking: str = ""
    numero_quartos: int = Field(ge=1)
    faturamento_anual: float = Field(ge=0)
    ano_referencia: int = Field(default_factory=lambda: date.today().year, ge=2000, le=2100)


@app.get("/")
def index():
    """Serve a página principal (Single Page)."""
    return render_template("index.html")


@app.get("/api/projetos")
def api_listar_projetos():
    """Lista projetos em JSON (padrão R3)."""
    projetos = listar_projetos()
    dados = [p.model_dump(mode="json") for p in projetos]
    return jsonify({"success": True, "message": "Projetos listados.", "data": dados})


@app.post("/projeto")
def criar_projeto():
    """Cria novo projeto; id único com sufixo numérico se slug já existir."""
    try:
        body = request.get_json(force=True, silent=True) or {}
        payload = CriarProjetoBody.model_validate(body)
    except Exception as e:
        logger.warning("Validação POST /projeto falhou: {}", e)
        return jsonify({
            "success": False,
            "message": str(e),
            "data": None,
        }), 400

    id_base = gerar_id_projeto(payload.nome)
    id_projeto = id_base
    n = 1
    while (PROJECTS_DIR / f"{id_projeto}.json").exists():
        id_projeto = f"{id_base}-{n}"
        n += 1

    projeto = Projeto(
        id=id_projeto,
        nome=payload.nome,
        url_booking=payload.url_booking,
        numero_quartos=payload.numero_quartos,
        faturamento_anual=payload.faturamento_anual,
        ano_referencia=payload.ano_referencia,
        financeiro=DadosFinanceiros(),
        dados_mercado=None,
    )
    salvar_projeto(projeto)
    logger.info("Projeto criado via POST: {}", id_projeto)
    return jsonify({
        "success": True,
        "message": "Projeto criado.",
        "data": {"id": projeto.id},
    }), 201
