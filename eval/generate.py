"""Synthetic labels with KNOWN violations for the trust number (docs/SPEC.md §4).

    python -m eval.generate [--seed N] [--out eval/cases]        (make generate)

Each case is eval/cases/<split>/<id>/: photo_<i>.jpg, spec.json (some cases) and truth.json =
{violations: [{rule_id, target}], expected_flags: [{rule_id, target}], extraction: the
LabelExtraction the photos are drawn FROM, meta: {synthetic: true, quality, template, scenario,
oov, ...}}. violations are label violations (safe recall); expected_flags are problems of the
photo, not of the label (LABEL-TRUNCATED, IMG-QUALITY: a separate metric). The photos are
rendered from the extraction (bold = the **…** spans), so it is their exact transcription.

The violations are what the law says about the drawn label, not what our rules say: B4b
checks the rules against them. Wording comes from eval/pools/<split>.yaml (dev and test do
not share it); oov pool entries (out of the dictionary) are listed in meta.oov.
"""

import argparse
import io
import json
import os
import random
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
POOLS = ROOT / "pools"
SPLITS = ("dev", "test")
DEFAULT_SEED = 20261001
FONT_DIR = Path(os.environ.get("LABEL_FONT_DIR", "/usr/share/fonts/truetype/dejavu"))

# meta.quality of non-cropped cases, assigned in turn so every scenario gets several
QUALITIES = ("clean", "blur", "rotate", "jpeg40")
JPEG_QUALITY = {"jpeg40": 40}
DEFAULT_JPEG_QUALITY = 88
BLUR_RADIUS = 1.2
ROTATE_DEGREES = (2.0, 5.0)  # |angle|, either direction
ENERGY_ERRORS = (1.4, 0.65)  # NUT-ENERGY: declared kcal = computed × this (outside ±15 %)
SPEC_SHARE = 0.5  # cases with a recipe (always for ALG-SPEC-MISSING)
SPEC_NUTRITION_SHARE = 0.6  # of those, with nutrition_per_100
MAY_CONTAIN_SHARE = 0.5
TRAP_SHARE = 0.35
CAPS_SHARE = 0.3  # allergens emphasized by CAPITALS instead of bold
LT_SUGARS = "<0,5 г"
LT_SUGARS_RECIPE = 0.2  # the recipe value behind "<0,5"

# scenario -> cases per split; a violation scenario puts {rule_id, target} into
# truth.violations, a flag scenario into truth.expected_flags
SCENARIOS: dict[str, int] = {
    "ALG-EMPH": 3,
    "sugar_free": 3,
    "protein_source": 2,
    "fat_low": 2,
    "no_added_sugar": 2,
    "NUT-ENERGY": 2,
    "ALG-SPEC-MISSING": 2,
    "LABEL-TRUNCATED": 2,
    "clean_sugar_free_lt": 3,  # "без цукру" with "<0,5 г": the number-parsing trap
    "clean_protein": 2,
    "clean_fat_low": 2,
    "clean_no_added_sugar": 1,
    "clean_fibre": 2,
    "clean_plain": 2,
}
FLAG_SCENARIOS = ("LABEL-TRUNCATED",)  # a problem of the photo, not of the label
VIOLATION_SCENARIOS = tuple(
    s for s in SCENARIOS if not s.startswith("clean") and s not in FLAG_SCENARIOS
)
CLAIM_IDS = ("sugar_free", "protein_source", "fat_low", "no_added_sugar", "fibre_source")


@dataclass(frozen=True)
class Template:
    form: str  # solid | liquid
    slots: tuple[str, ...]  # allergen categories filled from the pool
    plain: tuple[str, ...]
    sweet: tuple[str, ...]  # dropped where the scenario needs no added sugar
    tail: tuple[str, ...]  # minor ingredients at the end: the part a cropped photo loses
    nutrition: dict[str, float]  # per 100 g / 100 ml, without energy (computed)
    net: str
    storage: str
    colour: tuple[int, int, int]


def _n(fat, saturates, carbs, sugars, fibre, protein, salt) -> dict[str, float]:
    return dict(
        fat=fat,
        saturates=saturates,
        carbs=carbs,
        sugars=sugars,
        fibre=fibre,
        protein=protein,
        salt=salt,
    )


