"""
chat_agent.py
================
Agent conversationnel pour la collecte des informations du contrat en mode
"chatbot" (au lieu du formulaire Streamlit classique).

Principe :
  1. Au premier message utilisateur, on détecte automatiquement le type de
     contrat (parmi MOROCCAN_CONTRACT_INFO) via le LLM.
  2. On détermine les champs requis (get_required_fields) pour ce type.
  3. À chaque tour, on extrait via le LLM les champs déjà mentionnés dans
     toute la conversation (extraction cumulative, tolérante à la
     reformulation), puis on identifie ce qu'il manque encore.
  4. Tant qu'il manque des champs, l'agent répond par un message bref,
     professionnel et naturel (pas de formulaire, pas de listing brut) qui
     relance la conversation pour obtenir les informations manquantes.
  5. Dès que tout est rassemblé, l'agent confirme et signale que la
     génération du contrat (orchestrateur LangGraph : agent juridique +
     agent rédacteur + validation) peut démarrer.

Ce module ne dépend pas de Streamlit : il est appelé depuis app.py (page
chat) et s'appuie sur les mêmes contract_config / Groq que orchestrator.py.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_groq import ChatGroq

from contract_config import MOROCCAN_CONTRACT_INFO, get_required_fields

logger = logging.getLogger("chat_agent")

DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"


# ─── État de la conversation (côté Streamlit session_state) ─────────────────
class ChatState(TypedDict, total=False):
    messages: list[dict]          # [{role: "user"|"assistant", content: str}]
    contract_type: Optional[str]  # détecté dès que possible
    collected_fields: dict        # {field_key: value} progressivement rempli
    ready: bool                   # True quand tous les champs requis sont là


def new_chat_state() -> ChatState:
    return {
        "messages": [],
        "contract_type": None,
        "collected_fields": {},
        "ready": False,
    }


def _get_llm(groq_api_key: str, temperature: float = 0.2) -> ChatGroq:
    return ChatGroq(api_key=groq_api_key, model=DEFAULT_GROQ_MODEL, temperature=temperature, max_tokens=1024)


def _parse_json_safe(text: str) -> dict:
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
    return {}


def _conversation_text(messages: list[dict]) -> str:
    lines = []
    for m in messages:
        speaker = "المستخدم" if m["role"] == "user" else "المساعد"
        lines.append(f"{speaker}: {m['content']}")
    return "\n".join(lines)


# ─── Étape 1 : détection du type de contrat ──────────────────────────────────
def detect_contract_type(groq_api_key: str, messages: list[dict]) -> Optional[str]:
    """
    Détecte le type de contrat marocain le plus probable à partir de
    l'ensemble de la conversation. Retourne une clé de MOROCCAN_CONTRACT_INFO
    ou None si le LLM n'est pas encore assez confiant.
    """
    options = "\n".join(
        f"- {key} : {info['title']}" for key, info in MOROCCAN_CONTRACT_INFO.items()
    )
    prompt = f"""فيما يلي محادثة بين مستخدم ومساعد قانوني مغربي. حدد نوع العقد الذي يريد المستخدم صياغته من اللائحة التالية فقط:

{options}

المحادثة:
{_conversation_text(messages)}

