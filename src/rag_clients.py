"""
rag_clients.py
================
Wrappers HTTP pour les deux services RAG exposés via FastAPI + ngrok.

── API contrats  (contract-rag.ipynb) ──────────────────────────────────────
Endpoints réels :
  GET  /health    → {status, chunks_indexed, gpu_available, model_loaded}
  POST /retrieve  → {query, contract_type?, n?}
                  ← {chunks: [{text, meta, score}], total}
  POST /generate  → non utilisé par l'orchestrateur

  ⚠️  /metrics n'est PAS exposé par ce notebook.
      contract_metrics() lève RagApiError proprement — l'orchestrateur
      continue sans bloquer.

── API lois  (ai-juriste-lois-ngrok.ipynb) ─────────────────────────────────
Endpoints réels :
  GET  /health    → {status, checks: {retriever, reranker, ...}}
  POST /ask       → {question, top_k?}
                  ← {question_id, question, hors_scope,
                     articles: [{rang, numero, texte, score}],
                     temps_ecoule_s, timestamp}
  GET  /metrics   → {total_requests, total_errors, total_out_of_scope,
                     avg_time_s, min_time_s, max_time_s,
                     uptime_s, last_request_at}

  law_retrieve() appelle POST /ask et normalise la réponse vers le format
  attendu par l'orchestrateur :
    {articles: [{text, meta: {article_num}, score}],
     mandatory_clauses: [],
     total: int}
"""

from __future__ import annotations

import requests

DEFAULT_TIMEOUT = 25
DEFAULT_HEALTH_TIMEOUT = 8


class RagApiError(RuntimeError):
    """Levée pour tout échec d'appel à une API RAG (URL absente, ngrok mort,
    timeout, réponse HTTP en erreur, JSON invalide...)."""


# ─── Helpers internes ────────────────────────────────────────────────────────

def _get(base_url: str, path: str, timeout: int = DEFAULT_HEALTH_TIMEOUT) -> dict:
    if not base_url:
        raise RagApiError(f"URL de l'API non configurée (chemin : {path})")
    try:
        r = requests.get(f"{base_url.rstrip('/')}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise RagApiError(f"Échec GET {path} : {e}") from e


def _post(base_url: str, path: str, payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    if not base_url:
        raise RagApiError(f"URL de l'API non configurée (chemin : {path})")
    try:
        r = requests.post(
            f"{base_url.rstrip('/')}{path}",
            json=payload,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise RagApiError(f"Échec POST {path} : {e}") from e


# ─── API contrats  (contract-rag.ipynb) ─────────────────────────────────────

def contract_health(base_url: str) -> dict:
    """
    GET /health
    Retourne {status, chunks_indexed, gpu_available, model_loaded}.
    """
    return _get(base_url, "/health")


def contract_retrieve(base_url: str, query: str, contract_type: str = "", n: int = 5) -> dict:
    """
    POST /retrieve
    Retourne {chunks: [{text, meta, score}], total}.
    """
    payload: dict = {"query": query, "n": n}
    # On n'envoie contract_type que s'il est renseigné — le notebook filtre
    # sur Chroma uniquement si la valeur est non vide et hors "عقد_عام".
    if contract_type:
        payload["contract_type"] = contract_type
    return _post(base_url, "/retrieve", payload)


def contract_metrics(base_url: str) -> dict:
    """
    GET /metrics — NON exposé par contract-rag.ipynb.
    Lève RagApiError ; l'orchestrateur (finalize_node) continue sans bloquer.
    """
    return _get(base_url, "/metrics")


# ─── API lois  (ai-juriste-lois-ngrok.ipynb) ────────────────────────────────

def law_health(base_url: str) -> dict:
    """
    GET /health
    Retourne {status, checks: {retriever, reranker, langgraph_app, articles_db}}.
    """
    return _get(base_url, "/health")


def law_retrieve(
    base_url: str,
    contract_type: str,
    case_context: dict,
    query: str,
    n: int = 8,
) -> dict:
    """
    Interroge POST /ask et normalise la réponse vers le format
    attendu par orchestrator.py :

      {
        "articles": [
          {"text": "...", "meta": {"article_num": "230"}, "score": 0.82}
        ],
        "mandatory_clauses": [],   # le pipeline lois ne les expose pas encore
        "total": 3
      }

    La question envoyée combine : type de contrat + requête libre +
    champs clés du contexte (parties, objet…).
    """
    # Construire une question riche à partir du contexte disponible
    question_parts = []
    if contract_type:
        question_parts.append(f"نوع العقد: {contract_type}")
    if query:
        question_parts.append(query)
    # Ajouter les champs de contexte utiles (objet, parties…)
    for key in ("objet", "object", "parties", "description"):
        val = (case_context or {}).get(key)
        if val:
            question_parts.append(str(val))

    question = " — ".join(question_parts) if question_parts else contract_type or "عقد"

    payload: dict = {"question": question, "top_k": n}
    raw = _post(base_url, "/ask", payload)

    # ── Normalisation vers le format orchestrateur ──────────────────────────
    # Le notebook retourne :
    #   articles: [{rang, numero, texte, score}]
    # On remonte vers :
    #   articles: [{text, meta: {article_num}, score}]
    normalized_articles = [
        {
            "text": art.get("texte", ""),
            "meta": {"article_num": str(art.get("numero", ""))},
            "score": art.get("score", 0.0),
        }
        for art in raw.get("articles", [])
    ]

    return {
        "articles": normalized_articles,
        # Le pipeline lois ne calcule pas de clauses obligatoires séparément ;
        # l'orchestrateur se base sur contract_config pour les clauses métier.
        "mandatory_clauses": [],
        "total": len(normalized_articles),
        # Champs supplémentaires utiles pour le débogage / métriques Streamlit
        "hors_scope": raw.get("hors_scope", False),
        "question_id": raw.get("question_id", ""),
        "temps_ecoule_s": raw.get("temps_ecoule_s", 0.0),
    }


def law_metrics(base_url: str) -> dict:
    """
    GET /metrics
    Retourne {total_requests, total_errors, total_out_of_scope,
              avg_time_s, min_time_s, max_time_s, uptime_s, last_request_at}.
    """
    return _get(base_url, "/metrics")