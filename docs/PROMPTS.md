> **Зараз працюємо в автономному режимі:** після `/clear` пиши Claude Code лише
> «Виконай крок B2a» — він читає `docs/steps/B2a.md` і CLAUDE.md («Автономний режим»), сам
> запускає ворота, робить самоперевірку, комітить і пушить. Цей файл лишається як довідка.

# Label Check — промпти для Claude Code по кроках

## Як працюємо

Кожен блок розбито на **кроки** (B2a, B2b…). Один крок = одна ітерація Claude Code =
один коміт. Цикл кроку завжди однаковий:

```
1. Промпт кроку        → Claude Code пише код і тести, зупиняється
2. Ворота              → ти запускаєш команди з розділу кроку; все зелене?
3. Промпт R (рев'ю)    → Claude Code перевіряє свій diff за чеклістом, НІЧОГО не править
4. Ти вирішуєш         → «виправ 1, 3; 2 — ок як є» → Claude править → ворота ще раз
5. «ок, комітимо»      → коміт → git push
```

Після **B2 і B3** — ще **Промпт RR**: глибоке рев'ю в **новій** сесії Claude Code
(новий термінал → `claude`), щоб код перевіряв не той самий контекст, що його писав.

Правила для тебе:
- Якщо щось впало — встав Claude Code **повний** текст помилки, а не переказ.
- Не проси «зроби все одразу» і не пропускай ворота «бо поспішаю» — у `pet` баги знайшов ПМ
  саме там, де перевірки не було.
- Легке рев'ю (Промпт R) роби в тій самій сесії, що й крок, — контекст уже є, це дешево.
- Не вклався в блок — ріжемо скоп кроку за списком з `docs/OVERVIEW.md` §9, а не наступні
  кроки.

### Економія лімітів Claude

1. **`/clear` після кожного коміту.** Кожна репліка відправляє моделі всю історію сесії —
   довга сесія з'їдає ліміт у рази швидше. Новий крок починай з **Промпту S** (нижче).
2. **Модель під крок** (`/model`): колонка «Модель» у таблиці. Sonnet — рутина (скелет,
   CI, генератор, раннер, README); Opus — правила, промпт екстракції, рев'ю.
3. **Не вставляй великі виводи**: `make test 2>&1 | tail -40`, JSON — `| head -40`.
   Помилку (traceback) — повністю, логи — ні.
4. **На `~/pet` посилайся конкретними файлами**, не «подивись проєкт».
5. Claude Code сам читає лише CLAUDE.md і розділ `docs/SPEC.md`, на який посилається
   крок. OVERVIEW і PROMPTS йому не потрібні.
6. Ліміт закінчився — нічого страшного: усе в комітах. Наступного разу — Промпт S.

### Промпт S — старт кроку в чистій сесії

```text
Прочитай CLAUDE.md. Ми на кроці <B2b>; останній коміт: <вивід git log -1 --oneline>.
Попередні кроки зроблені й закомічені — не переробляй їх. Після кроку зупинись, дай
команди воріт і чекай мого «ок». Ось промпт кроку:
<встав промпт кроку>
```

