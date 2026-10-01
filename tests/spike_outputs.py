"""Real answers of gemini-3.5-flash-lite from the B1b spike (docs/NOTES.md), verbatim.

Model output, not hand-written fixtures: parsing and schema tests run on what the model
actually returned. p02/p03 came from the first draft prompt (`emphasis_visible`, no `[…]`);
p16/p17 from the second (`emphasis_resolvable`, `[…]`). Pretty-printed by the spike script.
"""

P02 = r"""{
  "photos": [
    {
      "index": 0,
      "side": "front",
      "quality": "ok",
      "note": null
    },
    {
      "index": 1,
      "side": "back",
      "quality": "ok",
      "note": null
    },
    {
      "index": 2,
      "side": "back",
      "quality": "ok",
      "note": null
    }
  ],
  "emphasis_visible": false,
  "ingredients_marked": {
    "text": "вода питна, паста томатна (22 %), цукор, оцет спиртовий, модифікований кукурудзяний, сіль кухонна, прянощі сушені мелені (оріган, гвоздика, мускатний горіх).",
    "photo_index": 1
  },
  "may_contain_text": {
    "text": "Може містити яєчні продукти, глютен, молоко, гірчицю, сою.",
    "photo_index": 1
  },
  "nutrition": {
    "per": "100g",
    "portion_text": "11 г/g",
    "energy": "418 кДж/kJ / 98 ккал/kcal",
    "fat": "0,2 г/g",
    "saturates": "0 г/g",
    "carbs": "22 г/g",
    "sugars": "19 г/g",
    "fibre": "0,5 г/g",
    "protein": "1,1 г/g",
    "salt": "2,5 г/g",
    "photo_index": 2
  },
  "other_text": [
    {
      "text": "ТОРЧИН",
      "photo_index": 0
    },
    {
      "text": "ЛАГІДНИЙ КЕТЧУП",
      "photo_index": 0
    },
    {
      "text": "З НАТУРАЛЬНИМИ ІНГРЕДІЄНТАМИ*",
      "photo_index": 0
    },
    {
      "text": "250 г/g",
      "photo_index": 0
    },
    {
      "text": "Кетчуп «Лагідний» пастеризований",
      "photo_index": 0
    },
    {
      "text": "Nestlé®",
      "photo_index": 1
    },
    {
      "text": "Good food, Good life®",
      "photo_index": 1
    },
    {
      "text": "ЛІНІЯ ТУРБОТИ NESTLÉ",
      "photo_index": 1
    },
    {
      "text": "0 800 50 09 50",
      "photo_index": 1
    },
    {
      "text": "info@ua.nestle.com",
      "photo_index": 1
    },
    {
      "text": "nestle.ua",
      "photo_index": 1
    },
    {
      "text": "Нам важлива Ваша думка!",
      "photo_index": 1
    },
    {
      "text": "Власник торговельних марок: Сосьєте де Продюі Нестле С.А., Веве, Швейцарія.",
      "photo_index": 1
    },
    {
      "text": "КЕТЧУП «ЛАГІДНИЙ» ПАСТЕРИЗОВАНИЙ",
      "photo_index": 1
    },
    {
      "text": "Зберігати за температури від 0 °C до 25 °C. Після відкриття упаковки продукт зберігати у холодильнику.",
      "photo_index": 1
    },
    {
      "text": "ТОВ «Нестле Україна», 03150, Україна, м. Київ, вул. Велика Васильківська, буд. 139.",
      "photo_index": 1
    },
    {
      "text": "Виробник: E: SAP „Voliniholding”, Ucraina, 45612, regiunea Volini, raionul Luţk, s. Radomyshl, str. Svyato-Pokrovska, 4. V: SRL „Voliniholding”, Ucraina, 45612, regiunea Volini, raionul Luţk, s. Radomyshl, str. Svyato-Pokrovska, 4.",
      "photo_index": 1
    },
    {
      "text": "ПОЖИВНА ЦІННІСТЬ / VALOAREA NUTRITIVĂ",
      "photo_index": 2
    },
    {
      "text": "*РВС - середня референсна величина добового споживання для осіб старше 18 років (8400 кДж/kJ / 2000 ккал/kcal). Особисті потреби можуть відрізнятися залежно від віку, статі та рівня фізичного навантаження. В упаковці ~ 22 порції.",
      "photo_index": 2
    },
    {
      "text": "КЕТЧУП «ЛАГІДНИЙ» ПАСТЕРИЗОВАНИЙ",
      "photo_index": 2
    }
  ]
}"""

