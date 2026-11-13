using System.Text;
using System.Text.Json.Nodes;

namespace MapgenStudio;

/// <summary>
/// The PO 12.11 (his mg_new_84719: two armours side by side, the railgun a step off them): the items' pick-up worth -
/// «Как достаются призы», «Призов под водой», «Ценные предметы друг от друга», «Чьи приёмы раскладки» on the page and
/// in the request, the hundred presets, and the old presets brought to the new rows («не забудь обновить существующие
/// пресеты на новые параметры - чтобы они сбрасывали их на дефолты или нужные значения»).
/// </summary>
public sealed partial class MainWindow
{
    internal static void ItemsSelfTest(StringBuilder b)
    {
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        var s = App.Settings;
        var keepScratch = s.Scratch;
        var keepMode = s.ScratchMode;
        var keepLang = Loc.Language;
        var keepCurrent = Generation.Current;
        try
        {
            Loc.Language = "ru";
            Generation.Current = null;
            s.ScratchMode = true;
            // (i1) a map of rooms shows the four rows; an open space only the two its majors keep (no floor to sink a well)
            List<string> Titles(string key)
            {
                var w = new MainWindow { _page = "generate" };
                w.Rebuild();
                w.LoadPreset(Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == key));
                LayOut(w, ScreenSizes[1], unfold: true);
                return RowsShown(w).Select(TitleOf).ToList();
            }
            var rooms = Titles("pz_duel_dive2");
            var space = Titles("space_duel");
            var keys = new[] { "scr.prize", "scr.under", "scr.spacing", "scr.practice" };
            bool Has(List<string> t, string k) => t.Contains(Loc.T(k));
            Row(keys.All(k => Has(rooms, k)) && Has(space, "scr.spacing") && Has(space, "scr.practice")
                && !Has(space, "scr.prize") && !Has(space, "scr.under"),
                $"the items' rows: «{string.Join("», «", keys.Select(Loc.T))}» on a map of rooms; an open space shows «{Loc.T("scr.spacing")}» and «{Loc.T("scr.practice")}» only",
                $"the items' rows: rooms {string.Join(", ", keys.Select(k => $"{k} {Has(rooms, k)}"))}; space {string.Join(", ", keys.Select(k => $"{k} {Has(space, k)}"))}");
            // (i2) the request: a map of rooms sends what it shows; an open space with the rows set sends neither prize row
            var dir = Path.GetTempPath();
            var roomsP = new ScratchParams { PrizeAccess = "water", Underwater = 2, ItemSpacing = "wide", ItemPractice = "q2dm+q2rdm" };
            var spaceP = new ScratchParams { Shape = "space", PrizeAccess = "water", Underwater = 2, ItemSpacing = "wide", ItemPractice = "q2dm" };
            var pr = JsonNode.Parse(roomsP.ToPython(dir, dir))!.AsObject();
            var ps = JsonNode.Parse(spaceP.ToPython(dir, dir))!.AsObject();
            Row(pr["prize_access"]?.ToString() == "water" && pr["underwater"]?.ToString() == "2" && pr["item_spacing"]?.ToString() == "wide"
                && pr["item_practice"]?.ToString() == "q2dm+q2rdm" && ps["prize_access"] == null && ps["underwater"] == null
                && ps["item_spacing"]?.ToString() == "wide" && ps["item_practice"]?.ToString() == "q2dm",
                "the items' rows in the request: a map of rooms sends all four, an open space the two it shows",
                $"the items' rows in the request: rooms {pr.ToJsonString()}; space {ps.ToJsonString()}");
            // (i3) the hundred presets: each value one its row offers; the old ones at «По умолчанию» but those the new
            // rows change
            var all = Presets.Factory(Presets.Scratch);
            var fresh = all.Where(x => Presets.FactoryKey(x) is var k && (k.StartsWith("pr_") || k.StartsWith("pz_"))).ToList();
            var offBad = fresh.Select(x => (k: Presets.FactoryKey(x), p: Presets.ScratchOf(x.Body)))
                              .Where(t => !ScratchParams.PrizeAccesses.Contains(t.p.PrizeAccess) || !ScratchParams.ItemPractices.Contains(t.p.ItemPractice)
                                          || t.p.Underwater is < 0 or > 3 || t.p.ItemSpacing is not ("" or "people" or "wide"))
                              .Select(t => t.k).ToList();
            var set = new Dictionary<string, (string access, int under)>
            {
                ["duel_water"] = ("", 1), ["ffa4_water"] = ("", 1), ["ffa8_water"] = ("", 1), ["ffa10_water"] = ("", 1),
                ["water_lake"] = ("", 2), ["water_canals"] = ("", 1), ["water_ffa8"] = ("", 2), ["hard_powerups8"] = ("nooks", 0),
                ["duel_open"] = ("exposed", 0), ["ffa4_open"] = ("exposed", 0),
            };
            var oldBad = new List<string>();
            foreach (var x in all.Where(x => !fresh.Contains(x) && !Presets.FactoryKey(x).StartsWith("pc_")))
            {
                var k = Presets.FactoryKey(x);
                var p = Presets.ScratchOf(x.Body);
                var want = set.TryGetValue(k, out var v) ? v : ("", 0);
                if (p.PrizeAccess != want.Item1 || p.Underwater != want.Item2 || p.ItemSpacing != "" || p.ItemPractice != "")
                    oldBad.Add($"{k}: {p.PrizeAccess}/{p.Underwater}/{p.ItemSpacing}/{p.ItemPractice}");
            }
            var cats = fresh.Select(x => x.Category).Distinct().Count();
            Row(fresh.Count == 100 && offBad.Count == 0 && oldBad.Count == 0 && cats == 4,
                $"a hundred presets of the items in 4 categories, every value one its row offers; the {all.Count - fresh.Count} old ones at «По умолчанию» in the new rows, {set.Count} of them at the values the new rows give them (the water's prize under it, the open arenas' in the open, the hard powerups' in nooks)",
                $"the items' presets: {fresh.Count} in {cats} categories, values no row offers {string.Join(", ", offBad.Take(5))}; old ones not as asked {string.Join("; ", oldBad.Take(5))}");
            // (i4) a preset saved by 3.65 (no new rows in it) over a form with the new rows set: they go back to «По умолчанию»
            var form = new Settings { Scratch = new ScratchParams { PrizeAccess = "water", Underwater = 3, ItemSpacing = "wide", ItemPractice = "q2dm" } };
            var old = JsonNode.Parse(new ScratchParams { Players = 4 }.Save())!.AsObject();
            foreach (var k in new[] { "PrizeAccess", "Underwater", "ItemSpacing", "ItemPractice" })
                old.Remove(k);
            Presets.Apply(form, Presets.Scratch, new JsonObject { ["scratch"] = old, ["minutes"] = 1, ["destruction"] = 0 });
            var f = form.Scratch;
            Row(f.Players == 4 && f.PrizeAccess == "" && f.Underwater == 0 && f.ItemSpacing == "" && f.ItemPractice == "",
                "a preset of 3.65 (no new rows in it) loaded over a form with them set: the four go back to «По умолчанию»",
                $"a preset of 3.65 loaded: players {f.Players}, {f.PrizeAccess}/{f.Underwater}/{f.ItemSpacing}/{f.ItemPractice}");
        }
        catch (Exception e)
        {
            Row(false, "", $"the items' rows: {e.GetType().Name}: {e.Message}");
        }
        finally
        {
            s.Scratch = keepScratch;
            s.ScratchMode = keepMode;
            Loc.Language = keepLang;
            Generation.Current = keepCurrent;
        }
    }
}
