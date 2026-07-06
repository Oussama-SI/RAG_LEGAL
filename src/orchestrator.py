"""
orchestrator.py
==================
Orchestrateur LangGraph pour la génération de contrats marocains.

Graphe :

    START → intake → law_agent ─┐
                  └→ contract_agent ─┴→ draft → validate ─┬→ draft (retry, max N fois)
                                                            └→ finalize → END

- intake        : vérifie que tous les champs requis sont fournis. S'il en
                   manque, interrompt le graphe (interrupt()) et attend que
                   Streamlit les fournisse via resume().
- law_agent      : interroge POST /ask sur l'API lois (ق.ل.ع) et normalise
                   la réponse vers {articles, mandatory_clauses, total}.
- contract_agent : interroge POST /retrieve sur l'API contrats pour des
                   exemples de structure/style.
- draft          : compose le contrat via Groq à partir des deux contextes.
- validate       : relit le brouillon et vérifie les clauses/articles
                   obligatoires ; boucle vers draft si non conforme
                   (jusqu'à MAX_VALIDATION_ITER fois).
- finalize       : fige le contrat final et agrège les métriques des deux
                   API RAG (+ stats d'orchestration) pour affichage Streamlit.
                   ⚠️  contract-rag.ipynb n'expose pas /metrics : on capture
                   l'erreur sans bloquer.

law_agent et contract_agent tournent en parallèle (fan-out depuis intake,
fan-in dans draft).
"""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from contract_config import MOROCCAN_CONTRACT_INFO, SYSTEM_PROMPT, get_required_fields
from rag_clients import (
    RagApiError,
    contract_metrics,
    contract_retrieve,
    law_metrics,
    law_retrieve,
)

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orchestrator")

MAX_VALIDATION_ITER = 2
DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


# ─── État du graphe ─────────────────────────────────────────────────────────
class OrchestratorState(TypedDict, total=False):
    # ── Entrées ──────────────────────────────────────────────────────────────
    request_text: str
    contract_type: str
    party_info: dict
    law_api_url: str
    contract_api_url: str
    groq_api_key: str

    # ── Sorties des agents RAG ────────────────────────────────────────────────
    # law_context : {articles:[{text,meta:{article_num},score}],
    #                mandatory_clauses:[], total:int,
    #                hors_scope?:bool, question_id?:str}
    law_context: dict
    law_warning: Optional[str]

    # contract_examples : {chunks:[{text,meta,score}], total:int}
    contract_examples: dict
    contract_warning: Optional[str]

    # ── Pipeline rédaction / validation ──────────────────────────────────────
    draft: str
    validation_issues: list
    validation_passed: bool
    iteration: int

    # ── Sortie finale ─────────────────────────────────────────────────────────
    final_contract: str
    metrics: dict
    started_at: float


# ─── Helpers ────────────────────────────────────────────────────────────────
def get_llm(groq_api_key: str, model: str = DEFAULT_GROQ_MODEL, temperature: float = 0.3) -> ChatGroq:
    return ChatGroq(api_key=groq_api_key, model=model, temperature=temperature, max_tokens=4096)


def _parse_json_safe(text: str) -> dict:
    """Parse la sortie JSON du LLM-critique en tolérant les ```json fences."""
    cleaned = re.sub(r"```json|```", "", text).strip()
    try:
        return json.loads(cleaned)
    except (json.JSONDecodeError, TypeError):
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                pass
    return {"conforme": True, "clauses_manquantes": []}


def _format_party_info(contract_type: str, party_info: dict) -> str:
    required = get_required_fields(contract_type)
    lines = [f"- {label} : {party_info[k]}" for k, label in required.items() if party_info.get(k)]
    return "\n".join(lines) if lines else "(لم تقدَّم معطيات)"


def _format_law_context(law_context: Optional[dict]) -> str:
    """
    Formate les articles du ق.ل.ع récupérés via law_retrieve().
    law_context["articles"] = [{text, meta:{article_num}, score}]
    """
    articles = (law_context or {}).get("articles", [])[:6]
    if not articles:
        return "(لا توجد مقتضيات قانونية محددة مسترجعة)"
    parts = []
    for a in articles:
        meta = a.get("meta") or {}
        ref = meta.get("article_num") or meta.get("chapter") or ""
        header = f"### الفصل {ref}" if ref else "### فصل"
        parts.append(f"{header}\n{(a.get('text') or '')[:500]}")
    return "\n\n".join(parts)