COLD = "Зберігати при температурі від +2 до +6 °C."
DRY = "Зберігати в сухому місці при температурі не вище +25 °C."
TEMPLATES: dict[str, Template] = {
    "yogurt": Template(
        "solid", ("milk",), ("наповнювач полуничний",), ("цукор",),
        ("стабілізатор пектин", "барвник кармін"),
        _n(3.2, 2.1, 12.5, 11.8, 0, 3.4, 0.12), "Маса нетто 300 г", COLD, (250, 232, 240),
    ),
    "cookies": Template(
        "solid", ("cereals", "eggs", "milk"), ("олія соняшникова", "крохмаль кукурудзяний"),
        ("цукор",), ("розпушувач гідрокарбонат натрію", "сіль", "ароматизатор ванілін"),
        _n(18, 8, 68, 24, 2.5, 7, 0.6), "Маса нетто 200 г", DRY, (250, 240, 215),
    ),
    "bar": Template(
        "solid", ("cereals", "nuts"), ("родзинки", "насіння соняшнику"), ("цукор",),
        ("емульгатор лецитин соняшниковий", "сіль", "антиоксидант токофероли"),
        _n(12, 2.5, 60, 22, 6, 9, 0.2), "Маса нетто 40 г", DRY, (235, 245, 225),
    ),
    "juice": Template(
        "liquid", (), ("пюре яблучне", "вода питна"), (),
        ("кислота лимонна", "кислота аскорбінова"),
        _n(0, 0, 10.5, 9.8, 0.2, 0.3, 0.01), "Об'єм 1 л", DRY, (255, 245, 210),
    ),
    "bread": Template(
        "solid", ("cereals", "cereals", "sesame"), ("вода питна", "дріжджі хлібопекарські"),
        ("цукор",), ("сіль", "олія соняшникова", "поліпшувач кислота аскорбінова"),
        _n(2.5, 0.4, 48, 3, 6, 8.5, 1.1), "Маса нетто 500 г", DRY, (240, 228, 210),
    ),
    "sauce": Template(
        "solid", ("eggs", "mustard"), ("олія соняшникова", "вода питна", "оцет спиртовий"),
        ("цукор",), ("сіль", "регулятор кислотності кислота лимонна", "консервант сорбат калію"),
        _n(30, 3, 8, 5, 0.5, 1.2, 1.5), "Маса нетто 250 г", COLD, (250, 250, 225),
    ),
    "kefir": Template(
        "liquid", ("milk",), ("закваска бактеріальна",), (), ("вітамін D3",),
        _n(2.5, 1.6, 4, 4, 0, 3, 0.1), "Об'єм 900 мл", COLD, (230, 240, 250),
    ),
    "spread": Template(
        "solid", ("fish", "mustard"), ("олія соняшникова", "цибуля ріпчаста"), (),
        ("сіль", "перець чорний мелений", "консервант бензоат натрію"),
        _n(22, 4, 3, 1, 0, 14, 1.8), "Маса нетто 150 г", COLD, (225, 235, 240),
    ),
}  # fmt: skip
ALLERGEN_TEMPLATES = tuple(k for k, t in TEMPLATES.items() if t.slots)
# where a scenario makes sense (and its claim's outcome is the intended one)
SCENARIO_TEMPLATES: dict[str, tuple[str, ...]] = {
    "ALG-EMPH": ALLERGEN_TEMPLATES,
    "sugar_free": ("yogurt", "cookies", "bar", "juice", "sauce", "kefir", "bread"),
    "protein_source": ("cookies", "bar", "sauce", "juice"),  # protein < 12 % of energy
    "fat_low": ("yogurt", "kefir", "spread"),  # fat > 3 g / 1.5 ml
    "no_added_sugar": ("yogurt", "cookies", "bar", "juice"),
    "NUT-ENERGY": tuple(TEMPLATES),
    "ALG-SPEC-MISSING": ALLERGEN_TEMPLATES,
    "LABEL-TRUNCATED": ("cookies", "bar", "bread", "sauce", "spread"),
    "clean_sugar_free_lt": ("bread", "sauce", "spread"),
    "clean_protein": ("yogurt", "kefir", "spread"),  # protein >= 12 % of energy
    "clean_fat_low": ("juice", "bread"),
    "clean_no_added_sugar": ("juice",),
    "clean_fibre": ("bar", "bread"),  # fibre >= 3 g
    "clean_plain": tuple(TEMPLATES),
}
# Added to the tail of a cropped case: the cut-off part is two lines of minor ingredients.
EXTRA_TAIL = ("ароматизатор ідентичний натуральному", "барвник бета-каротин", "вода питна")
PRODUCER = "Виробник: ТОВ «Тестовий завод», Україна, м. Київ."


