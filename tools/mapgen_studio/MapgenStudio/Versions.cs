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