أجب بصيغة JSON فقط، بدون أي نص إضافي:
{{"contract_type": "<المفتاح بالضبط من اللائحة أعلاه أو null إذا لم يكن واضحاً بعد>", "confidence": "high أو low"}}"""

    llm = _get_llm(groq_api_key, temperature=0.0)
    resp = llm.invoke([HumanMessage(content=prompt)])
    parsed = _parse_json_safe(resp.content)
    ctype = parsed.get("contract_type")
    confidence = parsed.get("confidence", "low")

    if ctype in MOROCCAN_CONTRACT_INFO and confidence == "high":
        logger.info("[chat_agent] Type de contrat détecté : %s (confiance=%s)", ctype, confidence)
        return ctype

    logger.info("[chat_agent] Type de contrat non confirmé (raw=%r, confidence=%s)", ctype, confidence)
    return None


# ─── Étape 2 : extraction cumulative des champs ──────────────────────────────
def extract_fields(
    groq_api_key: str,
    contract_type: str,
    messages: list[dict],
    already_collected: dict,
) -> dict:
    """
    Relit toute la conversation et extrait les valeurs des champs requis
    pour `contract_type`. Fusionne avec already_collected (les nouvelles
    valeurs explicites écrasent les anciennes si reformulées).
    """
    required = get_required_fields(contract_type)
    fields_desc = "\n".join(f"- {key} : {label}" for key, label in required.items())

    prompt = f"""أنت مساعد قانوني تجمع معطيات لصياغة عقد مغربي من نوع "{MOROCCAN_CONTRACT_INFO[contract_type]['title']}".

الحقول المطلوبة وأوصافها:
{fields_desc}

القيم المجمعة سابقاً (إن وجدت):
{json.dumps(already_collected, ensure_ascii=False)}

المحادثة الكاملة مع المستخدم:
{_conversation_text(messages)}

استخرج من المحادثة فقط القيم الصريحة والمؤكدة لهذه الحقول. لا تخترع أي معلومة غير مذكورة.
أجب بصيغة JSON فقط (مفاتيح الحقول المذكورة أعلاه فقط، أو فارغ إن لم توجد قيمة):
{{"<field_key>": "<valeur>", ...}}"""

    llm = _get_llm(groq_api_key, temperature=0.0)
    resp = llm.invoke([HumanMessage(content=prompt)])
    parsed = _parse_json_safe(resp.content)

    merged = dict(already_collected)
    for key in required:
        val = parsed.get(key)
        if val and str(val).strip() and str(val).strip().lower() not in ("null", "none", "n/a"):
            merged[key] = str(val).strip()

    return merged


def missing_fields(contract_type: str, collected: dict) -> dict:
    required = get_required_fields(contract_type)
    return {k: label for k, label in required.items() if not collected.get(k)}


# ─── Étape 3 : réponse conversationnelle (relance ou confirmation) ──────────
def generate_assistant_reply(
    groq_api_key: str,
    state: ChatState,
) -> str:
    """
    Produit la prochaine réplique de l'assistant :
      - si le type de contrat n'est pas encore identifié → question
        d'ouverture chaleureuse et professionnelle pour le cerner.
      - si des champs manquent → relance naturelle (1-3 questions max,
        formulées en phrases, jamais en formulaire brut) pour les obtenir,
        en restant bref et orienté action, à la manière de ChatGPT/Claude.
      - si tout est prêt → message de confirmation clair annonçant le
        lancement de la génération.
    """
    llm = _get_llm(groq_api_key, temperature=0.4)
    contract_type = state.get("contract_type")
    collected = state.get("collected_fields", {})

    if not contract_type:
        prompt = f"""أنت مساعد قانوني مغربي محترف وودود، متخصص في صياغة العقود، تتحدث بأسلوب طبيعي كما يفعل المساعدون الذكيون المعروفون (مثل ChatGPT أو Claude).

المحادثة حتى الآن:
{_conversation_text(state["messages"])}

لم يتضح بعد نوع العقد الذي يرغب المستخدم في صياغته من بين: عقد كراء سكني، عقد بيع، عقد شغل، عقد شركة، عقد مقاولة، عقد قرض.

اكتب رداً قصيراً (2-3 جمل كحد أقصى)، احترافياً وودوداً، ترحب فيه بالمستخدم بإيجاز إن كانت هذه بداية المحادثة، ثم تطرح سؤالاً واحداً واضحاً لمعرفة نوع العقد المطلوب. لا تستعمل قوائم أو نقط، اكتب بأسلوب محادثة طبيعي."""
        resp = llm.invoke([HumanMessage(content=prompt)])
        return resp.content.strip()

    missing = missing_fields(contract_type, collected)
    info = MOROCCAN_CONTRACT_INFO[contract_type]

    if missing:
        missing_desc = "\n".join(f"- {label}" for label in missing.values())
        prompt = f"""أنت مساعد قانوني مغربي محترف وودود، متخصص في صياغة العقود، تتحدث بأسلوب طبيعي كما يفعل المساعدون الذكيون المعروفون.

