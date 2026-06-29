"""
contract_config.py
====================
Configuration partagée entre l'orchestrateur LangGraph et l'app Streamlit.
Reprend MOROCCAN_CONTRACT_INFO et SYSTEM_PROMPT déjà définis dans app_old.py
(pour ne pas les dupliquer), et ajoute REQUIRED_FIELDS : la liste des champs
que l'utilisateur doit fournir pour chaque type de contrat.

NOTE : REQUIRED_FIELDS est une première version raisonnable. Idéalement, à
terme, ces champs devraient provenir du notebook "lois" (ALL_FIELDS /
REQUIRED_FIELDS définis dans la cellule 23/24) via un futur endpoint
/required_fields/{contract_type} sur l'API lois, pour garder une seule
source de vérité entre le RAG juridique et l'orchestrateur. Pour l'instant
c'est une copie locale à ajuster si besoin.
"""

from __future__ import annotations

# ─── Référentiel des types de contrats marocains ──────────────────────────
MOROCCAN_CONTRACT_INFO = {
    'عقد_إيجار': {
        'title': 'عقد كراء سكني',
        'law': 'القانون رقم 67.12 المتعلق بتنظيم العلاقات بين المكري والمكتري',
        'parties': ['المكري (الطرف الأول)', 'المكتري (الطرف الثاني)'],
        'clauses': ['وصف العقار', 'مدة الكراء', 'مبلغ الكراء وطريقة الأداء',
                    'الضمان', 'التزامات المكري', 'التزامات المكتري', 'فسخ العقد'],
        'icon': ''
    },
    'عقد_بيع': {
        'title': 'عقد البيع',
        'law': 'ظهير الالتزامات والعقود — الفصول 478 إلى 618',
        'parties': ['البائع (الطرف الأول)', 'المشتري (الطرف الثاني)'],
        'clauses': ['وصف المبيع', 'الثمن وطريقة الأداء', 'نقل الملكية',
                    'ضمان الاستحقاق', 'التسليم', 'الفسخ'],
        'icon': ''
    },
    'عقد_عمل': {
        'title': 'عقد الشغل',
        'law': 'مدونة الشغل المغربية — القانون رقم 65.99',
        'parties': ['المشغل (الطرف الأول)', 'الأجير (الطرف الثاني)'],
        'clauses': ['طبيعة العمل', 'الأجر والامتيازات', 'مدة العقد',
                    'فترة التجربة', 'أوقات العمل', 'الإجازات', 'الإنهاء'],
        'icon': ''
    },
    'عقد_شراكة': {
        'title': 'عقد الشركة',
        'law': 'القانون رقم 5.96 المتعلق بشركات الأشخاص',
        'parties': ['الشريك الأول', 'الشريك الثاني'],
        'clauses': ['موضوع الشركة', 'رأس المال وتوزيع الحصص',
                    'توزيع الأرباح', 'تسيير الشركة', 'حل الشركة'],
        'icon': ''
    },
    'عقد_مقاولة': {
        'title': 'عقد المقاولة',
        'law': 'ظهير الالتزامات والعقود — الفصول 723 إلى 769',
        'parties': ['صاحب المشروع (الطرف الأول)', 'المقاول (الطرف الثاني)'],
        'clauses': ['وصف الأشغال', 'الأثمان وطريقة الأداء', 'المدة', 'الضمانات'],
        'icon': ''
    },
    'عقد_قرض': {
        'title': 'عقد القرض',
        'law': 'ظهير الالتزامات والعقود — الفصول 860 إلى 877',
        'parties': ['المقرض (الطرف الأول)', 'المقترض (الطرف الثاني)'],
        'clauses': ['مبلغ القرض', 'الفائدة', 'مدة السداد', 'الضمانات', 'حالات الفسخ'],
        'icon': ''
    },
}

# ─── Prompt système (agent rédacteur) ──────────────────────────────────────
SYSTEM_PROMPT = """أنت محامٍ مغربي متخصص في صياغة العقود القانونية الرسمية وخبير في التشريع المغربي.
تصيغ عقوداً قانونية مغربية احترافية ومتوافقة مع القانون المغربي النافذ.

قواعد الصياغة الإلزامية:
١. ابدأ دائماً بـ "بسم الله الرحمن الرحيم" في سطر مستقل
٢. ثم "المملكة المغربية" في سطر مستقل
٣. أشر إلى القانون المغربي المنطبق في الديباجة
٤. حدد طرفي العقد بدقة مع بياناتهم الكاملة
٥. رقّم البنود بالأرقام العربية (البند الأول، البند الثاني...)
٦. استخدم المصطلحات القانونية المغربية الدقيقة
٧. اختم بخانة التوقيع: الطرف الأول والطرف الثاني والتاريخ والمكان
٨. أضف بند الفسخ وبند الاختصاص القضائي دائماً
٩. لا تضف أي تعليق أو شرح خارج نص العقد
١٠. اكتب العقد كاملاً بجميع بنوده دون اختصار

قواعد إلزامية:
- لا تضع أي تحليل داخلي أو تعليقات
- لا تستخدم <think> أو أي علامات خاصة
- اكتب العقد مباشرة بدون أي مقدمة
- لا تستخدم علامات التنسيق مثل **
- اكتب النص العربي فقط
"""

# ─── Champs requis par type de contrat ─────────────────────────────────────
_COMMON_FIELDS = {
    'party1_name': 'الاسم الكامل للطرف الأول',
    'party2_name': 'الاسم الكامل للطرف الثاني',
    'contract_date': 'تاريخ العقد',
    'contract_place': 'مكان إبرام العقد',
}

_TYPE_SPECIFIC_FIELDS = {
    'عقد_إيجار': {
        'property_address': 'عنوان العقار المكرى',
        'rent_amount': 'مبلغ الكراء الشهري',
        'lease_duration': 'مدة عقد الكراء',
    },
    'عقد_بيع': {
        'object_description': 'وصف المبيع',
        'price': 'الثمن',
        'delivery_terms': 'شروط التسليم',
    },
    'عقد_عمل': {
        'job_title': 'المهنة / الوظيفة',
        'salary': 'الأجر الشهري',
        'start_date': 'تاريخ بداية العمل',
        'contract_duration': 'مدة العقد (محدد / غير محدد)',
    },
    'عقد_شراكة': {
        'company_object': 'موضوع الشركة',
        'capital_amount': 'رأس المال',
        'profit_split': 'كيفية توزيع الأرباح',
    },
    'عقد_مقاولة': {
        'works_description': 'وصف الأشغال المطلوبة',
        'price': 'الثمن وطريقة الأداء',
        'duration': 'مدة التنفيذ',
    },
    'عقد_قرض': {
        'loan_amount': 'مبلغ القرض',
        'interest_rate': 'نسبة الفائدة (إن وجدت)',
        'repayment_duration': 'مدة السداد',
    },
}


def get_required_fields(contract_type: str) -> dict[str, str]:
    """Retourne {clé_champ: libellé_arabe} pour un type de contrat donné,
    champs communs (parties, date, lieu) + champs spécifiques au type."""
    fields = dict(_COMMON_FIELDS)
    fields.update(_TYPE_SPECIFIC_FIELDS.get(contract_type, {}))
    return fields
