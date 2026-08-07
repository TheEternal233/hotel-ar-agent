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

def _clean_val(val):
    """把pandas的nan/NaT/None统一洗成None"""
    if val is None or val == "":
        return None
    try:
        if val!=val:
            return None
    except TypeError:
        pass

    if isinstance(val, str) and val.strip().lower() in ("nan","nat","none"):
        return None

    return val