# --- pools ------------------------------------------------------------------------------------


def load_pool(split: str) -> dict:
    return yaml.safe_load((POOLS / f"{split}.yaml").read_text(encoding="utf-8"))


def plain_text(marked: str) -> str:
    return marked.replace("**", "")


def caps(marked: str) -> str:
    """Emphasis by capitals: the **…** words in upper case, without the markup."""
    return re.sub(r"\*\*(.+?)\*\*", lambda m: m[1].upper(), marked)


# --- building a case (no images) --------------------------------------------------------------


@dataclass
class Case:
    id: str
    split: str
    template: str
    scenario: str
    quality: str
    extraction: dict
    spec: dict | None
    violations: list[dict]
    expected_flags: list[dict]
    oov: list[str]
    full_ingredients: str  # what is printed; differs from the truth only when cropped
    angle: float = 0.0
    meta_extra: dict = field(default_factory=dict)

    def truth(self) -> dict:
        meta = {
            "synthetic": True,
            "quality": self.quality,
            "template": self.template,
            "scenario": self.scenario,
            "oov": self.oov,
            **self.meta_extra,
        }
        return {
            "violations": self.violations,
            "expected_flags": self.expected_flags,
            "extraction": self.extraction,
            "meta": meta,
        }


def fmt(value: float) -> str:
    return f"{value:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def energy(n: dict[str, float]) -> int:
    """kcal by Reg. 1169/2011 Annex XIV: 4·carbs + 4·protein + 9·fat + 2·fibre."""
    return round(4 * n["carbs"] + 4 * n["protein"] + 9 * n["fat"] + 2 * n["fibre"])


