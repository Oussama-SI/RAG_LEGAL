# ⚖️ نظام توليد العقود القانونية المغربية

Application Streamlit de génération de contrats marocains en arabe, propulsée par **Groq API (gratuit, ultra-rapide)** + `Qwen-QwQ-32B` et une architecture RAG.

## Architecture

```
PDFs uploadés → PyMuPDF (parsing RTL) → ChromaDB in-memory (embeddings)
                                              ↓
        Requête → RAG retrieval → Groq (Qwen-QwQ-32B) → Contrat + DOCX
```

| Composant | Technologie | Coût |
|-----------|-------------|------|
| Parsing PDF | PyMuPDF | Gratuit |
| Embeddings | `multilingual-e5-large` (CPU) | Gratuit |
| Base vectorielle | ChromaDB in-memory | Gratuit |
| LLM | **Qwen-QwQ-32B via Groq** | **Gratuit** (free tier) |
| Export | python-docx | Gratuit |
| Hébergement | Streamlit Community Cloud | **Gratuit** |

## Obtenir une clé Groq API (gratuit, 2 minutes)

1. Aller sur [console.groq.com](https://console.groq.com)
2. Se connecter (Google ou GitHub)
3. **API Keys** → **"Create API Key"**
4. Copier la clé (commence par `gsk_...`)
5. **Aucune carte bancaire requise** ✅

Free tier : ~14 400 requêtes/jour, 6000 tokens/min sur Qwen-QwQ-32B.

## Déploiement Streamlit Community Cloud

```bash
# 1. Push sur GitHub
git init && git add . && git commit -m "init" && git push

# 2. share.streamlit.io → New App → sélectionner app.py → Deploy
```

La clé Groq se saisit dans la sidebar de l'app — pas besoin de secrets.

## Types de contrats supportés

- 🏠 عقد كراء سكني (Loi 67.12)
- 📜 عقد البيع (Z.O.C. art. 478-618)
- 💼 عقد الشغل (Code du travail 65.99)
- 🤝 عقد الشركة (Loi 5.96)
- 🏗️ عقد المقاولة (Z.O.C. art. 723-769)
- 💰 عقد القرض (Z.O.C. art. 860-877)

## Note légale

Les contrats générés sont des modèles à titre indicatif. Validation par un professionnel du droit marocain requise.
