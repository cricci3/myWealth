"""Money helpers: ISO 4217 currencies, minor units, parsing of user input.

Amounts are stored as integers in minor units (cents) and computed with Decimal; float
is never used for money. User input accepts both Italian (`1.234,56`) and dot
(`1234.56`) notation; parse_amount() and parseAmount() in web/js/core.js follow the same rules.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import ValidationError

# code -> (Italian name, minor-unit decimals per ISO 4217)
CURRENCIES: dict[str, tuple[str, int]] = {
    "EUR": ("Euro", 2),
    "CHF": ("Franco svizzero", 2),
    "USD": ("Dollaro statunitense", 2),
    "GBP": ("Sterlina britannica", 2),
    "JPY": ("Yen giapponese", 0),
    "CAD": ("Dollaro canadese", 2),
    "AUD": ("Dollaro australiano", 2),
    "NZD": ("Dollaro neozelandese", 2),
    "SEK": ("Corona svedese", 2),
    "NOK": ("Corona norvegese", 2),
    "DKK": ("Corona danese", 2),
    "ISK": ("Corona islandese", 0),
    "PLN": ("Złoty polacco", 2),
    "CZK": ("Corona ceca", 2),
    "HUF": ("Fiorino ungherese", 2),
    "RON": ("Leu rumeno", 2),
    "BGN": ("Lev bulgaro", 2),
    "TRY": ("Lira turca", 2),
    "CNY": ("Renminbi cinese", 2),
    "HKD": ("Dollaro di Hong Kong", 2),
    "SGD": ("Dollaro di Singapore", 2),
    "KRW": ("Won sudcoreano", 0),
    "INR": ("Rupia indiana", 2),
    "ILS": ("Nuovo siclo israeliano", 2),
    "AED": ("Dirham degli Emirati", 2),
    "ZAR": ("Rand sudafricano", 2),
    "BRL": ("Real brasiliano", 2),
    "MXN": ("Peso messicano", 2),
}

BASE = "EUR"
ZERO = Decimal(0)
_NUM_RE = re.compile(r"-?\d+(\.\d+)?")


def check_currency(code) -> str:
    code = str(code or "").strip().upper()
    if code not in CURRENCIES:
        raise ValidationError(f"Valuta non supportata: '{code}'.")
    return code


def decimals(currency: str) -> int:
    return CURRENCIES[currency][1]


def to_minor(value: Decimal, currency: str) -> int:
    """Decimal amount -> integer minor units, rounding half up."""
    q = Decimal(1).scaleb(-decimals(currency))
    return int((value / q).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def from_minor(minor: int, currency: str) -> Decimal:
    return Decimal(int(minor)).scaleb(-decimals(currency))


def fmt(minor: int | None, currency: str) -> str | None:
    """Minor units -> plain decimal string for the API ("1234.50"); None stays None."""
    if minor is None:
        return None
    return f"{from_minor(minor, currency):.{decimals(currency)}f}"


def fmt_decimal(value: Decimal | None, places: int = 2) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP):.{places}f}"


def parse_decimal(text, field: str = "valore", grouping: bool = False, max_places: int | None = None) -> Decimal:
    """Parse "1000.50", "1000,50", "1,000.50", "1.000,50" or "1.000.000" into a Decimal.

    With both separators the last one is the decimal mark. With only one kind, repeated
    means thousands; a single one followed by exactly three digits ("1.000") means
    thousands when `grouping` is True and three decimals aren't allowed (amounts).
    """
    if isinstance(text, bool) or text is None:
        raise ValidationError(f"{field.capitalize()} mancante.")
    if isinstance(text, int):
        return Decimal(text)
    if isinstance(text, Decimal):
        s = str(text)
    else:
        s = re.sub(r"[\s'€$£  ]", "", str(text))
    if not s:
        raise ValidationError(f"{field.capitalize()} mancante.")
    if "," in s and "." in s:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(",", ".")
    elif "," in s or "." in s:
        parts = s.split("," if "," in s else ".")
        thousands = len(parts) > 2 or (
            grouping
            and (max_places is None or max_places < 3)
            and re.fullmatch(r"-?\d{1,3}", parts[0]) is not None
            and re.fullmatch(r"\d{3}", parts[1]) is not None
        )
        if len(parts) > 2 and not all(re.fullmatch(r"\d{3}", p) for p in parts[1:]):
            raise ValidationError(f"{field.capitalize()} non valido: '{text}'.")
        s = "".join(parts) if thousands else ".".join(parts)
    if not _NUM_RE.fullmatch(s):
        raise ValidationError(f"{field.capitalize()} non valido: '{text}'.")
    try:
        value = Decimal(s)
    except InvalidOperation:
        raise ValidationError(f"{field.capitalize()} non valido: '{text}'.") from None
    if max_places is not None and -value.as_tuple().exponent > max_places:
        if max_places == 0:
            raise ValidationError(f"{field.capitalize()}: questa valuta non ha decimali.")
        raise ValidationError(f"{field.capitalize()}: al massimo {max_places} decimali.")
    return value


def parse_amount(text, currency: str, field: str = "importo", allow_negative: bool = False,
                 allow_zero: bool = False) -> int:
    """User input -> minor units of `currency`. Positive unless allow_negative."""
    value = parse_decimal(text, field, grouping=True, max_places=decimals(currency))
    if value < 0 and not allow_negative:
        raise ValidationError(f"{field.capitalize()}: inserisci un valore positivo.")
    if value == 0 and not allow_zero:
        raise ValidationError(f"{field.capitalize()}: deve essere maggiore di zero.")
    return to_minor(value, currency)


def parse_date(text, field: str = "data") -> date:
    """Accept YYYY-MM-DD or DD/MM/YYYY."""
    from datetime import datetime

    if isinstance(text, date):
        return text
    s = str(text or "").strip()
    for f in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s, f).date()
        except ValueError:
            continue
    raise ValidationError(f"{field.capitalize()} non valida: '{s}' (usa gg/mm/aaaa).")


def currency_list() -> list[dict]:
    return [{"code": c, "name": n, "decimals": d} for c, (n, d) in CURRENCIES.items()]
