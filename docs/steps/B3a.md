# B3a — прийом фото і vision-клієнт (модель: Sonnet)

Без ендпоінта і без БД.
- `app/images.py`: тип за вмістом (Pillow), ≤ 10 МБ, EXIF-поворот, ≤ 2048 px, sha256;
  помилки 422 у нашому форматі (image_too_large, image_unsupported).
- `app/vision/base.py`: VisionClient.extract(images, prompt) -> VisionResult(data,
  raw_text, usage, model); повтори на 503/таймаут 2/4/8 с + джиттер, ≤ 60 с; коди
  vision_not_configured, vision_invalid_key (Gemini 400 API_KEY_INVALID, без повторів),
  vision_rate_limited (429), vision_unavailable, vision_timeout — як llm_* у
  `~/pet/app/llm/base.py`. Лог «vision request» з usage.
- `app/vision/gemini.py` (inline_data, JSON-режим; responseSchema, якщо модель підтримує),
  `app/vision/groq.py` (qwen/qwen3.8-27b, OpenAI-сумісний chat з image_url data-URI, JSON
  mode), `app/vision/fallback.py` (як `~/pet/app/llm/fallback.py`: основний → запасний
  після вичерпаних 503 або на 429; запасний лише якщо фото ≤ 3, інакше
  vision_rate_limited), `app/vision/fake.py`; get_vision_client(settings);
  /health показує реальних провайдерів.
- Тести з httpx.MockTransport (без мережі, без реального сну — пауза ін'єктується):
  успіх; 503→503→200; 400 API_KEY_INVALID одразу; 429; таймаут; fallback спрацьовує і НЕ
  спрацьовує на 4 фото. images: EXIF, resize, не-зображення, завеликий файл.

Ворота: `make test && make lint`.
Особливі пункти рев'ю: ключі не в логах і не в помилках; немає повторів на 400/401/429.
Коміт: `feat(b3a): image intake and vision clients`.