| Час | Крок | Що | Живий LLM | Модель |
|---|---|---|---|---|
| 0:00–0:25 | B0 | твоя частина: тека, ліміти, запасний провайдер, фото | — | — |
| 0:25–0:30 | P0 | старт Claude Code | — | Sonnet |
| 0:30–0:55 | B1a | скелет: FastAPI, Postgres, міграції, /health, compose | — | Sonnet |
| 0:55–1:15 | B1b | CI + проба моделі на фото | ти, 2–3 | Sonnet |
| 1:15–1:40 | B2a | схеми + розбір чисел і розмітки | — | Opus |
| 1:40–2:05 | B2b | алергени: словник + правила | — | Opus |
| 2:05–2:35 | B2c | твердження, нутрієнти, загальні, рушій, /rules | — | Opus |
| 2:35–2:45 | RR1 | глибоке рев'ю ядра | — | Opus |
| 2:45–3:10 | B3a | фото + vision-клієнт (без ендпоінта) | — | Sonnet |
| 3:10–3:40 | B3b | промпт, кеш, run_check, POST /checks | ти, 2–3 | Opus |
| 3:40–3:50 | RR2 | глибоке рев'ю шляху фото → вердикт | — | Opus |
| 3:50–4:25 | B4a | генератор синтетики | — | Sonnet |
| 4:25–4:45 | B4b | тест «правила на правді = 100 %» + справжні фото | — | Opus |
| 4:45–5:05 | B5a | eval-раннер | — | Sonnet |
| 5:05–5:30 | B5b | метрики + звіт + замір dev | ти, ≈ 30–40 | Opus |
| 5:30–6:30 | B6 | одне покращення, замір test | ти, ≈ 30–40 | Opus |
| 6:30–7:30 | B7 | README, звірка з кодом, чистий клон | ти, 1 | Sonnet |
| 7:30–8:00 | — | запас | — | — |

---

## B0 — твоя частина до старту (≈ 25 хв, без Claude Code)

```bash
mkdir -p ~/label-check/docs ~/label-check/samples && cd ~/label-check && git init
# розпакуй архів: CLAUDE.md → ~/label-check/, а docs/ (OVERVIEW, SPEC, PROMPTS) → ~/label-check/docs/
git add CLAUDE.md docs && git commit -m "docs(b0): decisions, architecture, plan"
```
Створи порожній репозиторій на GitHub і `git remote add origin <url>`.

1. **Ліміти Gemini.** AI Studio → Rate limits для свого проєкту. Запиши RPM і RPD для 2–3
   Flash-моделей (зокрема тієї, що в `~/pet/.env`). Потрібно ≥ 100 запитів на день на
   обрану модель. Менше — інша модель або менший набір. Цифри — в CLAUDE.md, «Рішення».
2. **Запасний vision без картки** (≤ 10 хв): Groq (console.groq.com → Models) і OpenRouter
   (моделі `:free` з входом image). Знайшов — запиши назву; ні — так і запиши.
3. **Сфотографуй 10–15 упаковок** (зворот: склад + таблиця; і фронт з написами) у
   `~/label-check/samples/` (назви `p01_front.jpg`, `p01_back.jpg`…). Різні продукти:
   молочне, печиво, батончик, напій, соус. `samples/` у git не потрапляє.
4. Ключ Gemini той самий, що в `pet`.

---

## Промпт P0 — старт

```text
Новий проєкт. Прочитай CLAUDE.md — там рішення, архітектура, жорсткі правила і порядок
роботи. docs/SPEC.md читай лише той розділ, на який посилається промпт кроку;
docs/OVERVIEW.md — лише якщо треба зрозуміти «чому», і скажи мені, навіщо. Для довідки є мій
попередній проєкт у ~/pet (той самий стек): звідти можна брати підходи до Dockerfile,
docker-compose (сервіс test в ізольованій мережі), Makefile, JSON-логів (app/logs.py),
помилок і повторів HTTP (app/llm/base.py), CI. Адаптуй, не копіюй бездумно.

Працюємо кроками: я даю промпт кроку, один крок = один коміт. Після кожного кроку
зупиняйся, показуй список змінених файлів і команди воріт, і чекай. Нічого не комітиш без
мого «ок, комітимо». Тести ніколи не ходять у живий LLM і мережу. Не роби роботу
наступних кроків наперед.

Зараз нічого не кодь. Перекажи своїми словами (5–10 рядків) архітектуру, для B1a
перелічи файли, які створиш. Якщо бачиш у документах суперечність чи неясність — скажи
зараз.
```

---

## Промпт R — рев'ю кроку (після КОЖНОГО кроку, перед комітом)