def _format_examples(contract_examples: Optional[dict]) -> str:
    chunks = (contract_examples or {}).get("chunks", [])[:4]
    if not chunks:
        return "(لا توجد أمثلة مرجعية مسترجعة)"
    return "\n\n".join(
        f"### مرجع {i + 1}\n{(c.get('text') or '')[:500]}"
        for i, c in enumerate(chunks)
    )


def _build_draft_prompt(state: OrchestratorState) -> str:
    info = MOROCCAN_CONTRACT_INFO.get(state["contract_type"], {})
    clauses_list = "\n".join(f"- {c}" for c in info.get("clauses", []))
    parties_list = "\n".join(f"- {p}" for p in info.get("parties", []))

    law_ctx = state.get("law_context") or {}
    hors_scope = law_ctx.get("hors_scope", False)
    law_section = _format_law_context(law_ctx)
    if hors_scope:
        law_section = "(⚠️ الوكيل القانوني: الطلب خارج نطاق ق.ل.ع — استخدام القواعد العامة)\n" + law_section

    feedback = ""
    if state.get("validation_issues"):
        feedback = "\n\n## ملاحظات يجب تصحيحها في هذه النسخة:\n" + "\n".join(
            f"- {i}" for i in state["validation_issues"]
        )

    return f"""## نوع العقد: {info.get('title', state['contract_type'])}
## القانون المغربي المنطبق: {info.get('law', 'القانون المدني المغربي')}

## أطراف العقد:
{parties_list}

## معطيات الأطراف والعقد المقدمة من المستخدم:
{_format_party_info(state["contract_type"], state.get("party_info", {}))}

## البنود الإلزامية الواجب تضمينها:
{clauses_list}

## مقتضيات قانونية ملزمة مسترجعة من ظهير الالتزامات والعقود (ق.ل.ع):
{law_section}

## أمثلة مرجعية من عقود مغربية فعلية:
{_format_examples(state.get("contract_examples"))}
{feedback}

اكتب العقد القانوني المغربي الكامل والمفصّل مع جميع البنود، باحترام صارم للمقتضيات القانونية أعلاه:"""


# ─── Nœuds du graphe ─────────────────────────────────────────────────────────

def intake_node(state: OrchestratorState) -> dict:
    contract_type = state.get("contract_type")
    logger.info("▶ [intake] contract_type=%r", contract_type)

    if contract_type not in MOROCCAN_CONTRACT_INFO:
        logger.error("[intake] Type de contrat inconnu : %r", contract_type)
        raise ValueError(f"Type de contrat inconnu : {contract_type!r}")

    required = get_required_fields(contract_type)
    party_info = dict(state.get("party_info") or {})

    while True:
        missing = [k for k in required if not party_info.get(k)]
        if not missing:
            logger.info("[intake] Tous les champs requis sont présents : %s", list(required.keys()))
            break
        logger.warning("[intake] Champs manquants → interruption : %s", missing)
        provided = interrupt(
            {
                "type": "missing_fields",
                "contract_type": contract_type,
                "fields": {k: required[k] for k in missing},
            }
        )
        party_info.update(provided or {})
        logger.info("[intake] Champs reçus via resume : %s", list((provided or {}).keys()))

    return {
        "party_info": party_info,
        "started_at": state.get("started_at") or time.time(),
        "iteration": 0,
        "validation_issues": [],
    }


def law_agent_node(state: OrchestratorState) -> dict:
    """
    Interroge POST /ask sur l'API lois (ai-juriste-lois-ngrok.ipynb).
    En cas d'échec : dégradation propre, l'orchestrateur continue sans
    contexte juridique réel.
    """
    logger.info("▶ [law_agent] Appel POST /ask → %s", state.get("law_api_url"))
    t0 = time.time()
    try:
        resp = law_retrieve(
            base_url=state["law_api_url"],
            contract_type=state["contract_type"],
            case_context=state.get("party_info", {}),
            query=state.get("request_text", ""),
        )
        n_articles = len(resp.get("articles", []))
        hors_scope = resp.get("hors_scope", False)
        logger.info(
            "[law_agent] ✓ %.2fs — %d article(s) récupéré(s) — hors_scope=%s",
            time.time() - t0, n_articles, hors_scope,
        )
        return {"law_context": resp, "law_warning": None}
    except RagApiError as e:
        logger.warning("[law_agent] ✗ %.2fs — RagApiError : %s", time.time() - t0, e)
        return {"law_context": {}, "law_warning": str(e)}


