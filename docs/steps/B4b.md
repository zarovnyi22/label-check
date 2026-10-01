# B4b — правила на правді і справжні фото (модель: Opus)

1. Тест: run_rules(truth.extraction, spec) для КОЖНОГО синтетичного кейсу дає рівно
   truth.violations (rule_id+target). Падає — з'ясуй, баг у правилах чи генераторі,
   виправ, запиши в NOTES.md.
2. Справжні фото: `samples/test/` (p04–p15, SOURCES.md) → `eval/real/<id>/` (фото не
   комітимо: `.gitignore`; комітимо truth.json, spec*.json і SOURCES.md з розкодованими
   HTML-сутностями).
   Розмітку робить **субагент** (Agent/Task tool), щоб основний контекст не бачив test-фото:
   дай йому SPEC §1–§2 і шаблон truth.json; він дивиться фото і пише truth.json
   (extraction вручну з фото + violations за правилами SPEC); сумнівне → поле "notes".
   Ти фото НЕ відкриваєш.
3. Напівсинтетика: скрипт, що для кожного справжнього кейсу робить 1–2 spec з навмисною
   розбіжністю (алерген у рецептурі, якого нема на етикетці) і додає в truth
   ALG-SPEC-MISSING. Справжні — лише test.

Ворота: `make test && make lint`; усі truth.json валідні за схемою.
Коміт: `feat(b4b): rules-on-truth test and real-photo labels`.
⏸ Зупинись: людина вибірково перевіряє 3 truth.json проти фото (список шляхів дай у звіті).