def build_case(split: str, index: int, scenario: str, quality: str, rng: random.Random) -> Case:
    pool = load_pool(split)
    key = rng.choice(SCENARIO_TEMPLATES[scenario])
    t = TEMPLATES[key]
    off: list[str] = []
    violations: list[dict] = []
    flags: list[dict] = []

    # allergen ingredients from the pool; two slots of one category get different entries
    entries: list[tuple[str, dict]] = []
    for category in dict.fromkeys(t.slots):
        count = t.slots.count(category)
        entries += [(category, e) for e in rng.sample(pool["allergens"][category], count)]
    use_caps = rng.random() < CAPS_SHARE
    plain_on = None
    if scenario == "ALG-EMPH":
        plain_on = rng.randrange(len(entries))
        violations.append({"rule_id": "ALG-EMPH", "target": entries[plain_on][0]})

    def shown(i: int, entry: dict) -> str:
        if i == plain_on:
            return plain_text(entry["text"])
        return caps(entry["text"]) if use_caps else entry["text"]

    allergen_items = [(shown(i, e), cat, e) for i, (cat, e) in enumerate(entries)]
    for _, _, e in allergen_items:
        if e.get("oov"):
            off.append(plain_text(e["text"]))

    no_sugar = scenario in ("no_added_sugar", "clean_no_added_sugar", "clean_sugar_free_lt")
    sweet = [] if no_sugar else list(t.sweet)
    if scenario == "no_added_sugar":
        sweet = [rng.choice(pool["sweeteners"])]
        violations.append({"rule_id": "no_added_sugar", "target": "no_added_sugar"})
    others = [*t.plain, *sweet]
    if rng.random() < TRAP_SHARE:
        trap = rng.choice(pool["traps"])
        others.append(trap["text"])
        if trap.get("oov"):
            off.append(trap["text"])
    # allergens and the rest interleaved (main part), then the minor tail
    main: list[tuple[str, str | None]] = []
    rest = list(others)
    rng.shuffle(rest)
    for text, cat, _ in allergen_items:
        main.append((text, cat))
        if rest:
            main.append((rest.pop(), None))
    main += [(r, None) for r in rest]
    cropped = scenario == "LABEL-TRUNCATED"
    tail = [*t.tail, *EXTRA_TAIL] if cropped else list(t.tail)
    ingredients = main + [(x, None) for x in tail]
    full = ", ".join(text for text, _ in ingredients) + "."

    # nutrition
    n = dict(t.nutrition)
    shown_n = {k: f"{fmt(v)} г" for k, v in n.items()}
    recipe_n = dict(n)
    if scenario == "clean_sugar_free_lt":
        shown_n["sugars"] = LT_SUGARS
        recipe_n["sugars"] = LT_SUGARS_RECIPE
    kcal = energy(n)
    declared = kcal
    if scenario == "NUT-ENERGY":
        declared = round(kcal * rng.choice(ENERGY_ERRORS))
        violations.append({"rule_id": "NUT-ENERGY", "target": "energy"})
    per = "100g" if t.form == "solid" else "100ml"

    # front: name + 0-2 claims (+ the natural sugars statement)
    claims: list[str] = []
    claim_ids = {
        "sugar_free": ["sugar_free"],
        "clean_sugar_free_lt": ["sugar_free"],
        "protein_source": ["protein_source"],
        "clean_protein": ["protein_source"],
        "fat_low": ["fat_low"],
        "clean_fat_low": ["fat_low"],
        "no_added_sugar": ["no_added_sugar"],
        "clean_no_added_sugar": ["no_added_sugar"],
        "clean_fibre": ["fibre_source", "fat_low"] if key == "bread" else ["fibre_source"],
    }.get(scenario, [])
    for cid in claim_ids:
        wording = rng.choice(pool["claims"][cid])
        claims.append(wording)
        if wording in pool.get("claims_oov", []):
            off.append(wording)
    if scenario in ("sugar_free", "protein_source", "fat_low"):
        violations.append({"rule_id": scenario, "target": scenario})
    name = rng.choice(pool["names"][key])
    front = [name, *claims]
    if scenario == "clean_no_added_sugar":
        front.append(pool["natural_sugars"])
    front.append(t.net)

    # may contain: categories that are not in the ingredients
    may: list[str] = []
    used = set(t.slots)
    if not cropped and rng.random() < MAY_CONTAIN_SHARE:
        free = [c for c in pool["may_contain_forms"] if c not in used]
        may = sorted(rng.sample(free, rng.choice((1, 2))))
        used |= set(may)
    may_text = (
        pool["may_contain"].format(", ".join(pool["may_contain_forms"][c] for c in may))
        if may
        else None
    )

    # photos: front + back; a cropped case has the ingredients alone on the cut back photo
    # and the table on a third (side) photo
    table_photo = 2 if cropped else 1
    photos = [
        {"index": 0, "side": "front", "quality": "ok", "note": None},
        {"index": 1, "side": "back", "quality": "cropped" if cropped else "ok", "note": None},
    ]
    if cropped:
        photos.append({"index": 2, "side": "side", "quality": "ok", "note": None})
    ingredients_text = full
    if cropped:
        ingredients_text = None  # set after layout: the visible part + "[…]"
        flags.append({"rule_id": "LABEL-TRUNCATED", "target": "ingredients"})
        flags.append({"rule_id": "IMG-QUALITY", "target": "photo_1"})
    extraction = {
        "photos": photos,
        "emphasis_resolvable": True,
        "ingredients_marked": {"text": ingredients_text, "photo_index": 1},
        "may_contain_text": {"text": may_text, "photo_index": 1} if may_text else None,
        "nutrition": {
            "per": per,
            "portion_text": None,
            "energy": f"{round(declared * 4.184)} кДж / {declared} ккал",
            **shown_n,
            "photo_index": table_photo,
        },
        "other_text": [
            *({"text": x, "photo_index": 0} for x in front),
            {"text": t.storage, "photo_index": table_photo},
            {"text": PRODUCER, "photo_index": table_photo},
        ],
    }

    # recipe
    spec = None
    if scenario == "ALG-SPEC-MISSING" or rng.random() < SPEC_SHARE:
        spec_ingredients = [
            {"name": plain_text(text).lower(), "allergens": [cat] if cat else []}
            for text, cat in ingredients
        ]
        if scenario == "ALG-SPEC-MISSING":
            missing = rng.choice(sorted(c for c in pool["allergens"] if c not in used))
            entry = rng.choice(pool["allergens"][missing])
            at = rng.randrange(len(main) + 1)
            spec_ingredients.insert(at, {"name": plain_text(entry["text"]), "allergens": [missing]})
            violations.append({"rule_id": "ALG-SPEC-MISSING", "target": missing})
        spec = {"product_name": name, "form": t.form, "ingredients": spec_ingredients}
        if may:
            spec["may_contain"] = may
        if scenario != "NUT-ENERGY" and rng.random() < SPEC_NUTRITION_SHARE:
            spec["nutrition_per_100"] = {"energy_kcal": kcal, **recipe_n}

    angle = 0.0
    if quality == "rotate":
        angle = rng.uniform(*ROTATE_DEGREES) * rng.choice((-1, 1))
    case = Case(
        id=f"{split}-{index:03d}",
        split=split,
        template=key,
        scenario=scenario,
        quality=quality,
        extraction=extraction,
        spec=spec,
        violations=violations,
        expected_flags=flags,
        oov=off,
        full_ingredients=full,
        angle=round(angle, 2),
        meta_extra={"emphasis": "caps" if use_caps else "bold"},
    )
    if cropped:
        visible = render_back_ingredients(case)[1]
        case.extraction["ingredients_marked"]["text"] = f"{visible} […]"
        # the cut part must hold nothing that matters (allergens, sugars): only the tail is lost
        assert all(full.find(text) + len(text) <= len(visible) for text, _ in main), case.id
    return case


