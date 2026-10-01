# B2b — алергени (модель: Opus)

Прочитай `docs/SPEC.md` §2 (алергени і словник).

Зробити:
- `app/rules/allergen_dict.py`: 14 категорій, основи uk + en форм, E220–E228, СПИСОК
  ВИКЛЮЧЕНЬ (кокосове молоко, мускатний горіх, гречка, какао-масло, соняшникова олія,
  рисове/вівсяне «молоко» → не milk). Коментар про підхід до відмінків.
- `app/rules/allergens.py`: find_allergens(mention) → категорії; ALG-EMPH,
  ALG-SPEC-MISSING, ALG-SPEC-EXTRA, ALG-MAY-CONTAIN; target = категорія; evidence з
  дослівним фрагментом і photo_index; message українською з коду.
- `app/rules/catalog.py`: rule_id → назва, legal_ref (поки алергени).
- Тести: кожне правило × (pass / violation / needs_review при emphasis_visible≠true /
  not_checked без spec); виключення; «сироватка», «лактоза», «меланж», «пшеничне
  борошно», «борошно пшеничне», «Wheat flour»; алерген лише в «може містити» не вимагає
  виділення; склад з проби (NOTES.md).

Ворота: `make test && make lint`; прожени find_allergens на складах з проби і переконайся,
що знайдено те, що видно на фото.
Особливі пункти рев'ю: хибні збіги підрядка («сир» у «сироп», «риб» у «рибофлавін»);
один алерген двічі → узгоджено з target.
Коміт: `feat(b2b): allergen dictionary and rules`.
