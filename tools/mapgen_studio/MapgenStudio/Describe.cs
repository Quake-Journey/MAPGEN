using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace MapgenStudio;

/// <summary>
/// A made map's description in plain words, Russian and English (R11): when it was made and how long it took, the
/// donor, likeness and variant, what likeness was asked and what was reached, and what is new against the donor -
/// counted from the run's ledger (accepted edits by family, digs by their shape) and the pickups the checks found in
/// the new rooms.
/// </summary>
public static class Describe
{
    private static readonly Regex Accepted = new(@"^\s*\d+\s+(\S+)\s+ACCEPTED\b(.*)$", RegexOptions.Multiline);
    private static readonly Regex Shape = new(@"\bshape (\S+)");
    private static readonly Regex Holds = new(@"holds ((?:weapon|item|ammo)_\w+)");
    // brief 14 F2: the stairways gate - «N stairways in the plan, M accepted, K built», once before the ruin and once after
    private static readonly Regex StairGate = new(@"stairways: every stairway[^\n]*?-- (\d+) stairways in the plan, (\d+) accepted, (\d+) built");

    private static string VerdictRu(string v) => v switch
    {
        "REJECTED_BURIED_ROUTE" => "перекрыла бы путь или подъём",
        "REJECTED_HIDDEN" => "открыла бы невидимое",
        "REJECTED_UNREACHABLE" => "отрезала бы часть карты",
        "REJECTED_LOST_PICKUP" => "закрыла бы предмет",
        _ => v,
    };

