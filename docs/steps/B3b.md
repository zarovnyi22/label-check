# B3b — промпт, кеш, run_check, POST /checks (модель: Opus; живий LLM: ≤ 6)

Прочитай `docs/SPEC.md` §1 і §3, `docs/NOTES.md`.
- `app/vision/prompt.py`: промпт зі spike, доведений до ладу з урахуванням NOTES.md;
  PROMPT_VERSION. Модель ЛИШЕ транскрибує: дослівно, без перекладу і «виправлень», числа
  як на фото, виділене шрифтом — у `**…**`, обрізане/нечитабельне → `[…]` (поле повністю
  → null), emphasis_resolvable чесно, side і quality для кожного фото.
- `app/extraction.py`: кеш (ключ з SPEC §3); валідація Pydantic; невалідний JSON — один
  повтор з текстом помилки, далі vision_bad_output.
- `app/checks.py`: run_check(images, spec) — кроки 1–5; її ж викличе eval.
- `app/routers/checks.py`: POST /checks (multipart: images 1–4, spec — JSON-рядок,
  optional; spec валідується ДО виклику моделі), GET /checks/{id}; збереження в БД (байти
  фото, raw_text, extraction, findings, verdict, model, версії, usage, cache_hit,
  duration_ms); помилка моделі → status=error у БД і наш формат у відповіді. Приклади в
  OpenAPI.
- Тести з FakeVision: повний шлях з БД; невалідний spec → 422 без виклику моделі; 0 і 5
  фото → 422; кеш (другий запит не викликає модель; інший порядок фото — інший ключ);
  помилка моделі → status=error; GET 404.

Ворота: `make test && make lint`; `make up`; живий POST з p02 (3 фото) і p03 (2 фото);
повтор того самого → cache_hit true; GET /checks/{id}. Порівняй findings з фото (Read):
чи правильні, чи evidence показує місце. Висновок — у NOTES.md («B3b — живі перевірки»).
Особливі пункти рев'ю: помилка моделі ніколи не дає pass; кеш не змішує порядок фото.
Коміт: `feat(b3b): extraction cache and POST /checks`.