```text
Зроби рев'ю змін цього кроку (git diff і нові файли) як суворий ревьюер. Нічого не
виправляй — лише звіт.

Чекліст:
1. Жорсткі правила CLAUDE.md: модель лише транскрибує; числа й тексти findings — з коду;
   «невідомо ≠ можна» (кожне None/null-поле веде до needs_review/not_checked, а не pass
   і не 0); формат помилок; секрети; тести без мережі й живого LLM.
2. Чи зроблено все з промпту кроку — і НІЧОГО з наступних кроків.
3. Тести: чи перевіряють поведінку, а не реалізацію; межові значення; null-поля; чи є
   тест, який впав би, якби логіку зламали. Чи немає ручних фікстур там, де їх треба
   генерувати.
4. Помилки: виняток, що проковтнуто; 500 замість нашого коду; ретрай там, де не можна.
5. Простота: мертвий код, зайві абстракції, дублювання, «магічні» числа без назви.
6. Узгодженість назв з CLAUDE.md (rule_id, поля схем, змінні .env, коди помилок).
<особливі пункти кроку — встав з розділу кроку>

Формат: таблиця № | серйозність (критично / важливо / дрібниця) | файл:рядок | що не так |
як виправити. Наприкінці — чи можна комітити після виправлення критичних.
```

## Промпт RR — глибоке рев'ю (нова сесія, після B2 і B3)

Відкрий **новий** термінал у `~/label-check` → `claude` → встав:

```text
Ти — незалежний ревьюер. Код писала інша сесія; ти його не бачив. Прочитай CLAUDE.md і
docs/SPEC.md §2, потім код <область — з розділу RR>. Нічого не виправляй.

Завдання: знайти, де сервіс може сказати pass (або не показати технологу порушення), хоча
порушення є. Для кожної підозри — придумай конкретну етикетку/екстракцію, на якій це
станеться, і перевір запуском (pytest -k або короткий скрипт у docker compose run --rm
test python -c ...). Неперевірене — познач як «гіпотеза».

Також: розбіжності коду з CLAUDE.md і SPEC.md; тести, що нічого не доводять; правила без legal_ref.

Звіт: таблиця № | серйозність | файл:рядок | сценарій відмови | доведено/гіпотеза | як
виправити. Максимум 10 пунктів, найважливіші першими.
```
Звіт встав у **основну** сесію: «ось рев'ю, виправ пункти …». Окремий коміт:
`fix(review-N): …`.

---

## B1a — скелет

```text
Крок B1a — скелет.
- pyproject.toml з uv (Python 3.12, версії закріплені ==, uv.lock): fastapi, uvicorn,
  asyncpg, pydantic-settings, httpx, pillow, python-multipart; dev: pytest,
  pytest-asyncio, ruff (налаштування як у ~/pet).
- app/config.py, app/errors.py (AppError і єдиний формат помилок, обробник 422 Pydantic
  теж у нашому форматі), app/logs.py (JSON-логи, request_id з X-Request-ID або
  згенерований), app/db.py (пул asyncpg, міграції на старті, ідемпотентні),
  app/main.py (lifespan), app/routers/health.py: GET /health
  {"status","db","vision_provider","vision_fallback_provider"}; 503, якщо БД недоступна.
- migrations/001_init.sql — схема з docs/SPEC.md §3.
- Dockerfile двостадійний (як у ~/pet, без torch і моделей; стадія dev з тестовими
  залежностями і fonts-dejavu-core для генератора в B4).
- docker-compose.yml: db (postgres:16-bookworm, закріплений тег, 127.0.0.1:5433,
  healthcheck), api (8010), test (profile test, мережа offline internal, ключі порожні,
  БД label_check_test, фікстури створюють і чистять її).
- Makefile: up, down, logs, health, test, lint, fmt.
- .env.example з коментарями: DATABASE_URL, VISION_PROVIDER=gemini,
  VISION_FALLBACK_PROVIDER=, GEMINI_API_KEY, VISION_MODEL, VISION_TIMEOUT_SECONDS,
  LOG_LEVEL. .gitignore (.env, .venv, кеші, samples/), .dockerignore.
- tests: /health (ok і БД недоступна), формат помилок (404, 422), міграції двічі поспіль.
- README: заготовка з розділами (що це, архітектура, запуск за 3 команди, приклади,
  число довіри, як працює перевірка на прикладі, рішення і компроміси, чим пожертвували,
  що далі).
Зупинись і дай команди воріт.
Коміт: "feat(b1a): skeleton, compose, migrations, health".
```

