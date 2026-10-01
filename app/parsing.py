"""Turn the model's verbatim strings into facts the rules can use (no model judgement here).

- parse_amount / parse_energy: numbers as printed ("<0,5 г/g", "418 кДж/kJ / 98 ккал/kcal")
  -> values. Anything not understood is None, never 0: None becomes needs_review in the
  rules. Decimal arithmetic, so "0,1 мг" gives exactly float("0.0001").
- parse_ingredients: the ingredient list with **emphasis** markup -> mentions with the
  emphasized and UPPERCASE word spans. The model's list boundary is not trusted: text from
  "Зберігати" / "Виробник" / "Може містити" etc. on is cut off as the tail (spike B1b:
  storage and producer ended up in the list).
"""

import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal, NamedTuple

TRUNCATION_MARKERS = ("[…]", "[...]")
_SPACES = str.maketrans({" ": " ", " ": " ", " ": " "})

# --- amounts -------------------------------------------------------------------------------


class Amount(NamedTuple):
    """`value` in grams. qualifier "lt": value is an upper bound ("<0,5", "≤0,5", "менше 0,5").
    qualifier "trace": "сліди"/"trace" -- value is None on purpose, so no rule can compare
    it as a number by accident."""

    value: float | None
    qualifier: Literal["eq", "lt", "trace"]


_GRAMS = {"г": Decimal(1), "гр": Decimal(1), "g": Decimal(1), "r": Decimal(1)}
_MILLIGRAMS = {"мг": Decimal("0.001"), "mg": Decimal("0.001")}
_UNIT_SCALE = _GRAMS | _MILLIGRAMS
_UNIT = r"мг|mg|гр|г|g"
_AMOUNT_RE = re.compile(
    r"(?P<q><|≤|менше\s+ніж|менш\s+ніж|менше|less\s+than)?\s*"
    r"(?P<n>\d+(?:[.,]\d+)?)\s*"
    # "г", "г/g", "г (g)", "мг/mg"; "r" is how the spike read a Cyrillic "г" after a slash.
    rf"(?:(?P<u1>{_UNIT})(?:\s*[/(]\s*(?P<u2>{_UNIT}|r)\s*\)?)?)?"
    r"\.?"
)
_TRACE_RE = re.compile(r"сліди|слідові\s+кількості|traces?|tr\.?")


def _decimal(number: str) -> Decimal:
    """A number already matched by a regex: digits, one "," or ".", thousands spaces."""
    return Decimal(number.replace(" ", "").replace(",", "."))


def parse_amount(text: str | None) -> Amount | None:
    """A nutrient amount as printed -> Amount in grams, or None if not understood.

    Accepts a decimal comma or point, "<", "≤", "менше (ніж)", "сліди"/"trace", units
    г/g/гр/мг/mg incl. "г/g" and "г (g)" doubles; no unit means grams. Anything else
    ("н/д", "-", "", "[…]", a range, "~5", kcal in a gram field) -> None.
    """
    if text is None:
        return None
    norm = text.translate(_SPACES).strip().lower()
    if _TRACE_RE.fullmatch(norm):
        return Amount(None, "trace")
    m = _AMOUNT_RE.fullmatch(norm)
    if not m:
        return None
    scales = {_UNIT_SCALE[u] for u in (m["u1"], m["u2"]) if u}
    if len(scales) > 1:  # "мг/g": which one?
        return None
    value = float(_decimal(m["n"]) * (scales.pop() if scales else Decimal(1)))
    return Amount(value, "lt" if m["q"] else "eq")


class Energy(NamedTuple):
    kj: float | None
    kcal: float | None


_ENERGY_RE = re.compile(
    r"(?P<q><|≤)?\s*"
    r"(?P<n>\d{1,3}(?: \d{3})+|\d+(?:[.,]\d+)?)\s*"  # "1 760" or "1760" or "418,5"
    r"(?P<u>кдж|kj|ккал|kcal)(?!\w)"
)
_ENERGY_UNIT = {"кдж": "kj", "kj": "kj", "ккал": "kcal", "kcal": "kcal"}


