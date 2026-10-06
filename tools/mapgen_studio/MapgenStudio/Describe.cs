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
        Add(families.GetValueOrDefault("stairway"), "лестница к новой площадке", "лестницы к новым площадкам", "лестниц к новым площадкам", "stairway(s) up to a new landing");
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
        // brief 11: the stairways asked and the places the map had for them
        var asked = g.Request.Options?.Stairways ?? 0;
        if (asked > 0 && families.GetValueOrDefault("stairway") < asked)
            b.AppendLine(ru ? $"Лестниц {families.GetValueOrDefault("stairway")} из {asked}: больше подходящих стен на этой основе не нашлось."
                            : $"Stairways {families.GetValueOrDefault("stairway")} of {asked}: this base had no more walls for them.");
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
