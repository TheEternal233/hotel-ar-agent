def _norm_orderno(oid):
    if oid is None:
        return ""
    return str(oid).strip().replace("\n", "").replace("\r", "").replace(" ", "")

def _norm_amount(v):
    if v is None:
        return 0.0
    try:
        return round(float(v), 2)
    except (ValueError, TypeError):
        return 0.0