def contract_agent_node(state: OrchestratorState) -> dict:
    """
    Interroge POST /retrieve sur l'API contrats (contract-rag.ipynb).
    Retourne {chunks:[{text, meta, score}], total}.
    """
    info = MOROCCAN_CONTRACT_INFO.get(state["contract_type"], {})
    query = state.get("request_text") or info.get("title", state["contract_type"])
    logger.info("▶ [contract_agent] Appel POST /retrieve → %s  (query=%r)", state.get("contract_api_url"), query[:60])
    t0 = time.time()
    try:
        resp = contract_retrieve(
            base_url=state["contract_api_url"],
            query=query,
            contract_type=state["contract_type"],
            n=5,
        )
        n_chunks = len(resp.get("chunks", []))
        logger.info("[contract_agent] ✓ %.2fs — %d chunk(s) récupéré(s)", time.time() - t0, n_chunks)
        return {"contract_examples": resp, "contract_warning": None}
    except RagApiError as e:
        logger.warning("[contract_agent] ✗ %.2fs — RagApiError : %s", time.time() - t0, e)
        return {"contract_examples": {}, "contract_warning": str(e)}


def draft_node(state: OrchestratorState) -> dict:
    """Compose le contrat via Groq à partir des deux contextes RAG."""
    iteration = state.get("iteration", 0) + 1
    logger.info("▶ [draft] Itération %d — appel Groq (%s)", iteration, DEFAULT_GROQ_MODEL)
    t0 = time.time()
    llm = get_llm(state["groq_api_key"])
    prompt = _build_draft_prompt(state)
    resp = llm.invoke([SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)])
    draft_text = resp.content.strip()
    logger.info("[draft] ✓ %.2fs — %d caractères générés", time.time() - t0, len(draft_text))
    return {
        "draft": draft_text,
        "iteration": iteration,
    }


def validate_node(state: OrchestratorState) -> dict:
    """Relit le brouillon et vérifie la conformité aux clauses/articles."""
    logger.info("▶ [validate] Itération %d — vérification conformité", state.get("iteration", 0))
    t0 = time.time()
    info = MOROCCAN_CONTRACT_INFO.get(state["contract_type"], {})
    mandatory_clauses = info.get("clauses", [])

    mandatory_articles = [
        ref
        for a in (state.get("law_context") or {}).get("articles", [])
        if (ref := (a.get("meta") or {}).get("article_num"))
        and ref
    ]

    llm = get_llm(state["groq_api_key"], temperature=0.0)
    check_prompt = f"""تحقق من نص العقد التالي. أجب بصيغة JSON فقط، بدون أي نص خارج JSON:
{{"conforme": true أو false, "clauses_manquantes": ["..."]}}

البنود الإلزامية المطلوبة:
{chr(10).join("- " + c for c in mandatory_clauses) or "لا توجد"}

أرقام الفصول/المواد الملزمة (ق.ل.ع):
{", ".join(str(a) for a in mandatory_articles) or "لا توجد"}

نص العقد المطلوب فحصه:
{state["draft"][:6000]}"""

    resp = llm.invoke([HumanMessage(content=check_prompt)])
    parsed = _parse_json_safe(resp.content)
    passed = bool(parsed.get("conforme", True))
    issues = parsed.get("clauses_manquantes") or []

    if passed:
        logger.info("[validate] ✓ %.2fs — Conforme", time.time() - t0)
    else:
        logger.warning("[validate] ✗ %.2fs — Non conforme — clauses manquantes : %s", time.time() - t0, issues)

    return {
        "validation_passed": passed,
        "validation_issues": issues,
    }


def route_after_validate(state: OrchestratorState) -> str:
    iteration = state.get("iteration", 0)
    if state.get("validation_passed") or iteration >= MAX_VALIDATION_ITER:
        route = "done"
        reason = "conforme" if state.get("validation_passed") else f"max itérations ({MAX_VALIDATION_ITER}) atteint"
        logger.info("[route_after_validate] → finalize (%s)", reason)
    else:
        route = "retry"
        logger.info("[route_after_validate] → draft (retry, itération %d)", iteration)
    return route


