"""
نظام توليد العقود القانونية المغربية — Streamlit Community Cloud
Architecture: Kaggle RAG Server (FastAPI+ngrok) + Groq API (génération) → DOCX export
"""

import streamlit as st
from groq import Groq
# import chromadb
# from sentence_transformers import SentenceTransformer
from datetime import datetime
# import hashlib

from env_conf import init_state
from _prompt import SYSTEM_PROMPT, MOROCCAN_CONTRACT_INFO
from docs_generation import contract_to_docx_bytes
from test_quality import evaluate_contract_quality
from rag_conf import (
    normalize_arabic, kaggle_retrieve, kaggle_generate,
    kaggle_health, clean_pdf_text
    )

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="نظام العقود المغربية",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&family=Cairo:wght@300;400;600;700&display=swap');

  html, body, [class*="css"] { direction: rtl; }

  .main { background: #f7f5f0; }

  h1, h2, h3 {
    font-family: 'Amiri', serif !important;
    color: #1a3a5c !important;
  }

  .stButton > button {
    font-family: 'Cairo', sans-serif !important;
    background: linear-gradient(135deg, #1a3a5c 0%, #2c5f8a 100%);
    color: white;
    border: none;
    border-radius: 8px;
    padding: 0.6rem 1.5rem;
    font-size: 1rem;
    font-weight: 600;
    transition: all 0.2s ease;
    box-shadow: 0 2px 8px rgba(26,58,92,0.25);
  }
  .stButton > button:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 16px rgba(26,58,92,0.35);
  }

  .contract-box {
    background: white;
    border: 1px solid #d0c8b8;
    border-radius: 12px;
    padding: 2rem;
    font-family: 'Amiri', serif;
    font-size: 1.1rem;
    line-height: 2;
    direction: rtl;
    text-align: right;
    box-shadow: 0 4px 20px rgba(0,0,0,0.06);
    white-space: pre-wrap;
  }

  .metric-card {
    background: white;
    border-radius: 10px;
    padding: 1rem 1.5rem;
    text-align: center;
    border: 1px solid #e8e0d0;
    box-shadow: 0 2px 10px rgba(0,0,0,0.05);
  }

  .score-high { color: #1a7a3c; font-weight: 700; font-size: 1.4rem; }
  .score-med  { color: #c07020; font-weight: 700; font-size: 1.4rem; }
  .score-low  { color: #c02020; font-weight: 700; font-size: 1.4rem; }

  .sidebar-header {
    font-family: 'Amiri', serif;
    font-size: 1.3rem;
    font-weight: 700;
    color: #1a3a5c;
    border-bottom: 2px solid #c0a060;
    padding-bottom: 0.5rem;
    margin-bottom: 1rem;
  }

  .badge {
    display: inline-block;
    padding: 0.2rem 0.8rem;
    border-radius: 20px;
    font-size: 0.8rem;
    font-weight: 600;
    margin: 0.2rem;
  }
  .badge-green { background: #e8f5e9; color: #1a7a3c; }
  .badge-blue  { background: #e3eef7; color: #1a3a5c; }
  .badge-gold  { background: #fdf5e0; color: #8b6914; }
</style>
""", unsafe_allow_html=True)

# ─── Session state init ───────────────────────────────────────────────────────
init_state = init_state(st)

# ─── Index PDFs : délégué au serveur Kaggle ──────────────────────────────────
# L'indexation se fait dans le notebook Kaggle (cellule 5).
# Streamlit ne fait qu'appeler l'API /retrieve.

# ═══════════════════════════════════════════════════════════════════════════════
# RAG retrieval — délégué au serveur Kaggle
# ═══════════════════════════════════════════════════════════════════════════════

def retrieve(query: str, contract_type: str = None, n: int = 5) -> list:
    api_url = st.session_state.get('kaggle_api_url', '').rstrip('/')
    if not api_url:
        return []
    return kaggle_retrieve(st, api_url, query, contract_type or '', n)

# ─── Build RAG prompt ─────────────────────────────────────────────────────────
def build_rag_prompt(request: str, contract_type: str, info: dict, context_chunks: list) -> str:
    ctx = ''
    if context_chunks:
        ctx = '\n\n## أمثلة مرجعية من عقود مغربية فعلية:\n'
        for i, c in enumerate(context_chunks[:4]):
            ctx += f'\n### مرجع {i+1} ({c["meta"].get("article", "")}):\n'
            ctx += c['text'][:600] + '...\n'

    clauses_list = '\n'.join(f'- {cl}' for cl in info.get('clauses', []))
    parties_list = '\n'.join(f'- {p}' for p in info.get('parties', []))

    return f"""## نوع العقد المطلوب: {info.get('title', contract_type)}
        ## القانون المغربي المنطبق: {info.get('law', 'القانون المدني المغربي')}

        ## أطراف العقد:
        {parties_list}

        ## البنود الإلزامية الواجب تضمينها:
        {clauses_list}

        {ctx}

        ## متطلبات العقد المحددة:
        {request}

        اكتب العقد القانوني المغربي الكامل والمفصّل مع جميع البنود:"""

# ─── Generate contract via Groq API (gratuit) ────────────────────────────────
def generate_contract_groq(prompt: str, api_key: str) -> str:
    client = Groq(api_key=api_key)
    chat_completion = client.chat.completions.create(
        # model="qwen/qwen3-32b",
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        max_tokens=4096,
        temperature=0.3,
        top_p=0.9,
    )
    return chat_completion.choices[0].message.content


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMLIT UI
# ═══════════════════════════════════════════════════════════════════════════════

# ─── Sidebar
with st.sidebar:
    st.markdown('<div class="sidebar-header">⚖️ نظام العقود المغربية</div>', unsafe_allow_html=True)

    # ── Groq API key ──
    st.markdown("**🔑 مفتاح Groq API (مجاني)**")
    api_key = st.text_input(
        "Groq Key", type="password", placeholder="gsk_...",
        label_visibility="collapsed"
    )
    if api_key:
        st.markdown('<span class="badge badge-green">✓ مفتاح Groq مُدخل</span>', unsafe_allow_html=True)

    st.divider()

    # ── Kaggle RAG server ──
    st.markdown("**🖥️ خادم RAG — Kaggle (ngrok)**")
    kaggle_url_input = st.text_input(
        "URL ngrok",
        value=st.session_state.get('kaggle_api_url', ''),
        placeholder="https://xxxx-xx-xx.ngrok-free.app",
        label_visibility="collapsed"
    )
    if kaggle_url_input != st.session_state.get('kaggle_api_url', ''):
        st.session_state.kaggle_api_url = kaggle_url_input.rstrip('/')
        st.session_state.kaggle_status = {}

    if st.button("🔌 Tester la connexion", use_container_width=True):
        url = st.session_state.get('kaggle_api_url', '')
        if url:
            with st.spinner("Vérification..."):
                st.session_state.kaggle_status = kaggle_health(url)
        else:
            st.warning("Entrez l'URL ngrok d'abord")

    status = st.session_state.get('kaggle_status', {})
    if status.get("status") == "ok":
        st.markdown(f'<span class="badge badge-green">✓ Connecté — {status.get("chunks_indexed",0)} chunks indexés</span>', unsafe_allow_html=True)
        if status.get("gpu_available"):
            st.markdown('<span class="badge badge-gold">⚡ GPU Kaggle actif</span>', unsafe_allow_html=True)
    elif status:
        st.error("✗ Serveur non joignable — vérifiez l'URL et le notebook Kaggle")
    else:
        st.caption("Non connecté → RAG désactivé, génération sans contexte")

    st.divider()

    # ── Generation mode ──
    st.markdown("**⚙️ Mode de génération**")
    use_kaggle_llm = st.toggle(
        "LLM Kaggle GPU (Qwen-32)",
        value=False,
        help="Activé = génération via Qwen-7B sur Kaggle. Désactivé = Groq API cloud."
    )
    if use_kaggle_llm:
        st.markdown('<span class="badge badge-gold">🖥️ Qwen-7B — Kaggle GPU</span>', unsafe_allow_html=True)
    else:
        st.markdown('<span class="badge badge-blue">☁️ Groq API — cloud</span>', unsafe_allow_html=True)

    st.divider()
    st.markdown("""
    <small style="color:#888; font-family:'Cairo',sans-serif; direction:rtl; display:block;">
    <b>Architecture:</b><br>
    📡 RAG ← Kaggle FastAPI + ngrok<br>
    🤖 LLM ← Groq (cloud) ou Kaggle GPU<br>
    📄 Export ← python-docx RTL
    </small>
    """, unsafe_allow_html=True)

# ─── Main content
st.markdown("""
<h1 style="text-align:center; font-family:'Amiri',serif; font-size:2.2rem; margin-bottom:0.2rem;">
  نظام توليد العقود القانونية المغربية
</h1>
<p style="text-align:center; color:#666; font-family:'Cairo',sans-serif; margin-bottom:2rem;">
  مدعوم بالذكاء الاصطناعي • متوافق مع التشريع المغربي النافذ
</p>
""", unsafe_allow_html=True)

# ─── Form
col1, col2 = st.columns([1, 2])

with col1:
    st.markdown("**نوع العقد**")
    contract_type = st.selectbox(
        "نوع العقد",
        options=list(MOROCCAN_CONTRACT_INFO.keys()),
        format_func=lambda k: f"{MOROCCAN_CONTRACT_INFO[k]['icon']} {MOROCCAN_CONTRACT_INFO[k]['title']}",
        label_visibility="collapsed"
    )

    info = MOROCCAN_CONTRACT_INFO[contract_type]

    with st.expander("📋 البنود المطلوبة"):
        for cl in info['clauses']:
            st.write(f"• {cl}")

    with st.expander("⚖️ القانون المنطبق"):
        st.write(info['law'])

with col2:
    st.markdown("**متطلبات العقد** (اكتب التفاصيل بالعربية)")
    user_request = st.text_area(
        "متطلبات العقد",
        height=220,
        placeholder="""مثال: قم بصياغة عقد كراء سكني بالمواصفات التالية:
- المكري: السيد أحمد بنعلي، المقيم بالدار البيضاء...
- المكتري: السيد يوسف الأمراني...
- العقار: شقة من 3 غرف، الطابق الثاني...
- مبلغ الكراء: 4500 درهم شهرياً
- مدة الكراء: سنة واحدة من 1 يناير 2025""",
        label_visibility="collapsed"
    )

generate_col, _ = st.columns([1, 3])
with generate_col:
    generate_btn = st.button("✨ توليد العقد", type="primary", use_container_width=True)

# ─── Generation
if generate_btn:
    if not user_request.strip():
        st.error("⚠️ الرجاء كتابة متطلبات العقد.")
    else:
        with st.spinner("🔍 استرجاع السياق من قاعدة البيانات..."):
            context = retrieve(user_request, contract_type, n=5)

        rag_info = f"تم استرجاع **{len(context)}** مقطع مرجعي"
        if context:
            best_score = context[0]['score']
            rag_info += f" (أفضل تشابه: {best_score:.0%})"
        st.info(rag_info)

        prompt = build_rag_prompt(user_request, contract_type, info, context)

        if use_kaggle_llm:
            spinner_msg = "⚙️ جاري توليد العقد عبر Kaggle GPU (Qwen-7B)..."
        else:
            spinner_msg = "⚙️ جاري توليد العقد عبر Groq API..."

        with st.spinner(spinner_msg):
            try:
                if use_kaggle_llm:
                    kaggle_url = st.session_state.get('kaggle_api_url', '')
                    if not kaggle_url:
                        st.error("⚠️ URL Kaggle non configurée — désactivez le toggle ou entrez l'URL.")
                        st.stop()
                    contract_text = kaggle_generate(kaggle_url, prompt)
                    if not contract_text:
                        st.error("Le serveur Kaggle n'a pas répondu. Vérifiez que le notebook tourne.")
                        st.stop()
                else:
                    if not api_key:
                        st.error("⚠️ الرجاء إدخال مفتاح Groq API في الشريط الجانبي.")
                        st.stop()
                    contract_text = generate_contract_groq(prompt, api_key)
                st.session_state.last_contract = contract_text
                st.session_state.last_contract_type = contract_type
                st.session_state.last_metrics = evaluate_contract_quality(contract_text, contract_type)
                st.session_state.generation_history.append({
                    'type': contract_type,
                    'title': info['title'],
                    'date': datetime.now().strftime('%H:%M:%S'),
                    'score': st.session_state.last_metrics['overall_score']
                })
                st.success("✅ تم توليد العقد بنجاح!")
            except Exception as e:
                st.error(f"خطأ في توليد العقد: {str(e)}")

# ─── Display result
if st.session_state.last_contract:
    st.divider()

    # Quality metrics
    m = st.session_state.last_metrics
    score = m.get('overall_score', 0)
    score_class = 'score-high' if score >= 75 else ('score-med' if score >= 50 else 'score-low')

    metrics_cols = st.columns(6)
    checks = [
        ('بسم الله', 'bismillah'),
        ('ترويسة المغرب', 'maroc_header'),
        ('الأطراف', 'has_parties'),
        ('التوقيع', 'has_signature'),
        ('تاريخ', 'has_date'),
        ('مرجع قانوني', 'has_law_ref'),
    ]
    for col, (label, key) in zip(metrics_cols, checks):
        val = m.get(key, False)
        icon = '✅' if val else '❌'
        col.markdown(f"""
        <div class="metric-card">
          <div style="font-size:1.4rem">{icon}</div>
          <div style="font-family:'Cairo',sans-serif; font-size:0.8rem; color:#555">{label}</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown(f"""
    <div style="text-align:center; margin:1rem 0; font-family:'Cairo',sans-serif;">
      البنود المغطاة: <b>{m.get('clauses_found',0)}/{m.get('clauses_total',0)}</b>
      &nbsp;|&nbsp; عدد الكلمات: <b>{m.get('word_count',0):,}</b>
      &nbsp;|&nbsp; نسبة النص العربي: <b>{m.get('arabic_ratio',0)*100:.0f}%</b>
      &nbsp;|&nbsp; <span class="{score_class}">النقاط: {score}%</span>
    </div>
    """, unsafe_allow_html=True)

    # Contract display
    st.markdown("### 📄 نص العقد")
    st.markdown(
        f'<div class="contract-box">{st.session_state.last_contract}</div>',
        unsafe_allow_html=True
    )

    # Export actions
    st.markdown("")
    dl_col1, dl_col2 = st.columns([1, 3])

    with dl_col1:
        ctype = st.session_state.last_contract_type
        ctitle = MOROCCAN_CONTRACT_INFO.get(ctype, {}).get('title', 'عقد')

        docx_bytes = contract_to_docx_bytes(
            st.session_state.last_contract,
            ctitle,
            ctype
        )
        filename = f"{ctitle}_{datetime.now().strftime('%Y%m%d_%H%M')}.docx"

        st.download_button(
            label="📥 تحميل DOCX",
            data=docx_bytes,
            file_name=filename,
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            use_container_width=True
        )

    with dl_col2:
        txt_bytes = st.session_state.last_contract.encode('utf-8')
        st.download_button(
            label="📋 تحميل نص (.txt)",
            data=txt_bytes,
            file_name=f"{ctitle}.txt",
            mime="text/plain",
            use_container_width=False
        )

# ─── History
if st.session_state.generation_history:
    st.divider()
    with st.expander(f"📊 سجل التوليد ({len(st.session_state.generation_history)} عقد)"):
        for entry in reversed(st.session_state.generation_history):
            score = entry['score']
            color = '#1a7a3c' if score >= 75 else ('#c07020' if score >= 50 else '#c02020')
            st.markdown(
                f"🕐 `{entry['date']}` — **{entry['title']}** — "
                f"<span style='color:{color}; font-weight:700'>{score}%</span>",
                unsafe_allow_html=True
            )