P03 = r"""{
  "photos": [
    {
      "index": 0,
      "side": "front",
      "quality": "ok",
      "note": null
    },
    {
      "index": 1,
      "side": "back",
      "quality": "ok",
      "note": null
    }
  ],
  "emphasis_visible": false,
  "ingredients_marked": {
    "text": "вода питна підготовлена, цукор, діоксид вуглецю, барвник (сульфітно-аміачна карамель), ароматизатори, регулятор кислотності (ортофосфорна кислота), кофеїн, підсолоджувачі (ацесульфам калію та сукралоза).",
    "photo_index": 1
  },
  "may_contain_text": null,
  "nutrition": {
    "per": "100ml",
    "portion_text": "250 мл (ml) - 1 порція",
    "energy": "120 кДж (kJ) / 28 ккал (kcal)",
    "fat": "0 г (g)",
    "saturates": "0 г (g)",
    "carbs": "7,0 г (g)",
    "sugars": "7,0 г (g)",
    "fibre": null,
    "protein": "0 г (g)",
    "salt": "0,01 г (g)",
    "photo_index": 1
  },
  "other_text": [
    {
      "text": "1 л",
      "photo_index": 0
    },
    {
      "text": "PEPSI",
      "photo_index": 0
    },
    {
      "text": "1,0 л",
      "photo_index": 0
    },
    {
      "text": "НАПІЙ БЕЗАЛКОГОЛЬНИЙ СИЛЬНОГАЗОВАНИЙ НА АРОМАТИЗАТОРАХ «ПЕПСІ-КОЛА» З ЦУКРОМ ТА ПІДССОЛОДЖУВАЧАМИ.",
      "photo_index": 1
    },
    {
      "text": "Поживна цінність на 100 мл (ml) напою: енергетична цінність – 120 кДж (kJ) / 28 ккал (kcal); жири – 0 г (g), з них: насичені жири – 0 г (g), вуглеводи – 7,0 г (g), з них: цукри – 7,0 г (g), білки – 0 г (g), сіль – 0,01 г (g). *-референсна величина споживання для дорослих становить 2000 ккал (kcal) / 8400 кДж (kJ). 250 мл (ml) – 1 порція.",
      "photo_index": 1
    },
    {
      "text": "Зберігати за температури від 0 °С до 25 °С. Дата розливу (виробництва) та дата \"Краще спожити до:\" зазначені на пляшці. Питний охолодженим. Оберігати від потрапляння прямих сонячних променів.",
      "photo_index": 1
    },
    {
      "text": "ТОВ “Сандора”, с. Миколаївське, Миколаївський р-н, Миколаївська обл., 57262, Україна.",
      "photo_index": 1
    },
    {
      "text": "Виготовлений з концентрату, за технологією і з дозволу компанії «ПепсіКо Інк.».",
      "photo_index": 1
    },
    {
      "text": "ПЕПСІ, ПЕПСІ-КОЛА та Пепсі Глоуб є зареєстрованими торговельними марками компанії «ПепсіКо Інк.».",
      "photo_index": 1
    },
    {
      "text": "Телефон гарячої лінії: 0 800 300 309 (усі дзвінки в межах України безкоштовні).",
      "photo_index": 1
    },
    {
      "text": "ДСТУ 4069.",
      "photo_index": 1
    },
    {
      "text": "Об'єм 1 л (L).",
      "photo_index": 1
    }
  ]
}"""