**Ворота:**
```bash
cp .env.example .env && nano .env      # ключ з ~/pet/.env, модель з B0
make up && curl -s localhost:8010/health        # {"status":"ok","db":"ok",...}
curl -s localhost:8010/nope                     # {"error":{"code":...}}
make test && make lint
docker compose down && make up && curl -s localhost:8010/health   # міграції вдруге — без помилок
git status                                      # .env і samples/ НЕ в списку
```
**Особливі пункти рев'ю:** порти лише 127.0.0.1 для db; сервіс test справді без інтернету;
версії закріплені; немає зайвого з `pet` (pgvector, torch, ембединги).

---

## B1b — CI і проба моделі

```text
Крок B1b.
- .github/workflows/ci.yml: ruff + pytest з Postgres-сервісом (той самий образ),
  docker build без push — як у ~/pet, без k8s.
- scripts/spike_vision.py: одноразова проба. Бере 1–2 фото (шляхи аргументами), шле в
  Gemini (REST generateContent, inline_data, responseMimeType application/json) з
  чорновим промптом транскрипції за схемою LabelExtraction з docs/SPEC.md §1 (склад дослівно з
  **виділенням**, числа рядками як на фото, other_text), друкує сирий JSON і
  usageMetadata. Без БД і FastAPI. Ключ і модель з .env.
- Сервіс tools у compose (profile tools, звичайна мережа, репозиторій змонтовано) для
  скриптів з інтернетом; make spike FILES="samples/p01_front.jpg samples/p01_back.jpg".
Зупинись і дай команди воріт.
Коміт: "feat(b1b): CI and vision spike".
```

**Ворота:**
```bash
make spike FILES="samples/p01_front.jpg samples/p01_back.jpg"
make spike FILES="samples/p02_back.jpg"
git push   # після коміту: у GitHub → Actions має бути зелено
```
**Подивись очима (найважливіше в B1):** чи правильно прочитана кирилиця; чи `**…**` саме
там, де на фото жирний; чи числа як на фото («3,1», «<0,5»); скільки токенів на виклик.
Запиши 2–3 речення висновку — вони підуть у промпт B2a. Якщо жирний вгадується погано —
скажи Claude зараз: міняємо схему/промпт до B2, а не після.

**Особливі пункти рев'ю:** ключ не потрапляє в лог/вивід; скрипт не імпортується тестами.

---

## B2a — схеми і розбір

```text
Крок B2a. Висновок з проби моделі: <встав 2–3 речення>.
- app/schemas.py: ProductSpec, LabelExtraction (docs/SPEC.md §1; врахуй висновок проби),
  Finding {rule_id, target, status, message, evidence, legal_ref}, статуси
  pass/violation/needs_review/not_checked/not_applicable, CheckOut.
- app/parsing.py:
  - parse_amount(str|None) -> Amount(value, qualifier: eq|lt|trace) | None: кома,
    "<", "≤", "менше", "сліди"/"trace", пробіли, одиниці (г, g, мг→г); "1760 кДж / 420
    ккал" → parse_energy -> (kj, kcal). Нерозбірне → None, ніколи 0.
  - parse_ingredients(marked: str) -> список згадок {text, emphasized_spans, upper,
    depth (вкладеність дужок)}; ВЕЛИКІ = усі літери слова великі і слово ≥ 2 літер.
- Тести: таблиця кейсів parse_amount (≥ 15, зокрема "0,5", "<0,5", "сліди", "", "н/д",
  "12.5 г"); parse_ingredients на вкладених дужках, на "сухе **молоко**", на "МОЛОКО",
  на незакритих **.
Зупинись і дай команди воріт. Коміт: "feat(b2a): schemas and label text parsing".
```

