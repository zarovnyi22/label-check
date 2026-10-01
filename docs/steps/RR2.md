# RR2 — глибоке рев'ю шляху фото → вердикт (модель: Opus)

Як RR1, але область для субагента: app/images.py, app/vision/, app/extraction.py,
app/checks.py, app/routers/checks.py (+ CLAUDE.md, SPEC §1, §3). Особливо: чи може збій
моделі, частково невалідна відповідь, порожня екстракція чи кеш дати pass; чи ключі
можуть потрапити в логи/відповідь.
Звіт → `docs/reviews/RR2.md`; виправлення з регресійними тестами.
Коміт: `fix(rr2): review fixes for extraction path`.
