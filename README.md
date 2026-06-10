# ⚖️ نظام توليد العقود القانونية المغربية

Application Streamlit de génération de contrats marocains en arabe, propulsée par **Groq API (gratuit, ultra-rapide)** + `Qwen-QwQ-32B` et une architecture RAG.

## Architecture

```
PDFs uploadés → PyMuPDF (parsing RTL) → ChromaDB in-memory (embeddings)
                                              ↓
        Requête → RAG retrieval → Groq (Qwen-QwQ-32B) → Contrat + DOCX
```

| Composant        | Technologie                   | Coût                    |
| ---------------- | ----------------------------- | ----------------------- |
| Parsing PDF      | PyMuPDF                       | Gratuit                 |
| Embeddings       | `multilingual-e5-large` (CPU) | Gratuit                 |
| Base vectorielle | ChromaDB in-memory            | Gratuit                 |
| LLM              | **Qwen-QwQ-32B via Groq**     | **Gratuit** (free tier) |
| Export           | python-docx                   | Gratuit                 |
| Hébergement      | Streamlit Community Cloud     | **Gratuit**             |

## Obtenir une clé Groq API (gratuit, 2 minutes)

1. Aller sur [console.groq.com](https://console.groq.com)
2. Se connecter (Google ou GitHub)
3. **API Keys** → **"Create API Key"**
4. Copier la clé (commence par `gsk_...`)
5. **Aucune carte bancaire requise** ✅

Free tier : ~14 400 requêtes/jour, 6000 tokens/min sur Qwen-QwQ-32B.

## Déploiement Streamlit Community Cloud

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

# نظام توليد العقود القانونية المغربية

## Moroccan Legal Contract Generator

Application Streamlit de generation de contrats marocains en arabe, propulsee par l'API Groq (gratuite) et une architecture RAG optionnelle.

---

## Table des matieres

1. Architecture
2. Prerequis
3. Obtenir une cle Groq API
4. Option 1: Execution locale
5. Option 2: Deployment Streamlit Community Cloud
6. Option 3: Activation du RAG (serveur Kaggle)
7. Types de contrats supportes
8. Exemple de prompt
9. Structure du projet
10. Dependances
11. Depannage
12. Note legale

---

## Architecture

L'application se decompose en deux parties independantes.

Partie 1 : Interface Streamlit (obligatoire)

- Role : Interface utilisateur, appel API, generation contrat, export DOCX
- Technologie : Streamlit
- Hebergement : Local ou Streamlit Cloud

Partie 2 : Serveur RAG (optionnel)

- Role : Indexation PDF, embeddings, recherche contextuelle
- Technologie : FastAPI + ChromaDB + Ngrok
- Hebergement : Kaggle (GPU T4)

Flux de donnees :

1. L'utilisateur saisit sa demande dans Streamlit
2. Streamlit appelle l'API Groq (ou d'abord le serveur RAG)
3. Groq genere le contrat
4. Streamlit affiche le resultat et permet l'export DOCX

---

## Prerequis

- Python 3.12 ou superieur
- Compte Groq (gratuit)
- Optionnel : Compte Kaggle pour le RAG
- Optionnel : Compte GitHub pour le deploiement cloud

---

## Obtenir une cle Groq API

Etape 1 : Aller sur https://console.groq.com

Etape 2 : Se connecter avec Google ou GitHub

Etape 3 : Cliquer sur "API Keys" puis "Create API Key"

Etape 4 : Donner un nom et copier la cle (commence par gsk\_...)

Etape 5 : Aucune carte bancaire requise

Free tier : 14 400 requetes par jour, 6000 tokens par minute.

---

## Option 1: Execution locale

Etape 1 : Cloner le depot

git clone https://github.com/votre-username/contract-generator
cd contract-generator

Etape 2 : Creer un environnement virtuel

python -m venv .venv

Linux/Mac : source .venv/bin/activate
Windows : .venv\Scripts\activate

Etape 3 : Installer les dependances

pip install -r requirements.txt

Etape 4 : Lancer l'application

streamlit run app.py

Etape 5 : Ouvrir le navigateur a http://localhost:8501

Etape 6 : Dans la sidebar, entrer votre cle Groq API

