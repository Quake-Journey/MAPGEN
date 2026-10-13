namespace MapgenStudio;

/// <summary>
/// The Studio's versions, newest first, as the «О программе» page lists them (the PO, 05.10: «почему версия 0.1.0?
/// Уже столько допилили ... со всей историей версий»). The first one is the program's own version - the project
/// file's &lt;Version&gt; must be the same (the self-test checks it).
/// </summary>
public static class Versions
{
    public sealed record Entry(string Number, string Date, string[] Ru, string[] En);

    public static readonly Entry[] All =
    {
        new("3.34", "13.10.2026",
            new[]
            {
                "Ссылка «Сайт» на главной странице ведёт на страницу MAPGEN: q2pro-x.com/mapgen",
            },
            new[]
            {
                "The «Site» link on the home page leads to MAPGEN's page: q2pro-x.com/mapgen",
            }),
        new("3.33", "13.10.2026",
            new[]
            {
                "Генерация снова заканчивается на 3–5 минут раньше: итоговая оценка отличий берёт уже сделанные обходы карты, а не обходит её ещё дважды (ошибка версии 3.32)",
            },
            new[]
            {
                "A generation ends 3–5 minutes sooner again: the final measure of difference takes the walks of the map the run already made instead of walking it twice more (a fault of 3.32)",
            }),
        new("3.32", "13.10.2026",
            new[]
            {
                "Оценка «план даст до N %» точнее на увеличенных картах: она опирается на пробные сборки самых крупных раскопов и не обещает больше, чем те намерили (q2dm1: было 64,6 % при итоге 57,4 %, стало 59,1 %)",
                "Карта, выросшая в полную высоту, больше не отбрасывается при пересборке основы: из-за одной «плоской» детали и долей пикселя в текстурах на наклонных стенах генератор молча уходил на карту обычного размера",
                "На карте такой высоты правки снова принимаются: измеритель отличий и проверка ходьбы рассчитаны на карту во весь объём игры",
                "Точки появления игроков на выросшей карте стоят над полом на своей высоте, а не поднимаются вместе с картой",
            },
            new[]
            {
                "The plan's word «up to N %» is closer on maps made larger: it leans on the trial builds of the largest digs and promises no more than they measured (q2dm1: 64.6 % against 57.4 % reached before, 59.1 % now)",
                "A map grown to its full height is no longer given up when its base is rebuilt: for one «flat» piece and fractions of a pixel in the textures of slanted walls the generator went on, without a word, with the map at its usual size",
                "On a map that tall edits are accepted again: the measure of difference and the walk hold a map as large as the game's whole space",
                "Players' starts on a map grown tall stand at their own height over the floor instead of rising with the map",
            }),
        new("3.31", "13.10.2026",
            new[]
            {
                "Большая карта встаёт в полную высоту с первой попытки: q3t2, увеличенная в 10 раз, вырастает вверх так же, как вширь (в 3,1 раза; раньше получалось только в 2)",
                "«Высота потолков» больше не отбрасывается целиком, когда карта упирается в предел координат игры: потолки поднимаются настолько, насколько игра позволяет, и ход генерации говорит, сколько дано",
                "Свет большой карты: размер световых участков и место под карту освещения выбираются заранее по самой карте — без пробных проходов, которые заканчивались ошибкой",
                "Лестницы с низкими ступенями на выросшей карте получают пандусы и там, где рядом стоит невидимое ограждение",
                "Предметы, стоявшие в исходной карте один над другим, на выросшей карте по-прежнему падают на пол и достижимы",
            },
            new[]
            {
                "A large map stands at its full height on the first try: q3t2 made ten times larger grows as tall as it grows wide (3.1 times; it used to reach only 2)",
                "«Ceiling height» is no longer given back whole when the map meets the limit of the game's coordinates: the ceilings rise as far as the game allows, and the run says how much was given",
                "A large map's light: the size of the light patches and the room for the lightmap are chosen beforehand from the map itself - no trial passes that ended in an error",
                "Flights of low steps on a map grown tall get their ramps where an unseen barrier stands beside them too",
                "Pickups that stood one over another in the original map still fall to the floor on the grown map and can be reached",
            }),
        new("3.30", "13.10.2026",
            new[]
            {
                "Генератор больше не теряет постройку, которая при пробной сборке в одиночку не собралась, а после соседней собирается: она строится заново в свой черёд (на q2dm3 так пропадал туннель с лифтом)",
            },
            new[]
            {
                "The generator no longer loses a piece whose trial build fails alone but builds after its neighbour: it is built again at its turn (q2dm3 lost a tunnel with a lift this way)",
            }),
        new("3.29", "12.10.2026",
            new[]
            {
                "На увеличенных картах окна снова встают во все подходящие стены (на q2dm1 — шесть стен вместо одной): генератор находит, какой комнате принадлежит узкое пространство за стеной",
                "Оценка «план даст до N %» точнее: раскоп, который не собрался при пробной сборке, оставил бы механизм без доступа или потерял бы предмет, больше не засчитывается и не строится второй раз",
            },
            new[]
            {
                "On maps made larger the windows stand in every wall that can hold one again (six walls on q2dm1, not one): the generator finds whose room a narrow space behind a wall is",
                "The plan's word «up to N %» is closer: a dig whose trial build failed, would leave a machine nobody can reach or would lose a pickup is no longer counted, nor built a second time",
            }),
        new("3.28", "12.10.2026",
            new[]
            {
                "В плашке «Разрушения» бегунок идёт во всю ширину плашки",
            },
            new[]
            {
                "In the «Ruin» card the slider runs the card's width",
            }),
        new("3.27", "12.10.2026",
            new[]
            {
                "В плашке «Разрушения» описание идёт во всю ширину, бегунок — под ним",
            },
            new[]
            {
                "In the «Ruin» card the words run across the card, the slider under them",
            }),
        new("3.26", "12.10.2026",
            new[]
            {
                "Страница генерации: «Карта-основа» одной высоты с двумя плашками справа; если карт больше, чем помещается, список прокручивается внутри неё",
                "Параметры генерации — плашками по группам с заголовками: «Каркас основы», «Новые помещения», «Переделка основы», «Вода, кислота, лава», «Разрушения», «Что можно менять»; плашки в паре одной высоты",
            },
            new[]
            {
                "The generation page: «Base map» is as tall as the two cards beside it; when the maps do not fit, its list scrolls inside it",
                "The generation's options are cards by group with their names: «The base's frame», «New rooms», «The base rebuilt», «Water, slime, lava», «Ruin», «What may change»; the cards of a pair are one height",
            }),
        new("3.25", "12.10.2026",
            new[]
            {
                "Страница генерации: «Новая карта» и «Готовая карта» стоят справа от «Карты-основы» и не уезжают вниз, когда карт в списке много",
                "Список карт-основ показывает восемь карт; если их больше, он прокручивается внутри своей карточки",
                "Параметры генерации — в две колонки под ними: страница стала короче",
            },
            new[]
            {
                "The generation page: «The new map» and «The finished map» stand to the right of «Base map» and no longer slide down when the list holds many maps",
                "The list of base maps shows eight maps; with more it scrolls inside its own card",
                "The generation's options are in two columns under them: the page is shorter",
            }),
        new("3.24", "12.10.2026",
            new[]
            {
                "Исправлено: после повторного расчёта света на очень большой карте пропадали точки появления, предметы и лампы — теперь расстановка сохраняется",
                "Правки следующих кругов (перестановка стен, блоки, сдвиги пола) больше не ложатся на то, что генератор построил в прошлых кругах: лестница этажа не упирается в стену",
                "Проверки готовой карты видят пристройки, этажи и лестницы всех кругов, а не только первого",
                "Перенесённая генератором точка появления стоит на полу, а не уходит в него",
                "Окно загрузки: при запуске сразу видно, сколько готово и что делается сейчас",
                "Студия открывается за секунду: главная страница и библиотека показывают маленькие копии обложек, а не снимки в полный размер",
                "Снимки игры хранятся в JPEG — в десять раз меньше места; прежние снимки пережимаются сами после запуска",
                "На главной странице — блок «Сообщество»: новости, группа сообщества и сайт",
            },
            new[]
            {
                "Fixed: after the light pass ran again on a very large map the starts, pickups and lights were lost - the map keeps them now",
                "A later round's edits (walls moved, blocks, floor shifts) no longer land on what the generator built in earlier rounds: a storey's flight no longer runs into a wall",
                "The finished map's checks see the annexes, storeys and stairways of every round, not of the first alone",
                "A start the generator moves stands on the floor, not sunk into it",
                "A loading window: at start it shows at once how much is done and what is being done",
                "The Studio opens in a second: the home page and the library show small copies of the covers, not the full shots",
                "The game's shots are kept as JPEGs - a tenth of the room; earlier shots are recompressed by themselves after the start",
                "A «Community» block on the home page: the news, the community group and the site",
            }),
        new("3.23", "12.10.2026",
            new[]
            {
                "Очень большие карты больше не выходят без освещения: если расчёт света упирается в свои пределы, генератор повторяет только этот шаг с более крупными участками освещения и большим объёмом данных света — видимость заново не считается",
                "Увеличенная карта растёт и в высоту, сохраняя пропорции: перед ступенями и уступами, на которые иначе не подняться, появляются пологие заезды или лесенки, щели в решётках, куда раньше нельзя было провалиться, перекрыты, лифты и батуты подстраиваются под новую высоту",
                "Если карта при полном росте высоты где-то становится непроходимой, генератор пробует чуть меньший рост, пока карта не станет проходимой целиком",
            },
            new[]
            {
                "Very large maps no longer come out unlit: when the light pass hits its limits the generator runs that step again with larger light patches and more room for the lightmap - the visibility is not worked out again",
                "A map made larger grows as tall, in proportion: the steps and ledges that could not be climbed any more get gentle ramps or small flights in front of them, the gaps in gratings a player could not fall through are bridged, lifts and jump pads follow the new height",
                "When full height leaves a map unwalkable somewhere, the generator tries a little less height until the whole map walks",
            }),
        new("3.22", "11.10.2026",
            new[]
            {
                "Страница генерации переделана: слева главное — насколько карта уже отличается от основы (крупно), ход правок (принято, сборок, рассмотрено, время) и план правок таблицей с полосками выполнения; справа схема карты во всю высоту окна",
                "Этапы, загрузка компьютера и обозначения на схеме убраны в свёрнутые разделы; в заголовке раздела видно главное — текущий этап, доля процессора",
                "Текущий этап с его временем — цветной плашкой под названием карты: синяя — идёт, жёлтая — пауза, зелёная — готово, красная — ошибка",
                "Обозначения на схеме — значками с короткими подписями, как они нарисованы на самой схеме",
                "Если имя карты уже занято (такая карта есть в библиотеке, есть её записи, она идёт или прервана), кнопка «Начать генерацию» спрашивает: перезаписать, исправить имя или отменить. «Исправить имя» сразу ставит курсор в поле имени",
                "Новый вид всей программы: меню слева с крупными цветными значками и подсветкой под мышью; все страницы — карточками в две колонки, с крупными заголовками",
                "Главная страница: пара абзацев о студии и генераторе, кнопки «Новая карта», «Карты», «Руководство», последняя карта с обложкой, готовность к работе, ссылки на руководство, которое лежит рядом с программой, и как сделать карту в четыре шага",
                "Пока идёт генерация, над любой другой страницей видна её строка: что делается, отличие от основы, правки, время и кнопка «Открыть генерацию»",
                "Параметры генерации — карточками; внизу всегда видны итог («будет создана карта … основа … похожесть …») и кнопка «Начать генерацию»",
                "Карты: поиск по имени или основе; на обложке — основа и отличие от основы, под ней — итог проверок цветом; страница карты — карточками",
                "Каждый этап виден на схеме: основа плавно растягивается в новый каркас; на «Свете и видимости» — волна расчёта видимости с «глазом» и лучами взгляда, свечение фонарей и их лучи",
                "Проценты «Света и видимости» больше не стоят на 100 % весь последний, самый долгий, десяток: 90 % теперь 90 %",
                "Двухэтажная комната на растянутой q2dm1 больше не ставит вход на верх стены под невидимой стенкой основы — до её верхнего этажа можно дойти",
            },
            new[]
            {
                "The generation page reworked: on the left what matters - how far the map already differs from the base (large), the edits (accepted, builds, considered, time) and the plan as a table with progress bars; on the right the map's scheme the window's whole height",
                "The stages, the computer's load and the scheme's legend are folded away; a folded section's header still says the gist - the stage now, the CPU share",
                "The stage under way and its time as a coloured badge under the map's name: blue running, yellow paused, green done, red failed",
                "The scheme's legend as signs with short words, drawn as on the scheme itself",
                "When the map's name is taken (the library has such a map, its records exist, it is running or was interrupted), «Start generating» asks: overwrite, correct the name, or cancel. «Correct the name» puts the cursor in the name field at once",
                "A new look for the whole program: the menu on the left with large coloured signs lit under the mouse; every page in cards, two columns, with large heads",
                "The home page: two paragraphs on the Studio and its generator, «New map», «Maps», «Guide», the latest map with its cover, readiness, links to the guide that comes beside the program, and a map in four steps",
                "While a run goes on, its strip stands over every other page: what it is doing, the difference from the base, the edits, the time and «Open the run»",
                "The generation's settings in cards; at the foot always the summary («the map … will be made: base … likeness …») and «Start generating»",
                "Maps: search by name or base; over the cover the base and the difference from it, under it the checks in colour; a map's page in cards",
                "Each stage shows on the scheme: the base easing into its new frame; at «Light and visibility» the visibility's wave with its eye and sight lines, the lamps' glow and rays",
                "«Light and visibility» no longer stands at 100 % through the whole last, longest tenth: 90 % now reads 90 %",
                "The two-storey room on stretched q2dm1 no longer puts its doorway on a wall top under the base's invisible clip - its upper floor is reached",
            }),
        new("3.21", "11.10.2026",
            new[]
            {
                "Двухэтажная комната на растянутой q2dm3 больше не отклоняется из-за крошечной щели, которую сборка карты оставила далеко от неё, в стене, которую правка не трогала; щель рядом с самой правкой по-прежнему не допускается",
            },
            new[]
            {
                "The two-storey room on stretched q2dm3 is no longer refused for a tiny crack the map's build left far from it, in a wall the change never touched; a crack near the change itself is still refused",
            }),
        new("3.20", "11.10.2026",
            new[]
            {
                "Двухэтажные комнаты: генератор находит для них место чаще — и там, где два входа смотрят в одну сторону, и комнатой с одним входом, — до двух на карте (на растянутой q2dm1 их две)",
                "Комнату, которую раньше выбрасывали из-за неба над двором, генератор теперь подстраивает: опускает проём под небом и заранее проверяет, что она построится",
                "Пристройки и комнаты, уходящие выше крыши, больше не открывают карту наружу: за стенами под поднятым небом пустота закрывается, а небо уже построенных комнат не трогается",
                "Окна всех видов на каждой карте: неподвижные, падающие от выстрела и открывающиеся плитой на полу. Окна разной формы — прямоугольные, круглые или овальные, арочные, с переплётом и форточкой — и с разным стеклом: светлым, синим, армированным, янтарным, оливковым, дымчатым",
                "Перестройка стены, под которой пол соседней части кончался раньше самой стены, больше не оставляет дыры наружу",
                "Обещание плана честнее: каждое место карты считается один раз, а большую правку, которую сборка всё равно отвергнет, генератор проверяет заранее и не обещает",
            },
            new[]
            {
                "Two-storey rooms: the generator finds room for them more often - also where both doorways face the same way, and as a room with one doorway - up to two a map (two on stretched q2dm1)",
                "A room thrown away before because of the sky over a courtyard is now fitted: its doorway is lowered under the sky and the room is checked to build before it is planned",
                "Annexes and rooms that reach above a roof no longer open the map to the outside: the void past the walls under the lifted sky is closed, and the sky of rooms already built is left alone",
                "Every kind of window on each map: fixed, dropping when shot, opened by a plate on the floor. Windows in different outlines - rectangular, round or oval, arched, with a transom and a vent - and with different glass: pale, blue, wired, amber, olive, smoke",
                "A wall moved back over a floor piece that ended short of it no longer leaves a hole to the outside",
                "The plan's promise is truer: every place of the map is counted once, and a large change the build would refuse anyway is checked beforehand and not promised",
            }),
        new("3.19", "11.10.2026",
            new[]
            {
                "На растянутой основе каждая видимая грань снова получает текстуру: стороны, которые исходная карта не рисовала, могли нести оси текстуры вдоль самой грани, и после растяжения такая грань оказывалась без рисунка (на q2dm3 — одна у бассейна). Теперь такие оси строятся заново по плоскости грани",
            },
            new[]
            {
                "On a stretched base every drawn face wears its texture again: sides the original map never drew could carry texture axes along the face itself, and stretched such a face showed no pattern (on q2dm3 one by a pool). Such axes are now built anew from the face's plane",
            }),
        new("3.18", "11.10.2026",
            new[]
            {
                "Пристройка получает ценный предмет и тогда, когда генератор не может проложить к нему путь пешком (на q2dm3 рельса, ракетница, квад и мегахелс стоят на верхнем ярусе, куда возят поезда): берётся самый ценный предмет поблизости, а доступность после переноса проверяет обход игрока. На q2dm3 вторая пристройка держит квад вместо пулемёта",
            },
            new[]
            {
                "An annex gets a valuable pickup even when the generator cannot find a walk to it (on q2dm3 the railgun, launcher, quad and megahealth stand on the top tier the trains carry players to): the most valuable pickup nearby is taken, and the player's walk checks it is still in reach after the move. On q2dm3 the second annex holds the quad instead of the machinegun",
            }),
        new("3.17", "11.10.2026",
            new[]
            {
                "Проверка готовой карты «на карте есть чейнган» больше не отклоняет карту, сделанную из основы без чейнгана (q2dm3): проверка ловит потерянный чейнган, а не тот, которого не было",
            },
            new[]
            {
                "The finished map's check «the chaingun is in the map» no longer refuses a map made from a base that has none (q2dm3): it catches a chaingun lost, not one that never was",
            }),
        new("3.16", "11.10.2026",
            new[]
            {
                "Окно больше не может смотреть в скалу: правка, которая ставит стену или блок вплотную перед уже прорезанным окном (на q2dm1 так встали блок и сдвинутая стена), теперь отклоняется",
            },
            new[]
            {
                "A window can no longer look into rock: an edit that puts a wall or a block right in front of a window already cut (on q2dm1 a block and a moved wall stood so) is now refused",
            }),
        new("3.15", "11.10.2026",
            new[]
            {
                "Точка появления игрока больше не может оказаться над полом: правка, после которой точка повисла бы (на q2dm1 её сдвинули лестница и две перестройки стен, и игрок при появлении падал на ступеньку), теперь отклоняется",
                "Перестройка комнаты, у которой стена стояла на пустоте (в углу комнаты или у торца стены), больше не открывает комнату наружу: под освобождённой полосой и у её торцов ставится плита. На q2dm3 при размере 150 % не собиралась каждая третья такая перестройка, теперь одна из четырнадцати",
            },
            new[]
            {
                "A player's start can no longer end up over the floor: an edit after which a start would hang (on q2dm1 a stairway and two wall reshapes moved one, and the player dropped a step at spawn) is now refused",
                "A room reshape whose wall stood on the void (at the room's corner or at the wall's end) no longer opens the room to the outside: a slab goes under the strip it gives up and at its ends. On q2dm3 at 150 % one such reshape in three failed its build, now one in fourteen",
            }),
        new("3.14", "10.10.2026",
            new[]
            {
                "Проверка готовой карты «вода» больше не считает «стоячей водой» боковину бассейна, к которой примыкает замкнутый карман пустоты: такой карман остаётся за длинным туннелем, туда никто не может попасть и его никто не видит — генератор считает так же",
                "q2dm3 с вашими настройками и основой 150 %: за 25 минут карта отличается от основы на 44,5 %, план обещал до 50 %. Прошли три крупные правки из четырёх: длинный туннель с залами и две пристройки",
            },
            new[]
            {
                "The finished map's «water» check no longer counts as «standing water» the side of a pool a sealed pocket of the void lies against: such a pocket is left behind a long tunnel, nobody can get into it or see it - the generator counts it so too",
                "q2dm3 with your options on a 150 % base: in 25 minutes the map differs from its base by 44.5 %, the plan said up to 50 %. Three of the four large edits went in: the long tunnel with its halls and two annexes",
            }),
        new("3.13", "10.10.2026",
            new[]
            {
                "Самая крупная правка плана — длинный туннель с залами — больше не отбрасывается из-за «стоячей воды» в далёком бассейне: туннель сквозь пустоту вокруг карты отрезал кусок этой пустоты, и боковина бассейна, к которой никто не может подойти, считалась водой, стоящей в воздухе. На q2dm3 с вашими настройками одна эта правка даёт около 37 % отличия",
                "Проверка готовой карты «вода» узнаёт вертикальные грани жидкости, которые были и на исходной карте, по месту, а не по текстуре: правка, заменившая лаву на воду, больше не делает их «новыми»",
            },
            new[]
            {
                "The plan's largest edit - a long tunnel with halls - is no longer thrown away for «standing water» in a pool far off: the tunnel through the void round the map cut a piece of that void off, and the side of a pool nobody can come near was counted as water standing in the air. On q2dm3 with your options this one edit gives about 37 % difference",
                "The finished map's «water» check knows the liquid's upright faces the original map had by their place, not by their texture: an edit that turned lava into water no longer makes them «new»",
            }),
        new("3.12", "10.10.2026",
            new[]
            {
                "На растянутой основе правки теперь достраиваются, а не отбрасываются: пристройка больше не оставляет щель наружу возле стены, которая после растяжения легла не по сетке; проём в стене получает порог, если под стеной не было пола; потолок, который дорастает до отодвинутой стены, больше не останавливается у старого угла",
                "Комната, где лежит предмет, недостижимый и на исходной карте, больше не считается потерянной после правки в другом конце карты: на q2dm3 при размере 150 % из-за этого отбрасывалась каждая пятая–шестая правка. Вместе с исправлениями выше: на q2dm3 с вашими настройками за те же 25 сборок карта отличается от основы на 12 % вместо 5 %",
                "Проверки готовой карты (предметы, стёкла, вода, лестницы, свет комнат) сравнивают её с растянутой основой, на которой она построена, а не со старыми местами исходной карты",
            },
            new[]
            {
                "On a stretched base edits are now built instead of thrown away: an annex no longer leaves a gap to the outside by a wall the stretch laid off the grid; a doorway gets a sill where there was no floor under the wall; a ceiling grown to a wall moved back no longer stops at the old corner",
                "A room holding a pickup that was out of reach on the original map too is no longer counted lost after an edit at the other end of the map: on q2dm3 at 150 % one edit in five or six was thrown away for it. With the fixes above: on q2dm3 with your options the same 25 builds make a map 12 % different from its base instead of 5 %",
                "The finished map's checks (pickups, glass, water, stairways, rooms' light) hold it to the stretched base it was built on, not to the original map's old places",
            }),
        new("3.11", "10.10.2026",
            new[]
            {
                "Генерация, запущенная без окна (из командной строки), теперь берёт те же настройки, что и окно: параметры правок, каркас основы и время генерации",
            },
            new[]
            {
                "A generation started without the window (from the command line) now takes the window's own settings: the edit options, the base's frame and the generation's time",
            }),
        new("3.10", "10.10.2026",
            new[]
            {
                "«Каркас основы»: новый регулятор «Сдвиг частей», 0–100 %. Части карты сдвигаются вбок друг относительно друга: комнаты одной части стоят смещёнными против соседней, проходы между частями изгибаются — получается другое расположение комнат. Полы ровные, стены вертикальные; части с дверями, лифтами и поездами переносятся целиком, без перекоса. q2dm1 со сдвигом 60 % прошла проверку с первого раза",
                "Линии, по которым режется основа, генератор теперь ставит подальше от концов стен: так не остаётся узких обрезков стен, из-за которых растянутая основа могла не пройти проверку повторной сборкой",
                "Если растянутая основа всё же не прошла проверку повторной сборкой, в событиях генерации сказано, почему",
            },
            new[]
            {
                "«The base's frame»: a new slider «Shift of the parts», 0-100 %. The map's parts slide sideways against each other: the rooms of one part stand moved over against the next one's, the passages between them bend - another layout of the rooms. Floors stay level, walls upright; parts with doors, lifts and trains move whole, not skewed. q2dm1 shifted by 60 % passed the check on the first try",
                "The lines the base is cut along are now placed away from the walls' ends: no thin scraps of wall are left, which could make a stretched base fail the rebuild check",
                "If a stretched base still fails the rebuild check, the generation's events say why",
            }),
        new("3.9", "10.10.2026",
            new[]
            {
                "«Каркас основы»: новый выбор «Поворот основы» — повернуть всю карту на 90°, 180° или 270°, отразить зеркально или «Случайно (по зерну)». Двери, лифты, поезда, прыжковые площадки, взгляд игроков на старте и текстуры поворачиваются вместе с ней. Если повёрнутая карта не проходит проверку, генератор оставляет растяжение, но не поворачивает: на q2dm1 так выходит из-за двух предметов на подставках, куда допрыгивают только на ракете",
                "«Каркас основы»: новый регулятор «Высота потолков» — от 100 до 200 %. Всё, что выше самого высокого места, где может стоять игрок, поднимается: залы верхнего уровня и небо становятся выше, полы, ступени и прыжки не трогаются. q2dm1 с потолками выше в полтора раза прошла проверку с первого раза",
                "Растянутая основа проверяется один раз и до первой правки: в описании карты сказано, повёрнута ли она и насколько подняты потолки",
            },
            new[]
            {
                "«The base's frame»: a new choice «Turn of the base» - turn the whole map by 90°, 180° or 270°, mirror it, or «By the seed». Doors, lifts, trains, jump pads, the players' facing at the start and the textures turn with it. If the turned map does not pass the check, the generator keeps the stretch but not the turn: on q2dm1 it is so because of two pickups on pedestals only a rocket jump reaches",
                "«The base's frame»: a new slider «Ceiling height» - 100 to 200 %. Everything above the highest place a player can stand is lifted: the top level's halls and the sky grow taller, floors, steps and jumps are untouched. q2dm1 with its ceilings half again higher passed the check on the first try",
                "The stretched base is checked once, before the first edit: the map's description says whether it was turned and how much the ceilings were lifted",
            }),
        new("3.8", "10.10.2026",
            new[]
            {
                "На увеличенной основе новые проходы могут быть длиннее — во столько раз, во сколько выросла карта. На q2dm3 с вашими настройками и размером 150 % план даёт 4 крупные правки, проверенные ещё до сборки (пристройки, проходы, двухэтажная комната), — на прежней основе их было 2; план обещает около 50 % отличия",
                "Если растянутая основа не прошла проверку повторной сборкой, генерация не останавливается: она идёт на исходной основе и пишет об этом",
            },
            new[]
            {
                "On a larger base new passages may run longer - as many times as the map grew. On q2dm3 with your options and a size of 150 % the plan gives 4 large edits checked before any build (annexes, passages, a two-storey room) - on the base as it was there were 2; the plan says up to about 50 % difference",
                "When a stretched base does not pass the rebuild check, the generation does not stop: it goes on the original base and says so",
            }),
        new("3.7", "10.10.2026",
            new[]
            {
                "Новое: «Каркас основы». Генератор теперь сначала меняет саму основу, а уже потом достраивает: режет карту по длине и ширине на части и растягивает или сжимает каждую по-своему — одна комната становится вдвое длиннее, проход рядом короче, двор шире. Высоты не меняются, поэтому ступени, уступы, прыжки и лифты остаются прежними. Линии разреза генератор выбирает сам и не проводит через двери, лифты, поезда и их пути",
                "Два регулятора: «Размер карты» — от 10 до 1000 % площади основы, и «Разные пропорции частей» — от 0 (вся карта растягивается одинаково) до 100 % (одни части в несколько раз длиннее других). По умолчанию 150 % и 50 %. Карта получает столько, сколько может принять: проходы не сжимаются уже игрока, карта не выходит за пределы, которые держит игра",
                "Растянутая основа собирается и проверяется на проходимость один раз, до первой правки, — около минуты. Если проверка не прошла, генератор пробует вариант мягче. Пример: q2dm1 втрое больше по площади, части растянуты от 1 до 3,5 раза — собрана и проходима с первого раза, все предметы достижимы",
                "Обещание плана перед генерацией теперь считается так же, как само отличие от основы: новые помещения добавляются и к изменённому, и ко всей карте. На вашей карте mg_10_6695 план говорит около 32 %, а получено было 27 %; раньше он говорил до 50 %",
                "У регулятора времени надпись больше не слипается: «Точнее» и «до 120 мин» стоят раздельно",
            },
            new[]
            {
                "New: «The base's frame». The generator now first changes the base itself, and only then builds onto it: it cuts the map along its length and width into parts and stretches or squeezes each in its own way - one room becomes twice as long, the passage beside it shorter, the yard wider. Heights do not change, so the steps, ledges, jumps and lifts stay as they were. The generator places the cuts itself and never through doors, lifts, trains and their paths",
                "Two sliders: «Map size» - 10 to 1000 % of the base's area, and «Unequal proportions of the parts» - from 0 (the whole map stretched evenly) to 100 % (some parts several times longer than others). By default 150 % and 50 %. The map gets as much as it can take: no passage is squeezed narrower than a player, and the map stays inside the limits the game holds",
                "The stretched base is built and its walk checked once, before the first edit - about a minute. If the check fails, the generator tries a milder one. For example: q2dm1 three times its area, parts stretched from 1 to 3.5 times - built and walkable on the first try, every pickup in reach",
                "The plan's word before a generation is now counted the way the difference from the base itself is: new rooms join both what changed and the whole map. On your map mg_10_6695 the plan says about 32 %, and 27 % was reached; before it said up to 50 %",
                "The time slider's label no longer runs together: «Closer» and «up to 120 min» stand apart",
            }),
        new("3.6", "10.10.2026",
            new[]
            {
                "В конце генерации и в описании карты сказано, как шли правки: сколько не подошло к карте и сколько отклонено проверкой ещё до сборки, сколько уже пробовалось и не предлагалось снова, сколько собрано и для скольких проходимость пересчитывалась полностью",
                "Путь поезда-платформы генератор обходит по самим отрезкам, по которым тот ездит, а не по всему прямоугольнику вокруг его пути: внутри петли поезда снова можно строить",
            },
            new[]
            {
                "At the end of a generation and in the map's description: how the edits went - how many did not fit the map and how many were refused by the check before the build, how many had been tried and were not offered again, how many were built and for how many the walk was worked out whole",
                "A train platform's path is kept clear along the segments it runs, not the whole box round its path: inside a train's loop the generator may build again",
            }),
        new("3.5", "10.10.2026",
            new[]
            {
                "Генерация в разы быстрее: после каждой сборки проходимость пересчитывается только около изменённого места, остальное берётся из прошлой проверки, и ответ тот же, что у полной проверки. На правках вашей карты mg_10_6695 эта проверка идёт в 7–10 раз быстрее",
                "Каждая правка проверяется ещё до сборки: если она засыпает место, по которому игрок поднимается, генератор отклоняет её сразу, без сборки. На журнале mg_10_6695 так отсеялись бы 69 из 72 сборок, ушедших впустую (около 83 минут), а из 64 принятых правок не отклонилась бы ни одна",
                "Отклонённую правку генератор больше не пробует снова в следующих кругах. Когда новых стоящих правок нет, он пишет «план исчерпан» и доводит карту до конца",
                "Замена жидкостей перенесена в конец генерации: отличия от основы она не прибавляет, а раньше занимала до часа",
                "Сначала строятся самые ценные правки — новые помещения и лестницы, окна и блоки — в конце. Ещё до первой сборки генерация пишет, сколько отличия план даёт самое большее при оставшихся сборках",
                "Регулятор «Быстрее ↔ Точнее» задаёт время генерации: 15, 30, 60 или 120 минут. Когда время выходит, карта доводится до конца, а в описании сказано, сколько отличия набрано за это время и сколько давал план",
            },
            new[]
            {
                "Generation is several times faster: after each build the walk is worked out again only around the changed place, the rest is taken from the last check, and the answer is the one the whole check gives. On edits of your map mg_10_6695 this check runs 7-10 times faster",
                "Every edit is checked before it is built: one that buries a place a player climbs by is refused at once, with no build. On the ledger of mg_10_6695 this would have kept back 69 of the 72 builds that were spent for nothing (about 83 minutes), and none of its 64 accepted edits",
                "An edit refused once is not tried again in the later rounds. When there are no new edits worth building the generation says «the plan ran out» and finishes the map",
                "Liquids are swapped at the end of a generation: they add no difference from the base, and used to take up to an hour",
                "The most valuable edits are built first - new rooms and stairways, windows and blocks last. Before its first build the generation says how much difference the plan gives at most with the builds left",
                "«Faster ↔ Closer» sets the generation's time: 15, 30, 60 or 120 minutes. When the time is up the map is finished, and its description says how much difference was reached in that time and how much the plan gave",
            }),
        new("3.4", "10.10.2026",
            new[]
            {
                "Новая архитектура больше не встаёт на пути лифтов, дверей и платформ-поездов: генератор обходит весь их ход, а не только место, где они стоят, и отклоняет правку, если механизм потерял хоть немного своего хода (на прошлой карте поезд-платформа ездил сквозь новую стену)",
                "Генератор берёт за основу ещё 4 карты (всего 111 из 128): предмет, спрятанный глубоко в камне, в копию не переносится; повторённый ключ у сущности читается, как в игре; невидимая служебная текстура не считается расхождением; границы механизмов сравниваются с допуском в единицу",
                "Понятнее надпись о ходе генерации: «Карта уже отличается от основы на N%, нужно M% (чем больше, тем меньше похожа на основу)»",
                "Оставшееся время правок считает и перестановки предметов, и комнаты других карт, которые идут после основных сборок (раньше в конце долго стояло «0 с»); в строке хода видно «после них перестановки предметов и комнаты других карт: k из n»",
            },
            new[]
            {
                "New architecture no longer stands in the way of lifts, doors and train platforms: the generator keeps clear of their whole travel, not only of where they rest, and refuses an edit after which a machine loses any of its room (on the last map a train platform rode through a new wall)",
                "The generator takes 4 more maps as a base (111 of 128): a pickup hidden deep in rock is left out of the copy; a key repeated in an entity reads as the game reads it; an invisible tool texture is no difference; machines' boxes are compared within a unit",
                "The run's difference line in plain words: «The map already differs from the base by N%, M% is asked (the more, the less like the base)»",
                "The edits' time left counts the item swaps and rooms of other maps that follow the main builds (it used to stand at «0 s» for minutes); the progress line says «then item swaps and rooms of other maps: k of n»",
            }),
        new("3.3", "09.10.2026",
            new[]
            {
                "Генератор берёт за основу почти любую карту: из 128 карт игры принимаются 107 (было 75). Карта больше не отклоняется из-за текстур, которых в игре нет у самой исходной карты, из-за пустых кусков геометрии, из-за слоёв стекла, которые новый сборщик не рисует, и из-за того, что лифты и двери с границей на нуле считались несовпавшими",
                "Если генератор не может взять карту за основу, он пишет почему: какая текстура не нашлась, что сказал сборщик карты",
            },
            new[]
            {
                "The generator takes almost any map as its base: 107 of the game's 128 maps are taken (it was 75). A map is no longer refused for textures its own original lacks in this game, for empty pieces of geometry, for layers of glass the new compiler does not draw, or because lifts and doors with a box ending at zero read as not matching",
                "When the generator cannot take a map as its base it says why: which texture was not found, what the map compiler said",
            }),
        new("3.2", "09.10.2026",
            new[]
            {
                "Основа q2dm6 принимается: генератор точно пересобирает её наклонные скалы (раньше их опорные точки уходили на миллиард единиц, и скат пропадал) и текстуры лифтов и дверей со своей точкой отсчёта (их сдвиг считался дважды) — генерация на q2dm6 больше не обрывается на сборке карты-основы",
            },
            new[]
            {
                "The q2dm6 base is taken: the generator rebuilds its sloped rocks exactly (their points used to go out a billion units and a slope was lost) and the textures of lifts and doors with an origin of their own (their shift was counted twice) - a generation on q2dm6 no longer stops at building the base",
            }),
        new("3.1", "09.10.2026",
            new[]
            {
                "Меню «Копировать» по правой кнопке мыши теперь видно: выделите текст мышью, нажмите правую кнопку — в меню «Копировать выделенное», «Копировать» весь этот текст и другие строки (раньше меню открывалось пустым и невидимым)",
            },
            new[]
            {
                "The right button's «Copy» menu is seen now: select a text with the mouse, press the right button - «Copy the selection», «Copy» the whole text and the other lines (the menu used to open empty and unseen)",
            }),
        new("3.0", "09.10.2026",
            new[]
            {
                "Ничего из перестроенного больше не стоит у неба: сдвинутая стена, колонна или блок заканчиваются ниже неба, а правка, для которой опорой оказалось бы само небо, не ставится (на прошлой карте стены, поставленные на крышу, висели в небе)",
                "Второй этаж у высоких стен: где на стене нет своего яруса, вдоль неё строится галерея на опорах в стену, к ней — лестница вдоль стены, на дальнем конце галереи — предмет",
                "Разрушения обходят лифты и двери на всём их ходу, а не только там, где они стоят: камни, обломки и пятна больше не ложатся в шахту лифта",
                "Карту можно запустить, даже когда игра уже открыта, и обложка снимается рядом с открытой игрой (раньше студия ждала, пока игра закроется, и через 10 минут бросала обложку)",
                "Меню «Копировать» по правой кнопке открывается после отпускания кнопки и по клавише меню; что с ним происходит, пишется в ui_clicks.txt рядом с программой",
            },
            new[]
            {
                "Nothing rebuilt stands against the sky any more: a moved wall, a column or a block stops under the sky, and an edit whose support would be the sky itself is not made (on the last map, walls set on a roof hung in the sky)",
                "A second floor at tall walls: where a wall has no tier of its own, a gallery is built along it on corbels into the wall, a flight along the wall up to it, a pickup at the gallery's far end",
                "The ruin keeps clear of lifts and doors over their whole travel, not only where they rest: no stones, chunks or patches in a lift's shaft",
                "A map can be played while the game is already open, and a cover is taken beside the open game (the Studio used to wait for the game to close and gave the cover up after 10 minutes)",
                "The right button's «Copy» menu opens once the button is let go, and from the menu key; what happens to it is written to ui_clicks.txt beside the program",
            }),
        new("2.9", "08.10.2026",
            new[]
            {
                "Перестройка основы: генератор меняет саму карту-основу, а не только пристраивает к ней, — стена комнаты сдвигается внутрь, стена поворачивается под углом, вдоль стены поднимается терраса со ступенями; в первую очередь на арене. Новый параметр «Перестройка основы»: «По умолчанию» (по похожести), «Нет» или от 1 до 16",
                "Блоки в комнатах основы: коробка, Г-образный, крест, восьмигранник или круглый, разного размера и под разными углами, низкие — запрыгнуть, высокие — укрытие; у стены или отдельно, из материала комнаты, в первую очередь на арене. Новый параметр «Блоки в комнатах»",
                "Пол основы меняется: поднимаются помосты со ступенями со всех сторон, опускаются каналы поперёк пола с лестницами на обоих концах (только там, где под полом нет другого помещения). Новый параметр «Пол: помосты и каналы»",
                "Лестницы основы переделываются между теми же двумя полами: старый марш становится площадкой, подъём на неё — полукруглыми ступенями у подножия или боковым маршем. Новый параметр «Переделка лестниц основы»",
                "На схеме генерации всё, что меняет архитектуру самой основы (перестройка, сдвиг и поворот стены, новый проём, окно, яма, смена уровня пола и т. п.), рисуется бирюзовым и подписывается, пока идут правки (потом гаснет, как принятые пристройки); в ленте событий — «перестроено: …»",
                "Любой текст в любом окне студии выделяется мышью — протянуть по тексту или двойной щелчок для всего текста (например, названия карты) — и копируется Ctrl+C; правая кнопка мыши над текстом — «Копировать» (выделенное, сам текст, весь его блок или весь текст окна); надписи схемы — тоже",
                "Обломки и камни разрушений больше не висят в воздухе: они кладутся только на пол, до которого игрок доходит от точек появления, и только на настоящий камень — не на крышу неба и не на края высоких стен",
                "Генерация не останавливается после четырёх кругов плана, пока остаются пробные сборки и основа даёт новые правки",
                "Правки, которые заведомо не применятся на этой карте (расширение прохода, перестройка помещения, поворот участка), отсеиваются ещё при составлении плана, с причиной — раньше на них уходило до трёх четвертей попыток",
                "Описание карты честно говорит, почему генерация закончилась: если сборки ещё оставались, а план правок исчерпан — так и сказано, со счётом сборок; и объяснено, что считает «отличие от основы»",
                "В описании карты — «Заказано и сделано»: по пристройкам, этажам, мостам, перестройке основы, блокам, полу и лестницам — сколько сделано из заказанного и почему не больше; пристройка, для которой не осталось оружия или брони, получает патроны или аптечку; если для заказанного размера пристроек места больше нет, ставятся пристройки поменьше (256–384), и это сказано",
                "Изменения самой основы ставятся раньше пристроек-лестниц, на арене — крупнее: стены сдвигаются до 256 и выступами от 64 в длину, помосты до 384 в поперечнике и 96 в высоту, террасы до 96; часть блоков на арене — колонны от пола до потолка. Предметы и точки появления у сдвинутой стены переносятся вперёд, на помосте — поднимаются на его верх. На трёх и более вариантах q2dm1 с вашими настройками сама основа арены меняется на 16–19 %",
                "Пристройки-лестницы ведут только наверх, куда иначе далеко идти: на ярус, проём или галерею над стеной комнаты. Лестница идёт вдоль стены и огибает её выступы и ниши (ниши за ступенями заделываются); высокий подъём делится на марши с площадками; где стена коротка, первый марш подходит из зала и поворачивает у стены. Лестниц к площадке с предметом посреди комнаты и отдельно стоящих площадок больше нет; предметы и точки появления на месте ступеней поднимаются на ступени",
                "В пристройках для предметов больше нет трибун (помостов в нише)",
                "Колонн больше и они разные: две рядом держат балку, одиночная либо держит кусок крыши, либо упала — остаётся пенёк и лежащий рядом ствол",
                "Изменения основы (перестройка стен, блоки, помосты) расходятся по всей карте: арене достаётся не больше половины, остальное — другим комнатам",
            },
            new[]
            {
                "Remodels of the base: the generator changes the base map itself, not only builds onto it - a room's wall moved in, a wall turned at an angle, a terrace with steps raised along a wall; the arena first. A new option «Remodel the base»: «Default» (by the likeness), «None» or 1 to 16",
                "Blocks in the base's rooms: a box, an L, a cross, an octagon or a round one, of different sizes and turned at different angles, low ones to climb, high ones a cover; against a wall or free, in the room's own material, the arena first. A new option «Blocks in the rooms»",
                "The base's floor changes: daises stepped on every side are raised, channels across the floor are sunk with a flight at both ends (only where no other room lies under the floor). A new option «Floor: daises and channels»",
                "The base's stairs are rebuilt between the same two floors: the old flight becomes a landing, reached by a half-round foot of steps or a side flight. A new option «Rebuild the base's stairs»",
                "On the generation's scheme everything that changes the base's own architecture (a remodel, a wall moved or turned, a new opening, a window, a pit, a floor level changed and so on) is drawn teal and labelled while the edits go on (then it fades as accepted annexes do); the feed says «rebuilt: …»",
                "Any text of any Studio window is selected with the mouse - a drag across it, or a double click for the whole of it (a map's name, say) - and Ctrl+C copies it; the right mouse button over it - «Copy» (the selection, the text, its whole block or the whole window's text); the scheme's words too",
                "The destruction's debris and stones no longer hang in the air: they are laid only on floors a player reaches from the spawns, and only on real rock - not on a sky's top or the edges of high walls",
                "The generation does not stop after four rounds of the plan while trial builds are left and the base offers new edits",
                "Edits that cannot apply on this map (a widened passage, a reshaped room, a turned section) are dropped when the plan is made, with the reason - they used to take up to three quarters of the tries",
                "The map's description says truly why the generation ended: when builds were left but the plan ran out, it says so, with the builds counted; and it explains what «difference from the base» counts",
                "The map's description has «Asked and made»: for annexes, storeys, bridges, remodels, blocks, the floor and the stairs - how many were made of those asked and why not more; an annex left without a weapon or armour gets ammunition or health; when the asked annex size has no more room, smaller annexes (256-384) are built, and it is said",
                "The base's own changes are dealt before the stairway annexes, larger in the arena: walls moved up to 256 and buttresses from 64 long, daises up to 384 across and 96 high, terraces up to 96; some of the arena's blocks are columns from floor to ceiling. Pickups and spawns before a moved wall go forward, on a dais they rise to its top. On q2dm1 at your options the arena's own architecture changes by 16-19 % on every variant tried",
                "Stairway annexes lead only up, to where the way round is long: a tier, an opening or a gallery over a room's wall. The flight runs along the wall and follows its pilasters and recesses (the recess behind the steps is filled); a high climb is broken into flights with landings; where the wall is short, the first flight comes from the room and turns at the wall. No more flights to a landing with a pickup in a room's middle, no free-standing platforms; pickups and spawns where the steps go are lifted onto the steps",
                "Item annexes no longer have tribunes (a dais in the niche)",
                "More columns, and different: two side by side carry a beam, a lone one either holds a piece of the roof or has fallen - a stump and its drum lying beside it",
                "The base's changes (remodelled walls, blocks, daises) spread over the whole map: the arena gets at most half, the other rooms the rest",
            }),
        new("2.8", "08.10.2026",
            new[]
            {
                "Разрушения до ×100: правая половина регулятора — множитель от ×1 до ×100; выше 100 % растёт объёмное — камни и обломки (и на открытом полу), воронки, проломы, отбитые края, обвалы и завалы, сколько вместит формат карты Quake 2 (на q2dm1 это примерно в 3–4 раза больше, чем на 100 %, на маленькой карте — намного больше); трещины и пятна остаются как на 100 %, новых текстур не добавляется; описание карты говорит, сколько объёмных разрушений заказано и сколько построено",
                "Бассейны с водой, кислотой и лавой не роются под новыми лестницами (на карте с лавой одна лестница оставалась без ступеней)",
                "Регулятор «Быстрее ↔ Точнее» рядом с похожестью: сколько пробных сборок может потратить генерация (от 15 до 140, посередине — 45, как раньше), рядом — примерное время. Если заданное отличие не набралось, описание карты говорит, что не хватило сборок",
                "Порядок после генерации: сначала проверки карты, потом разрушения (если включены), и уже на готовой — разрушенной — карте подбирается свет и проверяется. Раньше свет подбирался до разрушений, а они его меняли",
                "В открытой карте библиотеки — кнопка «Подготовить zip с картой»: архив для сервера, внутри baseq2/maps — карта, baseq2/textures — все её текстуры, которых нет в стандартной игре (разрушения, обломки), и небо, если оно своё; куда сохранить — спрашивает окно сохранения, потом показывает файл в папке",
            },
            new[]
            {
                "Destruction up to ×100: the slider's right half is the factor, ×1 to ×100; past 100 % the 3D ruin grows - stones and debris (on open floor too), craters, breaches, broken edges, falls and blockages, as much as the Quake 2 map format holds (on q2dm1 about 3-4 times what 100 % makes, on a small map far more); the cracks and stains stay as at 100 %, no new textures; the map's description says how much 3D ruin was asked and how much was built",
                "Pools of water, slime and lava are not dug under the new stairways (on a map with lava one stairway had lost its steps)",
                "«Faster ↔ Closer» beside the likeness: how many trial builds a generation may spend (15 to 140, the middle 45 as before), with a rough time beside it. When the difference asked for is not reached, the map's description says the builds ran out",
                "The order after the generation: the map's checks first, then the destruction (when asked), and the light is set and checked on the finished - ruined - map. The light used to be set before the destruction, which then changed it",
                "In a map opened in the library - «Prepare a zip of the map»: an archive for a server, baseq2/maps - the map, baseq2/textures - every texture of it the standard game does not have (the destruction, debris), and its sky if it is its own; where to save it, the save window asks, then the file is shown in its folder",
            }),
        new("2.7", "07.10.2026",
            new[]
            {
                "Проверки карты судят ровно тот план, который сделала генерация: в журнал записываются все настройки (проходы, пристройки, этажи, мосты, залы, украшения), раньше — только лестницы и жидкости",
                "Разрушения не трогают построенное генератором: лестницы, пристройки, галереи и мосты остаются целыми",
                "В описании карты — сколько площадок с лестницами стоит на самом деле после разрушений, и почему остальных нет",
                "Лестницы ставятся сначала у стен; отдельно стоящие — только в комнатах, где у стен места нет. Пролёт можно поставить и у неровной стены: щель за ним закладывается",
                "Ступени и бока лестницы — из материала пола комнаты, а не из стены со светящимися панелями",
                "Лава и кислота: бо́льшая заказанная доля берёт комнаты первой; водоём оставляет сухими места подъёма и не отклоняется за перекрытый путь; если жидкость не легла, в описании сказано почему",
                "Перенесённые комнаты с одним-двумя светильниками получают и свои; копию судят ещё и по разбросу света; трещины не затемняют стены больше чем на 10 %",
                "Если продолжить генерацию с прежнего места не удалось и она началась заново, студия об этом говорит",
            },
            new[]
            {
                "The map's checks judge exactly the plan the generation made: every option goes into its record (passages, annexes, storeys, bridges, halls, decor) - before, only the stairways and liquids",
                "The destruction leaves the generator's own building whole: stairways, annexes, galleries and bridges",
                "The map's description says how many platforms with stairs stand after the destruction, and why the rest do not",
                "Stairs go against walls first; standing free only in rooms whose walls have no place. A flight may stand by an uneven wall: the gap behind it is laid solid",
                "A stairway's steps and sides are of the room's floor material, not of a wall of lit panels",
                "Lava and slime: the larger share asked takes its rooms first; a pool keeps the climb places dry instead of being refused for a blocked way; a liquid not laid is said with why",
                "Carried rooms with one or two lamps get the room's own as well; a copy is judged by its light's spread too; cracks darken a wall by 10 % at most",
                "When a run could not go on from where it was and began again, the Studio says so",
            }),
        new("2.6", "07.10.2026",
            new[]
            {
                "Свет карты и её проверки работают на любом компьютере: раньше они искали игру в папке разработчика, и на других машинах этот шаг не выполнялся",
                "Кислота и лава появляются, когда их выбрали: водоём отступает от мест появления игроков, а не становится водой; в описании карты сказано, сколько новых водоёмов каждой жидкости",
                "Площадки с лестницами — и у стен, и отдельно стоящие на открытом полу, высотой 96–192: на тех же картах их выходит больше (q2dm1: 7 из 10 заказанных вместо 2)",
                "Разрушения: завал в коридоре — обрушившаяся стена из наклонных плит с просветами, а не сплошной блок; отдельные обломки не крупнее 32",
                "Пристройки: ниши 128 × 160 — зашёл и взял предмет; комнаты бывают восьмиугольные, крестом, буквой Г и со скруглёнными углами, не только прямоугольные",
                "Перенесённые под землю комнаты берутся сначала из освещённых светильниками; копия комнаты, освещённой небом, проверяется по свету у своей двери",
                "Свет: комната, которую подсвечивают соседи, больше не затемняется слишком резким шагом",
                "У студии своя иконка — в окне, на панели задач и при переключении окон",
                "Окно не замирает на первом запуске генерации за день: ядра с ошибками проверяются в фоне при старте студии",
                "Генерация, прерванная на проверках или разрушениях, продолжается с проверок: карта уже построена и не строится заново",
            },
            new[]
            {
                "The map's light and its checks work on any computer: they looked for the game in the developer's folder, and on other machines the step never ran",
                "Acid and lava appear when chosen: a pool draws back from the players' start points instead of turning to water; the map's description says how many new pools of each liquid",
                "Platforms with stairs both against walls and standing free on open floor, 96-192 up: more of them on the same maps (q2dm1: 7 of 10 asked instead of 2)",
                "Destruction: a corridor's blockage is a collapsed wall of leaning slabs with gaps, not one solid block; single pieces of debris no larger than 32",
                "Annexes: niches 128 x 160 - step in and take the item; rooms octagonal, cross-shaped, L-shaped and with rounded corners, not only rectangles",
                "Rooms carried underground are taken first from lamp-lit ones; a copy of a sky-lit room is checked against the light at its door",
                "Light: a room lit up by its neighbours is no longer darkened by too hard a step",
                "The Studio has its own icon - in the window, the taskbar and the window switcher",
                "The window no longer freezes on the day's first generation: the faulty cores are read in the background when the Studio starts",
                "A generation interrupted in its checks or its destruction resumes from the checks: the map is built already and is not built again",
            }),
        new("2.5", "07.10.2026",
            new[]
            {
                "Разрушения — отдельный этап в ходе работы, со своим временем; их процент назван в строке плана",
                "На схеме карты видны пристройки-лестницы по имени, а на этапе разрушений — каждая воронка, пролом, обвал и куча обломков по мере постройки",
                "Студия, развёрнутая на весь экран, после «Назад в студию» возвращается развёрнутой",
                "Кнопка «Начать генерацию» срабатывает с первого нажатия (над ней открывались две подсказки сразу)",
                "Генерация из студии не занимает ядра процессора, на которые жалуется Windows",
            },
            new[]
            {
                "Destruction is a stage of its own on the run's page, with its time; its percent is named in the plan's line",
                "The map's scheme names stairway annexes and, at the destruction stage, shows every crater, breach, fallen ceiling and debris pile as it is built",
                "The Studio maximised comes back maximised after «Back to the Studio»",
                "«Start generating» works on the first press (two tooltips were opening over it at once)",
                "A generation from the Studio keeps off the processor cores Windows reports hardware errors for",
            }),
        new("2.4", "07.10.2026",
            new[]
            {
                "Разрушения выглядят естественнее: трещины — неповторяющейся сеткой и не на всех стенах, а больше там, где был удар; пробоины, воронки и копоть — по одной, на своём месте, а не узором по всей стене",
                "Обломки — неровные куски того, что разрушилось (пол, стена, потолок), а не одинаковые бруски; лежат у стен, проломов и обвалов, не на ступенях",
                "Повреждённые поверхности рисуются в том же качестве, что и остальные текстуры игры",
                "Набор текстур: полосатые панели и доски больше не считаются камнем",
                "Обвалы потолка — только под настоящим потолком, не под открытым небом; у воды ничего не строится",
                "Генерация не занимает ядра процессора, на которые жалуется Windows (аппаратные ошибки в журнале): падения генератора на таком процессоре прекратились",
                "Лестницы: встают вплотную к стене, без щели; место у стены, стоящей над пустотой, больше не выбирается",
                "Свет: светильники перенесённых комнат окрашиваются в цвет оригинала; тоннели со светящимися панелями выравниваются быстрее; после подстройки света комнат общий свет карты проверяется ещё раз",
            },
            new[]
            {
                "Destruction looks more natural: cracks as a non-repeating network and not on every wall, more where it was hit; holes, craters and soot one by one, each in its place, not a pattern over the wall",
                "Debris are irregular pieces of what broke (floor, wall, ceiling), not identical bricks; they lie by walls, breaches and falls, never on steps",
                "Damaged surfaces are drawn at the same quality as the game's other textures",
                "The texture pack: striped panels and planks are no longer taken for stone",
                "Fallen ceilings only under a real ceiling, never under the open sky; nothing is built by water",
                "The generation keeps off the processor cores Windows reports hardware errors for: the generator's crashes on such a processor stopped",
                "Stairways stand flush against the wall, no slot; a wall standing over a void is no longer chosen",
                "Light: carried rooms' lamps take their original's colour; tunnels lit by glowing panels settle faster; after the rooms' light is set the map's shared light is checked once more",
            }),
        new("2.3", "06.10.2026",
            new[]
            {
                "«Пристройки-лестницы» (0–10): пролёты ступеней вдоль стен комнат к новым площадкам, на площадке предмет или выход на уступ; места ищутся на любой основе",
                "«Разрушения» (0–100 %): трещины, обломки, воронки, проломы, отбитые края, обвалы потолка, завалы — по нарастающей; точки появления всегда свободны",
                "Набор текстур генератора: поверхности из присланных картинок, образцы из интернета и сгенерированные трещины и воронки, в формате игры",
                "Свет: комната, перенесённая целиком со своими светильниками, больше не подсвечивается второй раз; в тоннелях с висящими светильниками меньше заливающего света; карта первой генерации на новой основе освещается верно",
            },
            new[]
            {
                "«Stairway annexes» (0-10): flights of steps along rooms' walls to new landings, a pickup on each or a ledge it meets; sites found on any base",
                "«Destruction» (0-100 %): cracks, rubble, craters, breaches, broken edges, fallen ceilings, blocked places - more with the percent; the starts are always free",
                "The generator's texture pack: surfaces made from the supplied pictures, samples from the web and generated cracks and craters, in the game's format",
                "Light: a room carried whole with its own lamps is no longer lit twice; tunnels with hung lamps get less fill light; the first map of a new base is lit right",
            }),
        new("2.2", "06.10.2026",
            new[]
            {
                "Обновления: «Автоматическая проверка обновлений» (включена) и кнопка «Проверить обновления» в настройках и в «О программе»; новая версия и весь лог изменений с GitHub на языке студии; «Да» — скачать, проверить, заменить программу и перезапустить, ваши карты и настройки остаются",
                "После обновления — окно «Что нового» с изменениями этой версии и всем логом",
            },
            new[]
            {
                "Updates: «Check for updates automatically» (on) and «Check for updates» in the settings and in About; the new version and the whole change log from GitHub in the Studio's language; «Yes» downloads, checks, replaces the program and restarts it, your maps and settings stay",
                "After an update, a «What's new» window with this version's changes and the whole log",
            }),
        new("2.1", "06.10.2026",
            new[]
            {
                "Первый выпуск на GitHub: архив работает сам — генератор, компилятор карт и готовые программы проверок внутри, компилятор C не нужен",
            },
            new[]
            {
                "The first release on GitHub: the zip works on its own - the generator, the map compiler and the checks' programs are inside, no C compiler needed",
            }),
        new("2.0", "06.10.2026",
            new[]
            {
                "Подпись автора «by ly» в «О программе», в руководстве и на GitHub — как у Q2PRO-X",
                "Исходники генератора и студии опубликованы на GitHub: github.com/Quake-Journey/MAPGEN",
                "В руководстве сказано, что сборка карты с нуля появится в будущих версиях",
            },
            new[]
            {
                "The author's credit «by ly» in About, in the guide and on GitHub - as Q2PRO-X has it",
                "The generator's and the Studio's sources are published on GitHub: github.com/Quake-Journey/MAPGEN",
                "The guide says that a map from scratch will come in a future version",
            }),
        new("1.9", "06.10.2026",
            new[]
            {
                "Руководство пользователя на русском и английском со снимками, которые делает сама программа",
                "Студия находит проверки карт в папке tools рядом с собой — для скачанной сборки не нужны исходники",
                "Главная страница говорит, найден ли Python для проверок; Python ищется и там, куда его ставит установщик без «Add to PATH»",
                "Если проверки пропущены, сказано почему: нет Python или нет папки с проверками",
                "Если Python нет, студия сама предлагает его установить (официальный установщик с python.org, подпись проверяется, без прав администратора) или указать путь к нему; выбор есть и в настройках",
            },
            new[]
            {
                "A user guide in Russian and English, with screenshots the program takes of itself",
                "The Studio finds the map checks in a tools folder beside itself - a downloaded build needs no sources",
                "The home page says whether Python for the checks was found; Python is also looked for where its installer puts it without «Add to PATH»",
                "Skipped checks say why: no Python, or no folder with the checks",
                "With no Python the Studio offers to install it (the official installer from python.org, its signature checked, no administrator) or to be pointed at it; the choice is in the settings too",
            }),
        new("1.8", "06.10.2026",
            new[]
            {
                "Пока карта развёрнута на весь экран, окно студии спрятано — по Alt+Tab между ними не переключаться",
                "Кнопка «Назад в студию» вместо «Свернуть» (и Esc): карта закрывается, студия снова на экране и активна",
            },
            new[]
            {
                "While the map is on the whole screen the Studio's window is hidden - Alt+Tab no longer flips between the two",
                "«Back to the Studio» instead of «Minimise» (and Esc): the map closes, the Studio is back on screen and active",
            }),
        new("1.7", "06.10.2026",
            new[]
            {
                "Новые регуляторы «Новая вода», «Новая кислота», «Новая лава»: по умолчанию решает генератор; 0 — этой жидкости нет совсем; 100 — ею заливаются все комнаты, где это можно (лава и кислота — не у точек появления)",
                "При большом количестве жидкости генератор пробует заливку первой, чтобы на неё хватило попыток",
            },
            new[]
            {
                "New sliders «New water», «New slime», «New lava»: by default the generator decides; 0 - none of that liquid; 100 - every room it can fill (slime and lava away from the starts)",
                "With much liquid asked for, the generator tries the floods first so the run's attempts reach them",
            }),
        new("1.6", "06.10.2026",
            new[]
            {
                "Карты, где невидимые зоны срабатывания хранятся вместе со своими гранями (например, q2duel1), больше не отвергаются как основа: сверка копии с оригиналом не сравнивает то, что никто не видит",
                "Если генератор всё же отвергает карту-основу, Студия пишет, что именно разошлось у копии с оригиналом, и точные слова генератора — и в окне, и в журнале сборки",
                "Факел и любые перенесённые детали сохраняют рисунок на своих гранях после поворота и переноса",
            },
            new[]
            {
                "Maps that keep their invisible trigger zones with their faces (q2duel1, say) are no longer refused as a base: the copy is not compared with the original on what nobody sees",
                "When the generator does refuse a base map, the Studio says which parts of the copy differ from the original and the generator's exact words - in the window and in the run's log",
                "A torch and every other carried piece keep the picture on their faces after a turn and a move",
            }),
        new("1.5", "05.10.2026",
            new[]
            {
                "Комнаты второй карты переносятся вырезанными целиком: потолки, стены и пол приходят вместе с тем, что на них висит; детали, которые ни на что не опираются, не переносятся",
                "Генератор находит на стенах основы её светильники и повторяющиеся украшения и вешает такие же на стены своих тоннелей",
                "Новый параметр «Украшения на стенах»: по умолчанию, без украшений, мало, много, очень много",
            },
            new[]
            {
                "Rooms of the second map are carried as a whole cut: ceilings, walls and floor come with what hangs on them; pieces that rest on nothing are left out",
                "The generator finds the base's wall lamps and repeated wall ornaments and hangs the same on its tunnels' walls",
                "New option «Wall decorations»: default, none, few, many, very many",
            }),
        new("1.4", "05.10.2026",
            new[]
            {
                "Генератор больше не строит свои пустые коробки-комнаты: новые комнаты — настоящие комнаты второй карты и самой основы, перенесённые целиком, со своими стенами, проёмами и деталями",
                "Генератор обходит стёкла, двери и лифты основы — новые стены не ложатся вплотную к ним",
                "В «Сделано по плану» — комнаты из второй карты и из основы",
            },
            new[]
            {
                "The generator no longer builds its own empty box rooms: new rooms are real rooms of the second map and of the base, carried whole with their walls, openings and detail",
                "The generator keeps clear of the base's panes, doors and lifts - no new wall lies against them",
                "«Done of the plan» counts the rooms of the second map and of the base",
            }),
        new("1.3", "05.10.2026",
            new[]
            {
                "Новые комнаты больше не одна квадратная коробка: разные пропорции, пол ровный, с бортиком или с галереей и ступенями, предмет на постаменте, у дальней стены, на галерее или между колоннами, колонны и отделка — в одной карте двух одинаковых нет",
                "Вторая карта даёт архитектуру: её комната строится в скале рядом с основой — со своими колоннами, ступенями, отделкой и светом",
                "Часть новых комнат получает отделку второй карты",
                "В конце сказано, что взято из второй карты, а если ничего — почему, по числу причин",
                "Журнал генерации сохраняется рядом с картой; проверки карты больше не ошибаются из-за работы в памяти",
            },
            new[]
            {
                "New rooms are no longer one square box: proportions, a flat floor, a rim or a gallery with steps, the pickup on a dais, by the far wall, on the gallery or between columns, columns and trims - no two alike in a map",
                "The second map gives architecture: a room of it is built in the rock beside the base, with its own columns, steps, trims and light",
                "Some new rooms take the second map's skin",
                "The end says what was taken from the second map, or why nothing, by count",
                "The run's log is kept with the map; the map's checks no longer fail for the run having worked in memory",
            }),
        new("1.2", "05.10.2026",
            new[]
            {
                "Схема во время генерации показывает текущую карту с принятыми правками — раньше показывала исходную основу",
                "На схеме бледными блоками видно, где будут ещё не опробованные правки: проходы и пристройки, мосты, водоёмы и замены жидкостей, окна",
                "«Сделано по плану»: сколько проходов, пристроек, комнат в два этажа, мостов, водоёмов, окон и замен жидкостей уже принято",
                "Ход расчёта видимости и света в процентах — на этапе и на схеме; после расчёта схема показывает карту с её настоящим светом",
                "Лента событий на схеме показывает и этапы генерации, а не только правки",
            },
            new[]
            {
                "The plan shows the map being built with its accepted edits while it runs - it showed the base before",
                "Faint blocks on the plan show where the edits not yet tried will go: passages and annexes, bridges, pools and liquids, windows",
                "«Done of the plan»: how many passages, annexes, two-storey rooms, bridges, pools, windows and liquid changes are accepted",
                "The visibility and light passes in percent - on the stage and on the plan; after them the plan shows the map in its own light",
                "The plan's feed shows the run's stages too, not only the edits",
            }),
        new("1.1", "05.10.2026",
            new[]
            {
                "Плитки карт и снимков увеличиваются колесом мыши с Ctrl или ползунком «Размер» — вместе с картинками и подписями",
                "Плитки занимают всю ширину окна; верх страницы с кнопками остаётся на месте",
                "Щелчок по снимку открывает его на всё окно: вперёд, назад, закрыть; там же — «Сделать обложкой»",
            },
            new[]
            {
                "The map and shot tiles grow with Ctrl and the mouse wheel or the «Size» slider - pictures and captions together",
                "The tiles take the window's whole width; the page's top with its buttons stays put",
                "A click on a shot shows it over the whole window: forward, back, close; «Make it the cover» there",
            }),
        new("1.0", "05.10.2026",
            new[]
            {
                "Ненужную генерацию можно удалить кнопкой «Удалить» — вместе со всеми её рабочими файлами",
                "«Отменить» останавливает идущую генерацию и сразу удаляет её файлы",
                "После удачной генерации её рабочие файлы убираются сами — карта уже в библиотеке",
                "Перед удалением студия спрашивает и говорит, сколько места освободится",
            },
            new[]
            {
                "A generation not wanted is deleted with «Delete» - with all its working files",
                "«Cancel» stops a running generation and deletes its files at once",
                "After a generation that ended well its working files go by themselves - the map is in the library",
                "Before deleting the Studio asks and says how much space it frees",
            }),
        new("0.9", "05.10.2026",
            new[]
            {
                "Генератор держит рабочие файлы в оперативной памяти, а не на диске: за генерацию на диск уходит около 2 МБ вместо 30",
                "Настройки «Память под рабочие файлы генератора» и «Сохранять принятые шаги на диск»",
                "Генерацию без сохранённых шагов студия не предлагает продолжить и говорит почему",
                "В карточке загрузки — видеокарта и видеопамять",
                "Карта на весь экран больше не обрезается, значки не отходят от карты",
            },
            new[]
            {
                "The generator keeps its working files in memory, not on the disk: about 2 MB written per generation instead of 30",
                "Settings «Memory for the generator's working files» and «Keep the accepted steps on the disk»",
                "A generation without its steps on the disk is not offered to resume, and the Studio says why",
                "The load card shows the graphics card and its memory",
                "The full-screen plan is no longer cut, its marks stay on the map",
            }),
        new("0.8.1", "05.10.2026",
            new[]
            {
                "Схема карты рисуется видеокартой — не тормозит и на весь экран",
                "События на полном экране под строками генерации, а не поверх них",
                "«На весь экран» выводит уже открытое окно вперёд",
            },
            new[]
            {
                "The plan is drawn by the graphics card - smooth on the full screen too",
                "The events on the full screen sit under the run's lines, not over them",
                "«Full screen» brings an open one forward",
            }),
        new("0.8", "05.10.2026",
            new[]
            {
                "Схема строящейся карты в 3D: вращение, приближение, на весь экран",
                "Карточка загрузки: процессор и память — всего компьютера и генератора",
                "Творческие параметры: новые проходы, пристройки, комнаты в два этажа, мосты, залы",
                "Замена жидкостей (вода, лава, кислота) — и вид, и свойства",
                "Выбранные основы и все поля формы запоминаются между запусками",
            },
            new[]
            {
                "The plan of the map being built in 3D: turn, zoom, full screen",
                "The load card: processor and memory - of the computer and of the generator",
                "Creative options: new passages, annex rooms, two-storey rooms, bridges, halls",
                "Liquids made other liquids (water, lava, acid) - their look and their harm",
                "The ticked bases and the whole form kept across starts",
            }),
        new("0.7", "05.10.2026",
            new[]
            {
                "Окно не зависает во время генерации",
                "Подробный журнал растягивается до низа окна",
                "Время каждого этапа и всей генерации, окончание этапа и остаток правок",
                "Пауза останавливает часы; этапы неудачной генерации отмечены честно",
            },
            new[]
            {
                "The window no longer hangs while a generation runs",
                "The detailed log reaches the window's bottom",
                "Each stage's time and the whole run's, the stage's end and the edits left",
                "A pause stops the clocks; a failed run's stages marked as they were",
            }),
        new("0.6", "04.10.2026",
            new[]
            {
                "Мосты между галереями над ареной",
                "Новые комнаты освещены так, как основа освещает свои",
                "Свет новой основы подбирается один раз сам",
                "Доля процессора днём и ночью — от быстрых ядер",
            },
            new[]
            {
                "Bridges between galleries across an arena",
                "New rooms lit the way their base lights its own",
                "A new base's light fitted once, by itself",
                "The day and night share of the processor - of its fast cores",
            }),
        new("0.5", "03.10.2026",
            new[]
            {
                "Расчёт света на всех быстрых ядрах процессора",
                "Свет каждой основы откалиброван под неё",
                "Студия — один файл, без библиотек рядом",
            },
            new[]
            {
                "The light pass on every fast core of the processor",
                "Each base's light calibrated for it",
                "The Studio is one file, no libraries beside it",
            }),
        new("0.4", "03.10.2026",
            new[]
            {
                "Карты Quake III как основы (cor, q3t2)",
                "Стартовая страница выбирается в настройках",
                "Генерация, идущая в другом окне студии, не путается с прерванной",
            },
            new[]
            {
                "Quake III layouts as bases (cor, q3t2)",
                "The start page chosen in the settings",
                "A generation another Studio window carries is not taken for an interrupted one",
            }),
        new("0.3", "03.10.2026",
            new[]
            {
                "Основой может быть любая карта Quake II, несколько сразу",
                "Отказы генератора простыми словами",
            },
            new[]
            {
                "Any Quake II map as a base, several at once",
                "The generator's refusals in plain words",
            }),
        new("0.2", "03.10.2026",
            new[]
            {
                "Генерация из студии, продолжение прерванной с того же места",
                "Обложки карт снимаются в игре сами",
                "Библиотека карт с описаниями и проверками",
            },
            new[]
            {
                "Generation from the Studio, an interrupted one resumed where it stopped",
                "Map covers shot in the game by themselves",
                "The map library with descriptions and checks",
            }),
        new("0.1", "03.10.2026",
            new[] { "Первая версия: оболочка, светлая и тёмная темы, русский и английский" },
            new[] { "The first version: the shell, light and dark themes, Russian and English" }),
    };

    public static string Current => All[0].Number;

    /// <summary>
    /// A version as the PO reads it - two numbers, each build a tenth more (1.1, 1.2 ... 1.9, 2.0; the PO, 05.10:
    /// «0.10 выглядит меньше чем 0.9»); the third only when it is not zero.
    /// </summary>
    public static string Said(Version? v) => v == null ? Current : v.Build > 0 ? v.ToString(3) : v.ToString(2);
}
