using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MapgenStudio;

/// <summary>
/// A preset of a form's parameters (brief 23 D2). `Kind` is the form: «scratch» (a new map from scratch) or «base» (a map
/// from a ready one). `Category` is a factory category's id («factory:duels») or the user's own words. `Body` holds the
/// form's values (Presets.BodyOf).
/// </summary>
public sealed record Preset(string Id, string Kind, string Name, string Category, JsonObject Body)
{
    public bool Factory => Id.StartsWith(Presets.FactoryPrefix, StringComparison.Ordinal);
}

/// <summary>
/// Brief 23 D2, the PO 06.11: «Давай сделаем пресеты для параметров генерации - как для форков, так и для новых карт.
/// Нужны default + несколько заводских … рядом с заводскими - пользовательские, неограниченно; сохранять, перезаписывать,
/// переименовывать, удалять». What a preset holds:
/// * scratch - every card of the form (ScratchParams) and «Быстрее ↔ Точнее»;
/// * base - the likeness, «Быстрее ↔ Точнее», the families, one map or several, every option of the cards.
/// Not the bases ticked, the variant's number, the map's name, the source and the covers (the «what», not the «how»).
/// The factory presets live here, their words in Loc; the user's in MapgenStudio.presets.json beside the settings (the
/// update replaces only the program's own files, so the file stays).
/// </summary>
public static class Presets
{
    public const string FactoryPrefix = "factory:";
    public const string Scratch = "scratch";
    public const string Base = "base";

    // ---- a form's body ------------------------------------------------------------------------------------------

    public static JsonObject BodyOf(Settings s, string kind) =>
        kind == Scratch ? ScratchBody(s.Scratch, s.Minutes, s.Options.Destruction)
                        : BaseBody(s.Fidelity, s.Minutes, s.SkipFamilies, s.GraftMode, s.Options);

    /// <summary>Brief 33 (the PO 08.11: presets carry every row of their page): the «Новая карта с нуля» page's rows -
    /// its parameters, the minutes and the ruin («Разрушения» is on this page too; 3.58's presets left it out).</summary>
    public static JsonObject ScratchBody(ScratchParams p, int minutes, int destruction = 0) => new()
    {
        ["scratch"] = JsonNode.Parse(p.Save()),
        ["minutes"] = minutes,
        ["destruction"] = destruction,
    };

    /// <summary>A scratch preset's ruin: 0 when it does not say (the factory's and 3.58's presets - no ruin).</summary>
    public static int DestructionOf(JsonObject body) => Int(body, "destruction", 0, 10000, 0);

    public static JsonObject BaseBody(int fidelity, int minutes, IEnumerable<string> skip, bool graft, GenerationOptions o) => new()
    {
        ["fidelity"] = fidelity,
        ["minutes"] = minutes,
        ["skip_families"] = new JsonArray(skip.Select(f => (JsonNode)f!).ToArray()),
        ["graft_mode"] = graft,
        ["options"] = JsonSerializer.SerializeToNode(o),
    };

    public static ScratchParams ScratchOf(JsonObject body) => ScratchParams.Load(body["scratch"]?.ToJsonString() ?? "{}");

    private static int Int(JsonObject body, string key, int lo, int hi, int fallback) =>
        body[key] is JsonValue v && v.TryGetValue<int>(out var n) ? Math.Clamp(n, lo, hi) : fallback;

    public static int MinutesOf(JsonObject body) => Int(body, "minutes", 0, Settings.MinuteSteps.Length - 1, 1);

    public static readonly GenerationOptions BaseOptions = new(WarpSize: 150, WarpShape: 50);

    public static GenerationOptions OptionsOf(JsonObject body)
    {
        try
        {
            return body["options"]?.Deserialize<GenerationOptions>() ?? BaseOptions;
        }
        catch (Exception e) when (e is JsonException or InvalidOperationException or NotSupportedException)
        {
            return BaseOptions;
        }
    }

    /// <summary>A preset's values into the settings: its form's fields only (the bases, the number, the name stay).</summary>
    public static void Apply(Settings s, string kind, JsonObject body)
    {
        s.Minutes = MinutesOf(body);
        if (kind == Scratch)
        {
            s.Scratch = ScratchOf(body);
            s.Options = s.Options with { Destruction = DestructionOf(body) };
            return;
        }
        s.Fidelity = Int(body, "fidelity", 1, 100, 20);
        s.SkipFamilies = (body["skip_families"] as JsonArray)?.Select(n => n is JsonValue v && v.TryGetValue<string>(out var f) ? f : "")
                                                                .Where(f => f.Length > 0).ToList() ?? new List<string>();
        s.GraftMode = body["graft_mode"] is JsonValue g && g.TryGetValue<bool>(out var gm) && gm;
        s.Options = OptionsOf(body);
    }

    /// <summary>
    /// What a body asks, in one string: two bodies the same when the runs they start are the same - a scratch body by its
    /// request to the generator (`ToPython`: what is not «По умолчанию», the language aside) with its likeness and
    /// minutes; a base body by its values. Keys sorted, lists of words sorted (ticked in another order is the same).
    /// </summary>
    public static string Canon(string kind, JsonObject body)
    {
        if (kind == Scratch)
        {
            var p = ScratchOf(body);
            var py = JsonNode.Parse(p.ToPython()) as JsonObject ?? new JsonObject();
            py.Remove("lang");
            return Sorted(py) + $"|dress={p.Fidelity}|min={MinutesOf(body)}|ruin={DestructionOf(body)}";
        }
        var o = JsonSerializer.SerializeToNode(OptionsOf(body));
        var skip = (body["skip_families"] as JsonArray)?.Select(n => n?.ToJsonString() ?? "").OrderBy(x => x, StringComparer.Ordinal) ?? Enumerable.Empty<string>();
        return $"fid={Int(body, "fidelity", 1, 100, 20)}|min={MinutesOf(body)}|skip={string.Join(",", skip)}"
               + $"|graft={body["graft_mode"] is JsonValue g && g.TryGetValue<bool>(out var gm) && gm}|{Sorted(o)}";
    }

    private static string Sorted(JsonNode? n) => n switch
    {
        JsonObject o => "{" + string.Join(",", o.OrderBy(kv => kv.Key, StringComparer.Ordinal).Select(kv => $"\"{kv.Key}\":{Sorted(kv.Value)}")) + "}",
        JsonArray a when a.All(x => x is JsonValue v && v.TryGetValue<string>(out _)) =>
            "[" + string.Join(",", a.Select(x => x!.ToJsonString()).OrderBy(x => x, StringComparer.Ordinal)) + "]",
        JsonArray a => "[" + string.Join(",", a.Select(Sorted)) + "]",
        null => "null",
        _ => n.ToJsonString(),
    };

    // ---- the factory's ------------------------------------------------------------------------------------------

    /// <summary>The factory categories of a form, in their order.</summary>
    public static string[] FactoryCategories(string kind) =>
        kind == Scratch
            ? new[] { "basic", "duels", "small", "ffa", "big", "tdm", "space", "tower", "worlds_duel", "worlds_ffa", "waters", "items",
                      "practice_a", "practice_b", "prizes_water", "prizes_nooks", "pieces_motion", "pieces_traps", "pieces_arch",
                      "pieces_mix", "pieces_machines", "moves", "mechanics", "look" }
            : new[] { "basic", "edits", "frame", "liquids", "ruins" };

    /// <summary>
    /// A factory category of a map from scratch that 3.50 split (brief 24 D5): «Миры» into the duels' and the
    /// free-for-all's. A user preset put into it in 3.48-3.49 goes with the duels' worlds (its category's words the same).
    /// </summary>
    public static string RetiredCategory(string kind, string category) =>
        kind == Scratch && category == FactoryPrefix + "worlds" ? FactoryPrefix + "worlds_duel" : category;

    private static ScratchParams Sp(Action<ScratchParams> set)
    {
        var p = new ScratchParams();
        set(p);
        return p;
    }