Etape 7 : Selectionner le type de contrat et decrire le contrat en arabe

Etape 8 : Cliquer sur "توليد العقد"

---

## Option 2: Deployment Streamlit Community Cloud

Etape 1 : Creer un depot public sur GitHub

git init
git add app.py requirements.txt
git commit -m "Initial commit"
git remote add origin https://github.com/votre-username/contract-generator
git push -u origin main

Etape 2 : Aller sur https://share.streamlit.io

Etape 3 : Cliquer sur "New app"

Etape 4 : Connecter votre compte GitHub

Etape 5 : Selectionner le depot, la branche (main) et le fichier (app.py)

Etape 6 : Cliquer sur "Deploy"

Etape 7 : L'application sera disponible a une URL du type https://nom.streamlit.app

Etape 8 : Dans l'interface, entrer votre cle Groq API dans la sidebar

Note : La cle API n'est pas stockee sur le serveur, elle est saisie par l'utilisateur.

---

## Option 3: Activation du RAG (serveur Kaggle)

Le RAG permet d'ajouter un contexte juridique pertinent a partir de PDFs existants.

Etape 1 : Ouvrir le notebook contract-rag.ipynb sur Kaggle

Etape 2 : Activer le GPU : Settings -> Accelerator -> GPU T4

Etape 3 : Executer toutes les cellules du notebook

Etape 4 : Une URL ngrok apparaîtra de la forme https://xxxx-xx-xx.ngrok-free.dev

Etape 5 : Copier cette URL

Etape 6 : Dans Streamlit, coller l'URL dans le champ "URL Kaggle" de la sidebar

Etape 7 : Cliquer sur "Tester la connexion"

Etape 8 : Si le message "Connecte" apparait, le RAG est actif

Note : Le notebook Kaggle doit rester execute pendant toute la session.

---

## Types de contrats supportes

1. عقد كراء سكني (Contrat de location residentielle) - Loi 67.12

2. عقد البيع (Contrat de vente) - Z.O.C. art. 478-618

3. عقد الشغل (Contrat de travail) - Code du travail 65.99

4. عقد الشركة (Contrat de societe) - Loi 5.96

5. عقد المقاولة (Contrat d'entreprise) - Z.O.C. art. 723-769

6. عقد القرض (Contrat de pret) - Z.O.C. art. 860-877

---

## Exemple de prompt

Copier ce texte dans le champ "متطلبات العقد" :

عقد كراء سكني في الدار البيضاء:

- المكري: السيد أحمد بنعلي، حامل بطاقة التعريف AB123456، العنوان: الدار البيضاء، عين الذئاب

- المكتري: السيد يوسف الأمراني، حامل بطاقة التعريف CD789012، العنوان: الرباط، حي الرياض

- العقار: شقة من 3 غرف، الطابق الثاني، عمارة الفتح، شارع محمد الخامس، الدار البيضاء

- مبلغ الكراء: 4500 درهم شهريا

- مدة الكراء: سنة واحدة، تبدأ من 1 يناير 2025

- الضمان: شهران (9000 درهم)

---

## Structure du projet

contract-generator/
|
├── app.py
├── requirements.txt
├── README.md
|
└── contract-rag.ipynb (optionnel)

---

## Dependances

Contenu du fichier requirements.txt :

streamlit==1.35.0
groq==0.9.0
requests==2.31.0
pymupdf==1.24.0
python-docx==1.1.0
protobuf==3.20.3
sentence-transformers==2.2.2
chromadb==0.4.15

---

## Depannage

Erreur : ModuleNotFoundError

pip install -r requirements.txt

Erreur : protobuf conflict

pip install protobuf==3.20.3

Erreur : chroma-hnswlib compilation fails (Windows)

pip install chromadb==0.4.15

Erreur : RAG non connecte

Verifier que le notebook Kaggle tourne et que l'URL ngrok est correcte

Erreur : texte blanc dans DOCX

La couleur du texte a ete forcee en noir dans la fonction set_arabic_font

---

## Note legale

Les contrats generes sont des modeles a titre indicatif.

Pour un usage officiel, une validation par un professionnel du droit marocain (avocat, notaire) est requise.

L'application n'est pas responsable de l'utilisation des contrats generes.

---

## Licence

MIT

---
