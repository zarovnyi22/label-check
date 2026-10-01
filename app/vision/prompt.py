"""The extraction prompt: transcription only (CLAUDE.md, "Модель лише транскрибує").

Built from the B1b spike prompt plus what the spike showed (docs/NOTES.md, B1b):
- cut-off text was completed from memory -> the "[…]" marker, never complete or skip;
- bold type was missed -> describe emphasis as thicker/brighter strokes, also in "may contain";
- the front's text was lost -> every printed text of every photo, the front included;
- storage/producer leaked into the ingredients -> where the list ends (the code cuts too);
- a per-portion table came back as null -> copy it with per = "portion".

Bump PROMPT_VERSION on any change: it is part of the extraction cache key.
"""

PROMPT_VERSION = "2026-10-01.1"

PROMPT = """\
You transcribe photos of ONE food package. You are NOT a reviewer: never judge whether
the label is legal or correct, never correct spelling, never translate, never add
hyphens or words, never complete text from memory. Copy exactly what is printed.
There are {n} photos; photo indexes start at 0 in the order given.

Return ONE JSON object with exactly these keys (any value may be null):
{{
  "photos": [{{"index": 0, "side": "front|back|side|unknown",
              "quality": "ok|blurry|glare|cropped|not_a_label", "note": "short or null"}}],
  "emphasis_resolvable": true | false | null,
  "ingredients_marked": {{"text": "...", "photo_index": 0}} | null,
  "may_contain_text": {{"text": "...", "photo_index": 0}} | null,
  "nutrition": {{"per": "100g|100ml|portion|prepared", "portion_text": "... or null",
                "energy": "...", "fat": "...", "saturates": "...", "carbs": "...",
                "sugars": "...", "fibre": "...", "protein": "...", "salt": "...",
                "photo_index": 0}} | null,
  "other_text": [{{"text": "...", "photo_index": 0}}]
}}

Rules:
- photos: exactly one entry per photo ({n} entries). side "front" is the face of the
  package with the product name. quality "cropped" if text runs off the photo edge,
  "blurry"/"glare" if text is hard to read, "not_a_label" if it is not packaging.
- ingredients_marked: the ingredient list verbatim, starting after "Склад:" /
  "Ingredients:", letter case as printed. If it is printed in several languages, copy the
  Ukrainian block only (English if there is no Ukrainian one). The list ends where storage
  conditions, the producer, "may contain", the nutrition table or a standard (ДСТУ, ТУ)
  begin: those are not part of it.
- Emphasis: compare each word with the surrounding plain text. Wrap every fragment printed
  in a different weight or style - bold (thicker, darker or brighter strokes), italic, bold
  italic, underlined, a different colour - in **double asterisks**, even a single word
  inside a phrase ("сухе **молоко**", "борошно **пшеничне**"). Do the same in
  may_contain_text. Mark nothing else: do not mark words because they are allergens.
  Capital letters in the same weight are not emphasis: keep the case, no asterisks.
- emphasis_resolvable: can the photo show font weight/style differences in the ingredient
  list at all? true if sharp enough to tell bold from regular (whether or not anything is
  bold), false if blur, glare or low resolution make it impossible, null if there is no
  ingredient list. It is about the photo, not about the label.
- may_contain_text: the "може містити / may contain" sentence verbatim, or null.
- nutrition: values as STRINGS exactly as printed, with units and signs ("0,5 г",
  "<0,5 г", "1760 кДж / 420 ккал"). Keep the decimal comma. Use the per 100 g / 100 ml
  column if there is one; if the table is only per portion, copy that column with
  per "portion"; "per" says which column you copied. Nutrition printed as running text
  counts too (and is not repeated in other_text). A value you cannot read is null; a
  nutrient that is not printed is null; never guess and never write 0 for a missing value.
- other_text: every other printed text from EVERY photo, the front included - product
  name, claims and slogans ("без цукру", "джерело білка", "натуральний"), footnotes,
  storage, producer, standards - one item per line or phrase, verbatim, with its photo.
  Do not repeat the ingredient list or the nutrition table.
- Cut off by the photo edge, hidden by a fold or glare, or unreadable: write "[…]" in its
  place, exactly where the missing text is ("[…]укор, борошно", "кислот[…]"). Never
  complete a word or a list from memory, from another language block or from what is
  typical; never skip a gap silently. A field unreadable as a whole is null.
"""

RETRY_SUFFIX = """

Your previous answer could not be used: {error}
Answer again with ONE valid JSON object in the format above and nothing else."""


def build_prompt(n_photos: int) -> str:
    return PROMPT.format(n=n_photos)
