using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace MapgenStudio;

/// <summary>
/// Brief 33 (the PO 08.11: «если генератор применяет что-либо из настроек, которые есть только на странице форков, то
/// нужно добавить их и на страницу новых карт … равно как и наоборот … а также учитываться … в пресетах — заводских и
/// пользовательских»): a run uses only the rows of the page that starts it, both ways, and a page's presets carry every
/// row of it. Settings made here are never saved.
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>Every settable property of an object set away from what it holds: numbers +7, words «x», switches
    /// turned, lists and maps one entry - what «every row at a value of its own» is for a preset's round trip.</summary>
    private static T Shifted<T>(T o) where T : class
    {
        foreach (var pi in typeof(T).GetProperties(BindingFlags.Public | BindingFlags.Instance).Where(p => p.CanWrite && p.CanRead))
        {
            var v = pi.GetValue(o);
            if (pi.PropertyType == typeof(int))
                pi.SetValue(o, (int)v! + 7);
            else if (pi.PropertyType == typeof(bool))
                pi.SetValue(o, !(bool)v!);
            else if (pi.PropertyType == typeof(string))
                pi.SetValue(o, ((string?)v ?? "") + "x");
            else if (pi.PropertyType == typeof(List<string>))
                pi.SetValue(o, new List<string> { "x" });
            else if (pi.PropertyType == typeof(Dictionary<string, int>))
                pi.SetValue(o, new Dictionary<string, int> { ["x"] = 3 });
        }
        return o;
    }

    /// <summary>The base page's options all away from their defaults - its ruin aside (both pages show «Разрушения»).</summary>
    private static GenerationOptions BaseShifted(int destruction) => new(Digs: 9, Annexes: 9, AnnexSize: 4, Storeys: 8, Spans: 6, Halls: 5,
        Liquids: "mix", Decor: 4, NewWater: 90, NewSlime: 80, NewLava: 70, Stairways: 10, Destruction: destruction, Remodels: 16,
        Blocks: 16, FloorShifts: 12, StairReshapes: 8, WarpSize: 400, WarpShape: 90, WarpTurn: 4, WarpHeight: 300, WarpShift: 80);

    internal static void PagesSelfTest(StringBuilder b)
    {
        var lang = Loc.Language;
        try
        {
            // ---- a scratch run: the other page at its maximum changes nothing ----------------------------------
            string Scratch(Settings s) => string.Join("\n", Generation.RequestLines(Generation.ScratchRequest(s, "mg_new_t", 7, s.Builds, s.TimeMinutes), false));
            Settings ScratchPlain() => new() { Scratch = new ScratchParams { Players = 4, StairAnnexes = 3 }, Options = new GenerationOptions(Destruction: 14) };
            Settings ScratchOther()
            {
                var s = ScratchPlain();
                s.Options = BaseShifted(14);
                s.SkipFamilies = Families.Values.SelectMany(x => x).ToList();
                s.GraftMode = true;
                s.Fidelity = 99;
                s.Bases = new List<string> { "q2dm1", "q2dm3" };
                return s;
            }
            var a = Scratch(ScratchPlain()).Split('\n');
            var o = Scratch(ScratchOther()).Split('\n');
            var differ = a.Zip(o).Where(x => x.First != x.Second).Select(x => $"{x.First} / {x.Second}").ToList();
            var stairs = a.FirstOrDefault(l => l.StartsWith("stairways=")) ?? "";
            b.AppendLine(differ.Count == 0 && stairs == "stairways=3"
                ? "PASS a map from scratch's request holds only its page's rows: the other page at its maximum changes none of its fields (its stairway annexes its own: 3)"
                : "FAIL a map from scratch's request holds only its page's rows -- " + string.Join("; ", differ.Take(6)) + $" ({stairs})");
            Generation.OldScratchRequest = true;
            try
            {
                var oldA = Scratch(ScratchPlain()).Split('\n');
                var oldO = Scratch(ScratchOther()).Split('\n');
                var leaks = oldA.Zip(oldO).Count(x => x.First != x.Second);
                b.AppendLine(leaks > 0
                    ? $"PASS RED: the 3.59 construction of a scratch request takes {leaks} fields from the other page"
                    : "FAIL RED: the 3.59 construction of a scratch request should leak the other page's fields and did not");
            }
            finally
            {
                Generation.OldScratchRequest = false;
            }
            // an open space or a tower: no stairway annexes whatever the row says
            var space = ScratchPlain();
            space.Scratch.Shape = "space";
            var spaceStairs = Generation.ScratchRequest(space, "mg_new_t", 7, 10, 1).Options?.Stairways ?? -1;
            b.AppendLine(spaceStairs == 0
                ? "PASS an open space's request deals no stairway annexes"
                : $"FAIL an open space's request deals no stairway annexes -- {spaceStairs}");

            // ---- a base run: the other page at its maximum changes nothing -------------------------------------
            string Base(Settings s) => string.Join("\n", Generation.BaseRequests(s, new[] { "q2dm1", "q2dm3" }, false, "mg_t", 30, 7, s.SkipFamilies)
                                                                 .SelectMany(r => Generation.RequestLines(r, false)));
            Settings BasePlain() => new() { Options = new GenerationOptions(Annexes: 2, Destruction: 14), SkipFamilies = new List<string> { "window" } };
            var other = BasePlain();
            other.Scratch = Shifted(new ScratchParams());
            var ba = Base(BasePlain()).Split('\n');
            var bo = Base(other).Split('\n');
            var bdiffer = ba.Zip(bo).Where(x => x.First != x.Second).Select(x => $"{x.First} / {x.Second}").ToList();
            b.AppendLine(bdiffer.Count == 0 && ba.All(l => !l.StartsWith("scratch=") || l == "scratch=")
                ? $"PASS a map from a ready one's requests hold only their page's rows: the scratch page at a value of its own in every row changes none of their fields ({ba.Length} lines)"
                : "FAIL a map from a ready one's requests hold only their page's rows -- " + string.Join("; ", bdiffer.Take(6)));

            // ---- presets: every row of each page round-trips ----------------------------------------------------
            var s1 = new Settings { Scratch = Shifted(new ScratchParams()), Minutes = 3, Options = new GenerationOptions(Destruction: 37) };
            var body = Presets.BodyOf(s1, Presets.Scratch);
            bool ScratchSame(Settings s2) => s2.Scratch.Save() == s1.Scratch.Save() && s2.Minutes == s1.Minutes
                                             && s2.Options.Destruction == s1.Options.Destruction;
            var s2 = new Settings();
            Presets.Apply(s2, Presets.Scratch, JsonNode.Parse(body.ToJsonString())!.AsObject());
            var props = typeof(ScratchParams).GetProperties(BindingFlags.Public | BindingFlags.Instance).Count(p => p.CanWrite);
            b.AppendLine(ScratchSame(s2)
                ? $"PASS a «Новая карта с нуля» preset carries every row of its page: {props} parameters, the minutes and the ruin, each at a value of its own, back as they were"
                : $"FAIL a «Новая карта с нуля» preset carries every row of its page -- got {s2.Scratch.Save()[..Math.Min(200, s2.Scratch.Save().Length)]}, minutes {s2.Minutes}, ruin {s2.Options.Destruction}");
            var cut = JsonNode.Parse(body.ToJsonString())!.AsObject();
            cut.Remove("destruction");
            var s3 = new Settings();
            Presets.Apply(s3, Presets.Scratch, cut);
            b.AppendLine(!ScratchSame(s3)
                ? "PASS RED: a «Новая карта с нуля» preset without its ruin (as 3.58 wrote them) does not bring the page back"
                : "FAIL RED: a preset without its ruin should not bring the page back");

            var g1 = new Settings
            {
                Options = BaseShifted(55), Fidelity = 42, Minutes = 3, GraftMode = true,
                SkipFamilies = new List<string> { "window", "flood" },
            };
            var gbody = Presets.BodyOf(g1, Presets.Base);
            bool BaseSame(Settings g2) => JsonSerializer.Serialize(g2.Options) == JsonSerializer.Serialize(g1.Options) && g2.Fidelity == g1.Fidelity
                                          && g2.Minutes == g1.Minutes && g2.GraftMode == g1.GraftMode
                                          && string.Join(",", g2.SkipFamilies) == string.Join(",", g1.SkipFamilies);
            var g2 = new Settings();
            Presets.Apply(g2, Presets.Base, JsonNode.Parse(gbody.ToJsonString())!.AsObject());
            var opts = typeof(GenerationOptions).GetProperties(BindingFlags.Public | BindingFlags.Instance).Length;
            b.AppendLine(BaseSame(g2)
                ? $"PASS a «Из готовых карт» preset carries every row of its page: {opts} options, the likeness, the minutes, «Что можно менять» and how several bases are used"
                : $"FAIL a «Из готовых карт» preset carries every row of its page -- {JsonSerializer.Serialize(g2.Options)}");
            var gcut = JsonNode.Parse(gbody.ToJsonString())!.AsObject();
            (gcut["options"] as JsonObject)?.Remove("Stairways");
            var g3 = new Settings();
            Presets.Apply(g3, Presets.Base, gcut);
            b.AppendLine(!BaseSame(g3)
                ? "PASS RED: a «Из готовых карт» preset missing one option does not bring the page back"
                : "FAIL RED: a preset missing one option should not bring the page back");
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the pages' own rows: {ex.GetType().Name}: {ex.Message}");
        }
        finally
        {
            Loc.Language = lang;
        }
    }
}