def parse_energy(text: str | None) -> Energy:
    """ "1760 кДж / 420 ккал", "418 кДж/kJ / 98 ккал/kcal", "120 кДж (kJ) / 28 ккал (kcal)"
    -> Energy(kj, kcal). A unit that is missing, qualified ("<") or given two different
    values (e.g. per 100 g and per portion in one string) is None."""
    found: dict[str, set[Decimal | None]] = {"kj": set(), "kcal": set()}  # None = qualified
    if text is not None:
        for m in _ENERGY_RE.finditer(text.translate(_SPACES).lower()):
            found[_ENERGY_UNIT[m["u"]]].add(None if m["q"] else _decimal(m["n"]))

    def single(values: set[Decimal | None]) -> float | None:
        if len(values) != 1:
            return None
        (value,) = values
        return None if value is None else float(value)

    return Energy(single(found["kj"]), single(found["kcal"]))


# --- ingredients ---------------------------------------------------------------------------

Span = tuple[int, int]  # [start, end) in Mention.text


@dataclass(frozen=True)
class Mention:
    """One ingredient between separators (",", ";", brackets) of the list.

    depth: bracket nesting (0 = top level). emphasized_spans: from the model's **…**.
    upper: words of >= 2 letters written in capitals (the code decides, not the model).
    """

    text: str
    emphasized_spans: tuple[Span, ...]
    upper: tuple[Span, ...]
    depth: int

    def is_emphasized(self, start: int, end: int) -> bool:
        """Whether [start, end) of `text` overlaps an emphasized or uppercase span."""
        return any(s < end and start < e for s, e in self.emphasized_spans + self.upper)


@dataclass(frozen=True)
class Ingredients:
    mentions: tuple[Mention, ...]
    # Text from the first non-ingredient marker on ("Зберігати…", "Виробник…", "Може
    # містити…"), or None. Not ingredients: no allergen emphasis is required there.
    tail: str | None
    truncated: bool  # the list part has a "[…]" marker
    # The whole list is in capitals / in **…**: then that style is the body text, not
    # emphasis, and its spans are dropped (an all-caps list would otherwise "pass").
    upper_is_body: bool
    marks_are_body: bool


_LIST_NAME = r"(?:склад|інгредієнти|ingredients)"
# "Склад:", "**Склад:**", "**Склад**:" -- without eating the "**" of the first ingredient.
_LIST_PREFIX_RE = re.compile(
    rf"\s*(?:\*\*\s*{_LIST_NAME}\s*:?\s*\*\*\s*:?|{_LIST_NAME}\s*:)\s*", re.I
)
# Where the ingredient list surely ends. Matched at a word start, case-insensitive
# (except the standards' abbreviations), on the marked text so "**Виробник**:" counts too.
# Only phrases that cannot be an ingredient: a false cut hides allergens from ALG-EMPH
# (so no bare "nutrition" -- "nutritional yeast"; no "вироблено з молока").
_LIST_END_RE = re.compile(
    r"(?<!\w)\**(?:"
    r"умови\s+зберігання|зберіга\w*|виробник\w*|виготовлювач\w*|"
    r"місцезнаходження|адреса\s+виробни\w*|імпортер\w*|"
    r"поживна\s+цінність|харчова\s+цінність|енергетична\s+цінність|"
    r"термін\s+придатності|придатн\w*\s+до|краще\s+спожити|вжити\s+до|дата\s+виготовлення|"
    r"маса\s+нетто|може\s+містити|може\s+вміщувати|"
    r"storage|store(?!\w)|manufacturer|produced\s+by|best\s+before|"
    r"nutrition(?:al)?\s+(?:information|facts|values?|declaration)|"
    r"may\s+contain|net\s+weight"
    r")",
    re.I,
)
# A standard ends the list only where a sentence starts: "пластівці (ДСТУ 4673:2006), цукор"
# names the standard of one ingredient, and cutting there hid "цукор" (RR1 #1).
_STANDARD_END_RE = re.compile(r"(?:^|(?<=[.;\n]))\s*\**(?:ДСТУ|ТУ\s+У)(?!\w)")
_WORD_RE = re.compile(r"[^\W\d_]+(?:['’ʼ][^\W\d_]+)*")
_STRIP = " \t\n.:;,-–—"
_NEXT_WORD_RE = re.compile(r"\s+([^\W\d_])")


