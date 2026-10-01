# B1b — CI і проба моделі (модель: Sonnet; живий LLM: ≤ 4 виклики)

Зробити:
- `.github/workflows/ci.yml`: ruff + pytest з Postgres-сервісом (той самий образ, що в
  compose), docker build без push — як у `~/pet/.github/workflows/ci.yml`, без k8s.
- `scripts/spike_vision.py`: одноразова проба. Бере 1–3 фото (шляхи аргументами), шле в
  Gemini (REST generateContent, inline_data, responseMimeType application/json) з
  чорновим промптом транскрипції за схемою LabelExtraction з `docs/SPEC.md` §1 (склад
  дослівно з `**виділенням**`, числа рядками як на фото, other_text, photos[side,quality],
  emphasis_visible), друкує сирий JSON і usageMetadata. Без БД і FastAPI. Ключ і модель
  з .env. Groq не потрібен.
- Сервіс `tools` у compose (profile tools, звичайна мережа, репозиторій змонтовано) для
  скриптів з інтернетом; `make spike FILES="..."` (python -u).

Ворота (запускаєш сам):
```
make test && make lint
make spike FILES="samples/p02_front.jpg samples/p02_back.jpg samples/p02_nutrition.jpg"
make spike FILES="samples/p03_front.jpg samples/p03_back.jpg"
```
(+ `samples/p16_back.jpg`, якщо файл є.) `samples/test/` не чіпати.

Аналіз проби: відкрий ці фото (Read) і порівняй з виводом: кирилиця; `**…**` саме на
виділених шрифтом словах (і ніде більше); числа як на фото («0,0», «<0,5»); написи
фронту в other_text; side/quality; токени на виклик. Запиши висновок (5–10 рядків,
конкретно: що модель робить добре, що погано, що змінити в схемі/промпті) у
`docs/NOTES.md`, розділ «B1b — проба моделі».

Особливі пункти рев'ю: ключ не потрапляє у вивід/логи; скрипт не імпортується тестами;
CI використовує той самий образ Postgres.

Коміт: `feat(b1b): CI and vision spike`.
⏸ Після звіту зупинись: людина може глянути висновок проби (одне повідомлення) і сказати
«далі».
