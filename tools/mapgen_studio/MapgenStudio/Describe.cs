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
        if (g.Target > 0)
            b.AppendLine(g.Divergence >= g.Target
                ? (ru ? $"Отличие от основы: просили {Pct(g.Target)}%, получилось {Pct(g.Divergence)}%."
                      : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached.")
                : (ru ? $"Отличие от основы: просили {Pct(g.Target)}%, получилось {Pct(g.Divergence)}% — больше на этой основе за отведённое число попыток не вышло."
                      : $"Difference from the base: {Pct(g.Target)}% asked, {Pct(g.Divergence)}% reached - all this base allowed within the attempts given."));
        // row 410: the generator says «-» when nothing ended the edits early - «[ended.-]» went into the description
        if (Loc.Has($"ended.{g.EndedBy}"))
            b.AppendLine(Loc.Language == lang ? Loc.T($"ended.{g.EndedBy}") : EndedIn(g.EndedBy, ru));
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
        Add(families.GetValueOrDefault("swap-item"), "перестановка предметов", "перестановки предметов", "перестановок предметов", "pickup swap(s)");
        Add(families.GetValueOrDefault("move-spawn"), "перенесённая точка появления", "перенесённые точки появления", "перенесённых точек появления", "moved spawn point(s)");
        b.AppendLine();
        b.AppendLine(ru ? "Что нового:" : "What is new:");
        b.AppendLine(news.Count > 0 ? "  " + string.Join(ru ? ";\n  " : ";\n  ", news) + "."
                                    : ru ? "  ничего — карта совпадает с основой." : "  nothing - the map is the base.");
        if (pickups.Count > 0)
            b.AppendLine(ru ? $"В новых комнатах: {string.Join(", ", pickups)}." : $"In the new rooms: {string.Join(", ", pickups)}.");
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
                if (offeredOf == 0)
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
            b.AppendLine(ru ? $"Разрушения {g.Request.Options!.Destruction}%: {string.Join(", ", parts)}; проходимость не гарантируется, точки появления свободны."
                            : $"Destruction {g.Request.Options!.Destruction}%: {string.Join(", ", parts)}; passage is not guaranteed, the starts are free.");
        }
        if (g.Gates.Count > 0)
            b.AppendLine(ru ? $"Проверки карты: пройдено {g.Gates.Count(x => x.pass)} из {g.Gates.Count}."
                            : $"The map's checks: {g.Gates.Count(x => x.pass)} of {g.Gates.Count} passed.");
        return b.ToString();
    }

    private static string EndedIn(string by, bool ru) => by switch
    {
        "budget" => ru ? "Правки закончились: исчерпано отведённое число пробных сборок." : "The edits ended: the trial builds allowed were spent.",
        "schedule" => ru ? "Правки закончились: пройдены все круги плана правок." : "The edits ended: every round of the plan was gone through.",
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