**Ворота:** `make test && make lint`; попроси Claude: «покажи вивід parse_amount для
кожного рядка таблиці нутрієнтів з моєї проби B1b».
**Особливі пункти рев'ю:** немає шляху, де нерозбірне стає 0; float-порівняння.

---

## B2b — алергени

```text
Крок B2b (docs/SPEC.md §2, алергени і словник).
- app/rules/allergen_dict.py: 14 категорій, основи uk + en форм, E220–E228, СПИСОК
  ВИКЛЮЧЕНЬ (кокосове молоко, мускатний горіх, гречка, какао-масло, соняшникова олія,
  рисове/вівсяне «молоко» → не milk). Поясни коротко підхід до відмінків.
- app/rules/allergens.py: find_allergens(mention) → категорії; ALG-EMPH,
  ALG-SPEC-MISSING, ALG-SPEC-EXTRA, ALG-MAY-CONTAIN; target = категорія; evidence з
  дослівним фрагментом і photo_index; message українською з коду.
- app/rules/catalog.py: rule_id → назва, legal_ref (поки для алергенів).
- Тести: кожне правило × (pass / violation / needs_review при emphasis_visible≠true /
  not_checked без spec); виключення; «сироватка», «лактоза», «меланж», «пшеничне
  борошно», «борошно пшеничне», «Wheat flour»; алерген лише у «може містити» не
  вимагає виділення.
Зупинись. Коміт: "feat(b2b): allergen dictionary and rules".
```

**Ворота:** `make test && make lint`; попроси Claude прогнати `find_allergens` на складі з
твоєї проби і показати, що знайдено. Відкрий `allergen_dict.py` очима.
**Особливі пункти рев'ю:** хибні збіги підрядка («сир» у «сироп», «риб» у «рибофлавін»,
«со» у «сол-»); алерген, що знайдено двічі, дає один finding чи два — узгоджено з
`target`.

---

## B2c — твердження, нутрієнти, загальні правила, рушій

```text
Крок B2c (docs/SPEC.md §2: загальні, твердження з таблицею порогів, узгодженість).
- app/rules/claims.py: пошук тверджень регулярками в other_text (uk + en, регістр,
  дефіси); 13 порогів з таблиці; form зі spec, інакше з nutrition.per; qualifier "lt"
  враховується («<0,5» при порозі 0.5 — pass); CLAIM-UNVERIFIABLE; твердження без
  потрібного нутрієнта → needs_review.
- app/rules/nutrition.py: NUT-ENERGY, NUT-KJ, NUT-SUBSETS, NUT-SPEC.
- app/rules/general.py: IMG-QUALITY, LABEL-MISSING, SIDE-FRONT-MISSING, NUT-PER.
- app/rules/engine.py: run_rules(extraction, spec|None) -> (findings, verdict);
  verdict fail > needs_review > incomplete > pass; RULES_VERSION.
- catalog.py доповнити; GET /rules.
- Тести: кожне правило × статуси; межові значення (рівно на порозі); рідке vs тверде;
  «без доданого цукру» з медом і з «містить природні цукри»; verdict на 4 комбінаціях.
Пороги звір з наказом МОЗ №1145. Не впевнений — TODO і скажи мені, не вигадуй.
Зупинись. Коміт: "feat(b2c): claims, nutrition checks and rules engine".
```

**Ворота:**
```bash
make test && make lint
curl -s localhost:8010/rules | python3 -m json.tool | head -60
```
Попроси Claude: «покажи findings для екстракції: "без цукру", цукри "3,1"; і для цукрів
"<0,5"» — у першому має бути violation з 3.1 і порогом 0.5, у другому pass.
**Особливі пункти рев'ю:** кожне правило є в catalog з legal_ref; TODO по порогах виписані.