نوع العقد الذي يريده المستخدم: {info['title']}.

المحادثة حتى الآن:
{_conversation_text(state["messages"])}

المعطيات التي تم جمعها لحد الآن:
{json.dumps(collected, ensure_ascii=False) if collected else "(لا شيء بعد)"}

المعطيات الناقصة التي يجب الحصول عليها من المستخدم:
{missing_desc}

اكتب رداً قصيراً واحترافياً (3-4 جمل كحد أقصى) يشكر فيه المستخدم بإيجاز على ما قدمه إن كان قد قدم معلومات، ثم يطرح بأسلوب طبيعي وسلس سؤالاً أو سؤالين (وليس أكثر) لجمع أهم المعطيات الناقصة أولاً. لا تستعمل قوائم أو نقط أو ترقيماً، اكتب بأسلوب محادثة متدفق وودود كما يفعل مساعد محترف، وتجنب تكرار نفس الصياغة في كل مرة."""
        resp = llm.invoke([HumanMessage(content=prompt)])
        return resp.content.strip()

    # Tout est prêt
    prompt = f"""أنت مساعد قانوني مغربي محترف وودود.

نوع العقد: {info['title']}.
تم جمع جميع المعطيات اللازمة من المستخدم:
{json.dumps(collected, ensure_ascii=False)}

اكتب رسالة قصيرة واحترافية (2-3 جمل) تؤكد فيها للمستخدم أن جميع المعطيات اللازمة أصبحت جاهزة، وأنك ستشرع الآن في صياغة العقد بالتعاون مع الوكيل القانوني المتخصص في ظهير الالتزامات والعقود، بأسلوب يبعث الثقة والاحترافية."""
    resp = llm.invoke([HumanMessage(content=prompt)])
    return resp.content.strip()


# ─── Orchestration d'un tour de conversation ─────────────────────────────────
def process_user_turn(groq_api_key: str, state: ChatState, user_message: str) -> ChatState:
    """
    Traite un nouveau message utilisateur :
      1. l'ajoute à l'historique,
      2. détecte le type de contrat si pas encore fait,
      3. extrait/complète les champs si le type est connu,
      4. met à jour `ready`,
      5. génère et ajoute la réponse de l'assistant.
    Retourne le state mis à jour (à stocker dans st.session_state).
    """
    state["messages"].append({"role": "user", "content": user_message})
    logger.info("[chat_agent] Tour utilisateur reçu (%d caractères)", len(user_message))

    if not state.get("contract_type"):
        detected = detect_contract_type(groq_api_key, state["messages"])
        if detected:
            state["contract_type"] = detected

    if state.get("contract_type"):
        state["collected_fields"] = extract_fields(
            groq_api_key,
            state["contract_type"],
            state["messages"],
            state.get("collected_fields", {}),
        )
        missing = missing_fields(state["contract_type"], state["collected_fields"])
        state["ready"] = not missing
        logger.info(
            "[chat_agent] contract_type=%s  collected=%s  missing=%s  ready=%s",
            state["contract_type"],
            list(state["collected_fields"].keys()),
            list(missing.keys()),
            state["ready"],
        )
    else:
        state["ready"] = False

    reply = generate_assistant_reply(groq_api_key, state)
    state["messages"].append({"role": "assistant", "content": reply})
    return state


def build_request_text(state: ChatState) -> str:
    """
    Construit le texte de requête libre (request_text) à transmettre à
    l'orchestrateur LangGraph, en résumant le besoin exprimé par
    l'utilisateur tout au long de la conversation.
    """
    user_turns = [m["content"] for m in state["messages"] if m["role"] == "user"]
    return " — ".join(user_turns)