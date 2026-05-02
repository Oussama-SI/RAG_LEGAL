# RAG_LEGAL

# 🇲🇦 Moroccan Legal Contract Generator — RAG-Powered Chatbot

An Arabic-first legal contract generation system using **local LLM (Ollama)**,
**ChromaDB** vector store, and **PDF/DOCX parsing** with `docling` + `PyMuPDF`.

---

## contrats_generation.ipynb parameters :

- Extrait depuis: https://drive.google.com/drive/folders/12pMw4B4H63GxqEjVtTsAWzAiFaeQcgCP
- FOLDER_ID = '12pMw4B4H63GxqEjVtTsAWzAiFaeQcgCP'

## Backends de Calcule

| Backend  | Hardware   | Performance  | Recommandation |
| -------- | ---------- | ------------ | -------------- |
| OpenBLAS | CPU        | 🐢 lent      | ❌             |
| CUDA     | NVIDIA GPU | 🚀 excellent | ✅ BEST        |
| Metal    | Apple GPU  | ⚡ bon       | ✅ Mac         |
| hipBLAS  | AMD GPU    | ⚠️ moyen     | 😐             |
| Vulkan   | multi GPU  | ⚠️           | 😐             |
| SYCL     | Intel GPU  | ⚠️           | ❌             |
| RPC      | réseau     | 🤯           | expert         |

## Architecture

```
contracts/samples/       ← Your PDF/DOCX contract corpus
      ↓
scripts/ingest.py        ← Parse → Chunk → Embed → ChromaDB
      ↓
backend/main.py          ← FastAPI: RAG retrieval + Ollama generation
      ↓
frontend/index.html      ← Chat UI (Arabic RTL, Moroccan design)
```

---

## 1. Prerequisites

### Install Ollama (local LLM — no API key needed)

```bash
# Linux/macOS
curl -fsSL https://ollama.com/install.sh | sh

# Pull Arabic-capable model (choose one):
ollama pull aya-expanse:8b        # Best Arabic support (recommended)
# or
ollama pull qwen2.5:7b            # Strong multilingual alternative
# or
ollama pull llama3.1:8b           # Fallback if RAM is limited (use 4b for 8GB RAM)
```

### Python environment

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

---

## 2. Add Your Contract Corpus

Place your Arabic contract PDFs/DOCXs in `contracts/samples/`:

```
contracts/samples/
  ├── عقد_إيجار_سكني.pdf
  ├── عقد_بيع_عقار.pdf
  ├── عقد_عمل.pdf
  ├── عقد_شراكة.pdf
  └── ...
```

A sample contract is included. Add as many as possible — more examples = better generation.

---

## 3. Ingest & Build Vector Database

```bash
python scripts/ingest.py --contracts-dir contracts/samples --db-dir contracts/chromadb
```

This will:

- Parse PDFs using PyMuPDF + docling fallback
- Extract Arabic text with proper reshaping
- Chunk contracts by clause/article
- Embed using `intfloat/multilingual-e5-large` (best Arabic support)
- Store in ChromaDB locally

---

## 4. Run the Backend

```bash
cd backend
uvicorn main:app --reload --port 8000
```

---

## 5. Open the Frontend

```bash
# Simply open in browser:
open frontend/index.html
# or serve it:
python3 -m http.server 3000 --directory frontend
```

---

## Model Recommendations (by RAM)

| RAM   | Model             | Quality    |
| ----- | ----------------- | ---------- |
| 8 GB  | `aya-expanse:8b`  | ⭐⭐⭐⭐   |
| 8 GB  | `qwen2.5:7b`      | ⭐⭐⭐⭐   |
| 16 GB | `aya-expanse:35b` | ⭐⭐⭐⭐⭐ |
| 4 GB  | `qwen2.5:3b`      | ⭐⭐⭐     |

> **Why Ollama over HuggingFace direct?** Ollama handles quantization,
> GPU/CPU offload, and Arabic tokenization automatically. For production
> use, it's far more reliable than raw `transformers` inference.

---

## API Endpoints

| Method | Endpoint          | Description                     |
| ------ | ----------------- | ------------------------------- |
| POST   | `/chat`           | Chat + generate contract        |
| POST   | `/generate`       | Generate full contract directly |
| GET    | `/contract-types` | List available contract types   |
| POST   | `/ingest`         | Ingest new contract files       |
| GET    | `/health`         | Check Ollama + DB status        |