### RR1 — глибоке рев'ю ядра
Область: `app/parsing.py`, `app/rules/`, `tests/`. Потім окремий коміт з виправленнями.

---

## B3a — фото і vision-клієнт

```text
Крок B3a (без ендпоінта і без БД).
- app/images.py: тип за вмістом (Pillow), ≤ 10 МБ, EXIF-поворот, ≤ 2048 px, sha256;
  помилки 422 у нашому форматі (image_too_large, image_unsupported).
- app/vision/base.py: VisionClient.extract(images, prompt) -> VisionResult(data,
  raw_text, usage, model); HTTP-повтори на 503/таймаут 2/4/8 с + джиттер, ≤ 60 с;
  коди: vision_not_configured, vision_invalid_key (Gemini 400 API_KEY_INVALID, без
  повторів), vision_rate_limited (429), vision_unavailable, vision_timeout — як llm_* у
  ~/pet/app/llm/base.py. Лог "vision request" з usage.
- app/vision/gemini.py (inline_data, JSON-режим; responseSchema, якщо модель підтримує),
  app/vision/fake.py; get_vision_client(settings); fallback — лише якщо в B0 знайдено
  провайдера: <так/ні, який>.
- Тести з httpx.MockTransport: успіх; 503→503→200 (повтори, без реального сну — пауза
  ін'єктується); 400 API_KEY_INVALID → vision_invalid_key одразу; 429; таймаут. images:
  EXIF-поворот, resize, не-зображення, завеликий файл.
Зупинись. Коміт: "feat(b3a): image intake and vision client".
```

**Ворота:** `make test && make lint`.
**Особливі пункти рев'ю:** ключ не логується і не потрапляє в помилки; тести не сплять
реально; немає повторів на 400/401/429.

---

## B3b — промпт, кеш, run_check, POST /checks

```text
Крок B3b.
- app/vision/prompt.py: промпт з B1b, доведений до ладу; PROMPT_VERSION. Модель ЛИШЕ
  транскрибує: дослівно, без перекладу і «виправлень», числа як на фото, виділене
  шрифтом — у **…**, нечитабельне → null, emphasis_visible чесно, side і quality для
  кожного фото. Познач, що я його перегляну руками.
- app/extraction.py: кеш extraction_cache (sha256 всіх фото по порядку + PROMPT_VERSION +
  модель); валідація Pydantic; невалідний JSON — один повтор з текстом помилки, далі
  vision_bad_output.
- app/checks.py: run_check(images, spec) — кроки 1–5; її ж викличе eval.
- app/routers/checks.py: POST /checks (multipart: images 1–4, spec — JSON-рядок,
  optional), GET /checks/{id}; збереження в БД (байти фото, raw_text, extraction,
  findings, verdict, model, версії, usage, cache_hit, duration_ms); помилка моделі теж
  зберігається (status=error) і повертається нашим форматом. Приклади запитів у OpenAPI.
- Тести з FakeVision: повний шлях з БД; невалідний spec → 422; 0 і 5 фото → 422;
  кеш — другий запит не викликає модель; помилка моделі → запис status=error; GET 404.
Дай мені curl для живої перевірки. Зупинись. Коміт: "feat(b3b): extraction cache and POST /checks".
```

**Ворота:**
```bash
make up
curl -s -X POST localhost:8010/checks \
  -F "images=@samples/p01_front.jpg" -F "images=@samples/p01_back.jpg" | python3 -m json.tool
# той самий запит ще раз → cache_hit: true, швидко
curl -s localhost:8010/checks/1 | python3 -m json.tool | head -30
make test && make lint
```
Дивись: склад прочитано правильно; `**…**` на жирних алергенах; числа як на фото; кожен
finding показує, де на упаковці проблема. **Прочитай `app/vision/prompt.py` очима.**
**Особливі пункти рев'ю:** немає шляху, де помилка моделі дає вердикт `pass`; кеш не
змішує різний порядок фото; spec валідований до виклику моделі (не палимо ліміт на
невалідний запит).

