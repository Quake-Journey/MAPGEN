using System.Text;
using System.Text.Json.Nodes;

namespace MapgenStudio;

/// <summary>
/// The PO 12.11 on his mg_new_7775 («никакого глубокого бассейна по типу как на q2dm1 в котором плывешь за рейлом»,
/// «на q2dm4 или q2dm5 там вообще многоуровневые конструкции с множеством глубоких водоемов»): the row «Водоёмы» on the
/// page and in the request, the presets that put their water on several levels, a 3.66 preset loaded; and his question
/// on the same map («зачем свет на готовой карте повторно делается?»): a map from scratch with no ruin has no stage
/// «Свет на готовой карте».
/// </summary>
public sealed partial class MainWindow
{
    internal static void WaterSelfTest(StringBuilder b)
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
            // (w1) a map of rooms shows «Водоёмы»; an open space and a tower do not (their water is not in halls' pools)
            List<string> Titles(string key)
            {
                var w = new MainWindow { _page = "generate" };
                w.Rebuild();
                w.LoadPreset(Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == key));
                LayOut(w, ScreenSizes[1], unfold: true);
                return RowsShown(w).Select(TitleOf).ToList();
            }
            var rooms = Titles("water_canals");
            var space = Titles("space_duel");
            var row = Loc.T("scr.waterbody");
            Row(rooms.Contains(row) && !space.Contains(row),
                $"«{row}» on a map of rooms, not on an open space",
                $"«{row}»: rooms {rooms.Contains(row)}, space {space.Contains(row)}");
            // (w2) the request: a map of rooms sends it, an open space does not
            var dir = Path.GetTempPath();
            var pr = JsonNode.Parse(new ScratchParams { WaterBody = "levels", WaterPercent = 20 }.ToPython(dir, dir))!.AsObject();
            var ps = JsonNode.Parse(new ScratchParams { Shape = "space", WaterBody = "levels" }.ToPython(dir, dir))!.AsObject();
            var pd = JsonNode.Parse(new ScratchParams { WaterPercent = 20 }.ToPython(dir, dir))!.AsObject();
            Row(pr["water_body"]?.ToString() == "levels" && ps["water_body"] == null && pd["water_body"] == null,
                "«Водоёмы» in the request: a map of rooms sends «levels», an open space nothing, «По умолчанию» nothing (the generator's deep pools)",
                $"«Водоёмы» in the request: rooms {pr["water_body"]}, space {ps["water_body"]}, default {pd["water_body"]}");
            // (w3) the presets: four on several levels, every other at «По умолчанию»
            var levels = new HashSet<string> { "water_canals", "water_ffa8", "pr_q2dm_water8", "pz_ffa8_lake_dive",
                                               "pc_ffa6_ladders", "pc_ffa4_water_mix" };
            var bad = new List<string>();
            foreach (var x in Presets.Factory(Presets.Scratch))
            {
                var k = Presets.FactoryKey(x);
                var p = Presets.ScratchOf(x.Body);
                var want = levels.Contains(k) ? "levels" : "";
                if (p.WaterBody != want || !ScratchParams.WaterBodies.Contains(p.WaterBody))
                    bad.Add($"{k}: «{p.WaterBody}»");
            }
            Row(bad.Count == 0,
                $"the presets: {levels.Count} on several levels (the canals, the water for 8, «Как q2dm, с водой…», «Озеро и призы на дне на 8», two of the pieces'), the other {Presets.Factory(Presets.Scratch).Count - levels.Count} at «По умолчанию»",
                $"the presets' «Водоёмы» not as asked: {string.Join(", ", bad.Take(6))}");
            // (w4) a preset saved by 3.66 (no «Водоёмы» in it) over a form with it set: back to «По умолчанию»
            var form = new Settings { Scratch = new ScratchParams { WaterBody = "shallow" } };
            var old = JsonNode.Parse(new ScratchParams { Players = 4 }.Save())!.AsObject();
            old.Remove("WaterBody");
            Presets.Apply(form, Presets.Scratch, new JsonObject { ["scratch"] = old, ["minutes"] = 1, ["destruction"] = 0 });
            Row(form.Scratch.Players == 4 && form.Scratch.WaterBody == "",
                "a preset of 3.66 (no «Водоёмы» in it) loaded over a form with it set: back to «По умолчанию»",
                $"a preset of 3.66 loaded: players {form.Scratch.Players}, «Водоёмы» «{form.Scratch.WaterBody}»");
            // (w5) the PO 12.11: «зачем свет на готовой карте повторно делается?» - a map from scratch with no ruin is lit
            // once; a map from a ready one and 3.66's run (the RED) have the stage
            s.Scratch = new ScratchParams();
            var scratch = GenerationView.StagesOf(Generation.ForSelfTest(s, "plan"));
            var donor = GenerationView.StagesOf(Generation.ForSelfTest(s, "plan", fromScratch: false));
            Generation.OldScratchRelight = true;
            string[] red;
            try
            {
                red = GenerationView.StagesOf(Generation.ForSelfTest(s, "plan"));
            }
            finally
            {
                Generation.OldScratchRelight = false;
            }
            Row(!scratch.Contains("relight") && donor.Contains("relight") && red.Contains("relight"),
                "a map from scratch with no ruin: no stage «Свет на готовой карте» (a map from a ready one has it; 3.66's run had it - the RED)",
                $"the stage «Свет на готовой карте»: from scratch {scratch.Contains("relight")}, from a ready map {donor.Contains("relight")}, 3.66's run {red.Contains("relight")}");
        }
        catch (Exception e)
        {
            Row(false, "", $"the water's rows: {e.GetType().Name}: {e.Message}");
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
