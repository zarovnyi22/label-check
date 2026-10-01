# B5a — eval-раннер (модель: Sonnet; живий LLM: ≤ 3)

`eval/run.py`: кейси через app.checks.run_check (без HTTP), з кешем екстракцій;
`--split dev|test`, `--live` (пауза EVAL_PAUSE_SECONDS, за замовчуванням 5), `--limit N`;
без --live і без кешу — зрозуміла помилка зі списком кейсів без кешу. Помилка моделі не
валить прогін: кейс = error, рахується окремо; повторний запуск догенеровує лише
відсутнє. Результат — `eval/reports/<split>_<дата>.json`. Makefile: `make eval SPLIT=dev`,
`make eval-live SPLIT=dev [LIMIT=3]` (сервіс tools). Тести з FakeVision на 3 кейсах.

Ворота: `make test && make lint`; `make eval-live SPLIT=dev LIMIT=3`; потім
`make eval SPLIT=dev LIMIT=3` (з кешу, без викликів).
Коміт: `feat(b5a): eval runner`.
