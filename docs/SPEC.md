# Label Check — специфікація (деталі для окремих кроків)

Тут — те, що потрібне лише на конкретних кроках: контракти даних, повний перелік правил з
порогами, словник, схема БД, eval. Загальні правила роботи — `CLAUDE.md`; «чому» —
`docs/OVERVIEW.md`. Читай лише розділ, на який посилається промпт кроку.

## 1. Вхід і вихід (B2a, B3b)

`POST /checks` — `multipart/form-data`: `images` (1–4 файли JPEG/PNG/WebP, ≤ 10 МБ кожен),
`spec` (необов'язково, JSON-рядок `ProductSpec`).

```json
ProductSpec = {
  "product_name": "Йогурт полуничний 2.5%",
  "form": "solid | liquid",
  "ingredients": [{"name": "молоко", "allergens": ["milk"]}, {"name": "цукор", "allergens": []}],
  "may_contain": ["nuts"],
  "nutrition_per_100": {"energy_kcal": 82, "fat": 2.0, "saturates": 1.3, "carbs": 13.7,
                        "sugars": 13.3, "fibre": 0.2, "protein": 2.4, "salt": 0.1}
}
```

`LabelExtraction` (що повертає модель; усі поля можуть бути `null`):
- `photos`: `[{index, side: front|back|side|unknown, quality: ok|blurry|glare|cropped|not_a_label, note}]`;
- `emphasis_visible`: чи видно на фото різницю шрифтів у складі (`true|false|null`);
- `ingredients_marked`: склад дослівно; виділені шрифтом фрагменти — у `**…**`;
  регістр як на фото; `photo_index`;
- `may_contain_text`: дослівно;
- `nutrition`: `per` (`100g | 100ml | portion | prepared | null`), `portion_text`,
  і рядки як на фото: `energy`, `fat`, `saturates`, `carbs`, `sugars`, `fibre`,
  `protein`, `salt`; `photo_index`;
- `other_text`: усі інші написи упаковки дослівно, по рядку, з `photo_index`
  (назва, твердження, «містить природні цукри», маркетинг).

Відповідь: `{check_id, verdict, summary, findings[], extraction, model, rules_version,
prompt_version, duration_ms}`.
`finding = {rule_id, target, status, message, evidence, legal_ref}`:
- `target` — об'єкт перевірки: категорія алергену (`milk`), id твердження
  (`sugar_free`), нутрієнт (`energy`) або `null`;
- `evidence` — `{photo_index, fragment, values, threshold}`: дослівний фрагмент з фото і
  числа, якими рахував код.

`verdict`: `fail` (є `violation`) > `needs_review` (є `needs_review`) > `incomplete`
(усе перевірене ок, але є `not_checked` — перелічено, що саме) > `pass`.

Також: `GET /checks/{id}`, `GET /rules` (усі правила з legal_ref), `GET /health`
`{"status","db","vision_provider","vision_fallback_provider"}`.


## 2. Правила (B2b, B2c)

Загальні:
- `IMG-QUALITY` — фото з `quality != ok` → `needs_review` («перефотографуйте фото N»).
- `LABEL-MISSING` — немає складу / таблиці нутрієнтів на жодному фото → `needs_review`.
- `SIDE-FRONT-MISSING` — немає фото фронту → твердження `not_checked`.
- `NUT-PER` — таблиця лише на порцію / у приготованому вигляді → пороги тверджень
  `needs_review`.

Алергени (Закон 2639-VIII; Регл. 1169/2011 ст. 21, дод. II):
- `ALG-EMPH` — кожна згадка алергену зі словника у складі виділена (жирний / ВЕЛИКІ) хоча
  б на слові-алергені. Не виділена → `violation`; `emphasis_visible` не `true` →
  `needs_review`. `target` = категорія.
- `ALG-SPEC-MISSING` — алерген з рецептури відсутній на етикетці → `violation`
  (критично). Без рецептури → `not_checked`.
- `ALG-SPEC-EXTRA` — алерген на етикетці, якого немає в рецептурі → `needs_review`.
- `ALG-MAY-CONTAIN` — «може містити» на етикетці vs `may_contain` у рецептурі →
  `needs_review` при розбіжності. (Різати першим, якщо бракує часу.)
- Словник (`app/rules/allergen_dict.py`): 14 категорій з основами українських і
  англійських форм (молок-, молоч-, вершк-, сироватк-, казеїн, лактоз-, масло вершкове,
  сир…; пшениц-/пшенич-, жит-, ячм-, овес/вівс-, спельт-, камут; яйц-/яєч-, меланж; соя/соєв-;
  арахіс-; горіхи — мигдал-, фундук, волоськ-, кеш'ю, пекан, бразильськ-, фісташк-,
  макадамі-; селер-; гірчиц-; кунжут-; діоксид сірки/сульфіт-/E220–E228; люпин-; молюск-;
  ракоподібн-; риб-). **Виключення** (не алергени): кокосове молоко, мускатний горіх,
  гречка, масло соняшникове / какао-масло, «рисове/вівсяне молоко» → лише овес, не молоко.
  Нормалізація: регістр, апострофи (’ ' ʼ), «е»/«є» не чіпати. Для злаків виділяють назву
  злаку, не «глютен».

Твердження (наказ МОЗ № 1145 / Регл. 1924/2006, додаток) — на 100 г (тверде) або 100 мл
(рідке); `form` зі spec, інакше з `nutrition.per`:
| id | Твердження | Умова |
|---|---|---|
| `sugar_free` | без цукру / sugar-free | цукри ≤ 0.5 г («<0,5» — pass) |
| `low_sugar` | низький вміст цукру | цукри ≤ 5 г (тверде), ≤ 2.5 г (рідке) |
| `no_added_sugar` | без доданого цукру | у складі немає моно-/дисахаридів і підсолоджувальних продуктів (цукор, мед, сиропи, декстроза, глюкоза, фруктоза, сахароза, мальтодекстрин — звірити з наказом); якщо цукри > 0 — в `other_text` має бути «містить природні цукри» |
| `protein_source` | джерело білка | білок ≥ 12 % енергії (4 ккал/г) |
| `protein_high` | високий вміст білка | білок ≥ 20 % енергії |
| `fat_low` | низький вміст жиру | жир ≤ 3 г (тверде), ≤ 1.5 г (рідке) |
| `fat_free` | без жиру / знежирений | жир ≤ 0.5 г |
| `satfat_low` | низький вміст насичених жирів | насичені ≤ 1.5 г (тверде), ≤ 0.75 г (рідке) і ≤ 10 % енергії |
| `fibre_source` | джерело клітковини | ≥ 3 г / 100 г або ≥ 1.5 г / 100 ккал |
| `fibre_high` | високий вміст клітковини | ≥ 6 г / 100 г або ≥ 3 г / 100 ккал |
| `salt_low` | низький вміст солі | сіль ≤ 0.3 г (натрій ≤ 0.12 г) |
| `salt_very_low` | дуже низький вміст солі | сіль ≤ 0.1 г |
| `energy_low` | низькокалорійний | ≤ 40 ккал (тверде), ≤ 20 ккал (рідке) |
Пороги звірити з текстом наказу № 1145; розбіжність або сумнів — `TODO` + README, не
мовчки. Порівняльні / здоров'я / нерегульовані → `CLAIM-UNVERIFIABLE` = `needs_review`.
Твердження є, а потрібного нутрієнта немає → `needs_review` («сфотографуйте таблицю»).

Узгодженість (ловить і помилки етикетки, і помилки читання фото):
- `NUT-ENERGY` — ккал ≈ 4·вуглеводи + 4·білок + 9·жир + 2·клітковина (допуск ±15 % або
  ±10 ккал) → інакше `needs_review` (поліоли/еритрит дають розбіжність — це очікувано).
- `NUT-KJ` — кДж ≈ ккал × 4.184 (±3 %).
- `NUT-SUBSETS` — цукри ≤ вуглеводи, насичені ≤ жир.
- `NUT-SPEC` (зі специфікацією) — нутрієнти етикетки vs рецептура (стартово ±20 % або
  ±2 г для малих значень) → `needs_review`. (Різати першим.)


## 3. Схема бази (B1a, B3b)

```sql
CREATE TABLE checks (
  id             BIGSERIAL PRIMARY KEY,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  status         TEXT NOT NULL,          -- done | error
  verdict        TEXT,                   -- fail | needs_review | incomplete | pass
  spec           JSONB,
  extraction     JSONB,
  findings       JSONB,
  error          JSONB,
  model          TEXT,
  prompt_version TEXT,
  rules_version  TEXT,
  usage          JSONB,                  -- токени з відповіді моделі
  raw_text       TEXT,                   -- сира відповідь моделі; зберігається і при помилці
                                         -- моделі (vision_bad_output), для аудиту
  cache_hit      BOOLEAN,
  duration_ms    INT
);
CREATE TABLE check_images (
  check_id BIGINT REFERENCES checks(id) ON DELETE CASCADE,
  idx INT, sha256 TEXT, mime TEXT, width INT, height INT,
  data BYTEA NOT NULL,                   -- фото після підготовки: саме те, що бачила модель
  PRIMARY KEY (check_id, idx)
);
CREATE TABLE extraction_cache (
  cache_key TEXT PRIMARY KEY,            -- sha256(конкатенація sha256 фото в порядку
                                         -- завантаження) + PROMPT_VERSION + модель;
                                         -- порядок важливий: від нього залежить photo_index
  prompt_version TEXT, model TEXT,
  extraction JSONB NOT NULL, raw_text TEXT, usage JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```


## 4. Число довіри (B4, B5)

- **Набір**:
  - **синтетичні етикетки** (генератор на Pillow, фіксований seed): шаблони продуктів,
    склад з алергенами, таблиця, твердження; навмисні порушення з каталогу; чисті +
    «зіпсовані» варіанти (розмиття, поворот ±7°, JPEG 40 %). Формулювання інгредієнтів
    беруться з **двох окремих пулів** (dev-пул і test-пул), щоб тюнінг словника на dev не
    бачив формулювань test; у пулах є форми, яких немає в словнику, і пастки-виключення.
  - **справжні фото**: 10–15 українських упаковок, сфотографованих телефоном (основне),
    або з Open Food Facts (CC BY-SA, атрибуція в `eval/real/SOURCES.md`); розмітка вручну.
    **Напівсинтетика**: до справжніх фото даємо рецептуру з навмисною розбіжністю
    (алерген є в рецептурі, але не на етикетці) — так справжні фото дають кейси
    `ALG-SPEC-MISSING` з відомою відповіддю. Справжні фото — лише в `test`.
- **Розмітка**: `truth.json` = `{violations: [{rule_id, target}], extraction: {...}}`.
- **Метрики** (на рівні порушень; порушення «знайдене», лише якщо є finding з тим самим
  `rule_id` + `target`):
  - **safe recall** — частка порушень, показаних технологу (`violation` або
    `needs_review`), з 95 % інтервалом Вілсона — **головне число**, завжди поруч із
  - **навантаженням на людину** — частка кейсів з вердиктом `needs_review`/`fail` серед
    чистих кейсів (і частка findings `needs_review`);
  - базова лінія «все → needs_review» (safe recall 100 %, навантаження 100 %) у звіті;
  - strict recall (лише `violation`); хибні тривоги (`violation` на чистих кейсах);
  - стадії окремо: точність екстракції (числа після `parse_amount`, виділення алергенів —
    precision/recall «не виділено», знайдені твердження) і точність правил на ідеальній
    екстракції (`truth.extraction` → має бути 100 %, це pytest-тест, без LLM);
  - розбивка за типом порушення, якістю фото, синтетика/справжні.
- `make eval SPLIT=dev` — з кешу екстракцій; `make eval-live SPLIT=dev` — з живим LLM
  (пауза між викликами під ліміт, `EVAL_PAUSE_SECONDS`). Звіти й сирі результати —
  `eval/reports/<split>_<дата>.md|json`, комітяться.

