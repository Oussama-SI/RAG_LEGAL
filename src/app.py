"""
app.py
========
Interface Streamlit du système de génération de contrats marocains.
Délègue tout à l'orchestrateur LangGraph :
  - agent juridique  → API lois   (POST /ask   sur ai-juriste-lois-ngrok.ipynb)
  - agent rédacteur  → API contrats (POST /retrieve sur contract-rag.ipynb) + Groq
  - boucle de validation Groq
"""

import uuid
from datetime import datetime

import streamlit as st
from langgraph.checkpoint.memory import MemorySaver

from contract_config import MOROCCAN_CONTRACT_INFO, get_required_fields
from docx_export import contract_to_docx_bytes
from orchestrator import ContractOrchestrator
from rag_clients import RagApiError, contract_health, law_health

# ─── Page config ─────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="نظام العقود المغربية",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  html, body, [class*="css"] { direction: rtl; }
  .main { background: #f7f5f0; }
  h1, h2, h3 { color: #F77C00 !important; }
  .contract-box {
    background: white; border: 1px solid #d0c8b8; border-radius: 12px;
    padding: 2rem; font-size: 1.05rem; line-height: 2;
    direction: rtl; text-align: right; white-space: pre-wrap;
    box-shadow: 0 4px 20px rgba(0,0,0,0.06);
  }
  .badge { display: inline-block; padding: 0.2rem 0.8rem; border-radius: 20px;
           font-size: 0.8rem; font-weight: 600; margin: 0.2rem; }
  .badge-green  { background: #e8f5e9; color: #1a7a3c; }
  .badge-gold   { background: #fdf5e0; color: #8b6914; }
  .badge-orange { background: #fff3e0; color: #e65100; }
</style>
""", unsafe_allow_html=True)

# ─── État de session ──────────────────────────────────────────────────────────
st.session_state.setdefault("thread_id", str(uuid.uuid4()))
st.session_state.setdefault("result", None)
st.session_state.setdefault("history", [])


@st.cache_resource
def get_checkpointer():
    return MemorySaver()


def get_orchestrator(law_url: str, contract_url: str, groq_key: str) -> ContractOrchestrator:
    return ContractOrchestrator(law_url, contract_url, groq_key, checkpointer=get_checkpointer())


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown("### نظام العقود المغربية")

    st.markdown("**LLM API**")
    groq_api_key = st.text_input(
        "Groq Key", type="password", placeholder="gsk_...", label_visibility="collapsed"
    )

    st.divider()
    st.markdown("**API أمثلة العقود** *(contract-rag.ipynb)*")
    contract_api_url = st.text_input(
        "Contract API URL",
        value=st.session_state.get("contract_api_url", ""),
        placeholder="https://xxxx.ngrok-free.app",
        label_visibility="collapsed",
        key="contract_api_url",
    ).rstrip("/")
    if st.button("🔌 اختبار API الأمثلة", use_container_width=True):
        try:
            status = contract_health(contract_api_url)
            chunks = status.get("chunks_indexed", 0)
            gpu = "GPU ✓" if status.get("gpu_available") else "CPU"
            st.markdown(
                f'<span class="badge badge-green">✓ {chunks} chunks — {gpu}</span>',
                unsafe_allow_html=True,
            )
        except RagApiError as e:
            st.error(str(e))

    st.divider()
    st.markdown("**API اللوائح القانونية** *(ai-juriste-lois-ngrok.ipynb)*")
    law_api_url = st.text_input(
        "Law API URL",
        value=st.session_state.get("law_api_url", ""),
        placeholder="https://yyyy.ngrok-free.app",
        label_visibility="collapsed",
        key="law_api_url",
    ).rstrip("/")
    if st.button("🔌 اختبار API اللوائح", use_container_width=True):
        try:
            status = law_health(law_api_url)
            checks = status.get("checks", {})
            all_ok = all(checks.values()) if checks else status.get("status") == "ok"
            badge_cls = "badge-green" if all_ok else "badge-orange"
            label = "✓ متصل" if all_ok else "⚠️ مخفَّض"
            # Afficher les composants manquants si dégradé
            missing = [k for k, v in checks.items() if not v]
            detail = f" — مفقود: {', '.join(missing)}" if missing else ""
            st.markdown(
                f'<span class="badge {badge_cls}">{label}{detail}</span>',
                unsafe_allow_html=True,
            )
        except RagApiError as e:
            st.error(f"{e}")
            st.caption("طبيعي إذا كان الـ kernel غير نشط — الوكيل سيعمل بدون سياق قانوني.")

# ─── Formulaire principal ─────────────────────────────────────────────────────
st.markdown("<h1 style='text-align:center;'>نظام العقود القانونية المغربية</h1>", unsafe_allow_html=True)

contract_type = st.selectbox(
    "نوع العقد",
    options=list(MOROCCAN_CONTRACT_INFO.keys()),
    format_func=lambda k: f"{MOROCCAN_CONTRACT_INFO[k]['icon']} {MOROCCAN_CONTRACT_INFO[k]['title']}",
)
info = MOROCCAN_CONTRACT_INFO[contract_type]

with st.expander("البنود الإلزامية لهذا العقد"):
    for cl in info["clauses"]:
        st.write(f"• {cl}")

required_fields = get_required_fields(contract_type)

with st.form("contract_form"):
    st.markdown("**معطيات العقد**")
    cols = st.columns(2)
    field_inputs = {}
    for i, (key, label) in enumerate(required_fields.items()):
        field_inputs[key] = cols[i % 2].text_input(label, key=f"field_{contract_type}_{key}")

    user_request = st.text_area(
        "تفاصيل إضافية (اختياري — تُحسّن جودة استرجاع الوكيلين)",
        height=100,
    )
    submitted = st.form_submit_button("توليد العقد", use_container_width=True, type="primary")

if submitted:
    if not groq_api_key:
        st.error("أدخل مفتاح Groq API في الشريط الجانبي أولاً.")
    else:
        party_info = {k: v.strip() for k, v in field_inputs.items() if v and v.strip()}
        oc = get_orchestrator(law_api_url, contract_api_url, groq_api_key)
        with st.spinner("الوكيل القانوني يستعلم ق.ل.ع + الوكيل المحرر يبحث عن أمثلة مرجعية…"):
            st.session_state.result = oc.start(
                st.session_state.thread_id, user_request, contract_type, party_info
            )
        st.session_state.last_contract_type = contract_type

# ─── Champs manquants (interruption LangGraph) ───────────────────────────────
result = st.session_state.result
if result and result.get("status") == "needs_input":
    st.warning("⚠️ بعض المعطيات الإلزامية غير مكتملة — أكملها للمتابعة:")
    with st.form("missing_fields_form"):
        provided = {}
        for key, label in result["fields"].items():
            provided[key] = st.text_input(label, key=f"missing_{key}")
        resume_submitted = st.form_submit_button("استئناف التوليد", type="primary")
    if resume_submitted:
        oc = get_orchestrator(law_api_url, contract_api_url, groq_api_key)
        with st.spinner("🤖 استئناف…"):
            st.session_state.result = oc.resume(st.session_state.thread_id, provided)
        st.rerun()

# ─── Résultat final ────────────────────────────────────────────────────────────
elif result and result.get("status") == "done":
    st.divider()
    metrics = result.get("metrics", {})

    # ── Métriques principales ────────────────────────────────────────────────
    cols = st.columns(5)
    cols[0].metric("عدد التكرارات", metrics.get("iterations", 0))
    cols[1].metric("الامتثال القانوني", "✅" if metrics.get("validation_passed") else "❌")
    cols[2].metric("زمن المعالجة", f"{metrics.get('elapsed_seconds', 0)} ث")
    cols[3].metric(
        "فصول ق.ل.ع المسترجعة",
        metrics.get("law_articles_count", 0),
        help="عدد الفصول التي أرجعها الوكيل القانوني من ق.ل.ع",
    )
    cols[4].metric(
        "أمثلة العقود",
        metrics.get("contract_chunks_count", 0),
        help="عدد المقاطع المرجعية التي أرجعها وكيل الأمثلة",
    )

    # ── Avertissements des agents ─────────────────────────────────────────────
    if metrics.get("law_hors_scope"):
        st.warning("⚠️ الوكيل القانوني: الطلب خارج نطاق ق.ل.ع — استُخدمت القواعد العامة.")
    if metrics.get("law_warning"):
        st.info(f"ℹ️ الوكيل القانوني غير متاح: {metrics['law_warning']}")
    if metrics.get("contract_warning"):
        st.info(f"ℹ️ وكيل الأمثلة: {metrics['contract_warning']}")

    # ── Métriques RAG détaillées ──────────────────────────────────────────────
    with st.expander("📊 مقاييس RAG (الوكيلان)"):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**وكيل القانون — API ق.ل.ع** *(ai-juriste-lois-ngrok.ipynb)*")
            law_rag = metrics.get("law_rag", {})
            if "error" in law_rag:
                st.warning(law_rag["error"])
            else:
                # Métriques clés en visuel avant le JSON brut
                r1, r2, r3 = st.columns(3)
                r1.metric("طلبات كلية", law_rag.get("total_requests", "—"))
                r2.metric("متوسط الزمن", f"{law_rag.get('avg_time_s', '—')} ث")
                r3.metric("خارج النطاق", law_rag.get("total_out_of_scope", "—"))
                with st.expander("JSON كامل"):
                    st.json(law_rag)
        with c2:
            st.markdown("**وكيل الأمثلة — API العقود** *(contract-rag.ipynb)*")
            contract_rag = metrics.get("contract_rag", {})
            if "note" in contract_rag:
                st.caption(f"ℹ️ {contract_rag['note']}")
            elif "error" in contract_rag:
                st.warning(contract_rag["error"])
            else:
                st.json(contract_rag)

    # ── Contrat généré ────────────────────────────────────────────────────────
    st.markdown("### نص العقد")
    st.markdown(f'<div class="contract-box">{result["contract"]}</div>', unsafe_allow_html=True)

    ctype = st.session_state.get("last_contract_type", contract_type)
    ctitle = MOROCCAN_CONTRACT_INFO.get(ctype, {}).get("title", "عقد")
    docx_bytes = contract_to_docx_bytes(result["contract"], ctitle, ctype)
    st.download_button(
        "📥 تحميل DOCX",
        data=docx_bytes,
        file_name=f"{ctitle}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )