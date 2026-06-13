from _prompt import MOROCCAN_CONTRACT_INFO


# ─── Quality evaluation ───────────────────────────────────────────────────────
def evaluate_contract_quality(contract_text: str, contract_type: str) -> dict:
    info = MOROCCAN_CONTRACT_INFO.get(contract_type, {})
    required_clauses = info.get('clauses', [])

    m = {}
    m['bismillah']    = 'بسم الله' in contract_text
    m['maroc_header'] = 'المملكة المغربية' in contract_text
    m['has_parties']  = 'الطرف الأول' in contract_text and 'الطرف الثاني' in contract_text
    m['has_signature']= any(kw in contract_text for kw in ['التوقيع', 'توقيع', 'إمضاء'])
    m['has_date']     = any(kw in contract_text for kw in ['التاريخ', 'بتاريخ', '2025', '2024', '2026'])
    m['has_law_ref']  = any(kw in contract_text for kw in ['القانون', 'المادة', 'الفصل', 'ظهير'])
    m['has_jurisdiction'] = any(kw in contract_text for kw in ['الاختصاص', 'المحكمة', 'قضائي'])

    clause_found = []
    for clause in required_clauses:
        keywords = [kw for kw in clause.split() if len(kw) > 3]
        clause_found.append(any(kw in contract_text for kw in keywords))

    m['clause_coverage'] = sum(clause_found) / len(clause_found) if clause_found else 0
    m['clauses_found']   = sum(clause_found)
    m['clauses_total']   = len(clause_found)
    m['char_count']      = len(contract_text)
    m['word_count']      = len(contract_text.split())
    m['arabic_ratio']    = sum(1 for c in contract_text if '\u0600' <= c <= '\u06FF') / max(len(contract_text), 1)

    binary = [v for v in m.values() if isinstance(v, bool)]
    score = (sum(binary) / len(binary) * 0.4 + m['clause_coverage'] * 0.4 +
             min(m['arabic_ratio'] * 1.2, 1.0) * 0.2)
    m['overall_score'] = round(score * 100, 1)

    return m