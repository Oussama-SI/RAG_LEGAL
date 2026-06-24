"""
rag_clients.py
================
Wrappers HTTP pour les deux services RAG exposés en FastAPI + ngrok depuis
les notebooks Kaggle/Colab. L'orchestrateur n'appelle jamais `requests`
directement : il passe toujours par ces fonctions, qui lèvent toutes la
même exception (RagApiError) en cas d'échec — ça permet à l'orchestrateur
de dégrader proprement (continuer sans contexte juridique ou sans exemples)
plutôt que de planter si une URL ngrok a expiré ou que le kernel Kaggle
est éteint.

── API contrats (contract-rag.ipynb) ───────────────────────────────────────
Déjà implémentée telle quelle dans le notebook : /health, /retrieve, /generate.
Il manque seulement /metrics (à ajouter — voir contract_metrics ci-dessous,
qui échouera tant que l'endpoint n'existe pas, sans bloquer le reste).

── API lois (ai-juriste-final-gradio.ipynb) ────────────────────────────────
N'existe pas encore : ce notebook ne sort que par Gradio aujourd'hui.
Ce module documente le contrat d'interface ATTENDU pour /retrieve_law et
/metrics, à implémenter dans le notebook lois en réutilisant le retriever
hybride + reranker + moteur doctrinal déjà présents (cellules 16-18), en
les exposant via FastAPI + ngrok sur le même modèle que contract-rag.ipynb.

Réponse attendue pour POST /retrieve_law :
{
  "articles": [
    {"text": "...", "meta": {"article_num": "754", "chapter": "..."}, "score": 0.87}
  ],
  "mandatory_clauses": ["بند الفسخ", "بند الاختصاص القضائي", ...],
  "total": 123
}

Réponse attendue pour GET /metrics (les deux API) : libre, mais idéalement
les métriques déjà calculées dans la cellule 12 (precision/recall/latence)
pour l'API lois, et un équivalent à construire pour l'API contrats.
"""

from __future__ import annotations

import requests

DEFAULT_TIMEOUT = 25
DEFAULT_HEALTH_TIMEOUT = 8


class RagApiError(RuntimeError):
    """Levée pour tout échec d'appel à une API RAG (URL absente, ngrok mort,
    timeout, réponse HTTP en erreur, JSON invalide...)."""


def _get(base_url: str, path: str, timeout: int = DEFAULT_HEALTH_TIMEOUT) -> dict:
    if not base_url:
        raise RagApiError(f"URL de l'API non configurée pour {path}")
    try:
        r = requests.get(f"{base_url.rstrip('/')}{path}", timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise RagApiError(f"Échec GET {path} : {e}") from e


def _post(base_url: str, path: str, payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    if not base_url:
        raise RagApiError(f"URL de l'API non configurée pour {path}")
    try:
        r = requests.post(f"{base_url.rstrip('/')}{path}", json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except requests.RequestException as e:
        raise RagApiError(f"Échec POST {path} : {e}") from e


# ─── API contrats (agent rédacteur) ────────────────────────────────────────
def contract_health(base_url: str) -> dict:
    return _get(base_url, "/health")


def contract_retrieve(base_url: str, query: str, contract_type: str = "", n: int = 5) -> dict:
    """Retourne {"chunks": [{"text","meta","score"}], "total": int}."""
    return _post(base_url, "/retrieve", {"query": query, "contract_type": contract_type, "n": n})


def contract_metrics(base_url: str) -> dict:
    """À ajouter côté notebook contrats — échoue tant que l'endpoint n'existe pas."""
    return _get(base_url, "/metrics")


# ─── API lois (agent juridique) — à implémenter côté notebook lois ────────
def law_health(base_url: str) -> dict:
    return _get(base_url, "/health")


def law_retrieve(base_url: str, contract_type: str, case_context: dict, query: str, n: int = 8) -> dict:
    """Retourne {"articles": [{"text","meta","score"}], "mandatory_clauses": [...], "total": int}."""
    payload = {
        "contract_type": contract_type,
        "case_context": case_context,
        "query": query,
        "n": n,
    }
    return _post(base_url, "/retrieve_law", payload)


def law_metrics(base_url: str) -> dict:
    """Doit exposer les métriques déjà calculées en cellule 12 du notebook lois."""
    return _get(base_url, "/metrics")