    public static string Map(Generation g, string lang)
    {
        var ru = lang == "ru";
        var ledger = Path.Combine(g.JobDir, "ledger.txt");
        var text = File.Exists(ledger) ? File.ReadAllText(ledger) : "";
        var families = new Dictionary<string, int>();
        var shapes = new Dictionary<string, int>();
        foreach (Match m in Accepted.Matches(text))
        {
            var fam = m.Groups[1].Value;
            families[fam] = families.GetValueOrDefault(fam) + 1;
            if (fam == "dig" && Shape.Match(m.Groups[2].Value) is { Success: true } sm)
                shapes[sm.Groups[1].Value] = shapes.GetValueOrDefault(sm.Groups[1].Value) + 1;
        }
        var gates = Path.Combine(g.RunDir, "gates.txt");
        var pickups = File.Exists(gates)
            ? Holds.Matches(File.ReadAllText(gates)).Select(m => Pickup(m.Groups[1].Value, ru)).Distinct().ToList()
            : new List<string>();

        var b = new StringBuilder();
        var end = g.Ended ?? DateTime.Now;
        var took = end - g.Began;
        b.AppendLine(ru ? $"Карта {g.Request.Name} сделана из {g.Request.Donor}."
                        : $"Map {g.Request.Name}, made from {g.Request.Donor}.");
        if (g.Request.Grafts is { Count: > 0 } grafts)
        {
            // brief 9 D4: what the second map gave, in the map's own words
            var keepLang = Loc.Language;
            Loc.Language = ru ? "ru" : "en";
            var second = g.SecondSaid();
            Loc.Language = keepLang;
            b.AppendLine(ru ? $"Комнаты разрешено было брать из: {string.Join(", ", grafts)}." : $"Rooms could come from: {string.Join(", ", grafts)}.");
            if (second.Length > 0)
                b.AppendLine(second);
        }
        b.AppendLine(ru ? $"Генерация: начало {g.Began:dd.MM.yyyy HH:mm}, конец {end:dd.MM.yyyy HH:mm}, длилась {Duration(took, ru)} (местное время)."
                        : $"Generation: began {g.Began:yyyy-MM-dd HH:mm}, ended {end:yyyy-MM-dd HH:mm}, took {Duration(took, ru)} (local time).");
        b.AppendLine(ru ? $"Похожесть на основу: {g.Request.Fidelity}%, номер варианта {g.Request.Seed}."
                        : $"Likeness to the base: {g.Request.Fidelity}%, variant number {g.Request.Seed}.");
        /*
         * Brief 15 D1 (the PO 08.10: «100% качество подготовки, но снова около 60% похожести»): the reason said as it
         * was - a run whose plan ran out with builds left was told «больше за отведённые пробные сборки не вышло»
         * while 86 of 140 builds were never used.
         */
        if (g.Target > 0)
        {
            if (g.Divergence >= g.Target)
                b.AppendLine(ru ? $"Отличие от основы: просили {Pct(g.Target)}%, получилось {Pct(g.Divergence)}%."
                                : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached.");
            else if (g.EndedBy == "time")
                /* brief 16 D6: the honest line - what the minutes gave, against what the plan could */
                b.AppendLine(ru ? $"Отличие от основы: просили {Pct(g.Target)}%, за {g.Request.TimeMinutes} мин получилось {Pct(g.Divergence)}%" + (g.PlanFirstCan >= 0 ? $", план давал до {Pct(g.PlanFirstCan)}%." : ".") + " Больше даст время дольше (регулятор «Быстрее ↔ Точнее» правее)."
                                : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached in {g.Request.TimeMinutes} min" + (g.PlanFirstCan >= 0 ? $", the plan gave up to {Pct(g.PlanFirstCan)}%." : ".") + " More time gives more («Faster ↔ Closer» to the right).");
            else if (g.EndedBy == "plan")
                b.AppendLine(ru ? $"Отличие от основы: просили {Pct(g.Target)}%, получилось {Pct(g.Divergence)}%" + (g.PlanFirstCan >= 0 ? $", план давал до {Pct(g.PlanFirstCan)}%" : "") + ". План правок исчерпан: каждую предложенную правку генератор проверил один раз, отклонённые повторно не пробовались, новых основа не дала. Больше отличия дадут параметры перестройки основы, пристроек, этажей и мостов."
                                : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached" + (g.PlanFirstCan >= 0 ? $", the plan gave up to {Pct(g.PlanFirstCan)}%" : "") + ". The plan ran out: every edit offered was tried once, a refused one was not tried again, and the base offered no new ones. The options for remodels of the base, annexes, storeys and spans give more.");
            else if (g.EndedBy == "schedule" && g.Budget > g.Compiles)
                b.AppendLine(ru ? $"Отличие от основы: просили {Pct(g.Target)}%, получилось {Pct(g.Divergence)}%. Пробных сборок использовано {g.Compiles} из {g.Budget}: сборки ещё оставались, но план правок исчерпан — все предложенные правки испробованы, а новых основа не дала. Больше отличия дадут параметры перестройки основы, пристроек, этажей и мостов (что сделано из заказанного и почему не больше — ниже)."
                                : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached. Trial builds used: {g.Compiles} of {g.Budget} - builds were left, but the plan ran out: every edit offered was tried and the base offered no new ones. The options for remodels of the base, annexes, storeys and spans give more (what was made of what was asked, and why not more, is below).");
            else
                b.AppendLine(ru ? $"Отличие от основы: просили {Pct(g.Target)}%, получилось {Pct(g.Divergence)}% — отведённые пробные сборки ({g.Compiles} из {g.Budget}) кончились; регулятор «Быстрее ↔ Точнее» правее даст их больше."
                                : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached - the trial builds allowed ({g.Compiles} of {g.Budget}) ran out; «Faster ↔ Closer» to the right gives more.");
            b.AppendLine(ru ? "Отличие считается по самой основе: её объём делится на кубики со стороной 32 единицы, и отличие — доля кубиков, где что-то стало другим: камень стал воздухом или наоборот, сдвинулся пол или стена, поменялась высота, путь игрока или повторяющийся узор. Пристройка снаружи основы прибавляет отличие только там, где врезается в неё; перестройка самой основы прибавляет его больше всего." : "The difference is counted on the base itself: its volume is cut into cubes 32 units a side, and the difference is the share of the cubes where something changed - rock became air or the other way round, a floor or a wall moved, a height, a player's way or a repeated pattern changed. An annex outside the base adds to it only where it cuts into the base; a remodel of the base itself adds the most.");
        }
        // row 410: the generator says «-» when nothing ended the edits early - «[ended.-]» went into the description
        else if (Loc.Has($"ended.{g.EndedBy}"))
            b.AppendLine(Loc.Language == lang ? Loc.T($"ended.{g.EndedBy}") : EndedIn(g.EndedBy, ru));
        /* the base's own frame, changed before the first edit (the PO, 10.10: «хочется именно менять донора») */
        if (g.WarpArea > 0)
        {
            var (lo, hi) = Generation.WarpSpread(g.WarpParts);
            string K(double k) => k.ToString("0.0#", ru ? CultureInfo.GetCultureInfo("ru-RU") : CultureInfo.InvariantCulture);
            b.AppendLine(ru ? $"Каркас основы изменён до первой правки: площадь карты {Pct(g.WarpArea)}% от исходной, её части растянуты по-разному — от {K(lo)} до {K(hi)} раза. Высоты прежние: ступени, уступы, прыжки и лифты те же. Отличие выше считается уже от изменённой основы."
                            : $"The base's frame was changed before the first edit: the map's area is {Pct(g.WarpArea)}% of the original, its parts stretched unequally - from {K(lo)} to {K(hi)} times. Heights are kept: the steps, ledges, jumps and lifts are the same. The difference above is counted from the changed base.");
            var (turn, mirror, height) = Generation.WarpFrame(g.WarpParts);
            if (Generation.WarpShiftOf(g.WarpParts) > 0)
                b.AppendLine(ru ? "Части основы сдвинуты вбок друг относительно друга: комнаты одной части стоят смещёнными против соседней, проходы между частями изгибаются; полы ровные, стены вертикальные, части с дверями, лифтами и поездами перенесены целиком."
                                : "The base's parts are slid sideways against each other: the rooms of one part stand moved over against the next one's, the passages between them bend; floors are level, walls upright, parts with doors, lifts and trains moved whole.");
            if (turn > 0 || mirror)
                b.AppendLine(ru ? $"Основа {(mirror ? "отражена зеркально" : "")}{(mirror && turn > 0 ? " и " : "")}{(turn > 0 ? $"повёрнута на {turn}°" : "")}: те же места стоят по другим сторонам света."
                                : $"The base is {(mirror ? "mirrored" : "")}{(mirror && turn > 0 ? " and " : "")}{(turn > 0 ? $"turned by {turn}°" : "")}: the same places face other ways.");
            if (height > 100)
                b.AppendLine(ru ? $"Потолки над самым высоким местом, где стоит игрок, подняты: пространство над ним выше в {height / 100.0:0.0#} раза; полы, ступени и прыжки не тронуты."
                                : $"The ceilings above the highest place a player stands are lifted: the room over it is {height / 100.0:0.0#} times taller; floors, steps and jumps are untouched.");
        }
        else if (g.WarpKept)
            b.AppendLine(ru ? "Каркас основы не изменён: растянутая карта не прошла проверку, и генерация шла на исходной основе."
                            : "The base's frame was not changed: the stretched map did not pass the check, and the generation went on the original base.");
        /* brief 16 D0: where the edits were answered - most before any build */
        if (g.Ladder is { Length: 6 } ladder)
            b.AppendLine(ru ? $"Как шли правки: {ladder[0]} не подошли к карте и {ladder[1]} отклонены проверкой до сборки — без сборки; {ladder[2]} уже пробовались и не предлагались снова; {ladder[3]} отложены на конец (замена жидкостей); собрано {ladder[4]}, из них проходимость полностью пересчитывалась {ladder[5]} раз, у остальных — только около правки."
                            : $"How the edits went: {ladder[0]} did not fit the map and {ladder[1]} were refused by the check before the build - no build; {ladder[2]} had been tried and were not offered again; {ladder[3]} kept for the end (liquids swapped); {ladder[4]} built, the walk worked out whole {ladder[5]} times, for the rest only around the edit.");
        var news = new List<string>();
        void Add(int n, string ruOne, string ruFew, string ruMany, string en)
        {
            if (n > 0)
                news.Add(ru ? $"{n} {RuForm(n, ruOne, ruFew, ruMany)}" : $"{n} {en}");
        }
        Add(shapes.GetValueOrDefault("annex"), "пристройка с предметом", "пристройки с предметами", "пристроек с предметами", "annex room(s) holding a pickup");
        Add(shapes.GetValueOrDefault("storeys"), "комната в два этажа", "комнаты в два этажа", "комнат в два этажа", "two-storey room(s)");
        Add(shapes.GetValueOrDefault("hall"), "новый зал", "новых зала", "новых залов", "new hall(s)");
        Add(shapes.GetValueOrDefault("tunnel") + shapes.GetValueOrDefault("corridor"), "новый проход", "новых прохода", "новых проходов", "new passage(s)");
        Add(shapes.GetValueOrDefault("tunnel+lift"), "проход с лифтом", "прохода с лифтами", "проходов с лифтами", "passage(s) with a lift");
        Add(families.GetValueOrDefault("span"), "мост над ареной", "моста над ареной", "мостов над ареной", "bridge(s) over the arena");
        // brief 14 F2: the stairways that STAND in the finished map, when the checks counted them
        var stairGates = File.Exists(gates) ? StairGate.Matches(File.ReadAllText(gates)) : null;
        Add(stairGates is { Count: > 0 } sg ? int.Parse(sg[sg.Count - 1].Groups[3].Value, CultureInfo.InvariantCulture)
                                            : families.GetValueOrDefault("stairway"), "лестница к новой площадке", "лестницы к новым площадкам", "лестниц к новым площадкам", "stairway(s) up to a new landing");
        Add(families.GetValueOrDefault("flood"), "место с водой", "места с водой", "мест с водой", "flooded place(s)");
        Add(families.GetValueOrDefault("window"), "окно", "окна", "окон", "window(s)");
        Add(families.GetValueOrDefault("stairs-to-lift"), "лестница заменена лифтом", "лестницы заменены лифтами", "лестниц заменено лифтами", "stair(s) replaced by a lift");
        Add(families.GetValueOrDefault("reshape-room") + families.GetValueOrDefault("push-wall")
            + families.GetValueOrDefault("relevel") + families.GetValueOrDefault("widen-connector")
            + families.GetValueOrDefault("turn-bundle") + families.GetValueOrDefault("open-connector"),
            "перестроенное помещение", "перестроенных помещения", "перестроенных помещений", "reshaped room(s)");
        // brief 15 D6: the base's own walls and rooms changed, in the PO's words («стен сдвинуто 5, блоков 6»)
        Add(families.GetValueOrDefault("remodel"), "стена основы сдвинута, повёрнута или с террасой", "стены основы сдвинуты, повёрнуты или с террасой",
            "стен основы сдвинуто, повёрнуто или с террасой", "wall(s) of the base moved, turned or with a terrace");
        Add(families.GetValueOrDefault("block"), "блок в комнате основы", "блока в комнатах основы", "блоков в комнатах основы", "block(s) in the base's rooms");
        Add(families.GetValueOrDefault("floor-shift"), "изменение пола (помост или канал)", "изменения пола (помосты или каналы)", "изменений пола (помосты или каналы)", "floor change(s) (a dais or a channel)");
        Add(families.GetValueOrDefault("stair-reshape"), "лестница основы переделана", "лестницы основы переделаны", "лестниц основы переделано", "stair(s) of the base rebuilt");
        Add(families.GetValueOrDefault("swap-item"), "перестановка предметов", "перестановки предметов", "перестановок предметов", "pickup swap(s)");
        Add(families.GetValueOrDefault("move-spawn"), "перенесённая точка появления", "перенесённые точки появления", "перенесённых точек появления", "moved spawn point(s)");
        b.AppendLine();
        b.AppendLine(ru ? "Что нового:" : "What is new:");
        b.AppendLine(news.Count > 0 ? "  " + string.Join(ru ? ";\n  " : ";\n  ", news) + "."
                                    : ru ? "  ничего — карта совпадает с основой." : "  nothing - the map is the base.");
        if (pickups.Count > 0)
            b.AppendLine(ru ? $"В новых комнатах: {string.Join(", ", pickups)}." : $"In the new rooms: {string.Join(", ", pickups)}.");
        // brief 15 D3: each large family - asked, made, and why not more - in words
        var askedMade = AskedAndMade(g, families, shapes, ru);
        if (askedMade.Count > 0)
        {
            b.AppendLine(ru ? "Заказано и сделано:" : "Asked and made:");
            foreach (var line in askedMade)
                b.AppendLine("  " + line);
        }
        // brief 13 W7 (the PO on mg_1_6662: «я выбирал кислоту и лаву, а там одна вода»): the floods by their liquid,
        // as the generator dealt them (job/liquids.txt) and the ledger accepted them; and the base's own pools a
        // «mix» could not touch, said with why
        var liquids = Path.Combine(g.JobDir, "liquids.txt");
        var ledgerFile = Path.Combine(g.JobDir, "ledger.txt");
        if (File.Exists(liquids) && File.Exists(ledgerFile))
        {
            var offered = new List<(float[] box, string tex)>();
            foreach (var line in File.ReadAllLines(liquids))
            {
                var m = System.Text.RegularExpressions.Regex.Match(line,
                    @"flood offered: (\S+) in room \d+, .* (-?\d+) (-?\d+) \.\. (-?\d+) (-?\d+)\s*$");
                if (m.Success)
                    offered.Add((new[] { float.Parse(m.Groups[2].Value), float.Parse(m.Groups[3].Value),
                                         float.Parse(m.Groups[4].Value), float.Parse(m.Groups[5].Value) }, m.Groups[1].Value));
            }
            int water = 0, slime = 0, lava = 0, unplayable = 0;
            var refusedKinds = new List<(string kind, string verdict)>();
            foreach (var line in File.ReadAllLines(ledgerFile))
            {
                var m = System.Text.RegularExpressions.Regex.Match(line,
                    @"^\s*\d+\s+(flood|reliquid)\s+(\S+)\s+\d+\s+(-?\d+) (-?\d+) -?\d+\s+(-?\d+) (-?\d+)");
                if (!m.Success)
                    continue;
                if (m.Groups[1].Value == "reliquid")
                {
                    if (m.Groups[2].Value == "REJECTED_UNPLAYABLE")
                        unplayable++;
                    continue;
                }
                var box = new[] { float.Parse(m.Groups[3].Value), float.Parse(m.Groups[4].Value),
                                  float.Parse(m.Groups[5].Value), float.Parse(m.Groups[6].Value) };
                var tex = offered.FirstOrDefault(o => o.box.Zip(box, (a, c) => Math.Abs(a - c) <= 1).All(x => x)).tex ?? "";
                if (m.Groups[2].Value != "ACCEPTED")
                {
                    // brief 14 F1: a pool of an asked kind the walk check refused - said with why
                    var kindName = tex.Contains("lava") ? "lava" : tex.Contains("slime") || tex.Contains("sewer") ? "slime" : "";
                    if (kindName.Length > 0)
                        refusedKinds.Add((kindName, m.Groups[2].Value));
                    continue;
                }
                if (tex.Contains("lava"))
                    lava++;
                else if (tex.Contains("slime") || tex.Contains("sewer"))
                    slime++;
                else
                    water++;
            }
            if (water + slime + lava > 0)
                b.AppendLine(ru ? $"Новые водоёмы: воды {water}, кислоты {slime}, лавы {lava}."
                                : $"New pools: water {water}, slime {slime}, lava {lava}.");
            // brief 14 F1 (the PO: «лавы не вижу, хотя задавал 100 %»): an asked hazard that came to nothing, and why
            foreach (var (kindName, askedPct, made, ruName, enName) in new[]
                     {
                         ("lava", g.Request.Options?.NewLava ?? -1, lava, "Лава", "Lava"),
                         ("slime", g.Request.Options?.NewSlime ?? -1, slime, "Кислота", "Slime"),
                     })
            {
                if (askedPct <= 0 || made > 0)
                    continue;
                var offeredOf = offered.Count(o => kindName == "lava" ? o.tex.Contains("lava") : o.tex.Contains("slime") || o.tex.Contains("sewer"));
                var why = refusedKinds.Where(x => x.kind == kindName).Select(x => x.verdict).ToList();
                string reason;
                var other = kindName == "lava" ? slime : lava;
                var otherAsked = kindName == "lava" ? g.Request.Options?.NewSlime ?? -1 : g.Request.Options?.NewLava ?? -1;
                if (offeredOf == 0 && other > 0 && otherAsked > askedPct)
                    // the PO's mg_1_6662 on 2.7: lava 100 took all three rooms and the description said slime had
                    // no room at all
                    reason = ru ? $"все подходящие комнаты взяла {(kindName == "lava" ? "кислота" : "лава")} — её доля больше ({otherAsked}% против {askedPct}%)"
                                : $"the {(kindName == "lava" ? "slime" : "lava")} took every room it could - its share is larger ({otherAsked}% against {askedPct}%)";
                else if (offeredOf == 0)
                    reason = ru ? "на этой основе не нашлось комнаты, где она не закрыла бы подъёмы и места появления игроков"
                                : "this base had no room where it would not cover the climbs and the players' starts";
                else if (why.Count > 0)
                    reason = ru ? $"предложена в {offeredOf} комн., отклонена проверкой хода: {string.Join(", ", why.Select(v => VerdictRu(v)).Distinct())}"
                                : $"offered in {offeredOf} room(s), refused by the walk check: {string.Join(", ", why.Distinct())}";
                else
                    reason = ru ? $"предложена в {offeredOf} комн., но до неё не дошли попытки" : $"offered in {offeredOf} room(s), never tried";
                b.AppendLine(ru ? $"{ruName} не легла: {reason}." : $"{enName} was not laid: {reason}.");
            }
            if (unplayable > 0 && !string.IsNullOrEmpty(g.Request.Options?.Liquids))
                b.AppendLine(ru ? "Часть водоёмов основы осталась прежней: через них проходит путь назад, другая жидкость отрезала бы его."
                                : "Some of the base's pools stayed as they were: the way back runs through them, another liquid would cut it.");
        }
        // brief 11: the stairways asked and the places the map had for them; brief 14 F2: what STANDS in the finished
        // map (the gate's «built», asked again after the ruin), not what the ledger accepted - the PO's mg_1_6662 was
        // told «6 из 10» while 2 stood
        var asked = g.Request.Options?.Stairways ?? 0;
        if (asked > 0)
        {
            var stairs = File.Exists(gates) ? StairGate.Matches(File.ReadAllText(gates)) : null;
            if (stairs is { Count: > 0 })
            {
                int N(Match m, int k) => int.Parse(m.Groups[k].Value, CultureInfo.InvariantCulture);
                var first = stairs[0];
                var last = stairs[stairs.Count - 1];
                var placed = N(first, 1);
                var accepted = N(first, 2);
                var standing = N(last, 3);
                var ruined = Math.Max(0, N(first, 3) - standing);
                var parts = new List<string>();
                if (placed < asked)
                    parts.Add(ru ? $"мест на этой основе нашлось {placed}" : $"this base had places for {placed}");
                if (accepted < placed)
                    parts.Add(ru ? $"{placed - accepted} отклонены проверкой хода (перекрыли бы путь или подъём)"
                                 : $"{placed - accepted} refused by the walk check (they would block a way or a climb)");
                if (N(first, 3) < accepted)
                    parts.Add(ru ? $"{accepted - N(first, 3)} не построились" : $"{accepted - N(first, 3)} did not build");
                if (ruined > 0)
                    parts.Add(ru ? $"{ruined} разрушены разрушениями" : $"{ruined} broken by the destruction");
                b.AppendLine((ru ? $"Площадок с лестницами стоит {standing} из {asked}" : $"Platforms with stairs standing: {standing} of {asked}")
                             + (parts.Count > 0 ? ": " + string.Join(", ", parts) + "." : "."));
            }
            else if (families.GetValueOrDefault("stairway") < asked)
                b.AppendLine(ru ? $"Площадок с лестницами {families.GetValueOrDefault("stairway")} из {asked}: больше подходящих мест на этой основе не нашлось."
                                : $"Platforms with stairs {families.GetValueOrDefault("stairway")} of {asked}: this base had no more places for them.");
        }
        // brief 11 D2: what was destroyed, by kind, and that passage is not guaranteed
        var ruin = Path.Combine(g.RunDir, "candidate.destroyed.json");
        if ((g.Request.Options?.Destruction ?? 0) > 0 && File.Exists(ruin))
        {
            var j = System.Text.Json.JsonDocument.Parse(File.ReadAllText(ruin)).RootElement;
            int N(string k) => j.TryGetProperty(k, out var v) && int.TryParse(v.GetString(), out var n) ? n : 0;
            var parts = new List<string>();
            void P(int n, string r1, string r2, string r5, string en)
            {
                if (n > 0)
                    parts.Add(ru ? $"{RuForm(n, r1, r2, r5)} {n}" : $"{en} {n}");
            }
            P(N("cracks"), "трещина", "трещины", "трещин", "cracked faces");
            P(N("rubble"), "куча обломков", "кучи обломков", "куч обломков", "rubble piles");
            P(N("craters"), "воронка", "воронки", "воронок", "craters");
            P(N("breaches"), "пролом", "пролома", "проломов", "breaches");
            P(N("gouges"), "выбоина в стене", "выбоины в стенах", "выбоин в стенах", "gouges");
            P(N("broken"), "отбитый край", "отбитых края", "отбитых краёв", "broken edges");
            P(N("collapses"), "обвал потолка", "обвала потолка", "обвалов потолка", "fallen ceilings");
            P(N("ruins"), "завал", "завала", "завалов", "blocked or sunken places");
            var pctAsked = g.Request.Options!.Destruction;
            var factor = pctAsked > 100 ? $" (×{pctAsked / 100.0:0.#})" : "";
            b.AppendLine(ru ? $"Разрушения {pctAsked}%{factor}: {string.Join(", ", parts)}; проходимость не гарантируется, точки появления свободны."
                            : $"Destruction {pctAsked}%{factor}: {string.Join(", ", parts)}; passage is not guaranteed, the starts are free.");
            // the PO, 07.10: «главное, чтобы пользователь по итогу получал такую информацию» - the 3D ruin asked and built
            var built3d = N("rubble") + N("craters") + N("breaches") + N("gouges") + N("broken") + N("collapses") + N("ruins");
            if (N("wanted_total") > 0)
                b.AppendLine(ru ? $"Объёмных разрушений (обломки, воронки, проломы, выбоины, отбитые края, обвалы, завалы) заказано {N("wanted_total")}, построено {built3d}."
                                : $"3D ruin (debris, craters, breaches, gouges, broken edges, falls, blockages): {N("wanted_total")} asked, {built3d} built.");
            // the PO, 07.10 (up to 1000 %): what the map's format could not hold, and a ruin the compiler refused, said
            if (N("budget") > 0)
                b.AppendLine(ru ? $"Ещё {N("budget")} разрушений не поместилось: карта упёрлась в предел формата Quake 2 по числу граней и блоков (на маленькой карте места больше, на большой — меньше)."
                                : $"{N("budget")} more pieces of the ruin did not fit: the map reached the Quake 2 format's limit on brush sides and brushes (a small map has more room, a large one less).");
            if (j.TryGetProperty("left_out", out var lo) && lo.GetString() is { Length: > 0 } leftOut)
                b.AppendLine(ru ? $"Карта с полными разрушениями не собралась — собрана без части их ({(leftOut.Contains("carving") ? "без воронок, проломов, отбитых краёв, обвалов и завалов" : leftOut.Contains("cracks") ? "оставлены только трещины" : leftOut)})."
                                : $"The map with the whole ruin did not compile - it was built with part of it ({leftOut}).");
        }
        if (g.Gates.Count > 0)
            b.AppendLine(ru ? $"Проверки карты: пройдено {g.Gates.Count(x => x.pass)} из {g.Gates.Count}."
                            : $"The map's checks: {g.Gates.Count(x => x.pass)} of {g.Gates.Count} passed.");
        return b.ToString();
    }

    /// <summary>
    /// Brief 15 D3: the plan's own account (job/plan_said.txt, its first round) against what the ledger accepted, for
    /// the families the PO orders by count: «сделано N из M: почему».
    /// </summary>
    private static List<string> AskedAndMade(Generation g, Dictionary<string, int> families, Dictionary<string, int> shapes,
                                             bool ru)
    {
        var path = Path.Combine(g.JobDir, "plan_said.txt");
        if (!File.Exists(path))
            path = Path.Combine(g.RunDir, "plan_said.txt");
        return File.Exists(path) ? AskedAndMadeFrom(path, families, shapes, ru) : new List<string>();
    }

    /// <summary>The same from a plan_said.txt by its path - the self-test asks it of the PO's options' real account.</summary>
    public static List<string> AskedAndMadeFrom(string path, Dictionary<string, int> families, Dictionary<string, int> shapes,
                                                bool ru)
    {
        var said = new List<string>();
        var lines = new List<string>();
        var rounds = 0;
        foreach (var l in File.ReadAllLines(path))
        {
            if (l.StartsWith("# round"))
            {
                if (++rounds > 1)
                    break;
                continue;
            }
            lines.Add(l);
        }
        Match? M(string pattern) => lines.Select(l => Regex.Match(l, pattern)).FirstOrDefault(m => m.Success);
        int N(Match m, int k) => int.Parse(m.Groups[k].Value, CultureInfo.InvariantCulture);
        void Say(string ruName, string enName, int made, int dealt, int wanted, string? ruWhy, string? enWhy)
        {
            if (wanted <= 0)
                return;
            var parts = new List<string>();
            if (dealt < wanted && ruWhy != null)
                parts.Add(ru ? $"в плане {dealt} — {ruWhy}" : $"{dealt} in the plan - {enWhy}");
            if (made < Math.Min(dealt, wanted))
                parts.Add(ru ? $"{Math.Min(dealt, wanted) - made} не прошли проверки карты (перекрыли бы путь, отрезали бы часть карты или не собрались)"
                             : $"{Math.Min(dealt, wanted) - made} did not pass the map's checks (they would block a way, cut part of the map off, or did not build)");
            said.Add((ru ? $"{ruName}: сделано {made} из {wanted}" : $"{enName}: {made} made of {wanted}")
                     + (parts.Count > 0 ? "; " + string.Join("; ", parts) + "." : "."));
        }
        if (M(@"^dig annexes: (\d+) dealt of (\d+) wanted; (\d+) sites proved, (\d+) meet a dig, (\d+) would wall somebody in, (\d+) without a pickup(?:.*?(\d+) hold ammunition)?(?:.*?(\d+) smaller)?") is { } an)
            Say("Пристройки", "Annexes", shapes.GetValueOrDefault("annex"), N(an, 1), N(an, 2),
                $"мест в скале проверено {N(an, 3)}, из них {N(an, 4)} задевают другие новые проходы, {N(an, 6)} без предмета, ради которого стоит туда идти"
                + (an.Groups[7].Success && N(an, 7) > 0 ? $"; {N(an, 7)} держат патроны или аптечку — оружия и брони на всех не хватило" : "")
                + (an.Groups[8].Success && N(an, 8) > 0 ? $"; {N(an, 8)} поменьше (256–384) — для заказанного размера места больше не нашлось" : ""),
                $"{N(an, 3)} rock sites checked, {N(an, 4)} meet other new passages, {N(an, 6)} with no pickup worth the walk"
                + (an.Groups[7].Success && N(an, 7) > 0 ? $"; {N(an, 7)} hold ammunition or health - weapons and armour ran out" : "")
                + (an.Groups[8].Success && N(an, 8) > 0 ? $"; {N(an, 8)} smaller (256-384) - the asked size had no more room" : ""));
        if (M(@"^dig storeys dealt: (\d+) of (\d+) wanted; (\d+) pairs qualify") is { } st)
            Say("Комнаты в два этажа", "Two-storey rooms", shapes.GetValueOrDefault("storeys"), N(st, 1), N(st, 2),
                $"на основе нашлось {N(st, 3)} подходящих пар мест (нужны два прохода на разной высоте 96–256 у одной стены)",
                $"the base had {N(st, 3)} fitting pairs of places (two ways at heights 96-256 apart by one wall)");
        if (M(@"^spans: (\d+) dealt of (\d+) wanted") is { } sp)
        {
            var spr = M(@"^spans refused: (\d+) too narrow for the deck, (\d+) floors at two heights, (\d+) an entity near");
            Say("Мосты над ареной", "Bridges over the arena", families.GetValueOrDefault("span"), N(sp, 1), N(sp, 2),
                spr != null ? $"у {N(spr, 1)} пролётов нет пола под краями или настил не помещается, у {N(spr, 2)} края на разной высоте, у {N(spr, 3)} рядом предмет или точка появления"
                            : "подходящих пролётов на основе нет",
                spr != null ? $"{N(spr, 1)} gaps have no floor under their ends or no room for the deck, {N(spr, 2)} have ends at two heights, {N(spr, 3)} a pickup or a spawn near"
                            : "the base has no fitting gaps");
        }
        if (M(@"^remodels: (\d+) dealt of (\d+) wanted") is { } rm)
        {
            var rr = M(@"^remodels refused: (\d+) sites of (\d+) walls");
            Say("Перестройка основы", "Remodels of the base", families.GetValueOrDefault("remodel"), N(rm, 1), N(rm, 2),
                rr != null ? $"у стен основы нашлось {N(rr, 1)} мест из {N(rr, 2)} стен — у остальных рядом предметы, точки появления, светильники или нет ровного пола перед стеной"
                           : "мест у стен больше нет",
                rr != null ? $"the base's walls gave {N(rr, 1)} places of {N(rr, 2)} walls - the rest have pickups, spawns, lamps near or no flat floor before them"
                           : "no more places by the walls");
        }
        if (M(@"^blocks: (\d+) dealt of (\d+) wanted") is { } bl)
        {
            var br = M(@"^blocks refused: (\d+) places of (\d+) looked at");
            Say("Блоки в комнатах", "Blocks in the rooms", families.GetValueOrDefault("block"), N(bl, 1), N(bl, 2),
                br != null ? $"ровных свободных мест нашлось {N(br, 1)}" : "мест больше нет",
                br != null ? $"{N(br, 1)} flat open places found" : "no more places");
        }
        if (M(@"^floor-shifts: (\d+) dealt of (\d+) wanted") is { } fl)
        {
            var fr = M(@"^floor-shifts refused: (\d+) places of (\d+) looked at.*?(\d+) a room under the floor");
            Say("Пол: помосты и каналы", "Floor: daises and channels", families.GetValueOrDefault("floor-shift"), N(fl, 1), N(fl, 2),
                fr != null ? $"ровного открытого пола нужного размера нашлось {N(fr, 1)} мест; канал не копается там, где под полом другое помещение ({N(fr, 3)} раз)"
                           : "ровного пола нужного размера больше нет",
                fr != null ? $"{N(fr, 1)} places of flat open floor of the size; a channel is not dug over another room ({N(fr, 3)} times)"
                           : "no more flat floor of the size");
        }
        if (M(@"^stair-reshapes: (\d+) dealt of (\d+) wanted .*? of the base's (\d+) stairs; refused: (\d+) rise not [\d.]+, (\d+) no open floor in front, (\d+) a pickup, start or trigger near, (\d+) another edit") is { } sr)
            Say("Переделка лестниц основы", "Stairs of the base rebuilt", families.GetValueOrDefault("stair-reshape"), N(sr, 1), N(sr, 2),
                $"лестниц у основы {N(sr, 3)}; перед {N(sr, 5)} нет свободного ровного пола для новых ступеней, у {N(sr, 6)} рядом предмет или точка появления, {N(sr, 7)} заняты другими правками, у {N(sr, 4)} неподходящая высота",
                $"the base has {N(sr, 3)} stairs; {N(sr, 5)} have no open flat floor in front for new steps, {N(sr, 6)} a pickup or spawn near, {N(sr, 7)} taken by other edits, {N(sr, 4)} an unfitting rise");
        if (M(@"^reshaping families dropped at the plan.*?widen (\d+) of (\d+).*?reshape (\d+) of (\d+).*?turn (\d+) of (\d+)") is { } dr
            && N(dr, 1) + N(dr, 3) + N(dr, 5) > 0)
            said.Add(ru ? $"Не предлагались, потому что на этой основе их не построить: расширений проходов {N(dr, 1)} из {N(dr, 2)}, перестроек помещений {N(dr, 3)} из {N(dr, 4)}, поворотов участков {N(dr, 5)} из {N(dr, 6)} (стены основы сложены из нескольких частей, и одну нельзя сдвинуть без другой)."
                        : $"Not offered, since they cannot be built on this base: widened passages {N(dr, 1)} of {N(dr, 2)}, reshaped rooms {N(dr, 3)} of {N(dr, 4)}, turned sections {N(dr, 5)} of {N(dr, 6)} (the base's walls are built of several pieces, one cannot move without another).");
        return said;
    }

    private static string EndedIn(string by, bool ru) => by switch
    {
        "budget" => ru ? "Правки закончились: исчерпано отведённое число пробных сборок." : "The edits ended: the trial builds allowed were spent.",
        "schedule" => ru ? "Правки закончились: план правок исчерпан — все предложенные правки испробованы, новых основа не дала." : "The edits ended: the plan ran out - every edit offered was tried and the base offered no new ones.",
        _ => ru ? "Правки закончились: отличие от основы достигнуто." : "The edits ended: the difference from the base was reached.",
    };

    /// <summary>The Russian form for a number: 1, 21 -> one; 2-4, 22-24 -> few; 0, 5-20, 25 -> many.</summary>
    public static string RuForm(int n, string one, string few, string many)
    {
        var tens = n % 100;
        var units = n % 10;
        return tens is >= 11 and <= 14 ? many : units == 1 ? one : units is >= 2 and <= 4 ? few : many;
    }

    private static int Pct(int permille) => (permille + 5) / 10;

    private static string Duration(TimeSpan t, bool ru) =>
        t.TotalHours >= 1 ? (ru ? $"{(int)t.TotalHours} ч {t.Minutes} мин" : $"{(int)t.TotalHours} h {t.Minutes} min")
                          : (ru ? $"{Math.Max(1, (int)t.TotalMinutes)} мин" : $"{Math.Max(1, (int)t.TotalMinutes)} min");

    private static string Pickup(string cls, bool ru) => cls switch
    {
        "weapon_rocketlauncher" => ru ? "ракетница" : "rocket launcher",
        "weapon_hyperblaster" => ru ? "гипербластер" : "hyperblaster",
        "weapon_railgun" => ru ? "рельсотрон" : "railgun",
        "weapon_grenadelauncher" => ru ? "гранатомёт" : "grenade launcher",
        "weapon_chaingun" => ru ? "пулемёт" : "chaingun",
        "weapon_machinegun" => ru ? "автомат" : "machinegun",
        "weapon_supershotgun" => ru ? "двустволка" : "super shotgun",
        "weapon_shotgun" => ru ? "дробовик" : "shotgun",
        "weapon_bfg" => "BFG",
        "item_armor_body" => ru ? "красная броня" : "body armour",
        "item_armor_combat" => ru ? "жёлтая броня" : "combat armour",
        "item_armor_jacket" => ru ? "куртка-броня" : "jacket armour",
        "item_health_mega" => ru ? "мегаздоровье" : "megahealth",
        "item_quad" => ru ? "квад" : "quad damage",
        "item_invulnerability" => ru ? "неуязвимость" : "invulnerability",
        "item_power_shield" => ru ? "силовой щит" : "power shield",
        "item_pack" => ru ? "рюкзак" : "ammo pack",
        "item_bandolier" => ru ? "патронташ" : "bandolier",
        "item_adrenaline" => ru ? "адреналин" : "adrenaline",
        _ => cls,
    };
}