    /// <summary>
    /// The factory presets of a map from scratch - 160 in 13 categories (brief 24 D5, the PO 06.11: «нужно ещё раз в 10
    /// больше примеров заводских пресетов по новым картам, чтобы было из чего выбирать … только чётко проверь»). Written by
    /// tools/mapgen_scratch_presets_codegen.py from Fable's oracle table (each through make_plan on 12 seeds: 160 of 160);
    /// every value one of its row's choices (the self-test asks), each request the oracle's (the codegen's --compare on
    /// --presets-dump), each makes skeletons (tools/check_mapgen_presets.py).
    /// </summary>
    internal static (string key, string cat, ScratchParams p)[] ScratchFactory() => new[]
    {
    // <generated by tools/mapgen_scratch_presets_codegen.py - the table checked by Fable's oracle>
        ("default", "basic", Sp(_ => { })),
        ("players_3", "basic", Sp(p => { p.Players = 3; })),
        ("players_4", "basic", Sp(p => { p.Players = 4; })),
        ("players_6", "basic", Sp(p => { p.Players = 6; })),
        ("players_8", "basic", Sp(p => { p.Players = 8; })),
        ("players_10", "basic", Sp(p => { p.Players = 10; })),
        ("players_12", "basic", Sp(p => { p.Players = 12; })),
        ("players_16", "basic", Sp(p => { p.Players = 16; })),
        ("duel_vertical", "duels", Sp(p => { p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 3; p.Ramps = 2; p.Stairs = 8; p.ItemsAtHeight = 80; p.LongLines = 1; })),
        ("duel_sky_arena", "duels", Sp(p => { p.Shape = "arena"; p.SkyPercent = 70; p.CorridorPercent = 30; p.OpenPercent = 30; p.LongLines = 4; p.Sun = "yes"; })),
        ("duel_corridors", "duels", Sp(p => { p.CorridorPercent = 70; p.OpenPercent = 0; p.SizePercent = 80; p.Windows = 2; p.Doors = 2; p.Teleporters = 1; p.LongLines = 1; })),
        ("duel_powerups", "duels", Sp(p => { p.PowerupAccess = "hard"; p.Stack = "ra_mh_quad"; })),
        ("duel_tight", "duels", Sp(p => { p.SizePercent = 60; p.CorridorPercent = 60; p.OpenPercent = 0; p.LongLines = 0; p.Windows = 2; })),
        ("duel_big", "duels", Sp(p => { p.SizePercent = 150; p.LongLines = 3; p.Lifts = 3; p.Pads = 1; })),
        ("duel_flat", "duels", Sp(p => { p.Levels = 2; p.VerticalSpan = 128; p.Lifts = 0; p.Stairs = 2; p.Ramps = 2; })),
        ("duel_highrise", "duels", Sp(p => { p.Levels = 7; p.VerticalSpan = 1024; p.Lifts = 4; p.Stairs = 12; p.Drops = 6; p.ItemsAtHeight = 100; })),
        ("duel_ring", "duels", Sp(p => { p.Shape = "ring"; p.LongLines = 2; p.Pads = 1; })),
        ("duel_open", "duels", Sp(p => { p.Shape = "arena"; p.CorridorPercent = 20; p.OpenPercent = 40; p.LongLines = 4; p.PrizeAccess = "exposed"; })),
        ("duel_water", "duels", Sp(p => { p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; })),
        ("duel_lava", "duels", Sp(p => { p.LavaPercent = 10; p.Pits = 1; p.WaterPercent = 0; })),
        ("duel_ladders", "duels", Sp(p => { p.Ladders = 2; p.Lifts = 2; })),
        ("duel_teleports", "duels", Sp(p => { p.Teleporters = 2; p.LongLines = 1; })),
        ("duel_windows", "duels", Sp(p => { p.Windows = 12; p.LongLines = 3; })),
        ("duel_doors", "duels", Sp(p => { p.Doors = 6; p.CorridorPercent = 50; })),
        ("duel_rail", "duels", Sp(p => { p.LongLines = 6; p.OpenPercent = 30; p.SkyPercent = 50; })),
        ("duel_close", "duels", Sp(p => { p.LongLines = 0; p.CorridorPercent = 50; p.OpenPercent = 0; p.Doors = 2; })),
        ("duel_pads", "duels", Sp(p => { p.Pads = 3; p.Lifts = 1; })),
        ("duel_dark", "duels", Sp(p => { p.SkyPercent = 0; p.Sun = "no"; p.Tone = "cold"; })),
        ("ffa3_arena", "small", Sp(p => { p.Players = 3; p.Shape = "arena"; })),
        ("ffa4_arena", "small", Sp(p => { p.Players = 4; p.Shape = "arena"; })),
        ("ffa4_halves", "small", Sp(p => { p.Players = 4; p.Shape = "halves"; })),
        ("ffa4_ring", "small", Sp(p => { p.Players = 4; p.Shape = "ring"; })),
        ("ffa4_vertical", "small", Sp(p => { p.Players = 4; p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 3; p.Stairs = 8; p.ItemsAtHeight = 80; })),
        ("ffa4_corridors", "small", Sp(p => { p.Players = 4; p.CorridorPercent = 60; p.OpenPercent = 5; p.Doors = 3; p.LongLines = 1; })),
        ("ffa4_open", "small", Sp(p => { p.Players = 4; p.Shape = "arena"; p.CorridorPercent = 20; p.OpenPercent = 40; p.SkyPercent = 70; p.Sun = "yes"; p.LongLines = 5; p.PrizeAccess = "exposed"; })),
        ("ffa4_water", "small", Sp(p => { p.Players = 4; p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; })),
        ("ffa4_pads", "small", Sp(p => { p.Players = 4; p.Pads = 4; p.Teleporters = 2; })),
        ("ffa3_small", "small", Sp(p => { p.Players = 3; p.SizePercent = 80; p.LongLines = 2; })),
        ("ffa4_big", "small", Sp(p => { p.Players = 4; p.SizePercent = 150; p.Lifts = 4; p.Pads = 2; })),
        ("ffa4_powerups", "small", Sp(p => { p.Players = 4; p.Stack = "2ya_adren_quad"; p.PowerupAccess = "easy"; })),
        ("ffa_arena8", "ffa", Sp(p => { p.Players = 8; p.Shape = "arena"; p.SizePercent = 125; p.Pads = 3; p.Teleporters = 2; p.LongLines = 5; p.Stack = "2ya_adren_quad"; })),
        ("ffa_maze6", "ffa", Sp(p => { p.Players = 6; p.CorridorPercent = 60; p.OpenPercent = 5; p.Doors = 4; p.Teleporters = 3; p.Windows = 8; p.LongLines = 1; })),
        ("ffa_ring8", "ffa", Sp(p => { p.Players = 8; p.Shape = "ring"; p.Pads = 2; p.LongLines = 3; })),
        ("ffa6_arena", "ffa", Sp(p => { p.Players = 6; p.Shape = "arena"; })),
        ("ffa6_halves", "ffa", Sp(p => { p.Players = 6; p.Shape = "halves"; })),
        ("ffa6_vertical", "ffa", Sp(p => { p.Players = 6; p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 4; p.Stairs = 12; p.ItemsAtHeight = 80; })),
        ("ffa8_flat", "ffa", Sp(p => { p.Players = 8; p.Levels = 2; p.VerticalSpan = 128; p.Lifts = 0; p.Stairs = 2; p.Ramps = 4; })),
        ("ffa8_corridors", "ffa", Sp(p => { p.Players = 8; p.CorridorPercent = 70; p.OpenPercent = 0; p.Doors = 4; p.LongLines = 1; })),
        ("ffa8_sky", "ffa", Sp(p => { p.Players = 8; p.Shape = "arena"; p.SkyPercent = 100; p.Sun = "yes"; p.OpenPercent = 30; p.LongLines = 5; })),
        ("ffa8_water", "ffa", Sp(p => { p.Players = 8; p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; })),
        ("ffa8_lava", "ffa", Sp(p => { p.Players = 8; p.LavaPercent = 10; p.Pits = 2; p.WaterPercent = 0; })),
        ("ffa8_pads", "ffa", Sp(p => { p.Players = 8; p.Pads = 6; p.Teleporters = 1; })),
        ("ffa8_teleports", "ffa", Sp(p => { p.Players = 8; p.Teleporters = 4; p.LongLines = 2; })),
        ("ffa8_ladders", "ffa", Sp(p => { p.Players = 8; p.Ladders = 6; p.Drops = 6; })),
        ("ffa8_big", "ffa", Sp(p => { p.Players = 8; p.SizePercent = 150; p.Lifts = 4; p.Pads = 3; })),
        ("ffa8_small", "ffa", Sp(p => { p.Players = 8; p.SizePercent = 80; p.LongLines = 2; })),
        ("ffa6_rail", "ffa", Sp(p => { p.Players = 6; p.LongLines = 6; p.OpenPercent = 30; p.SkyPercent = 50; })),
        ("ffa8_ring_big", "ffa", Sp(p => { p.Players = 8; p.Shape = "ring"; p.SizePercent = 150; p.Pads = 3; })),
        ("ffa10_arena", "big", Sp(p => { p.Players = 10; p.Shape = "arena"; })),
        ("ffa10_ring", "big", Sp(p => { p.Players = 10; p.Shape = "ring"; p.Pads = 3; })),
        ("ffa_big12", "big", Sp(p => { p.Players = 12; p.SizePercent = 125; p.Pads = 4; p.Lifts = 4; })),
        ("ffa12_ring", "big", Sp(p => { p.Players = 12; p.Shape = "ring"; p.Pads = 4; p.Teleporters = 2; })),
        ("ffa12_corridors", "big", Sp(p => { p.Players = 12; p.CorridorPercent = 60; p.OpenPercent = 5; p.Doors = 6; p.LongLines = 2; })),
        ("ffa16_arena", "big", Sp(p => { p.Players = 16; p.Shape = "arena"; })),
        ("ffa16_huge", "big", Sp(p => { p.Players = 16; p.SizePercent = 200; p.Pads = 6; p.Lifts = 6; p.Teleporters = 4; })),
        ("ffa16_vertical", "big", Sp(p => { p.Players = 16; p.Levels = 7; p.VerticalSpan = 1024; p.Lifts = 8; p.Stairs = 16; })),
        ("ffa16_pads", "big", Sp(p => { p.Players = 16; p.Pads = 6; p.Teleporters = 4; p.LongLines = 6; })),
        ("ffa10_water", "big", Sp(p => { p.Players = 10; p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; })),
        ("tdm_2v2", "tdm", Sp(p => { p.Players = 4; p.Mode = "tdm"; })),
        ("tdm_3v3", "tdm", Sp(p => { p.Players = 6; p.Mode = "tdm"; p.Stack = "mh_adren_2ya"; })),
        ("tdm_4v4", "tdm", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Stack = "mh_adren_2ya"; })),
        ("tdm_5v5", "tdm", Sp(p => { p.Players = 10; p.Mode = "tdm"; p.Stack = "mh_adren_2ya"; })),
        ("tdm_6v6", "tdm", Sp(p => { p.Players = 12; p.Mode = "tdm"; p.Stack = "mh_adren_2ya"; p.SizePercent = 125; })),
        ("tdm_8v8", "tdm", Sp(p => { p.Players = 16; p.Mode = "tdm"; p.Stack = "mh_adren_2ya"; p.SizePercent = 150; })),
        ("tdm_4v4_ring", "tdm", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Shape = "ring"; })),
        ("tdm_4v4_vertical", "tdm", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 4; p.Stairs = 12; })),
        ("tdm_3v3_corridors", "tdm", Sp(p => { p.Players = 6; p.Mode = "tdm"; p.CorridorPercent = 60; p.OpenPercent = 5; p.Doors = 4; })),
        ("tdm_5v5_open", "tdm", Sp(p => { p.Players = 10; p.Mode = "tdm"; p.CorridorPercent = 20; p.OpenPercent = 40; p.SkyPercent = 70; p.Sun = "yes"; })),
        ("world_snow", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "snow"; p.SkyPercent = 50; p.Sun = "yes"; p.Tone = "cold"; p.Decor = "few"; p.Round = "some"; })),
        ("world_bunker", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "base"; p.WaterPercent = 30; p.Levels = 3; p.Decor = "many"; })),
        ("world_gothic", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "gothic"; p.Round = "many"; p.Levels = 5; p.Decor = "many"; p.Windows = 8; })),
        ("world_desert", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "desert"; p.SkyPercent = 70; p.Sun = "yes"; p.Tone = "warm"; p.Ramps = 4; })),
        ("world_tech", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "tech"; p.Lifts = 3; p.Doors = 2; p.Decor = "some"; })),
        ("world_industrial", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "industrial"; p.Ladders = 2; p.SlimePercent = 5; p.Decor = "some"; })),
        ("world_forest", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "forest"; p.SkyPercent = 70; p.Sun = "yes"; p.WaterPercent = 10; p.Round = "few"; })),
        ("world_city_duel", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "city"; p.SkyPercent = 100; p.Sun = "yes"; p.CorridorPercent = 20; p.OpenPercent = 40; })),
        ("world_planet_duel", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "planet"; p.SlimePercent = 10; p.Pads = 2; p.Teleporters = 1; })),
        ("world_fantasy_duel", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "fantasy"; p.Round = "some"; p.Stairs = 8; p.Levels = 5; })),
        ("world_hell_duel", "worlds_duel", Sp(p => { p.Style = "generated"; p.GenTheme = "hell"; p.LavaPercent = 10; p.Pits = 1; p.Tone = "warm"; p.Sun = "no"; p.WaterPercent = 0; })),
        ("world_hell", "worlds_ffa", Sp(p => { p.Players = 4; p.Style = "generated"; p.GenTheme = "hell"; p.LavaPercent = 15; p.Pits = 2; p.Tone = "warm"; p.Sun = "no"; p.WaterPercent = 0; })),
        ("world_city", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "city"; p.SkyPercent = 100; p.CorridorPercent = 20; p.OpenPercent = 40; p.Sun = "yes"; })),
        ("world_planet", "worlds_ffa", Sp(p => { p.Players = 4; p.Style = "generated"; p.GenTheme = "planet"; p.SlimePercent = 10; p.Pads = 3; p.Teleporters = 2; p.Ladders = 2; })),
        ("world_fantasy", "worlds_ffa", Sp(p => { p.Players = 4; p.Style = "generated"; p.GenTheme = "fantasy"; p.Round = "some"; p.Stairs = 12; p.Levels = 6; p.VerticalSpan = 768; })),
        ("world_snow8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "snow"; p.SkyPercent = 50; p.Sun = "yes"; p.Tone = "cold"; p.Round = "some"; })),
        ("world_bunker8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "base"; p.WaterPercent = 20; p.Levels = 3; p.Decor = "many"; })),
        ("world_gothic8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "gothic"; p.Round = "many"; p.Levels = 5; p.Windows = 8; })),
        ("world_desert8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "desert"; p.SkyPercent = 70; p.Sun = "yes"; p.Tone = "warm"; p.Ramps = 6; })),
        ("world_tech8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "tech"; p.Lifts = 4; p.Doors = 4; p.Decor = "some"; })),
        ("world_industrial8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "industrial"; p.Ladders = 4; p.SlimePercent = 10; })),
        ("world_forest8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "forest"; p.SkyPercent = 70; p.Sun = "yes"; p.WaterPercent = 10; p.Round = "few"; })),
        ("world_hell8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "hell"; p.LavaPercent = 15; p.Pits = 3; p.Tone = "warm"; p.Sun = "no"; p.WaterPercent = 0; })),
        ("world_planet8", "worlds_ffa", Sp(p => { p.Players = 8; p.Style = "generated"; p.GenTheme = "planet"; p.SlimePercent = 15; p.Pads = 4; p.Teleporters = 3; })),
        ("water_lake", "waters", Sp(p => { p.WaterPercent = 30; p.Levels = 3; p.Underwater = 2; })),
        ("water_canals", "waters", Sp(p => { p.WaterPercent = 20; p.CorridorPercent = 60; p.OpenPercent = 5; p.Underwater = 1; p.WaterBody = "levels"; })),
        ("water_flood", "waters", Sp(p => { p.Players = 4; p.WaterPercent = 30; p.WaterAboveFloor = true; })),
        ("lava_river", "waters", Sp(p => { p.LavaPercent = 20; p.WaterPercent = 0; p.Pits = 1; })),
        ("lava_pits", "waters", Sp(p => { p.Players = 4; p.LavaPercent = 10; p.Pits = 3; p.WaterPercent = 0; })),
        ("slime_sewer", "waters", Sp(p => { p.SlimePercent = 20; p.WaterPercent = 0; p.Style = "generated"; p.GenTheme = "base"; p.CorridorPercent = 60; })),
        ("slime_pits", "waters", Sp(p => { p.Players = 4; p.SlimePercent = 10; p.Pits = 2; p.WaterPercent = 0; })),
        ("three_liquids", "waters", Sp(p => { p.Players = 4; p.WaterPercent = 10; p.LavaPercent = 10; p.SlimePercent = 10; })),
        ("dry", "waters", Sp(p => { p.WaterPercent = 0; })),
        ("chasms", "waters", Sp(p => { p.Pits = 3; p.WaterPercent = 0; })),
        ("lava_arena8", "waters", Sp(p => { p.Players = 8; p.Shape = "arena"; p.LavaPercent = 15; p.Pits = 2; p.WaterPercent = 0; })),
        ("water_ffa8", "waters", Sp(p => { p.Players = 8; p.WaterPercent = 30; p.Levels = 3; p.Underwater = 2; p.WaterBody = "levels"; })),
        ("rockets_only", "items", Sp(p => { p.Weapons = new() { ["weapon_shotgun"] = 1, ["weapon_supershotgun"] = 0, ["weapon_machinegun"] = 0, ["weapon_chaingun"] = 0, ["weapon_grenadelauncher"] = 0, ["weapon_rocketlauncher"] = 2, ["weapon_hyperblaster"] = 0, ["weapon_railgun"] = 0, ["weapon_bfg"] = 0 }; })),
        ("rail_only", "items", Sp(p => { p.Weapons = new() { ["weapon_shotgun"] = 1, ["weapon_supershotgun"] = 0, ["weapon_machinegun"] = 0, ["weapon_chaingun"] = 0, ["weapon_grenadelauncher"] = 0, ["weapon_rocketlauncher"] = 0, ["weapon_hyperblaster"] = 0, ["weapon_railgun"] = 2, ["weapon_bfg"] = 0 }; p.LongLines = 5; })),
        ("shotguns", "items", Sp(p => { p.Weapons = new() { ["weapon_shotgun"] = 2, ["weapon_supershotgun"] = 3, ["weapon_machinegun"] = 0, ["weapon_chaingun"] = 0, ["weapon_grenadelauncher"] = 0, ["weapon_rocketlauncher"] = 0, ["weapon_hyperblaster"] = 0, ["weapon_railgun"] = 0, ["weapon_bfg"] = 0 }; })),
        ("chaingun_duel", "items", Sp(p => { p.Weapons = new() { ["weapon_shotgun"] = 1, ["weapon_supershotgun"] = 0, ["weapon_machinegun"] = 1, ["weapon_chaingun"] = 2, ["weapon_grenadelauncher"] = 0, ["weapon_rocketlauncher"] = 0, ["weapon_hyperblaster"] = 0, ["weapon_railgun"] = 0, ["weapon_bfg"] = 0 }; })),
        ("grenades", "items", Sp(p => { p.Weapons = new() { ["weapon_shotgun"] = 0, ["weapon_supershotgun"] = 0, ["weapon_machinegun"] = 0, ["weapon_chaingun"] = 0, ["weapon_grenadelauncher"] = 2, ["weapon_rocketlauncher"] = 1, ["weapon_hyperblaster"] = 0, ["weapon_railgun"] = 0, ["weapon_bfg"] = 0 }; })),
        ("hyper", "items", Sp(p => { p.Weapons = new() { ["weapon_shotgun"] = 0, ["weapon_supershotgun"] = 1, ["weapon_machinegun"] = 0, ["weapon_chaingun"] = 0, ["weapon_grenadelauncher"] = 0, ["weapon_rocketlauncher"] = 0, ["weapon_hyperblaster"] = 2, ["weapon_railgun"] = 0, ["weapon_bfg"] = 0 }; })),
        ("every_weapon_twice", "items", Sp(p => { p.Players = 4; p.Weapons = new() { ["weapon_shotgun"] = 2, ["weapon_supershotgun"] = 2, ["weapon_machinegun"] = 2, ["weapon_chaingun"] = 2, ["weapon_grenadelauncher"] = 2, ["weapon_rocketlauncher"] = 2, ["weapon_hyperblaster"] = 2, ["weapon_railgun"] = 2, ["weapon_bfg"] = 2 }; })),
        ("no_bfg_ffa8", "items", Sp(p => { p.Players = 8; p.Weapons = new() { ["weapon_shotgun"] = 1, ["weapon_supershotgun"] = 1, ["weapon_machinegun"] = 1, ["weapon_chaingun"] = 1, ["weapon_grenadelauncher"] = 1, ["weapon_rocketlauncher"] = 1, ["weapon_hyperblaster"] = 1, ["weapon_railgun"] = 1, ["weapon_bfg"] = 0 }; })),
        ("quad_arena8", "items", Sp(p => { p.Players = 8; p.Shape = "arena"; p.Stack = "2ya_adren_quad"; p.PowerupAccess = "easy"; })),
        ("hard_powerups8", "items", Sp(p => { p.Players = 8; p.Stack = "ra_mh_quad"; p.PowerupAccess = "hard"; p.PrizeAccess = "nooks"; })),
        ("invulnerability", "items", Sp(p => { p.Players = 4; p.Stack = "custom"; p.StackCounts = new() { ["item_invulnerability"] = 1, ["item_armor_body"] = 1, ["item_health_mega"] = 1 }; })),
        ("armour_only", "items", Sp(p => { p.Stack = "custom"; p.StackCounts = new() { ["item_armor_body"] = 1, ["item_armor_combat"] = 1, ["item_armor_jacket"] = 2 }; })),
        ("rich", "items", Sp(p => { p.HealthPerSpawn10 = 30; p.AmmoPerSpawn10 = 40; p.Shards = 12; })),
        ("scarce", "items", Sp(p => { p.HealthPerSpawn10 = 5; p.AmmoPerSpawn10 = 10; p.Shards = 0; })),
        ("items_high", "items", Sp(p => { p.ItemsAtHeight = 100; p.Levels = 5; })),
        ("items_low", "items", Sp(p => { p.ItemsAtHeight = 0; })),
        ("lifts8", "moves", Sp(p => { p.Players = 4; p.Lifts = 8; p.Stairs = 4; })),
        ("pads6", "moves", Sp(p => { p.Players = 4; p.Pads = 6; p.Lifts = 1; })),
        ("teleports4", "moves", Sp(p => { p.Players = 4; p.Teleporters = 4; p.Lifts = 1; })),
        ("ladders4", "moves", Sp(p => { p.Players = 4; p.Ladders = 4; p.Lifts = 2; p.Stairs = 4; })),
        ("drops12", "moves", Sp(p => { p.Players = 4; p.Drops = 12; p.Levels = 6; })),
        ("stairs24", "moves", Sp(p => { p.Players = 4; p.Stairs = 24; p.Lifts = 0; p.Levels = 6; })),
        ("ramps12", "moves", Sp(p => { p.Players = 4; p.Ramps = 12; p.Stairs = 0; p.Lifts = 0; })),
        ("doors8", "moves", Sp(p => { p.Players = 4; p.Doors = 8; p.CorridorPercent = 50; })),
        ("windows12", "moves", Sp(p => { p.Players = 4; p.Windows = 12; p.LongLines = 3; })),
        ("no_lifts", "moves", Sp(p => { p.Lifts = 0; p.Stairs = 16; p.Levels = 5; })),
        ("seven_levels", "moves", Sp(p => { p.Players = 4; p.Levels = 7; p.VerticalSpan = 1024; p.Lifts = 6; p.Stairs = 16; p.Drops = 8; })),
        ("two_levels", "moves", Sp(p => { p.Players = 4; p.Levels = 2; p.VerticalSpan = 128; p.Lifts = 0; p.Stairs = 2; })),
        ("mech_all", "mechanics", Sp(p => { p.Mechanics = new() { "clock", "halves", "key_gun_ledge", "asymmetry", "small_health", "spawn_pressure", "dead_end_stack", "three_approaches", "tele_mirror", "pad_pit", "lift_exposure", "ladder_item" }; })),
        ("mech_none", "mechanics", Sp(p => { p.Mechanics = new(); })),
        ("mech_classic", "mechanics", Sp(p => { p.Mechanics = new() { "clock", "halves", "key_gun_ledge" }; })),
        ("mech_pressure", "mechanics", Sp(p => { p.Mechanics = new() { "small_health", "spawn_pressure", "three_approaches", "asymmetry" }; })),
        ("mech_tricks", "mechanics", Sp(p => { p.Mechanics = new() { "tele_mirror", "pad_pit", "lift_exposure", "ladder_item", "dead_end_stack" }; p.Teleporters = 2; p.Pads = 2; p.Lifts = 2; p.Ladders = 2; })),
        ("mech_ffa_all", "mechanics", Sp(p => { p.Players = 8; p.Mechanics = new() { "clock", "halves", "key_gun_ledge", "asymmetry", "small_health", "spawn_pressure", "dead_end_stack", "three_approaches", "tele_mirror", "pad_pit", "lift_exposure", "ladder_item" }; p.Teleporters = 2; p.Pads = 2; p.Ladders = 2; })),
        ("decor_many", "look", Sp(p => { p.Decor = "many"; })),
        ("round_many", "look", Sp(p => { p.Round = "many"; })),
        ("round_apses", "look", Sp(p => { p.Round = "many"; p.RoundKinds = new() { "apses" }; })),
        ("round_podiums", "look", Sp(p => { p.Round = "some"; p.RoundKinds = new() { "podiums", "corners" }; })),
        ("sunlit", "look", Sp(p => { p.SkyPercent = 70; p.Sun = "yes"; })),
        ("cold_tech", "look", Sp(p => { p.Style = "generated"; p.GenTheme = "tech"; p.GenColour = "cold"; p.Tone = "cold"; })),
        ("rust_industrial", "look", Sp(p => { p.Style = "generated"; p.GenTheme = "industrial"; p.GenColour = "rust"; p.GenWear = "dirty"; })),
        ("green_bunker", "look", Sp(p => { p.Style = "generated"; p.GenTheme = "base"; p.GenColour = "green"; })),
        ("grey_gothic", "look", Sp(p => { p.Style = "generated"; p.GenTheme = "gothic"; p.GenColour = "grey"; p.GenRelief = "sharp"; })),
        ("clean_tech", "look", Sp(p => { p.Style = "generated"; p.GenTheme = "tech"; p.GenWear = "clean"; p.GenScale = "small"; })),
        ("large_blocks", "look", Sp(p => { p.Players = 4; p.Style = "generated"; p.GenTheme = "gothic"; p.GenScale = "large"; p.GenRelief = "soft"; })),
        ("walls_only", "look", Sp(p => { p.Style = "generated"; p.GenTheme = "city"; p.GenShare = "walls"; p.SkyPercent = 70; p.Sun = "yes"; })),
        ("space_duel", "space", Sp(p => { p.Shape = "space"; })),
        ("space_yard", "space", Sp(p => { p.Players = 4; p.Shape = "space"; p.Islands = 12; p.PadOnly = 3; p.HeightSpread = 1300; p.PadReach = "long"; p.Ships = 2; })),
        ("space_arena8", "space", Sp(p => { p.Players = 8; p.Shape = "space"; p.Islands = 12; p.PadOnly = 2; })),
        ("space_bridges", "space", Sp(p => { p.Players = 4; p.Shape = "space"; p.Bridges = "many"; p.PadReach = "short"; p.Islands = 8; })),
        ("space_rails", "space", Sp(p => { p.Shape = "space"; p.Edges = "railings"; })),
        ("space_low", "space", Sp(p => { p.Players = 4; p.Shape = "space"; p.HeightSpread = 400; })),
        ("space_high", "space", Sp(p => { p.Players = 4; p.Shape = "space"; p.HeightSpread = 1300; p.PadOnly = 4; p.PadReach = "long"; })),
        ("space_tele", "space", Sp(p => { p.Players = 8; p.Shape = "space"; p.Teleporters = 3; p.Islands = 12; })),
        ("space_small", "space", Sp(p => { p.Shape = "space"; p.Islands = 6; p.PadOnly = 1; })),
        ("space_quad_hunt", "space", Sp(p => { p.Players = 4; p.Shape = "space"; p.PadOnly = 3; p.Stack = "2ya_adren_quad"; })),
        ("space_planet", "space", Sp(p => { p.Players = 4; p.Shape = "space"; p.Style = "generated"; p.GenTheme = "planet"; p.Edges = "some"; })),
        ("space_tech", "space", Sp(p => { p.Shape = "space"; p.Style = "generated"; p.GenTheme = "tech"; p.Edges = "some"; p.Bridges = "many"; p.Ships = 3; })),
        ("space_industrial", "space", Sp(p => { p.Players = 8; p.Shape = "space"; p.Style = "generated"; p.GenTheme = "industrial"; p.Islands = 16; p.HeightSpread = 1000; })),
        ("tower_duel", "tower", Sp(p => { p.Shape = "tower"; })),
        ("tower_tight", "tower", Sp(p => { p.Shape = "tower"; p.StoreyHeight = 160; })),
        ("tower_2", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.Storeys = 2; })),
        ("tower_3", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; })),
        ("tower_roomy", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.StoreyHeight = 224; })),
        ("tower_atrium", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.Shafts = 1; p.Perches = 3; })),
        ("tower_quad", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.Perches = 3; p.Stack = "2ya_adren_quad"; })),
        ("tower_tech", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.Style = "generated"; p.GenTheme = "tech"; })),
        ("tower_8", "tower", Sp(p => { p.Players = 8; p.Shape = "tower"; p.Shafts = 3; })),
        ("tower_4", "tower", Sp(p => { p.Players = 8; p.Shape = "tower"; p.Storeys = 4; })),
        ("tower_16", "tower", Sp(p => { p.Players = 16; p.Shape = "tower"; p.Storeys = 4; p.Shafts = 3; })),
        ("tower_skyscraper", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.Storeys = 4; p.Lifts = 2; p.Pads = 1; })),
        ("tower_pads", "tower", Sp(p => { p.Players = 4; p.Shape = "tower"; p.Stairs = 0; p.Lifts = 0; p.Pads = 3; })),
        ("tower_stairs", "tower", Sp(p => { p.Shape = "tower"; p.Lifts = 0; p.Pads = 0; })),
        ("pr_q2dm_ffa6", "practice_a", Sp(p => { p.Players = 6; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_ffa8", "practice_a", Sp(p => { p.Players = 8; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_ring8", "practice_a", Sp(p => { p.Players = 8; p.Shape = "ring"; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_halves8", "practice_a", Sp(p => { p.Players = 8; p.Shape = "halves"; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_vertical6", "practice_a", Sp(p => { p.Players = 6; p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 3; p.Stairs = 8; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_water8", "practice_a", Sp(p => { p.Players = 8; p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; p.ItemPractice = "q2dm"; p.WaterBody = "levels"; })),
        ("pr_q2dm_lava6", "practice_a", Sp(p => { p.Players = 6; p.LavaPercent = 10; p.Pits = 1; p.WaterPercent = 0; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_tdm", "practice_a", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.ItemPractice = "q2dm"; })),
        ("pr_q2dm_wide8", "practice_a", Sp(p => { p.Players = 8; p.ItemSpacing = "wide"; p.ItemPractice = "q2dm"; })),
        ("pr_q2duel", "practice_a", Sp(p => { p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_vertical", "practice_a", Sp(p => { p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 3; p.Stairs = 8; p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_ring", "practice_a", Sp(p => { p.Shape = "ring"; p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_corridors", "practice_a", Sp(p => { p.CorridorPercent = 60; p.OpenPercent = 0; p.Doors = 2; p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_open", "practice_a", Sp(p => { p.Shape = "arena"; p.PrizeAccess = "exposed"; p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_water", "practice_a", Sp(p => { p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_wide", "practice_a", Sp(p => { p.ItemSpacing = "wide"; p.ItemPractice = "q2duel"; })),
        ("pr_q2duel_teleports", "practice_a", Sp(p => { p.Teleporters = 2; p.ItemPractice = "q2duel"; })),
        ("pr_q2rdm_ffa4", "practice_a", Sp(p => { p.Players = 4; p.ItemPractice = "q2rdm"; })),
        ("pr_q2rdm_ffa6", "practice_a", Sp(p => { p.Players = 6; p.ItemPractice = "q2rdm"; })),
        ("pr_q2rdm_ffa8", "practice_a", Sp(p => { p.Players = 8; p.ItemPractice = "q2rdm"; })),
        ("pr_q2rdm_halves6", "practice_a", Sp(p => { p.Players = 6; p.Shape = "halves"; p.ItemPractice = "q2rdm"; })),
        ("pr_q2rdm_pads6", "practice_a", Sp(p => { p.Players = 6; p.Pads = 4; p.ItemPractice = "q2rdm"; })),
        ("pr_q2rdm_vertical8", "practice_a", Sp(p => { p.Players = 8; p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 4; p.Stairs = 12; p.ItemPractice = "q2rdm"; })),
        ("pr_q2rdm_nooks4", "practice_a", Sp(p => { p.Players = 4; p.PrizeAccess = "nooks"; p.ItemPractice = "q2rdm"; })),
        ("pr_ztn2dm_ffa4", "practice_b", Sp(p => { p.Players = 4; p.ItemPractice = "ztn2dm"; })),
        ("pr_ztn2dm_ffa6", "practice_b", Sp(p => { p.Players = 6; p.ItemPractice = "ztn2dm"; })),
        ("pr_ztn2dm_ring6", "practice_b", Sp(p => { p.Players = 6; p.Shape = "ring"; p.ItemPractice = "ztn2dm"; })),
        ("pr_ztn2dm_drops4", "practice_b", Sp(p => { p.Players = 4; p.Drops = 8; p.Levels = 5; p.ItemPractice = "ztn2dm"; })),
        ("pr_ztn2dm_lifts6", "practice_b", Sp(p => { p.Players = 6; p.Lifts = 4; p.ItemPractice = "ztn2dm"; })),
        ("pr_ztn2dm_water4", "practice_b", Sp(p => { p.Players = 4; p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; p.ItemPractice = "ztn2dm"; })),
        ("pr_kold_duel", "practice_b", Sp(p => { p.ItemPractice = "koldduel1"; })),
        ("pr_kold_vertical", "practice_b", Sp(p => { p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 3; p.ItemPractice = "koldduel1"; })),
        ("pr_kold_lifts", "practice_b", Sp(p => { p.Lifts = 3; p.Ladders = 1; p.ItemPractice = "koldduel1"; })),
        ("pr_ptrip_duel", "practice_b", Sp(p => { p.ItemPractice = "ptrip"; })),
        ("pr_ptrip_small3", "practice_b", Sp(p => { p.Players = 3; p.SizePercent = 80; p.ItemPractice = "ptrip"; })),
        ("pr_match1_ffa4", "practice_b", Sp(p => { p.Players = 4; p.ItemPractice = "match1"; })),
        ("pr_match1_tele4", "practice_b", Sp(p => { p.Players = 4; p.Teleporters = 2; p.ItemPractice = "match1"; })),
        ("pr_omf_ffa4", "practice_b", Sp(p => { p.Players = 4; p.ItemPractice = "omf"; })),
        ("pr_omf_water6", "practice_b", Sp(p => { p.Players = 6; p.WaterPercent = 20; p.Levels = 3; p.Underwater = 1; p.ItemPractice = "omf"; })),
        ("pr_mix_duel_ztn", "practice_b", Sp(p => { p.ItemPractice = "q2duel+ztn2dm"; })),
        ("pr_mix_ffa8_dm_rdm", "practice_b", Sp(p => { p.Players = 8; p.ItemPractice = "q2dm+q2rdm"; })),
        ("pr_mix_duel_kold", "practice_b", Sp(p => { p.Levels = 5; p.Lifts = 3; p.ItemPractice = "q2duel+koldduel1"; })),
        ("pr_mix_ffa6_dm_ztn", "practice_b", Sp(p => { p.Players = 6; p.ItemPractice = "q2dm+ztn2dm"; })),
        ("pr_mix_ffa6_rdm_omf", "practice_b", Sp(p => { p.Players = 6; p.ItemPractice = "q2rdm+omf"; })),
        ("pr_mix_ffa3_ptrip_match", "practice_b", Sp(p => { p.Players = 3; p.ItemPractice = "ptrip+match1"; })),
        ("pr_mix_ffa4_dm_duel", "practice_b", Sp(p => { p.Players = 4; p.ItemPractice = "q2dm+q2duel"; })),
        ("pr_mix_ffa8_ring_ztn_rdm", "practice_b", Sp(p => { p.Players = 8; p.Shape = "ring"; p.ItemPractice = "ztn2dm+q2rdm"; })),
        ("pr_mix_duel_water", "practice_b", Sp(p => { p.WaterPercent = 20; p.Levels = 3; p.Underwater = 2; p.ItemPractice = "q2dm+q2duel"; })),
        ("pr_all_duel_wide", "practice_b", Sp(p => { p.ItemSpacing = "wide"; p.ItemPractice = "mix"; })),
        ("pr_all_ffa8_wide", "practice_b", Sp(p => { p.Players = 8; p.ItemSpacing = "wide"; p.ItemPractice = "mix"; })),
        ("pz_duel_nooks", "prizes_nooks", Sp(p => { p.PrizeAccess = "nooks"; })),
        ("pz_duel_nooks_hard", "prizes_nooks", Sp(p => { p.PrizeAccess = "nooks"; p.PowerupAccess = "hard"; })),
        ("pz_ffa4_nooks", "prizes_nooks", Sp(p => { p.Players = 4; p.PrizeAccess = "nooks"; })),
        ("pz_ffa8_nooks", "prizes_nooks", Sp(p => { p.Players = 8; p.PrizeAccess = "nooks"; })),
        ("pz_tdm_nooks", "prizes_nooks", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.PrizeAccess = "nooks"; })),
        ("pz_duel_dive1", "prizes_water", Sp(p => { p.Underwater = 1; })),
        ("pz_duel_dive2", "prizes_water", Sp(p => { p.Underwater = 2; })),
        ("pz_duel_dive3", "prizes_water", Sp(p => { p.Underwater = 3; })),
        ("pz_ffa4_dive1", "prizes_water", Sp(p => { p.Players = 4; p.Underwater = 1; })),
        ("pz_ffa4_dive2", "prizes_water", Sp(p => { p.Players = 4; p.Underwater = 2; })),
        ("pz_ffa6_dive2", "prizes_water", Sp(p => { p.Players = 6; p.Underwater = 2; })),
        ("pz_ffa8_dive2", "prizes_water", Sp(p => { p.Players = 8; p.Underwater = 2; })),
        ("pz_ffa8_dive3", "prizes_water", Sp(p => { p.Players = 8; p.Underwater = 3; })),
        ("pz_duel_water_all", "prizes_water", Sp(p => { p.PrizeAccess = "water"; })),
        ("pz_ffa4_water_all", "prizes_water", Sp(p => { p.Players = 4; p.PrizeAccess = "water"; })),
        ("pz_ffa8_water_all", "prizes_water", Sp(p => { p.Players = 8; p.PrizeAccess = "water"; })),
        ("pz_duel_lake_dive", "prizes_water", Sp(p => { p.WaterPercent = 30; p.Levels = 3; p.Underwater = 2; })),
        ("pz_ffa8_lake_dive", "prizes_water", Sp(p => { p.Players = 8; p.WaterPercent = 30; p.Levels = 3; p.Underwater = 2; p.WaterBody = "levels"; })),
        ("pz_duel_dive_vertical", "prizes_water", Sp(p => { p.Levels = 6; p.VerticalSpan = 768; p.Lifts = 3; p.Underwater = 1; })),
        ("pz_ffa6_dive_ring", "prizes_water", Sp(p => { p.Players = 6; p.Shape = "ring"; p.Underwater = 2; })),
        ("pz_ffa8_dive_halves", "prizes_water", Sp(p => { p.Players = 8; p.Shape = "halves"; p.Underwater = 2; })),
        ("pz_tdm_dive", "prizes_water", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Underwater = 2; })),
        ("pz_duel_dive_dark", "prizes_water", Sp(p => { p.SkyPercent = 0; p.Sun = "no"; p.Tone = "cold"; p.Underwater = 1; })),
        ("pz_duel_dive_wide", "prizes_water", Sp(p => { p.Underwater = 1; p.ItemSpacing = "wide"; })),
        ("pz_duel_exposed", "prizes_nooks", Sp(p => { p.PrizeAccess = "exposed"; })),
        ("pz_ffa4_exposed", "prizes_nooks", Sp(p => { p.Players = 4; p.PrizeAccess = "exposed"; })),
        ("pz_ffa8_exposed", "prizes_nooks", Sp(p => { p.Players = 8; p.PrizeAccess = "exposed"; })),
        ("pz_arena_exposed", "prizes_nooks", Sp(p => { p.Players = 4; p.Shape = "arena"; p.PrizeAccess = "exposed"; })),
        ("pz_duel_exposed_rail", "prizes_nooks", Sp(p => { p.PrizeAccess = "exposed"; p.LongLines = 5; p.OpenPercent = 30; })),
        ("pz_ffa8_exposed_sky", "prizes_nooks", Sp(p => { p.Players = 8; p.PrizeAccess = "exposed"; p.SkyPercent = 70; p.Sun = "yes"; })),
        ("pz_duel_wide", "prizes_nooks", Sp(p => { p.ItemSpacing = "wide"; })),
        ("pz_ffa4_wide", "prizes_nooks", Sp(p => { p.Players = 4; p.ItemSpacing = "wide"; })),
        ("pz_ffa8_wide", "prizes_nooks", Sp(p => { p.Players = 8; p.ItemSpacing = "wide"; })),
        ("pz_ffa16_wide", "prizes_nooks", Sp(p => { p.Players = 16; p.ItemSpacing = "wide"; })),
        ("pz_duel_people", "prizes_nooks", Sp(p => { p.PrizeAccess = "people"; })),
        ("pz_ffa8_people", "prizes_nooks", Sp(p => { p.Players = 8; p.PrizeAccess = "people"; })),
        ("pz_duel_nooks_wide", "prizes_nooks", Sp(p => { p.PrizeAccess = "nooks"; p.ItemSpacing = "wide"; })),
        ("pz_ffa8_nooks_wide", "prizes_nooks", Sp(p => { p.Players = 8; p.PrizeAccess = "nooks"; p.ItemSpacing = "wide"; })),
        ("pz_duel_nooks_quad", "prizes_nooks", Sp(p => { p.PrizeAccess = "nooks"; p.Stack = "ra_mh_quad"; })),
        ("pz_ffa8_nooks_quad", "prizes_nooks", Sp(p => { p.Players = 8; p.PrizeAccess = "nooks"; p.Stack = "ra_mh_quad"; })),
        ("pz_duel_dive_quad", "prizes_water", Sp(p => { p.Underwater = 2; p.Stack = "ra_mh_quad"; })),
        ("pz_ffa8_dive_quad", "prizes_water", Sp(p => { p.Players = 8; p.Underwater = 2; p.Stack = "ra_mh_quad"; })),
        ("pz_duel_dive_rail", "prizes_water", Sp(p => { p.Underwater = 1; p.LongLines = 4; })),
        ("pz_ffa6_exposed_tele", "prizes_nooks", Sp(p => { p.Players = 6; p.PrizeAccess = "exposed"; p.Teleporters = 2; })),
        ("pz_ffa4_dive_lifts", "prizes_water", Sp(p => { p.Players = 4; p.Underwater = 1; p.Lifts = 4; })),
        ("pz_duel_dive_mech", "prizes_water", Sp(p => { p.Underwater = 1; p.Mechanics = new() { "clock", "halves", "small_health", "spawn_pressure" }; })),
        ("pz_ffa10_dive2", "prizes_water", Sp(p => { p.Players = 10; p.Underwater = 2; })),
        ("pz_ffa12_nooks", "prizes_nooks", Sp(p => { p.Players = 12; p.PrizeAccess = "nooks"; })),
        ("pz_ffa12_dive3", "prizes_water", Sp(p => { p.Players = 12; p.Underwater = 3; })),
        ("pz_tdm_exposed", "prizes_nooks", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.PrizeAccess = "exposed"; })),
        ("pc_duel_trains", "pieces_motion", Sp(p => { p.Trains = 1; p.LavaPercent = 10; })),
        ("pc_duel_island", "pieces_motion", Sp(p => { p.Trains = 1; p.TrainPath = "island"; p.LavaPercent = 10; })),
        ("pc_ffa4_trains2", "pieces_motion", Sp(p => { p.Players = 4; p.Trains = 2; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_ffa6_loops", "pieces_motion", Sp(p => { p.Players = 6; p.Trains = 2; p.TrainPath = "loop"; p.SlimePercent = 10; })),
        ("pc_ffa8_trains3", "pieces_motion", Sp(p => { p.Players = 8; p.Trains = 3; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_duel_stones", "pieces_motion", Sp(p => { p.Stones = 1; p.LavaPercent = 10; })),
        ("pc_duel_stones_gaps", "pieces_motion", Sp(p => { p.Stones = 1; p.StoneShape = "gaps"; p.LavaPercent = 10; })),
        ("pc_ffa4_stones_zz", "pieces_motion", Sp(p => { p.Players = 4; p.Stones = 2; p.StoneShape = "zigzag"; p.SlimePercent = 10; })),
        ("pc_ffa6_stones_fast", "pieces_motion", Sp(p => { p.Players = 6; p.Stones = 2; p.LavaPercent = 10; p.PieceWait = 50; })),
        ("pc_duel_waves", "pieces_motion", Sp(p => { p.Waves = 1; p.LavaPercent = 10; })),
        ("pc_ffa6_waves2", "pieces_motion", Sp(p => { p.Players = 6; p.Waves = 2; p.LavaPercent = 10; })),
        ("pc_duel_current", "pieces_motion", Sp(p => { p.Currents = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_currents", "pieces_motion", Sp(p => { p.Players = 4; p.Currents = 2; p.SlimePercent = 10; })),
        ("pc_ffa4_turnbridge", "pieces_motion", Sp(p => { p.Players = 4; p.TurnBridges = 1; p.LavaPercent = 10; })),
        ("pc_ffa8_turnbridges", "pieces_motion", Sp(p => { p.Players = 8; p.TurnBridges = 1; p.LavaPercent = 15; })),
        ("pc_duel_drum", "pieces_motion", Sp(p => { p.Rotators = 1; p.RotatorKind = "drum"; p.LavaPercent = 10; })),
        ("pc_ffa6_drums", "pieces_motion", Sp(p => { p.Players = 6; p.Rotators = 2; p.RotatorKind = "drum"; p.LavaPercent = 10; })),
        ("pc_duel_ride_stones", "pieces_motion", Sp(p => { p.Trains = 1; p.Stones = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_ride_wave", "pieces_motion", Sp(p => { p.Players = 4; p.Trains = 1; p.Waves = 1; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_ffa6_slow", "pieces_motion", Sp(p => { p.Players = 6; p.Trains = 2; p.Stones = 1; p.LavaPercent = 10; p.PieceSpeed = 50; p.PieceWait = 200; })),
        ("pc_ffa8_fast", "pieces_motion", Sp(p => { p.Players = 8; p.Trains = 2; p.Waves = 1; p.Currents = 1; p.LavaPercent = 10; p.PieceSpeed = 200; p.PieceWait = 50; })),
        ("pc_ffa4_levels", "pieces_motion", Sp(p => { p.Players = 4; p.Trains = 1; p.Stones = 1; p.Levels = 4; p.LavaPercent = 10; })),
        ("pc_ffa6_sky", "pieces_motion", Sp(p => { p.Players = 6; p.Trains = 2; p.Waves = 1; p.SkyPercent = 70; p.LavaPercent = 10; })),
        ("pc_tdm_motion", "pieces_motion", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Trains = 2; p.Stones = 1; p.LavaPercent = 10; })),
        ("pc_ffa10_motion", "pieces_motion", Sp(p => { p.Players = 10; p.Trains = 2; p.Stones = 2; p.Waves = 1; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_duel_trap", "pieces_traps", Sp(p => { p.Traps = 1; })),
        ("pc_duel_trap_lava", "pieces_traps", Sp(p => { p.Traps = 1; p.TrapTrigger = "buttons"; p.TrapHazard = "lava"; })),
        ("pc_ffa4_trap_slime", "pieces_traps", Sp(p => { p.Players = 4; p.Traps = 1; p.TrapTrigger = "plate"; p.TrapHazard = "slime"; })),
        ("pc_ffa6_trap_crush", "pieces_traps", Sp(p => { p.Players = 6; p.Traps = 1; p.TrapTrigger = "item"; p.TrapHazard = "crusher"; })),
        ("pc_ffa8_traps2", "pieces_traps", Sp(p => { p.Players = 8; p.Traps = 2; })),
        ("pc_duel_trapdoor", "pieces_traps", Sp(p => { p.Trapdoors = 1; p.LavaPercent = 10; })),
        ("pc_ffa6_trapdoors", "pieces_traps", Sp(p => { p.Players = 6; p.Trapdoors = 2; p.LavaPercent = 10; })),
        ("pc_duel_lasers", "pieces_traps", Sp(p => { p.Lasers = 1; })),
        ("pc_ffa4_lasers2", "pieces_traps", Sp(p => { p.Players = 4; p.Lasers = 2; })),
        ("pc_ffa6_lasers_fast", "pieces_traps", Sp(p => { p.Players = 6; p.Lasers = 2; p.PieceWait = 50; })),
        ("pc_duel_pistons", "pieces_traps", Sp(p => { p.Pistons = 1; })),
        ("pc_ffa4_pistons", "pieces_traps", Sp(p => { p.Players = 4; p.Pistons = 2; p.PieceSpeed = 150; })),
        ("pc_duel_geyser", "pieces_traps", Sp(p => { p.Geysers = 1; })),
        ("pc_ffa6_geysers", "pieces_traps", Sp(p => { p.Players = 6; p.Geysers = 3; })),
        ("pc_ffa4_pendulum", "pieces_traps", Sp(p => { p.Players = 4; p.Pendulums = 1; p.BentBridges = 1; p.LavaPercent = 10; })),
        ("pc_ffa8_pendulums", "pieces_traps", Sp(p => { p.Players = 8; p.Pendulums = 2; p.LavaPercent = 10; })),
        ("pc_duel_trap_lasers", "pieces_traps", Sp(p => { p.Traps = 1; p.Lasers = 1; })),
        ("pc_ffa4_trap_geyser", "pieces_traps", Sp(p => { p.Players = 4; p.Traps = 1; p.Geysers = 2; p.TrapHazard = "lava"; })),
        ("pc_ffa6_lasers_pistons", "pieces_traps", Sp(p => { p.Players = 6; p.Lasers = 1; p.Pistons = 1; })),
        ("pc_ffa6_trapdoor_pend", "pieces_traps", Sp(p => { p.Players = 6; p.Trapdoors = 1; p.Pendulums = 1; p.LavaPercent = 10; })),
        ("pc_ffa8_all_traps", "pieces_traps", Sp(p => { p.Players = 8; p.Traps = 1; p.Trapdoors = 1; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; })),
        ("pc_tdm_traps", "pieces_traps", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Traps = 2; p.Lasers = 1; })),
        ("pc_ffa10_traps", "pieces_traps", Sp(p => { p.Players = 10; p.Traps = 2; p.Geysers = 2; p.Lasers = 1; })),
        ("pc_ffa4_slow_traps", "pieces_traps", Sp(p => { p.Players = 4; p.Traps = 1; p.Lasers = 1; p.PieceWait = 200; })),
        ("pc_ffa6_quick_traps", "pieces_traps", Sp(p => { p.Players = 6; p.Traps = 1; p.Pistons = 2; p.PieceSpeed = 200; p.PieceWait = 50; })),
        ("pc_duel_bent", "pieces_arch", Sp(p => { p.BentBridges = 1; p.LavaPercent = 10; })),
        ("pc_ffa6_bent2", "pieces_arch", Sp(p => { p.Players = 6; p.BentBridges = 2; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_duel_steps", "pieces_arch", Sp(p => { p.WallSteps = 1; })),
        ("pc_ffa6_steps", "pieces_arch", Sp(p => { p.Players = 6; p.WallSteps = 2; })),
        ("pc_duel_ladders", "pieces_arch", Sp(p => { p.PoolLadders = true; p.WaterPercent = 15; })),
        ("pc_ffa6_ladders", "pieces_arch", Sp(p => { p.Players = 6; p.PoolLadders = true; p.WaterPercent = 20; p.WaterBody = "levels"; })),
        ("pc_duel_shutters", "pieces_arch", Sp(p => { p.Shutters = 1; })),
        ("pc_ffa4_shutters", "pieces_arch", Sp(p => { p.Players = 4; p.Shutters = 2; })),
        ("pc_duel_pickup_wall", "pieces_arch", Sp(p => { p.PickupWalls = 1; })),
        ("pc_ffa6_pickup_walls", "pieces_arch", Sp(p => { p.Players = 6; p.PickupWalls = 2; })),
        ("pc_duel_flaps", "pieces_arch", Sp(p => { p.Rotators = 1; p.RotatorKind = "flap"; })),
        ("pc_ffa6_flaps", "pieces_arch", Sp(p => { p.Players = 6; p.Rotators = 2; p.RotatorKind = "flap"; })),
        ("pc_duel_fans", "pieces_arch", Sp(p => { p.Rotators = 1; p.RotatorKind = "fan"; })),
        ("pc_ffa4_fans", "pieces_arch", Sp(p => { p.Players = 4; p.Rotators = 2; p.RotatorKind = "fan"; })),
        ("pc_duel_bent_steps", "pieces_arch", Sp(p => { p.BentBridges = 1; p.WallSteps = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_shutter_wall", "pieces_arch", Sp(p => { p.Players = 4; p.Shutters = 1; p.PickupWalls = 1; })),
        ("pc_ffa6_pool_steps", "pieces_arch", Sp(p => { p.Players = 6; p.PoolLadders = true; p.WallSteps = 1; p.WaterPercent = 15; })),
        ("pc_ffa8_architecture", "pieces_arch", Sp(p => { p.Players = 8; p.BentBridges = 1; p.WallSteps = 2; p.Shutters = 1; p.PickupWalls = 1; p.LavaPercent = 10; })),
        ("pc_duel_halves_arch", "pieces_arch", Sp(p => { p.Shape = "halves"; p.Shutters = 1; p.WallSteps = 1; })),
        ("pc_ffa6_ring_arch", "pieces_arch", Sp(p => { p.Players = 6; p.Shape = "ring"; p.BentBridges = 1; p.PickupWalls = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_vertical_arch", "pieces_arch", Sp(p => { p.Players = 4; p.Levels = 4; p.WallSteps = 2; p.Rotators = 1; p.RotatorKind = "flap"; })),
        ("pc_ffa6_sky_arch", "pieces_arch", Sp(p => { p.Players = 6; p.SkyPercent = 70; p.BentBridges = 1; p.Shutters = 1; p.LavaPercent = 10; })),
        ("pc_tdm_arch", "pieces_arch", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Shutters = 2; p.WallSteps = 1; })),
        ("pc_ffa10_arch", "pieces_arch", Sp(p => { p.Players = 10; p.BentBridges = 2; p.WallSteps = 2; p.PickupWalls = 2; p.LavaPercent = 10; })),
        ("pc_ffa4_water_arch", "pieces_arch", Sp(p => { p.Players = 4; p.PoolLadders = true; p.WaterPercent = 20; p.Underwater = 1; p.Shutters = 1; })),
        ("pc_duel_showcase", "pieces_mix", Sp(p => { p.Trains = 1; p.Traps = 1; p.Geysers = 1; p.LavaPercent = 10; })),
        ("pc_duel_q2dm3_like", "pieces_mix", Sp(p => { p.Trains = 1; p.Traps = 1; p.SlimePercent = 10; p.LavaPercent = 5; })),
        ("pc_duel_q2dm6_like", "pieces_mix", Sp(p => { p.Stones = 1; p.Shutters = 1; p.PickupWalls = 1; p.Rotators = 1; p.RotatorKind = "drum"; p.LavaPercent = 10; })),
        ("pc_duel_q2dm4_like", "pieces_mix", Sp(p => { p.BentBridges = 1; p.PoolLadders = true; p.Rotators = 1; p.RotatorKind = "flap"; p.WaterPercent = 15; p.LavaPercent = 5; })),
        ("pc_ffa4_showcase", "pieces_mix", Sp(p => { p.Players = 4; p.Trains = 1; p.Traps = 1; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_lava_world", "pieces_mix", Sp(p => { p.Players = 4; p.Trains = 1; p.Stones = 1; p.Waves = 1; p.Trapdoors = 1; p.LavaPercent = 15; })),
        ("pc_ffa4_slime_world", "pieces_mix", Sp(p => { p.Players = 4; p.Trains = 1; p.Currents = 1; p.Traps = 1; p.TrapHazard = "slime"; p.SlimePercent = 15; })),
        ("pc_ffa6_showcase", "pieces_mix", Sp(p => { p.Players = 6; p.Trains = 1; p.Traps = 1; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; })),
        ("pc_ffa6_machines", "pieces_mix", Sp(p => { p.Players = 6; p.Rotators = 2; p.Lasers = 1; p.Shutters = 1; })),
        ("pc_ffa6_crossings", "pieces_mix", Sp(p => { p.Players = 6; p.Trains = 1; p.Stones = 1; p.TurnBridges = 1; p.Currents = 1; p.LavaPercent = 15; })),
        ("pc_ffa6_danger", "pieces_mix", Sp(p => { p.Players = 6; p.Traps = 1; p.Trapdoors = 1; p.Geysers = 2; p.LavaPercent = 10; })),
        ("pc_ffa8_showcase", "pieces_mix", Sp(p => { p.Players = 8; p.Trains = 2; p.Stones = 1; p.Traps = 1; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_ffa8_amusement", "pieces_mix", Sp(p => { p.Players = 8; p.Trains = 1; p.Waves = 1; p.Rotators = 1; p.RotatorKind = "drum"; p.LavaPercent = 15; })),
        ("pc_ffa8_fortress", "pieces_mix", Sp(p => { p.Players = 8; p.Traps = 2; p.Shutters = 2; p.Pistons = 1; p.PickupWalls = 1; })),
        ("pc_ffa8_lava_works", "pieces_mix", Sp(p => { p.Players = 8; p.Trains = 1; p.Stones = 1; p.Waves = 1; p.Currents = 1; p.Geysers = 2; p.LavaPercent = 15; })),
        ("pc_ffa10_showcase", "pieces_mix", Sp(p => { p.Players = 10; p.Trains = 2; p.Traps = 2; p.Stones = 1; p.Lasers = 1; p.Pendulums = 1; p.LavaPercent = 10; })),
        ("pc_ffa12_showcase", "pieces_mix", Sp(p => { p.Players = 12; p.Trains = 3; p.Traps = 2; p.Waves = 1; p.Geysers = 2; p.LavaPercent = 15; p.SlimePercent = 5; })),
        ("pc_tdm_showcase", "pieces_mix", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Trains = 2; p.Traps = 1; p.Shutters = 1; p.LavaPercent = 10; })),
        ("pc_duel_halves_mix", "pieces_mix", Sp(p => { p.Shape = "halves"; p.Trains = 1; p.Traps = 1; p.LavaPercent = 10; })),
        ("pc_ffa6_ring_mix", "pieces_mix", Sp(p => { p.Players = 6; p.Shape = "ring"; p.Stones = 1; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_vertical_mix", "pieces_mix", Sp(p => { p.Players = 4; p.Levels = 4; p.Trains = 1; p.WallSteps = 1; p.Pistons = 1; p.LavaPercent = 10; })),
        ("pc_ffa6_slow_mix", "pieces_mix", Sp(p => { p.Players = 6; p.Trains = 2; p.Traps = 1; p.Stones = 1; p.LavaPercent = 10; p.PieceSpeed = 50; p.PieceWait = 200; })),
        ("pc_ffa6_fast_mix", "pieces_mix", Sp(p => { p.Players = 6; p.Trains = 2; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; p.PieceSpeed = 200; p.PieceWait = 50; })),
        ("pc_ffa4_water_mix", "pieces_mix", Sp(p => { p.Players = 4; p.PoolLadders = true; p.WaterPercent = 20; p.WaterBody = "levels"; p.Traps = 1; p.Lasers = 1; })),
        ("pc_ffa8_everything", "pieces_mix", Sp(p => { p.Players = 8; p.Trains = 1; p.Stones = 1; p.Traps = 1; p.Rotators = 1; p.Shutters = 1; p.PickupWalls = 1; p.BentBridges = 1; p.WallSteps = 1; p.Lasers = 1; p.Geysers = 1; p.LavaPercent = 10; p.SlimePercent = 5; })),
        ("pc_duel_drill", "pieces_machines", Sp(p => { p.Drills = 1; })),
        ("pc_ffa4_drills2", "pieces_machines", Sp(p => { p.Players = 4; p.Drills = 2; })),
        ("pc_ffa6_drill_field", "pieces_machines", Sp(p => { p.Players = 6; p.Drills = 3; })),
        ("pc_duel_cogs", "pieces_machines", Sp(p => { p.Cogs = 1; })),
        ("pc_ffa6_workshop", "pieces_machines", Sp(p => { p.Players = 6; p.Cogs = 2; p.Drills = 1; })),
        ("pc_ffa8_factory", "pieces_machines", Sp(p => { p.Players = 8; p.Conveyors = 1; p.Cogs = 2; p.Drills = 1; p.Turrets = 1; })),
        ("pc_duel_conveyor", "pieces_machines", Sp(p => { p.Conveyors = 1; })),
        ("pc_ffa6_conveyors2", "pieces_machines", Sp(p => { p.Players = 6; p.Conveyors = 2; })),
        ("pc_ffa4_turrets", "pieces_machines", Sp(p => { p.Players = 4; p.Turrets = 1; })),
        ("pc_ffa6_turret_run", "pieces_machines", Sp(p => { p.Players = 6; p.Turrets = 2; p.Lasers = 1; })),
        ("pc_duel_sickle", "pieces_machines", Sp(p => { p.Pendulums = 1; p.PendulumKind = "sickle"; p.BentBridges = 1; p.LavaPercent = 10; })),
        ("pc_ffa4_hammers", "pieces_machines", Sp(p => { p.Players = 4; p.Pendulums = 2; p.PendulumKind = "hammer"; p.LavaPercent = 10; })),
        ("pc_ffa6_saws", "pieces_machines", Sp(p => { p.Players = 6; p.Pendulums = 2; p.PendulumKind = "saw"; p.LavaPercent = 10; })),
        ("pc_ffa4_mace_blast", "pieces_machines", Sp(p => { p.Players = 4; p.Pendulums = 1; p.PendulumKind = "mace"; p.HammerBlast = true; p.LavaPercent = 10; })),
        ("pc_duel_anchor", "pieces_machines", Sp(p => { p.Pendulums = 1; p.PendulumKind = "anchor"; p.LavaPercent = 10; })),
        ("pc_ffa6_labrys", "pieces_machines", Sp(p => { p.Players = 6; p.Pendulums = 2; p.PendulumKind = "labrys"; p.HammerBlast = true; p.LavaPercent = 15; })),
        ("pc_ffa8_blast_hammers", "pieces_machines", Sp(p => { p.Players = 8; p.Pendulums = 2; p.HammerBlast = true; p.LavaPercent = 15; })),
        ("pc_ffa6_mine", "pieces_machines", Sp(p => { p.Players = 6; p.Drills = 2; p.Conveyors = 1; p.LavaPercent = 5; })),
        ("pc_tdm_factory", "pieces_machines", Sp(p => { p.Players = 8; p.Mode = "tdm"; p.Conveyors = 1; p.Turrets = 1; p.Cogs = 1; })),
        ("pc_ffa4_even_machines", "pieces_machines", Sp(p => { p.Players = 4; p.Pistons = 1; p.Drills = 1; p.PieceMotion = "even"; })),
        ("pc_ffa6_smooth_pistons", "pieces_machines", Sp(p => { p.Players = 6; p.Pistons = 1; p.Waves = 1; p.LavaPercent = 10; })),
        ("pc_ffa8_forge", "pieces_machines", Sp(p => { p.Players = 8; p.Drills = 1; p.Pistons = 1; p.Pendulums = 1; p.PendulumKind = "sledge"; p.LavaPercent = 15; })),
        ("pc_duel_machine_room", "pieces_machines", Sp(p => { p.Cogs = 1; p.Turrets = 1; p.Drills = 1; })),
        ("pc_ffa10_industry", "pieces_machines", Sp(p => { p.Players = 10; p.Conveyors = 2; p.Drills = 2; p.Cogs = 2; p.Turrets = 1; })),
        ("pc_ffa6_wonders", "pieces_machines", Sp(p => { p.Players = 6; p.Conveyors = 1; p.Drills = 1; p.Cogs = 1; p.Pendulums = 1; p.Traps = 1; p.LavaPercent = 10; })),
        // </generated>
    };

    /// <summary>The factory presets of a map from a ready one: the likeness and the options (every family on, one map a base).</summary>
    internal static (string key, string cat, int fidelity, GenerationOptions o)[] BaseFactory() => new[]
    {
        ("default", "basic", 20, BaseOptions),
        ("gentle", "edits", 70, BaseOptions with { WarpSize = 100, WarpShape = 0, Remodels = 0, Blocks = 0, FloorShifts = 0, StairReshapes = 0 }),
        ("rebuild", "edits", 10, BaseOptions with { Digs = 4, Annexes = 4, AnnexSize = 3, Storeys = 2, Spans = 2, Halls = 2, Remodels = 8 }),
        ("niches", "edits", 20, BaseOptions with { Annexes = 6, AnnexSize = 5, Blocks = 8, FloorShifts = 6, StairReshapes = 4 }),
        ("towers", "edits", 20, BaseOptions with { Storeys = 4, Spans = 4, Stairways = 4, WarpHeight = 150 }),
        ("giant", "frame", 20, BaseOptions with { WarpSize = 300, WarpShape = 30, WarpHeight = 130, Annexes = 6, Halls = 3 }),
        ("mirror", "frame", 20, BaseOptions with { WarpTurn = 4, WarpShift = 50, WarpShape = 70 }),
        ("flood", "liquids", 20, BaseOptions with { NewWater = 60 }),
        ("fire", "liquids", 20, BaseOptions with { Liquids = "water-lava", NewLava = 20, NewSlime = 10 }),
        ("ruins", "ruins", 20, BaseOptions with { Destruction = 40, Decor = 1 }),
    };

    /*
     * Built once per form and language (brief 24 D5: 160 of them): the label asks which preset the form's values are at
     * every change of the form (KeepForm), each preset's request compared - 3 x 160 builds and comparisons per change made
     * the form slow. The lists are read only; a factory preset's request (Canon) is kept by its id.
     */
    private static readonly Dictionary<string, List<Preset>> s_factory = new();
    private static readonly Dictionary<string, string> s_factoryCanon = new();

    public static List<Preset> Factory(string kind)
    {
        var key = kind + "|" + Loc.Language;
        if (!s_factory.TryGetValue(key, out var list))
            s_factory[key] = list = BuildFactory(kind);
        return list;
    }

    /// <summary>What a preset asks (Canon), a factory one's kept.</summary>
    public static string CanonOf(Preset p)
    {
        if (!p.Factory)
            return Canon(p.Kind, p.Body);
        if (!s_factoryCanon.TryGetValue(p.Id, out var c))
            s_factoryCanon[p.Id] = c = Canon(p.Kind, p.Body);
        return c;
    }

    private static List<Preset> BuildFactory(string kind) => kind == Scratch
        ? ScratchFactory().Select(f => new Preset(FactoryPrefix + Scratch + ":" + f.key, Scratch, Loc.T($"preset.{Scratch}.{f.key}"),
                                                  FactoryPrefix + f.cat, ScratchBody(f.p, 1))).ToList()
        : BaseFactory().Select(f => new Preset(FactoryPrefix + Base + ":" + f.key, Base, Loc.T($"preset.{Base}.{f.key}"),
                                               FactoryPrefix + f.cat, BaseBody(f.fidelity, 1, Array.Empty<string>(), false, f.o))).ToList();

    /// <summary>A factory preset's own key («duel_vertical») - its tip's key; "" for a user's.</summary>
    public static string FactoryKey(Preset p) => p.Factory ? p.Id[(p.Id.LastIndexOf(':') + 1)..] : "";

    /// <summary>A category's words: a factory one in the program's language, the user's as typed.</summary>
    public static string CategoryName(string category) =>
        category.StartsWith(FactoryPrefix, StringComparison.Ordinal) ? Loc.T("preset.cat." + category[FactoryPrefix.Length..]) : category;

    /// <summary>
    /// A category typed: a factory category's name in either language is that category (a preset put into «Дуэли» stays
    /// with the factory duels in English too); else the words as typed, trimmed.
    /// </summary>
    public static string CategoryOf(string kind, string typed)
    {
        var t = typed.Trim();
        foreach (var c in FactoryCategories(kind))
            if (new[] { "ru", "en" }.Any(l => string.Equals(Loc.In(l, "preset.cat." + c), t, StringComparison.OrdinalIgnoreCase)))
                return FactoryPrefix + c;
        return t;
    }

    /// <summary>A name a factory preset of the form has, in either language.</summary>
    public static bool IsFactoryName(string kind, string name)
    {
        var t = name.Trim();
        var keys = kind == Scratch ? ScratchFactory().Select(f => f.key) : BaseFactory().Select(f => f.key);
        return keys.Any(k => new[] { "ru", "en" }.Any(l => string.Equals(Loc.In(l, $"preset.{kind}.{k}"), t, StringComparison.OrdinalIgnoreCase)));
    }

    // ---- the user's -----------------------------------------------------------------------------------------------

    /// <summary>The self-test's own file (never the user's).</summary>
    public static string? PathOverride { get; set; }

    public static string FilePath => PathOverride ?? Path.Combine(Settings.ProgramDir, "MapgenStudio.presets.json");

    private static List<Preset>? s_user;
    private static List<JsonNode> s_unread = new();

    /// <summary>Why the file could not be read; while it is set nothing is written over it (it is the user's to mend).</summary>
    public static string? ReadError { get; private set; }

    /// <summary>The file read again at the next ask.</summary>
    public static void Forget()
    {
        s_user = null;
        s_unread = new List<JsonNode>();
        ReadError = null;
    }

    public static List<Preset> User()
    {
        if (s_user != null)
            return s_user;
        s_user = new List<Preset>();
        s_unread = new List<JsonNode>();
        ReadError = null;
        try
        {
            if (!File.Exists(FilePath))
                return s_user;
            var root = JsonNode.Parse(File.ReadAllText(FilePath, Encoding.UTF8)) as JsonObject
                       ?? throw new JsonException("not an object");
            var list = root["presets"] as JsonArray ?? throw new JsonException("no «presets» list");
            foreach (var n in list)
            {
                if (n is JsonObject o && o["id"] is JsonValue id && id.TryGetValue<string>(out var ids) && ids.Length > 0
                    && !ids.StartsWith(FactoryPrefix, StringComparison.Ordinal)
                    && o["kind"] is JsonValue k && k.TryGetValue<string>(out var kind) && kind is Scratch or Base
                    && o["name"] is JsonValue nm && nm.TryGetValue<string>(out var name) && name.Trim().Length > 0
                    && o["body"] is JsonObject body)
                {
                    var cat = RetiredCategory(kind, o["category"] is JsonValue c && c.TryGetValue<string>(out var cs) ? cs : "");
                    s_user.Add(new Preset(ids, kind, name.Trim(), cat, (JsonObject)body.DeepClone()));
                }
                else if (n != null)
                    s_unread.Add(n.DeepClone());       // a preset of a later version, kept as it is
            }
        }
        catch (Exception e) when (e is JsonException or IOException or UnauthorizedAccessException or InvalidOperationException)
        {
            s_user = new List<Preset>();
            ReadError = $"{FilePath}: {e.Message}";
        }
        return s_user;
    }

    private static bool Write(List<Preset> all)
    {
        User();
        if (ReadError != null)
            return false;
        var list = new JsonArray();
        foreach (var p in all)
            list.Add(new JsonObject
            {
                ["id"] = p.Id, ["kind"] = p.Kind, ["name"] = p.Name, ["category"] = p.Category, ["body"] = p.Body.DeepClone(),
            });
        foreach (var n in s_unread)
            list.Add(n.DeepClone());
        var root = new JsonObject { ["version"] = 1, ["presets"] = list };
        try
        {
            var tmp = FilePath + ".tmp";
            File.WriteAllText(tmp, root.ToJsonString(new JsonSerializerOptions { WriteIndented = true }), new UTF8Encoding(false));
            File.Move(tmp, FilePath, overwrite: true);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return false;
        }
        s_user = all;
        return true;
    }

    /// <summary>Every preset of a form: the factory's first, then the user's.</summary>
    public static List<Preset> All(string kind) => Factory(kind).Concat(User().Where(p => p.Kind == kind)).ToList();

    /// <summary>The categories of a form: the factory's in their order, then the user's own, sorted.</summary>
    public static List<string> Categories(string kind) =>
        FactoryCategories(kind).Select(c => FactoryPrefix + c)
            .Concat(User().Where(p => p.Kind == kind && !p.Category.StartsWith(FactoryPrefix, StringComparison.Ordinal) && p.Category.Length > 0)
                          .Select(p => p.Category).Distinct(StringComparer.OrdinalIgnoreCase).OrderBy(c => c, StringComparer.CurrentCultureIgnoreCase))
            .ToList();

    /// <summary>A user preset of a form by its name, if one is.</summary>
    public static Preset? UserNamed(string kind, string name) =>
        User().FirstOrDefault(p => p.Kind == kind && string.Equals(p.Name, name.Trim(), StringComparison.OrdinalIgnoreCase));

    /// <summary>
    /// A user preset saved: a new one, or `replaceId`'s written over (its id kept) - its name, category and, when `body`
    /// is given, its values. Null when the file cannot be written (ReadError, a locked disk).
    /// </summary>
    public static Preset? Save(string kind, string name, string category, JsonObject? body, string? replaceId = null)
    {
        var all = User().ToList();
        var at = replaceId == null ? -1 : all.FindIndex(p => p.Id == replaceId);
        var keep = at >= 0 ? all[at].Body : null;
        var made = new Preset(at >= 0 ? all[at].Id : Guid.NewGuid().ToString("N"), kind, name.Trim(), category,
                              (JsonObject)(body ?? keep ?? new JsonObject()).DeepClone());
        if (at >= 0)
            all[at] = made;
        else
            all.Add(made);
        return Write(all) ? made : null;
    }

    /// <summary>A user preset removed (never a factory one). False when nothing was removed.</summary>
    public static bool Delete(string id)
    {
        if (id.StartsWith(FactoryPrefix, StringComparison.Ordinal))
            return false;
        var all = User().ToList();
        return all.RemoveAll(p => p.Id == id) > 0 && Write(all);
    }

    /// <summary>The preset of a form whose values are the form's now - the one last loaded first.</summary>
    public static Preset? Matching(string kind, JsonObject now, string lastId)
    {
        var canon = Canon(kind, now);
        var all = All(kind);
        var last = all.FirstOrDefault(p => p.Id == lastId);
        if (last != null && CanonOf(last) == canon)
            return last;
        return all.FirstOrDefault(p => CanonOf(p) == canon);
    }
}