def finalize_node(state: OrchestratorState) -> dict:
    """
    Agrège métriques d'orchestration + métriques RAG pour Streamlit.
    """
    elapsed = round(time.time() - state.get("started_at", time.time()), 1)
    logger.info("▶ [finalize] Contrat finalisé — %d itération(s) — %.1fs", state.get("iteration", 0), elapsed)

    metrics: dict = {
        "iterations": state.get("iteration", 0),
        "validation_passed": state.get("validation_passed"),
        "elapsed_seconds": elapsed,
        "law_warning": state.get("law_warning"),
        "contract_warning": state.get("contract_warning"),
        "law_hors_scope": (state.get("law_context") or {}).get("hors_scope", False),
        "law_articles_count": len((state.get("law_context") or {}).get("articles", [])),
        "contract_chunks_count": len((state.get("contract_examples") or {}).get("chunks", [])),
    }

    # Métriques API lois
    try:
        metrics["law_rag"] = law_metrics(state["law_api_url"])
        logger.info("[finalize] Métriques API lois récupérées")
    except RagApiError as e:
        metrics["law_rag"] = {"error": str(e)}
        logger.warning("[finalize] Métriques API lois indisponibles : %s", e)

    # Métriques API contrats (endpoint non exposé par contract-rag.ipynb)
    try:
        metrics["contract_rag"] = contract_metrics(state["contract_api_url"])
        logger.info("[finalize] Métriques API contrats récupérées")
    except RagApiError:
        metrics["contract_rag"] = {"note": "endpoint /metrics non exposé par contract-rag.ipynb"}
        logger.debug("[finalize] /metrics absent de contract-rag.ipynb (comportement attendu)")

    logger.info(
        "[finalize] ✓ Terminé — validation=%s  articles_loi=%d  chunks_contrat=%d",
        metrics["validation_passed"],
        metrics["law_articles_count"],
        metrics["contract_chunks_count"],
    )
    return {"final_contract": state.get("draft", ""), "metrics": metrics}


# ─── Construction du graphe ──────────────────────────────────────────────────

def build_graph(checkpointer=None):
    logger.info("Construction du graphe LangGraph...")
    graph = StateGraph(OrchestratorState)
    graph.add_node("intake", intake_node)
    graph.add_node("law_agent", law_agent_node)
    graph.add_node("contract_agent", contract_agent_node)
    graph.add_node("draft", draft_node)
    graph.add_node("validate", validate_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "law_agent")
    graph.add_edge("intake", "contract_agent")
    graph.add_edge("law_agent", "draft")
    graph.add_edge("contract_agent", "draft")
    graph.add_edge("draft", "validate")
    graph.add_conditional_edges(
        "validate",
        route_after_validate,
        {"retry": "draft", "done": "finalize"},
    )
    graph.add_edge("finalize", END)

    compiled = graph.compile(checkpointer=checkpointer or MemorySaver())
    logger.info("Graphe compilé ✓")
    return compiled


# ─── Façade pour Streamlit ───────────────────────────────────────────────────

class ContractOrchestrator:
    """Point d'entrée unique pour Streamlit."""

    def __init__(
        self,
        law_api_url: str,
        contract_api_url: str,
        groq_api_key: str,
        checkpointer=None,
    ):
        self.law_api_url = law_api_url
        self.contract_api_url = contract_api_url
        self.groq_api_key = groq_api_key
        self.graph = build_graph(checkpointer)
        logger.info(
            "ContractOrchestrator initialisé — law_api=%s  contract_api=%s",
            law_api_url or "(non défini)",
            contract_api_url or "(non défini)",
        )

    def start(
        self,
        thread_id: str,
        request_text: str,
        contract_type: str,
        party_info: Optional[dict] = None,
    ) -> dict:
        logger.info(
            "start() — thread_id=%s  contract_type=%r  party_info_keys=%s",
            thread_id, contract_type, list((party_info or {}).keys()),
        )
        config = {"configurable": {"thread_id": thread_id}}
        initial_state: OrchestratorState = {
            "request_text": request_text,
            "contract_type": contract_type,
            "party_info": party_info or {},
            "law_api_url": self.law_api_url,
            "contract_api_url": self.contract_api_url,
            "groq_api_key": self.groq_api_key,
        }
        result = self.graph.invoke(initial_state, config=config)
        formatted = self._format_result(result)
        logger.info("start() → status=%r", formatted.get("status"))
        return formatted

    def resume(self, thread_id: str, provided_fields: dict) -> dict:
        logger.info("resume() — thread_id=%s  provided_keys=%s", thread_id, list(provided_fields.keys()))
        config = {"configurable": {"thread_id": thread_id}}
        result = self.graph.invoke(Command(resume=provided_fields), config=config)
        formatted = self._format_result(result)
        logger.info("resume() → status=%r", formatted.get("status"))
        return formatted

    @staticmethod
    def _format_result(result: dict) -> dict:
        if result.get("__interrupt__"):
            payload = result["__interrupt__"][0].value
            logger.info("_format_result → needs_input  missing=%s", list(payload.get("fields", {}).keys()))
            return {"status": "needs_input", **payload}
        return {
            "status": "done",
            "contract": result.get("final_contract", ""),
            "metrics": result.get("metrics", {}),
            "law_warning": result.get("law_warning"),
            "contract_warning": result.get("contract_warning"),
        }