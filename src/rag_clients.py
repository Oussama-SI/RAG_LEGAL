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

import logging
import re
from typing import Optional

import requests

DEFAULT_TIMEOUT = 25
DEFAULT_HEALTH_TIMEOUT = 8

logger = logging.getLogger(__name__)


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

# Questions juridiques génériques par type de contrat
_CONTRACT_LEGAL_QUESTIONS = {
    "عقد_إيجار": "ما هي شروط وأحكام عقد الكراء السكني في ظهير الالتزامات والعقود المغربي؟",
    "عقد_بيع": "ما هي شروط عقد البيع وأحكامه في ظهير الالتزامات والعقود المغربي؟",
    "عقد_عمل": "ما هي أحكام عقد الشغل في مدونة الشغل المغربية؟",
    "عقد_شراكة": "ما هي أحكام عقد الشركة في القانون المغربي؟",
    "عقد_مقاولة": "ما هي أحكام عقد المقاولة في ظهير الالتزامات والعقود المغربي؟",
    "عقد_قرض": "ما هي أحكام عقد القرض في ظهير الالتزامات والعقود المغربي؟",
    "عقد_كفالة": "ما هي شروط عقد الكفالة وأحكامه في ظهير الالتزامات والعقود المغربي؟",
    "عقد_وكالة": "ما هي أحكام عقد الوكالة في ظهير الالتزامات والعقود المغربي؟",
    "عقد_رهن": "ما هي أحكام عقد الرهن في ظهير الالتزامات والعقود المغربي؟",
}

# Mots-clés indiquant une question juridique (pour détection automatique)
_LEGAL_KEYWORDS = [
    "شروط", "أحكام", "حق", "التزام", "بطلان", "فسخ", "تعويض",
    "مسؤولية", "أهلية", "قاصر", "ناقص", "ضمان", "كفالة",
    "بيع", "شراء", "إيجار", "كراء", "قرض", "وكالة",
    "الالتزامات", "العقود", "المادة", "الفصل", "ظهير",
    "قانون", "مدونة", "نص", "مقتضى", "إجراء",
]


def _is_legal_question(text: str) -> bool:
    """
    Détecte si une requête est une question juridique ou une simple description.
    """
    if not text:
        return False
    # Vérifier la présence de mots-clés juridiques
    text_lower = text.lower()
    return any(kw in text_lower for kw in _LEGAL_KEYWORDS)


def _build_legal_question(
    contract_type: str,
    query: str,
    case_context: Optional[dict] = None,
) -> str:
    """
    Construit une question juridique pertinente pour l'API Loi.
    
    Stratégie :
    1. Si la requête utilisateur est une question juridique → l'utiliser
    2. Sinon, utiliser une question générique basée sur le type de contrat
    3. Ajouter des informations contextuelles utiles (parties, objet)
    4. Limiter la longueur à 300 caractères maximum
    """
    # 1. Si c'est une question juridique, l'utiliser directement
    if _is_legal_question(query):
        question = query[:300]  # Limiter la longueur
        logger.info(f"[law_retrieve] Question juridique détectée : {question[:100]}...")
        return question
    
    # 2. Construire une question à partir du type de contrat
    question = _CONTRACT_LEGAL_QUESTIONS.get(
        contract_type,
        f"ما هي الأحكام القانونية المتعلقة بعقد {contract_type} في ظهير الالتزامات والعقود المغربي؟"
    )
    
    # 3. Ajouter le contexte utile (parties, objet) sans surcharger
    context_parts = []
    if case_context:
        # Parties prenantes
        parties = case_context.get("parties") or case_context.get("parties_names")
        if parties and len(str(parties)) < 150:
            context_parts.append(f"الأطراف: {parties}")
        
        # Objet du contrat (si ce n'est pas une adresse)
        objet = case_context.get("object") or case_context.get("objet")
        if objet and len(str(objet)) < 100:
            # Vérifier que ce n'est pas une adresse
            is_address = bool(re.search(r"(شارع|زنقة|طريق|عمارة|رقم|دار)", str(objet)))
            if not is_address:
                context_parts.append(f"الموضوع: {objet}")
    
    # 4. Ajouter les contextes utiles
    if context_parts:
        question = f"{question} — {' — '.join(context_parts)}"
    
    # 5. Limiter la longueur finale
    if len(question) > 300:
        question = question[:300]
    
    logger.info(f"[law_retrieve] Question construite : {question[:150]}...")
    return question


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
    attendu par orchestrator.py.

    La question envoyée est construite intelligemment :
    - Si la requête utilisateur est une question juridique → l'utiliser
    - Sinon, construire une question générique basée sur le type de contrat
    - Ajouter les champs de contexte utiles (parties, objet) sans surcharger
    """
    # Construire la question juridique
    question = _build_legal_question(
        contract_type=contract_type,
        query=query,
        case_context=case_context,
    )
    
    # Si la question est vide, utiliser une question générique
    if not question:
        question = "ما هي الأحكام العامة للعقود في ظهير الالتزامات والعقود المغربي؟"
    
    # Envoyer la requête
    payload: dict = {"question": question, "top_k": n}
    logger.info(f"[law_retrieve] Envoi à l'API Loi : {question[:100]}...")
    
    try:
        raw = _post(base_url, "/ask", payload)
    except RagApiError as e:
        logger.error(f"[law_retrieve] Erreur API Loi : {e}")
        # Retourner une réponse vide mais avec une structure valide
        return {
            "articles": [],
            "mandatory_clauses": [],
            "total": 0,
            "hors_scope": True,
            "question_id": "",
            "temps_ecoule_s": 0.0,
            "error": str(e),
        }

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


# ─── Fonctions utilitaires pour l'orchestrateur ──────────────────────────────

def format_law_articles_for_prompt(articles: list, max_articles: int = 3) -> str:
    """
    Formate les articles juridiques pour le prompt de l'agent rédacteur.
    """
    if not articles:
        return "(لا توجد مقتضيات قانونية محددة مسترجعة)"
    
    parts = []
    for i, article in enumerate(articles[:max_articles], 1):
        meta = article.get("meta", {})
        ref = meta.get("article_num") or meta.get("chapter") or ""
        text = article.get("text", "")
        
        if ref:
            header = f"### الفصل {ref} من ظهير الالتزامات والعقود"
        else:
            header = f"### مقتضى قانوني {i}"
        
        # Tronquer le texte si trop long (2000 caractères max)
        if len(text) > 2000:
            text = text[:2000] + " [...]"
        
        parts.append(f"{header}\n{text}")
    
    return "\n\n".join(parts)