### RR2 — глибоке рев'ю шляху фото → вердикт
Область: `app/images.py`, `app/vision/`, `app/extraction.py`, `app/checks.py`,
`app/routers/checks.py`.

---

## B4a — генератор синтетики

```text
Крок B4a (docs/SPEC.md §4; каталог порушень — docs/OVERVIEW.md §7, останній абзац).
eval/generate.py — синтетичні етикетки на Pillow (DejaVu Sans / Bold):
- 6–8 шаблонів продуктів (йогурт, печиво, батончик, сік, хліб, соус…), тверді й рідкі;
- зворот: склад з виділеними алергенами (жирний або ВЕЛИКІ), «може містити», таблиця
  нутрієнтів з комою і інколи «<0,5»; фронт: назва + 0–2 твердження;
- формулювання з eval/pools/dev.yaml і eval/pools/test.yaml (різні!), з формами поза
  словником і пастками-виключеннями;
- каталог навмисних порушень + чисті етикетки (зокрема «без цукру» при
  «<0,5»);
- якість: чистий, розмиття, поворот ±7°, JPEG 40 %;
- кейс = eval/cases/<split>/<id>/: фото, spec.json (для частини), truth.json
  {violations: [{rule_id, target}], extraction: <правильна LabelExtraction>, meta:
  {synthetic: true, quality, template}};
- фіксований seed; ~60 кейсів; dev/test 50/50 зі стратифікацією за типом порушення;
  make generate.
- Тести: детермінованість за seed; кожен тип порушення є і в dev, і в test.
Покажи 3 картинки (шляхи): чисту, з порушенням, зіпсовану.
Зупинись. Коміт: "feat(b4a): synthetic label generator".
```

**Ворота:** `make generate && make test`; відкрий 3 картинки (пробіл у Finder): чи схожі на
етикетки, чи видно жирні алергени; відкрий `eval/pools/test.yaml` — інші формулювання,
ніж у dev?
**Особливі пункти рев'ю:** truth.extraction справді відповідає намальованому (не окремо
вигаданий); пули не перетинаються.

---

## B4b — правила на правді і справжні фото

```text
Крок B4b.
1. Тест: run_rules(truth.extraction, spec) для КОЖНОГО синтетичного кейсу (dev і test)
   дає рівно truth.violations (за rule_id+target) — «правила на ідеальних даних = 100 %».
   Падає — розберись, баг у правилах чи генераторі, і скажи мені до виправлення.
2. eval/real/README.md для мене: куди класти фото, шаблон truth.json, як розмічати;
   напівсинтетика — скрипт, що для кожного справжнього кейсу робить 1–2 варіанти spec з
   навмисною розбіжністю (алерген у рецептурі, якого нема на етикетці). Справжні — лише
   test. Порадь, чи комітити власні фото упаковок; атрибуція OFF — eval/real/SOURCES.md.
Зупинись. Коміт: "feat(b4b): rules-on-truth test and real-photo protocol".
```

**Твоя частина (≈ 25 хв):** розклади фото по `eval/real/`, заповни `truth.json` за шаблоном.
Сумніваєшся — скинь фото в чат, розберемо.
**Ворота:** `make test` (тест «100 %» зелений); `truth.json` усіх справжніх кейсів
валідні (попроси Claude перевірити схемою).

---

## B5a — eval-раннер

```text
Крок B5a.
eval/run.py: кейси через app.checks.run_check (без HTTP), з кешем екстракцій;
--split dev|test; --live (живий LLM, пауза EVAL_PAUSE_SECONDS); без --live і без кешу —
зрозуміла помилка зі списком кейсів без кешу. Помилка моделі (429 тощо) не валить
прогін: кейс = error, рахується окремо; повторний запуск догенеровує лише відсутнє.
Результат — eval/reports/<split>_<дата>.json (findings кожного кейсу). Makefile:
make eval SPLIT=dev, make eval-live SPLIT=dev (сервіс tools).
Тести з FakeVision на 3 кейсах. Зупинись. Коміт: "feat(b5a): eval runner".
```

