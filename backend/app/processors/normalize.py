"""Locale-aware normalization of amounts, dates, currencies and vendor names."""
import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "ISK", "HUF"}
THREE_DECIMAL = {"BHD", "KWD", "OMR", "JOD", "TND"}
ISO_CURRENCIES = {
    "INR", "USD", "EUR", "GBP", "AUD", "CAD", "SGD", "AED", "JPY", "CHF", "CNY", "HKD", "NZD", "SEK", "NOK",
    "DKK", "ZAR", "BRL", "MXN", "KRW", "THB", "MYR", "IDR", "PHP", "SAR", "QAR", "KWD", "BHD", "OMR", "PLN",
    "CZK", "HUF", "TRY", "ILS", "RUB", "VND", "PKR", "BDT", "LKR", "NPR", "EGP", "NGN", "KES", "CLP", "COP", "ARS",
}


def currency_decimals(code: str | None) -> int:
    if code in ZERO_DECIMAL:
        return 0
    if code in THREE_DECIMAL:
        return 3
    return 2


def quantize_money(value: Decimal, currency: str | None) -> Decimal:
    return value.quantize(Decimal(1).scaleb(-currency_decimals(currency)), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- amounts
def detect_decimal_style(values: list[str]) -> str | None:
    """Look at many number strings and guess whether '.' or ',' is the decimal separator."""
    dot = sum(1 for v in values if re.search(r"\d\.\d{1,2}(?!\d)", v))
    comma = sum(1 for v in values if re.search(r"\d,\d{1,2}(?!\d)", v))
    if dot > comma:
        return "."
    if comma > dot:
        return ","
    return None


def parse_amount(raw: str | None, decimal_hint: str | None = None) -> Decimal | None:
    value, _ = parse_amount_ex(raw, decimal_hint)
    return value


def parse_amount_ex(raw: str | None, decimal_hint: str | None = None) -> tuple[Decimal | None, bool]:
    """Return (amount, ambiguous). Handles 1,234.56 / 1.234,56 / 1 234,56 / 1'234.56 / (12.00) / lakh grouping."""
    if raw is None:
        return None, False
    s = str(raw).strip()
    if not re.search(r"\d", s):
        return None, False
    neg = (s.startswith("(") and s.endswith(")")) or s.startswith("-") or s.endswith("-") or s.startswith("\u2212")
    s = re.sub(r"[^\d.,\u00a0\u202f' \u2019]", "", s)
    s = re.sub(r"[\u00a0\u202f' \u2019]", "", s)
    s = s.strip(".,")
    if not s:
        return None, False
    ambiguous = False
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
    elif has_dot or has_comma:
        sep = "." if has_dot else ","
        if decimal_hint in (".", ","):
            dec = decimal_hint if sep == decimal_hint else None
        elif s.count(sep) > 1:
            dec = None
        else:
            after = len(s) - s.rfind(sep) - 1
            if after == 3:
                dec = None  # 1,234 -> thousands
                ambiguous = True
            else:
                dec = sep
        if dec is None and decimal_hint is None and not ambiguous and s.count(sep) > 1:
            dec = None
    else:
        dec = None
    if dec:
        thousands = "," if dec == "." else "."
        s = s.replace(thousands, "").replace(dec, ".")
    else:
        s = s.replace(",", "").replace(".", "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return None, False
    return (-d if neg else d), ambiguous


# ---------------------------------------------------------------- dates
MONTHS = {
    "jan": 1, "january": 1, "januar": 1, "janvier": 1, "enero": 1, "ene": 1, "janv": 1,
    "feb": 2, "february": 2, "februar": 2, "fevrier": 2, "février": 2, "febrero": 2, "fév": 2, "fevr": 2,
    "mar": 3, "march": 3, "märz": 3, "marz": 3, "mars": 3, "marzo": 3, "mär": 3,
    "apr": 4, "april": 4, "avril": 4, "abril": 4, "avr": 4, "abr": 4,
    "may": 5, "mai": 5, "mayo": 5,
    "jun": 6, "june": 6, "juni": 6, "juin": 6, "junio": 6,
    "jul": 7, "july": 7, "juli": 7, "juillet": 7, "julio": 7, "juil": 7,
    "aug": 8, "august": 8, "août": 8, "aout": 8, "agosto": 8, "ago": 8,
    "sep": 9, "sept": 9, "september": 9, "septembre": 9, "septiembre": 9,
    "oct": 10, "october": 10, "oktober": 10, "octobre": 10, "octubre": 10, "okt": 10,
    "nov": 11, "november": 11, "novembre": 11, "noviembre": 11,
    "dec": 12, "december": 12, "dezember": 12, "décembre": 12, "decembre": 12, "diciembre": 12, "dez": 12, "dic": 12,
}
_ISO = re.compile(r"(?<!\d)(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)")
_NUM = re.compile(r"(?<![\d.])(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?!\d)")
_DMY_TXT = re.compile(r"(?<!\d)(\d{1,2})(?:st|nd|rd|th|\.)?[\s\-]+([A-Za-zäéûôàÀ]{3,10})\.?,?[\s\-]+(\d{4})(?!\d)")
_MDY_TXT = re.compile(r"\b([A-Za-zäéûôà]{3,10})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)")


def _mk(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str | None, preferred: str = "DMY") -> tuple[date | None, bool]:
    """Return (date, ambiguous). `preferred` (DMY|MDY|ISO) resolves numeric dates such as 05/10/2026."""
    if not text:
        return None, False
    m = _ISO.search(text)
    if m:
        return _mk(int(m[1]), int(m[2]), int(m[3])), False
    m = _DMY_TXT.search(text)
    if m and m[2].lower().rstrip(".") in MONTHS:
        return _mk(int(m[3]), MONTHS[m[2].lower().rstrip(".")], int(m[1])), False
    m = _MDY_TXT.search(text)
    if m and m[1].lower().rstrip(".") in MONTHS:
        return _mk(int(m[3]), MONTHS[m[1].lower().rstrip(".")], int(m[2])), False
    m = _NUM.search(text)
    if m:
        a, b, y = int(m[1]), int(m[2]), int(m[3])
        if y < 100:
            y += 2000
        if a > 12 and b <= 12:
            return _mk(y, b, a), False
        if b > 12 and a <= 12:
            return _mk(y, a, b), False
        ambiguous = a != b and a <= 12 and b <= 12
        if "." in m[0]:  # dotted numeric dates are day-first almost everywhere
            return _mk(y, b, a), False
        if preferred == "MDY":
            return _mk(y, a, b), ambiguous
        return _mk(y, b, a), ambiguous
    return None, False


def alternate_reading(text: str, preferred: str = "DMY") -> str | None:
    m = _NUM.search(text or "")
    if not m:
        return None
    a, b, y = int(m[1]), int(m[2]), int(m[3])
    y = y + 2000 if y < 100 else y
    first = _mk(y, b, a) if preferred != "MDY" else _mk(y, a, b)
    second = _mk(y, a, b) if preferred != "MDY" else _mk(y, b, a)
    return f"{first} or {second}" if first and second else None


# ---------------------------------------------------------------- currency
SYMBOLS = {"₹": "INR", "€": "EUR", "£": "GBP", "¥": "JPY"}
_CODE_RE = re.compile(r"\b(" + "|".join(sorted(ISO_CURRENCIES)) + r")\b")


def detect_currency(text: str) -> tuple[str | None, bool]:
    """Return (code, ambiguous). A bare '$' is ambiguous (USD/AUD/CAD/SGD...)."""
    codes: dict[str, int] = {}
    for m in _CODE_RE.finditer(text):
        codes[m[1]] = codes.get(m[1], 0) + 1
    if codes:
        best = max(codes, key=lambda c: codes[c])
        return best, len(codes) > 1
    for sym, code in SYMBOLS.items():
        if sym in text:
            return code, False
    if re.search(r"\bRs\.?\s*\d|\bRs\.", text):
        return "INR", False
    if "$" in text:
        return "USD", True
    return None, False


# ---------------------------------------------------------------- vendors
LEGAL = {"ltd", "limited", "pvt", "private", "inc", "incorporated", "llc", "llp", "co", "corp", "corporation",
         "gmbh", "ag", "sa", "sarl", "plc", "bv", "srl", "sl", "pty", "company", "the", "und", "kg", "ug", "lp"}
BANK_NOISE = {"upi", "neft", "imps", "rtgs", "pos", "ach", "txn", "payment", "pay", "to", "from", "debit", "card",
              "purchase", "transfer", "online", "ref", "bill", "paid", "dr", "cr", "by", "via", "trf", "wire", "sepa"}


def _ascii(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()


def normalize_vendor(name: str | None, bank_description: bool = False) -> str:
    if not name:
        return ""
    s = _ascii(name.lower())
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    out = []
    for tok in s.split():
        if tok in LEGAL:
            continue
        if bank_description and (tok in BANK_NOISE or tok.isdigit() or re.fullmatch(r"[a-z]*\d{4,}[a-z\d]*", tok)):
            continue
        out.append(tok)
    return " ".join(out)


def alnum(s: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", _ascii((s or "").lower()))