def build_cases(split: str, seed: int = DEFAULT_SEED) -> list[Case]:
    """The cases of one split: SCENARIOS × count, qualities in turn (cropped for truncation)."""
    rng = random.Random(f"{seed}:{split}")
    cases = []
    turn = 0
    for scenario, count in SCENARIOS.items():
        for _ in range(count):
            if scenario == "LABEL-TRUNCATED":
                quality = "cropped"
            else:
                quality = QUALITIES[turn % len(QUALITIES)]
                turn += 1
            cases.append(build_case(split, len(cases) + 1, scenario, quality, rng))
    return cases


# --- rendering ----------------------------------------------------------------------------------

WIDTH = 800
MARGIN = 40
TEXT = (30, 30, 30)
WHITE = (255, 255, 255)
_fonts: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}


def font(bold: bool, size: int) -> ImageFont.FreeTypeFont:
    if (bold, size) not in _fonts:
        name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
        _fonts[bold, size] = ImageFont.truetype(str(FONT_DIR / name), size)
    return _fonts[bold, size]


@dataclass
class Word:
    pieces: list[tuple[str, bool]]  # (text, bold)
    start: int  # offset in the marked text


def words(marked: str) -> list[Word]:
    """The marked text split on spaces; each word's pieces keep their bold flag."""
    out: list[Word] = []
    pieces: list[tuple[str, bool]] = []
    bold = False
    start = None
    i = 0
    while i <= len(marked):
        if i == len(marked) or marked[i] == " ":
            if pieces:
                out.append(Word(pieces, start))
            pieces, start = [], None
            i += 1
            continue
        if start is None:
            start = i
        if marked.startswith("**", i):
            bold = not bold
            i += 2
            continue
        if pieces and pieces[-1][1] == bold:
            pieces[-1] = (pieces[-1][0] + marked[i], bold)
        else:
            pieces.append((marked[i], bold))
        i += 1
    return out


def draw_rich(
    draw: ImageDraw.ImageDraw, marked: str, y: int, size: int, prefix: str = ""
) -> tuple[int, list[tuple[int, Word]]]:
    """Wrapped text with bold spans; returns the y below it and (line top, word) per word."""
    line_h = int(size * 1.45)
    x, placed = MARGIN, []
    space = draw.textlength(" ", font=font(False, size))
    if prefix:
        draw.text((x, y), prefix, font=font(True, size), fill=TEXT)
        x += draw.textlength(prefix, font=font(True, size)) + space
    for word in words(marked):
        width = sum(draw.textlength(t, font=font(b, size)) for t, b in word.pieces)
        if x + width > WIDTH - MARGIN and x > MARGIN:
            x, y = MARGIN, y + line_h
        placed.append((y, word))
        for t, b in word.pieces:
            draw.text((x, y), t, font=font(b, size), fill=TEXT)
            x += draw.textlength(t, font=font(b, size))
        x += space
    return y + line_h, placed


def _canvas(colour=WHITE, height=1600) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (WIDTH, height), colour)
    return image, ImageDraw.Draw(image)


