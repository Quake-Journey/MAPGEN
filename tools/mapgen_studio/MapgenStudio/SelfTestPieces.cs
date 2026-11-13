using System.Text;
using System.Text.Json.Nodes;

namespace MapgenStudio;

/// <summary>
/// The PO 13.11 («нам не хватает архитектурного уникального для карт лоска ... постройками, которые имеют движение и/или
/// интерактивность с игроком»; «мне нужны доп 100 новых пресетов которые настраивают вариации подобного»): the card
/// «Скриптовые конструкции» on a map of rooms (not on an open space or a tower), its rows in the request, the hundred
/// presets each with values its rows offer, and a 3.67 preset loaded (no pieces in it) back to «По умолчанию».
/// </summary>
public sealed partial class MainWindow
{
    internal static void PiecesSelfTest(StringBuilder b)
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
            List<string> Titles(string key)
            {
                var w = new MainWindow { _page = "generate" };
                w.Rebuild();
                w.LoadPreset(Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == key));
                LayOut(w, ScreenSizes[1], unfold: true);
                return RowsShown(w).Select(TitleOf).ToList();
            }
            var rooms = Titles("pc_ffa8_everything");
            var space = Titles("space_duel");
            var keys = new[] { "scr.pc.trains", "scr.pc.stones", "scr.pc.traps", "scr.pc.rotators", "scr.pc.waves", "scr.pc.lasers",
                               "scr.pc.geysers", "scr.pc.pool_ladders", "scr.pc.piece_speed" };
            bool Has(List<string> t, string k) => t.Contains(Loc.T(k));
            Row(keys.All(k => Has(rooms, k)) && !keys.Any(k => Has(space, k)),
                $"«{Loc.T("scr.pieces")}»: its rows on a map of rooms ({keys.Length} of them looked for), none on an open space",
                $"«{Loc.T("scr.pieces")}»: rooms {string.Join(", ", keys.Select(k => $"{k} {Has(rooms, k)}"))}; space {string.Join(", ", keys.Where(k => Has(space, k)))}");
            var dir = Path.GetTempPath();
            var pr = JsonNode.Parse(new ScratchParams { Trains = 2, TrainPath = "island", Traps = 1, TrapHazard = "slime", Lasers = 1,
                                                        PoolLadders = true, PieceSpeed = 150 }.ToPython(dir, dir))!.AsObject();
            var ps = JsonNode.Parse(new ScratchParams { Shape = "space", Trains = 2, Lasers = 1 }.ToPython(dir, dir))!.AsObject();
            var pd = JsonNode.Parse(new ScratchParams().ToPython(dir, dir))!.AsObject();
            Row(pr["trains"]?.ToString() == "2" && pr["train_path"]?.ToString() == "island" && pr["traps"]?.ToString() == "1"
                && pr["trap_hazard"]?.ToString() == "slime" && pr["lasers"]?.ToString() == "1" && pr["pool_ladders"]?.ToString() == "true"
                && pr["piece_speed"]?.ToString() == "150" && ps["trains"] == null && ps["lasers"] == null && pd["trains"] == null,
                "the pieces in the request: a map of rooms sends what its rows say, an open space nothing, «По умолчанию» nothing",
                $"the pieces in the request: rooms {pr.ToJsonString()}; space {ps.ToJsonString()}");
            var all = Presets.Factory(Presets.Scratch);
            var fresh = all.Where(x => Presets.FactoryKey(x).StartsWith("pc_")).ToList();
            var bad = new List<string>();
            foreach (var x in fresh)
            {
                var p = Presets.ScratchOf(x.Body);
                var n = p.Trains + p.Stones + p.Traps + p.Rotators + p.Shutters + p.PickupWalls + p.BentBridges + p.WallSteps + p.Lasers
                        + p.Pistons + p.Pendulums + p.Trapdoors + p.Geysers + p.TurnBridges + p.Currents + p.Waves + (p.PoolLadders ? 1 : 0)
                        + p.Drills + p.Cogs + p.Turrets + p.Conveyors;
                if (n == 0 || !ScratchParams.TrainPaths.Contains(p.TrainPath) || !ScratchParams.StoneShapes.Contains(p.StoneShape)
                    || !ScratchParams.TrapTriggers.Contains(p.TrapTrigger) || !ScratchParams.TrapHazards.Contains(p.TrapHazard)
                    || !ScratchParams.RotatorKinds.Contains(p.RotatorKind) || !ScratchParams.PendulumKinds.Contains(p.PendulumKind)
                    || !ScratchParams.PieceMotions.Contains(p.PieceMotion)
                    || (p.PieceSpeed != 0 && !ScratchParams.PieceSpeeds.Contains(p.PieceSpeed))
                    || (p.PieceWait != 0 && !ScratchParams.PieceWaits.Contains(p.PieceWait)))
                    bad.Add(Presets.FactoryKey(x));
            }
            var oldWith = all.Where(x => !Presets.FactoryKey(x).StartsWith("pc_")).Select(x => (k: Presets.FactoryKey(x), p: Presets.ScratchOf(x.Body)))
                             .Where(t => t.p.Trains + t.p.Traps + t.p.Lasers + t.p.Stones > 0).Select(t => t.k).ToList();
            var cats = fresh.Select(x => x.Category).Distinct().Count();
            Row(fresh.Count == 125 && bad.Count == 0 && oldWith.Count == 0 && cats == 5,
                $"125 presets of the scripted pieces and machines in 5 categories, each asking a piece with values its rows offer; the other {all.Count - fresh.Count} ask none",
                $"the pieces' presets: {fresh.Count} in {cats} categories, not as asked {string.Join(", ", bad.Take(5))}; old ones asking pieces {string.Join(", ", oldWith.Take(5))}");
            var form = new Settings { Scratch = new ScratchParams { Trains = 3, Traps = 2, Lasers = 2, PoolLadders = true, TrapHazard = "lava" } };
            var old = JsonNode.Parse(new ScratchParams { Players = 4 }.Save())!.AsObject();
            foreach (var k in new[] { "Trains", "Traps", "Lasers", "PoolLadders", "TrapHazard" })
                old.Remove(k);
            Presets.Apply(form, Presets.Scratch, new JsonObject { ["scratch"] = old, ["minutes"] = 1, ["destruction"] = 0 });
            var f = form.Scratch;
            Row(f.Players == 4 && f.Trains == 0 && f.Traps == 0 && f.Lasers == 0 && !f.PoolLadders && f.TrapHazard == "",
                "a preset of 3.67 (no pieces in it) loaded over a form with them set: back to «По умолчанию»",
                $"a preset of 3.67 loaded: trains {f.Trains}, traps {f.Traps}, lasers {f.Lasers}, ladders {f.PoolLadders}, hazard «{f.TrapHazard}»");
        }
        catch (Exception e)
        {
            Row(false, "", $"the pieces' rows: {e.GetType().Name}: {e.Message}");
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
