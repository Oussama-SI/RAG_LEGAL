import re
import requests
import fitz  # PyMuPDF (upload PDF local optionnel)


#  ─── PDF parsing ──────────────────────────────────────────────────────────────
def parse_pdf_bytes(pdf_bytes: bytes) -> str:
    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    pages = []
    for i, page in enumerate(doc):
        text = page.get_text('text', flags=fitz.TEXT_PRESERVE_WHITESPACE)
        if text.strip():
            pages.append(f'[صفحة {i+1}]\n{text}')
    doc.close()
    return clean_pdf_text('\n\n'.join(pages))

def detect_contract_type(text: str) -> str:
    CONTRACT_KEYWORDS = {
        'عقد_إيجار':  ['إيجار', 'مستأجر', 'مؤجر', 'أجرة', 'كراء', 'مكتري', 'مكري'],
        'عقد_بيع':    ['بيع', 'مشتري', 'بائع', 'ثمن', 'ملكية', 'شراء'],
        'عقد_عمل':    ['عمل', 'عامل', 'صاحب العمل', 'راتب', 'أجر', 'توظيف', 'أجير', 'مشغل'],
        'عقد_شراكة':  ['شراكة', 'شريك', 'حصة', 'أرباح', 'خسائر', 'شركة'],
        'عقد_مقاولة': ['مقاولة', 'مقاول', 'أشغال', 'بناء', 'تشييد'],
        'عقد_قرض':    ['قرض', 'مقترض', 'مقرض', 'فائدة', 'دين', 'سلفة'],
    }
    sample = normalize_arabic(text[:3000])
    scores = {t: sum(kw in sample for kw in kws) for t, kws in CONTRACT_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else 'عقد_عام'


# ─── Arabic text utilities ────────────────────────────────────────────────────
def normalize_arabic(text: str) -> str:
    text = re.sub(r'ـ+', '', text)
    text = re.sub(r'[إأآا]', 'ا', text)
    text = re.sub(r'[\u064B-\u065F\u0670]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

def clean_pdf_text(text: str) -> str:
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    return '\n'.join(lines)

ARTICLE_RE = re.compile(
    r'(البند\s+(?:الأول|الثاني|الثالث|الرابع|الخامس|السادس|السابع|الثامن|التاسع|العاشر'
    r'|الحادي عشر|الثاني عشر|[\d\u0660-\u0669]+)'
    r'|المادة\s+(?:الأولى|الثانية|الثالثة|[\d\u0660-\u0669]+)'
    r'|الفصل\s+(?:الأول|الثاني|[\d\u0660-\u0669]+)'
    r'|أولاً|ثانياً|ثالثاً|رابعاً|خامساً)',
    re.UNICODE
)

def chunk_contract(text: str, max_size: int = 1200, min_size: int = 150) -> list:
    parts = ARTICLE_RE.split(text)
    chunks = []
    if len(parts) > 3:
        cur_art, cur_txt = 'مقدمة', ''
        for part in parts:
            if not part:
                continue
            if ARTICLE_RE.match(part):
                if len(cur_txt.strip()) >= min_size:
                    chunks.append({'text': cur_txt.strip(), 'article': cur_art})
                cur_art, cur_txt = part.strip(), part
            else:
                cur_txt += ' ' + part
                if len(cur_txt) > max_size:
                    chunks.append({'text': cur_txt[:max_size].strip(), 'article': cur_art})
                    cur_txt = cur_txt[max_size:]
        if len(cur_txt.strip()) >= min_size:
            chunks.append({'text': cur_txt.strip(), 'article': cur_art})
    else:
        step = max_size // 6
        words = text.split()
        for i in range(0, len(words), step - step // 5):
            chunk = ' '.join(words[i:i + step])
            if len(chunk) >= min_size:
                chunks.append({'text': chunk, 'article': f'قسم_{i // step + 1}'})
    return chunks


# ─── Kaggle RAG API helpers ───────────────────────────────────────────────────
def kaggle_health(api_url: str) -> dict:
    """Vérifie que le serveur Kaggle est actif."""
    try:
        r = requests.get(f"{api_url}/health", timeout=8)
        return r.json() if r.status_code == 200 else {}
    except Exception:
        return {}

def kaggle_retrieve(st, api_url: str, query: str, contract_type: str, n: int = 5) -> list:
    """Appelle /retrieve sur le serveur Kaggle."""
    try:
        r = requests.post(
            f"{api_url}/retrieve",
            json={"query": query, "contract_type": contract_type, "n": n},
            timeout=20
        )
        if r.status_code == 200:
            return r.json().get("chunks", [])
    except Exception as e:
        st.warning(f"RAG Kaggle non disponible: {e}")
    return []

def kaggle_generate(api_url: str, prompt: str) -> str | None:
    """Appelle /generate sur le serveur Kaggle (LLM local GPU)."""
    try:
        r = requests.post(
            f"{api_url}/generate",
            json={"prompt": prompt, "max_new_tokens": 2500},
            timeout=120
        )
        if r.status_code == 200:
            return r.json().get("contract", "")
    except Exception:
        return None