**Ворота:** `make test`; `make eval-live SPLIT=dev LIMIT=3` (або як скаже Claude) —
3 живі виклики; потім `make eval SPLIT=dev LIMIT=3` — з кешу, без викликів.

---

## B5b — метрики і перший замір

```text
Крок B5b. eval/metrics.py:
- зарахування за {rule_id, target}, НЕ за вердиктом;
- safe recall і strict recall з 95 % інтервалом Вілсона;
- навантаження на людину: частка чистих кейсів з вердиктом fail/needs_review; частка
  findings needs_review; базова лінія «все → needs_review»;
- хибні тривоги (violation на чистих);
- точність екстракції: числа після parse_amount, виділення алергенів (precision/recall
  «не виділено»), знайдені твердження;
- розбивка за типом порушення, якістю фото, синтетика/справжні; error-кейси окремо.
Звіт eval/reports/<split>_<дата>.md поруч із .json (комітимо).
Тести: Вілсон на відомих числах; зарахування (finding з іншим target не зараховується;
needs_review через погане фото не зараховує порушення іншого правила).
Перший замір — лише dev, запускаю я. Зупинись. Коміт: "feat(b5b): metrics and dev report".
```

**Твоя частина:** `make eval-live SPLIT=dev` (≈ 30 кейсів, 10–15 хв), потім `make eval
SPLIT=dev`. Відкрий звіт: де втрати — у читанні чи в правилах (має бути 100 %)?

Метрики перевір легким рев'ю (Промпт R) з особливим пунктом: чи може метрика бути
завищеною (зарахування не за rule_id+target, кейси з error, витік test у dev).

---

## B6 — покращення на dev, замір на test

```text
Крок B6. Ось звіт dev: <встав>. Обрали проблему: <встав>.
Виправ її (промпт / словник / правило / розбір) — лише на основі dev. Змінюєш промпт —
підніми PROMPT_VERSION. Перезапусти eval на dev. Покажи до/після.
Потім ОДИН раз: make eval-live SPLIT=test — фінальне число, після нього нічого не
налаштовуємо. Команду запускаю я.
Коміт: "feat(b6): <що виправлено>; final test evaluation".
```

**Твоя частина:** `make eval-live SPLIT=test`. Число погане — **не** доналаштовуй: чесне
погане число з поясненням краще за підігнане.

---

## B7 — README і здача

```text
Крок B7 — здача. README (структура як у ~/pet/README.md):
1. Що це і для кого (3 рядки). Схема архітектури.
2. Запуск з нуля за 3 команди, приклад curl.
3. API з прикладом відповіді з реального запуску.
4. Число довіри: safe recall на test з 95 % інтервалом + навантаження + базова лінія;
   strict recall, хибні тривоги, точність екстракції (окремо виділення); розбивка; як
   отримано (синтетика з окремими пулами + N справжніх + напівсинтетика, dev/test, без
   доналаштування на test); dev до/після B6; чесні межі.
5. Як працює перевірка — на прикладі одного finding (фото → екстракція → розбір →
   правило → evidence).
6. Рішення і компроміси, чим пожертвували, що далі; ліміти Gemini з B0; запасний
   провайдер.
Потім звір README і CLAUDE.md з кодом (rule_id, коди помилок, змінні .env, команди make)
і виправ розбіжності. CLAUDE.md: статуси кроків. Зупинись.
Коміт: "docs(b7): README, trust number, decisions".
```

**Ворота (як у `pet`):**
```bash
git push
cd ~ && rm -rf label-check-check && git clone <url> label-check-check && cd label-check-check
cp ~/label-check/.env .env
make up && curl -s localhost:8010/health
curl -s -X POST localhost:8010/checks -F "images=@$HOME/label-check/samples/p01_back.jpg" | head -c 600
make test
```
CI у GitHub зелений. Прочитай README від початку до кінця так, ніби бачиш проєкт уперше.