def render_front(case: Case) -> Image.Image:
    t = TEMPLATES[case.template]
    image, draw = _canvas(t.colour, 600)
    items = [i["text"] for i in case.extraction["other_text"] if i["photo_index"] == 0]
    name, *claims, net = items
    draw.text((WIDTH // 2, 140), name, font=font(True, 48), fill=TEXT, anchor="mm")
    y = 250
    for claim in claims:
        w = draw.textlength(claim, font=font(True, 30))
        box = (WIDTH // 2 - w / 2 - 24, y - 30, WIDTH // 2 + w / 2 + 24, y + 30)
        draw.rounded_rectangle(box, radius=28, fill=(40, 120, 60))
        draw.text((WIDTH // 2, y), claim, font=font(True, 30), fill=WHITE, anchor="mm")
        y += 85
    draw.text((WIDTH - MARGIN, 560), net, font=font(False, 26), fill=TEXT, anchor="rs")
    return image


def render_back_ingredients(case: Case) -> tuple[Image.Image, str]:
    """The ingredient list (+ may contain). A cropped case is cut through its last line:
    returns the image and the marked text that stays fully visible."""
    image, draw = _canvas()
    y, placed = draw_rich(draw, case.full_ingredients, MARGIN, 24, prefix="Склад:")
    visible = case.full_ingredients
    if case.quality == "cropped":
        last_top = placed[-1][0]
        first_cut = next(word for top, word in placed if top == last_top)
        visible = case.full_ingredients[: first_cut.start].rstrip()
        return image.crop((0, 0, WIDTH, last_top + 16)), visible
    may = case.extraction["may_contain_text"]
    if may:
        y, _ = draw_rich(draw, may["text"], y + 10, 22)
    return image.crop((0, 0, WIDTH, y + 10)), visible


def render_table(case: Case, image: Image.Image, y: int) -> int:
    draw = ImageDraw.Draw(image)
    n = case.extraction["nutrition"]
    basis = "100 г" if n["per"] == "100g" else "100 мл"
    draw.text((MARGIN, y), f"Поживна цінність на {basis}", font=font(True, 26), fill=TEXT)
    y += 44
    rows = [
        ("Енергетична цінність", n["energy"]),
        ("Жири", n["fat"]),
        ("  з них насичені жири", n["saturates"]),
        ("Вуглеводи", n["carbs"]),
        ("  з них цукри", n["sugars"]),
        ("Харчові волокна", n["fibre"]),
        ("Білки", n["protein"]),
        ("Сіль", n["salt"]),
    ]
    for label, value in rows:
        draw.line((MARGIN, y, WIDTH - MARGIN, y), fill=TEXT, width=1)
        draw.text((MARGIN + 8, y + 8), label, font=font(False, 22), fill=TEXT)
        draw.text((WIDTH - MARGIN - 8, y + 8), value, font=font(False, 22), fill=TEXT, anchor="ra")
        y += 40
    draw.line((MARGIN, y, WIDTH - MARGIN, y), fill=TEXT, width=1)
    return y + 20


def render_table_photo(case: Case, index: int, y: int = MARGIN, image=None) -> Image.Image:
    if image is None:
        image, _ = _canvas()
    y = render_table(case, image, y)
    draw = ImageDraw.Draw(image)
    for item in case.extraction["other_text"]:
        if item["photo_index"] == index:
            y, _ = draw_rich(draw, item["text"], y, 20)
    return image.crop((0, 0, WIDTH, y + MARGIN))


def render_photos(case: Case) -> list[Image.Image]:
    front = render_front(case)
    ingredients, _ = render_back_ingredients(case)
    if case.quality == "cropped":
        return [front, ingredients, render_table_photo(case, 2)]
    back, _ = _canvas()
    back.paste(ingredients, (0, 0))
    return [front, render_table_photo(case, 1, ingredients.height + 10, back)]


def degrade(image: Image.Image, case: Case) -> bytes:
    if case.quality == "blur":
        image = image.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    if case.quality == "rotate":
        image = image.rotate(
            case.angle, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=(205, 205, 205)
        )
    out = io.BytesIO()
    image.save(out, "JPEG", quality=JPEG_QUALITY.get(case.quality, DEFAULT_JPEG_QUALITY))
    return out.getvalue()


def render_case(case: Case) -> list[bytes]:
    return [degrade(image, case) for image in render_photos(case)]


# --- writing --------------------------------------------------------------------------------


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_case(case: Case, root: Path) -> None:
    folder = root / case.split / case.id
    folder.mkdir(parents=True)
    for i, data in enumerate(render_case(case)):
        (folder / f"photo_{i}.jpg").write_bytes(data)
    if case.spec is not None:
        write_json(folder / "spec.json", case.spec)
    write_json(folder / "truth.json", case.truth())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--out", type=Path, default=ROOT / "cases")
    args = parser.parse_args()
    for split in SPLITS:
        shutil.rmtree(args.out / split, ignore_errors=True)  # only generated files live here
        cases = build_cases(split, args.seed)
        for case in cases:
            write_case(case, args.out)
        violations = sum(len(c.violations) for c in cases)
        flags = sum(len(c.expected_flags) for c in cases)
        print(f"{split}: {len(cases)} cases, {violations} violations, {flags} expected flags")


if __name__ == "__main__":
    main()