P16 = r"""{
  "photos": [
    {
      "index": 0,
      "side": "front",
      "quality": "ok",
      "note": null
    },
    {
      "index": 1,
      "side": "back",
      "quality": "ok",
      "note": null
    },
    {
      "index": 2,
      "side": "back",
      "quality": "ok",
      "note": null
    }
  ],
  "emphasis_resolvable": true,
  "ingredients_marked": {
    "text": "[…]укор, борошно **пшеничне**, жири рослинні (негідрогенізована пальмова олія, повністю гідрогенізована пальмоядрова олія), какао-порошок зі зниженим вмістом жиру 7%, олія кокосова, сироватковий пермеат сухий (з **молока**), молоко сухе незбиране, **молоко** сухе знежирене, емульгатор **соєвий** лецитин, розпушувачі (гідрокарбонат амонію, гідрокарбонат натрію), **сіль**, ароматизатор.",
    "photo_index": 1
  },
  "may_contain_text": {
    "text": "Може містити яєчні продукти, фундук, мигдаль, арахіс, кунжут.",
    "photo_index": 1
  },
  "nutrition": null,
  "other_text": [
    {
      "text": "ВАФЛІ ГЛАЗУВАНІ \"ROSHETTO DARK\". Вафлі з какао-начинкою (49%) у какаовмісній глазурі (30%).",
      "photo_index": 1
    },
    {
      "text": "Зберігати при температурі (18±5) °C і відносній вологості повітря не вище 75%. (v091024B) Дарк.",
      "photo_index": 1
    },
    {
      "text": "Виробник, місцезнаходження: ПрАТ \"Вінницька кондитерська фабрика\", вул. Є. Коновальця, 8, м. Вінниця, 21001, Україна.",
      "photo_index": 1
    },
    {
      "text": "Лінія підтримки споживачів: 0-800-300-970.",
      "photo_index": 1
    }
  ]
}"""

P17 = r"""{
  "photos": [
    {
      "index": 0,
      "side": "front",
      "quality": "ok",
      "note": null
    },
    {
      "index": 1,
      "side": "back",
      "quality": "ok",
      "note": null
    },
    {
      "index": 2,
      "side": "back",
      "quality": "ok",
      "note": null
    }
  ],
  "emphasis_resolvable": true,
  "ingredients_marked": {
    "text": "цукор, какао-масло, какао терте, молоко сухе незбиране, сироватка суха молочна, молоко сухе знежирене, жир молочний, паста горіхова (фундук), емульгатори (лецитин соєвий, Е 476), ароматизатор. Мінімальний вміст какао-продуктів в шоколадній масі - 25 %. Мінімум 25 % від загальної кількості молочних продуктів в шоколадній масі мають альпійське походження. Зберігати при температурі (18±3) °С і відносній вологості повітря не більше 75 %. Виробник: ПрАТ «Монделіз Україна»; 42600, Україна, Сумська обл., м.Тростянець, вул.Набережна, 28а. ДСТУ 3924.",
    "photo_index": 1
  },
  "may_contain_text": {
    "text": "Може вміщувати в незначній кількості арахіс, інші горіхи, пшеницю.",
    "photo_index": 1
  },
  "nutrition": {
    "per": "100g",
    "portion_text": "18g/r",
    "energy": "2222 кДж / kJ / 532 ккал / kcal",
    "fat": "30,0 г/g",
    "saturates": "18,0 г/g",
    "carbs": "59,0 г/g",
    "sugars": "58,0 г/g",
    "fibre": "2,3 г/g",
    "protein": "5,7 г/g",
    "salt": "0,29 г/g",
    "photo_index": 2
  },
  "other_text": [
    {
      "text": "Milka",
      "photo_index": 0
    },
    {
      "text": "Молочний шоколад",
      "photo_index": 0
    },
    {
      "text": "МІСТИТЬ АЛЬПІЙСЬКЕ МОЛОКО",
      "photo_index": 0
    },
    {
      "text": "ВІДКРИВАТИ І ЗАКРИВАТИ ТУТ",
      "photo_index": 1
    },
    {
      "text": "МОЛОЧНИЙ ШОКОЛАД «МІЛКА».",
      "photo_index": 1
    }
  ]
}"""
