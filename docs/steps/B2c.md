# B2c — твердження, нутрієнти, загальні правила, рушій (модель: Opus)

Прочитай `docs/SPEC.md` §2 (загальні, твердження з таблицею порогів, узгодженість).

Зробити:
- `app/rules/claims.py`: пошук тверджень регулярками в other_text (uk + en, регістр,
  дефіси); 13 порогів; form зі spec, інакше з nutrition.per; qualifier «lt» («<0,5» при
  порозі 0.5 — pass); CLAIM-UNVERIFIABLE; твердження без потрібного нутрієнта →
  needs_review.
- `app/rules/nutrition.py`: NUT-ENERGY, NUT-KJ, NUT-SUBSETS, NUT-SPEC.
- `app/rules/general.py`: IMG-QUALITY, LABEL-MISSING, SIDE-FRONT-MISSING, NUT-PER.
- `app/rules/engine.py`: run_rules(extraction, spec|None) -> (findings, verdict);
  fail > needs_review > incomplete > pass; RULES_VERSION.
- catalog.py доповнити; `GET /rules`.
- Тести: кожне правило × статуси; рівно на порозі; рідке vs тверде; «без доданого цукру» з
  медом і з «містить природні цукри»; verdict на 4 комбінаціях.
Пороги звір з наказом МОЗ №1145. Сумнів — TODO у коді + рядок у NOTES.md
(«Відкриті питання»), не вигадувати.

Ворота: `make test && make lint`; `make up && curl -s localhost:8010/rules | head -c 800`;
run_rules на «без цукру» + цукри «3,1» → violation з 3.1 і порогом 0.5; цукри «<0,5» → pass.
Особливі пункти рев'ю: кожне правило є в catalog з legal_ref.
Коміт: `feat(b2c): claims, nutrition checks and rules engine`.
