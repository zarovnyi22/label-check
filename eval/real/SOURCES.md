# Джерела справжніх фото (eval/real)

Фото з Open Food Facts, ліцензія CC BY-SA 3.0 (Open Food Facts contributors).
Лише українські етикетки, без продуктових ліній dev-фото. Оригінали — `samples/test/`
(r13–r17 — `samples/test/off/`); `photo_0` = front, `photo_1` = склад, `photo_2` = нутрієнти.

| кейс | id | продукт | штрихкод | сторінка | файли → кейс |
|---|---|---|---|---|---|
| r01 | p04 | Bonny fruit Mix citrus | 4823077624247 | https://world.openfoodfacts.org/product/4823077624247 | p04_front.jpg → photo_0.jpg, p04_back.jpg → photo_1.jpg, p04_nutrition.jpg → photo_2.jpg |
| r02 | p05 | Майонез 67% | 4820241520930 | https://world.openfoodfacts.org/product/4820241520930 | p05_front.jpg → photo_0.jpg, p05_back.jpg → photo_1.jpg, p05_nutrition.jpg → photo_2.jpg |
| r03 | p06 | Печиво цукрове «До кави», з ароматом пряженого молока | 4823077614675 | https://world.openfoodfacts.org/product/4823077614675 | p06_front.jpg → photo_0.jpg, p06_back.jpg → photo_1.jpg, p06_nutrition.jpg → photo_2.jpg |
| r05 | p08 | Шоколадний батон "Dark Chocolate with Cocoa Fondant" | 4823077621154 | https://world.openfoodfacts.org/product/4823077621154 | p08_front.jpg → photo_0.jpg, p08_back.jpg → photo_1.jpg, p08_nutrition.jpg → photo_2.jpg |
| r09 | p12 | BORJOMI | 4860019001346 | https://world.openfoodfacts.org/product/4860019001346 | p12_front.jpg → photo_0.jpg, p12_back.jpg → photo_1.jpg, p12_nutrition.jpg → photo_2.jpg |
| r13 | off | Йогурт "Білий" густий, 1.6% жиру | 4820045704130 | https://world.openfoodfacts.org/product/4820045704130 | off/4820045704130_front.jpg → photo_0.jpg, off/4820045704130_ingredients.jpg → photo_1.jpg, off/4820045704130_nutrition.jpg → photo_2.jpg |
| r14 | off | Крем-сир 60% Original Filladel | 4820019493855 | https://world.openfoodfacts.org/product/4820019493855 | off/4820019493855_front.jpg → photo_0.jpg, off/4820019493855_ingredients.jpg → photo_1.jpg, off/4820019493855_nutrition.jpg → photo_2.jpg |
| r15 | off | Шоколад молочний "Very Peri Chocolate Cookies" | 4820240032953 | https://world.openfoodfacts.org/product/4820240032953 | off/4820240032953_front.jpg → photo_0.jpg, off/4820240032953_ingredients.jpg → photo_1.jpg, off/4820240032953_nutrition.jpg → photo_2.jpg |
| r16 | off | Шоколадний батончик Bounty молочний | 5000159558259 | https://world.openfoodfacts.org/product/5000159558259 | off/5000159558259_front.jpg → photo_0.jpg, off/5000159558259_ingredients.jpg → photo_1.jpg, off/5000159558259_nutrition.jpg → photo_2.jpg |
| r17 | off | Напій безалкогольний сильногазований соковий з соком яблука | 4820000195423 | https://world.openfoodfacts.org/product/4820000195423 | off/4820000195423_front.jpg → photo_0.jpg, off/4820000195423_ingredients.jpg → photo_1.jpg, off/4820000195423_nutrition.jpg → photo_2.jpg |

r06 (p09) і r07 (p10) вилучено: ті самі продуктові лінії, що й dev-фото p02/p03 (витік dev → test).
r04, r08, r10, r11, r12 перенесено в `eval/real_out_of_scope/` (неукраїнські етикетки).
