# B2a — схеми і розбір (модель: Opus)

Прочитай `docs/SPEC.md` §1 і `docs/NOTES.md` («B1b — проба моделі») — врахуй висновок.

Зробити:
- `app/schemas.py`: ProductSpec, LabelExtraction (SPEC §1 з поправками з проби), Finding
  {rule_id, target, status, message, evidence, legal_ref}, статуси
  pass/violation/needs_review/not_checked/not_applicable, CheckOut.
- `app/parsing.py`:
  - `parse_amount(str|None) -> Amount(value, qualifier: eq|lt|trace) | None`: кома, «<»,
    «≤», «менше», «сліди»/«trace», пробіли, одиниці (г, g, мг→г); `parse_energy("1760 кДж
    / 420 ккал") -> (kj, kcal)`. Нерозбірне → None, ніколи 0.
  - `parse_ingredients(marked) ->` згадки {text, emphasized_spans, upper, depth}; ВЕЛИКІ =
    усі літери слова великі і слово ≥ 2 літер; незакриті `**` не ламають розбір.
- Тести: ≥ 15 кейсів parse_amount (зокрема «0,5», «<0,5», «сліди», «», «н/д», «12.5 г»);
  parse_ingredients на вкладених дужках, «сухе **молоко**», «МОЛОКО», незакритих `**`;
  і на реальному виводі проби з NOTES.md (вставити як рядок у тест — це вивід моделі, не
  ручна вигадка).

Ворота: `make test && make lint`.
Особливі пункти рев'ю: немає шляху, де нерозбірне стає 0; порівняння float.
Коміт: `feat(b2a): schemas and label text parsing`.