def _strip_marks(marked: str) -> tuple[str, list[Span]]:
    """ "сухе **молоко**" -> ("сухе молоко", [(5, 11)]). `**` pairs toggle emphasis; an odd
    last `**` is ignored (no emphasis is the safe reading); stray single `*` are dropped."""
    pairs = marked.count("**")
    usable = pairs - pairs % 2
    plain: list[str] = []
    spans: list[Span] = []
    seen = 0
    start: int | None = None
    i = 0
    while i < len(marked):
        if marked.startswith("**", i):
            if seen < usable:
                if start is None:
                    start = len(plain)
                else:
                    if len(plain) > start:
                        spans.append((start, len(plain)))
                    start = None
            seen += 1
            i += 2
            continue
        if marked[i] != "*":
            plain.append(marked[i])
        i += 1
    return "".join(plain), spans


def _upper_spans(text: str) -> list[Span]:
    return [
        m.span()
        for m in _WORD_RE.finditer(text)
        if m[0].isupper() and sum(c.isalpha() for c in m[0]) >= 2
    ]


def _is_body_style(text: str, spans: list[Span]) -> bool:
    """More than half of the words (>= 2 letters) are covered by `spans`."""
    words = [m.span() for m in _WORD_RE.finditer(text) if len(m[0]) >= 2]
    covered = sum(any(s < we and ws < e for s, e in spans) for ws, we in words)
    return bool(words) and covered * 2 > len(words)


def _segments(text: str) -> list[tuple[int, int, int]]:
    """(start, end, depth) of the pieces between separators (",", ";", brackets, ". X");
    "[…]" is not a bracket and a comma between digits ("7,5 %") is a decimal comma."""
    out: list[tuple[int, int, int]] = []
    depth = seg_start = seg_depth = 0
    i = 0
    while i < len(text):
        marker = next((t for t in TRUNCATION_MARKERS if text.startswith(t, i)), None)
        if marker:
            i += len(marker)
            continue
        ch = text[i]
        decimal_comma = (
            ch == ","
            and 0 < i < len(text) - 1
            and text[i - 1].isdigit()
            and (text[i + 1].isdigit())
        )
        # "ароматизатор. Мінімальний вміст…": a sentence end splits too (nothing is cut off).
        after = _NEXT_WORD_RE.match(text, i + 1) if ch == "." else None
        sentence_end = after is not None and after[1].isupper()
        if (ch in "([{)]},;" and not decimal_comma) or sentence_end:
            out.append((seg_start, i, seg_depth))
            if ch in "([{":
                depth += 1
            elif ch in ")]}":
                depth = max(0, depth - 1)
            seg_start, seg_depth = i + 1, depth
        i += 1
    out.append((seg_start, len(text), seg_depth))
    return out


def _clip(spans: list[Span], start: int, end: int) -> tuple[Span, ...]:
    return tuple(
        (max(s, start) - start, min(e, end) - start) for s, e in spans if s < end and start < e
    )


def split_list_end(marked: str) -> tuple[str, str | None]:
    """Cut the marked ingredient text at the first non-ingredient marker -> (list, tail)."""
    prefix = _LIST_PREFIX_RE.match(marked)
    if prefix:
        marked = marked[prefix.end() :]
    starts = [m.start() for r in (_LIST_END_RE, _STANDARD_END_RE) if (m := r.search(marked))]
    if not starts:
        return marked, None
    end = min(starts)
    tail = marked[end:].strip()
    return marked[:end], tail or None


def parse_ingredients(marked: str | None) -> Ingredients:
    """The model's ingredient text with **…** markup -> mentions with emphasis spans."""
    if not marked:
        return Ingredients((), None, False, False, False)
    list_part, tail = split_list_end(marked)
    text, emphasized = _strip_marks(list_part)
    upper = _upper_spans(text)
    upper_is_body = _is_body_style(text, upper)
    marks_are_body = _is_body_style(text, emphasized)
    if upper_is_body:
        upper = []
    if marks_are_body:
        emphasized = []

    mentions = []
    for start, end, depth in _segments(text):
        while start < end and text[start] in _STRIP:
            start += 1
        while end > start and text[end - 1] in _STRIP:
            end -= 1
        piece = text[start:end]
        if not any(c.isalnum() for c in piece) and piece not in TRUNCATION_MARKERS:
            continue
        mentions.append(
            Mention(piece, _clip(emphasized, start, end), _clip(upper, start, end), depth)
        )
    truncated = any(t in text for t in TRUNCATION_MARKERS)
    return Ingredients(tuple(mentions), tail, truncated, upper_is_body, marks_are_body)
