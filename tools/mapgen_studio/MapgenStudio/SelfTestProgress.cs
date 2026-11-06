using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.LogicalTree;

namespace MapgenStudio;

/// <summary>
/// Brief 24 D1/D2 (the PO 06.11: «тут нужно рисовать общий прогресс построения, процент текущий до конца, сколько
/// осталось времени»; «ограничение 80 %, а реально студия юзает гораздо меньше»): «Ход работы» of a map from scratch,
/// its record, the strip, the edits' clock and the load box's header - on the self-test's own runs and record folder.
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>A run of a map from scratch at a stage: the stage under way began 20 s ago, each before it a minute before.</summary>
    private static Generation FreshRun(string stage, bool fromScratch = true)
    {
        var g = Generation.ForSelfTest(App.Settings, stage, fromScratch);
        var order = new[] { "scratch", "start", "baseline", "plan", "attempt", "judge", "light", "gates", "cover", "done" };
        var at = Array.IndexOf(order, stage);
        var now = DateTime.Now;
        if (stage != "done")
            for (var k = 0; k <= at; k++)
                g.StageBegan[order[k]] = now.AddSeconds(-20 - 60 * (at - k));
        g.Began = g.StageBegan.Values.Min();
        return g;
    }

    /// <summary>The generate page with a run on it, laid out at the wide screen.</summary>
    private static MainWindow RunPage(Generation g)
    {
        Generation.Current = g;
        var w = new MainWindow { _page = "generate" };
        w.Rebuild();
        LayOut(w, ScreenSizes[1], unfold: true);
        return w;
    }

    internal static void ProgressSelfTest(StringBuilder b)
    {
        var s = App.Settings;
        var keepCurrent = Generation.Current;
        var keepLang = Loc.Language;
        var keepMode = s.ScratchMode;
        var dir = Path.Combine(s.TempPath, $"selftest_progress_{Environment.ProcessId}");
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        try
        {
            Loc.Language = "ru";
            s.ScratchMode = true;
            Directory.CreateDirectory(Path.Combine(dir, "descriptions"));
            RunHistory.PathOverride = Path.Combine(dir, "descriptions");
            RunHistory.Forget();

            // (ii) the percent grows stage by stage, 100 at the end
            var seq = new List<string> { "scratch", "start", "plan", "attempt", "judge", "light", "gates" };
            if (FreshRun("gates").CoverPlanned)
                seq.Add("cover");
            seq.Add("done");
            var pcts = seq.Select(st => RunProgress.Of(FreshRun(st)).Percent).ToList();
            var rising = pcts.Zip(pcts.Skip(1)).All(p => p.Second > p.First);
            Row(rising && pcts[^1] == 100,
                $"«Ход работы» grows stage by stage: {string.Join(" → ", seq.Zip(pcts).Select(t => $"{t.First} {t.Second:0}"))} %",
                $"«Ход работы» by stage: {string.Join(" → ", seq.Zip(pcts).Select(t => $"{t.First} {t.Second:0.#}"))} % (want rising, 100 at the end)");

            // (iii) the skeleton by its own log: 4 of 10 candidates built
            var log = "the Studio's textures: set g1 (theme=city) in 12 s\nplans: 100 of 100\n"
                      + "skeletons: 85 of 100 seeds made a plan (21.0 s)\ncandidates built: 4 of 10\n";
            var (frac, said) = Generation.ScratchProgressOf(log);
            var gs = FreshRun("scratch");
            Directory.CreateDirectory(gs.ScratchDir);
            File.WriteAllText(Path.Combine(gs.ScratchDir, "scratch.txt"), log);
            gs.ReadScratchProgress();
            var ps = RunProgress.Of(gs);
            File.Delete(Path.Combine(gs.ScratchDir, "scratch.txt"));
            Row(frac > 0.55 && frac < 1 && gs.ScratchFraction == frac && ps.Inner == Loc.F("run.progress.scratch.cands", 4, 10),
                $"the skeleton's log read as it grows: 4 of 10 variants built = {frac:P0} of its stage, said «{ps.Inner}»",
                $"the skeleton's log: {frac:P0} (want 55..100 %), read from the file {gs.ScratchFraction:P0}, said «{ps.Inner}»");

            // (iv) a record of the same kind changes what a stage is expected to take
            var g0 = FreshRun("scratch");
            var e0 = RunProgress.Expected(g0, "scratch");
            var left0 = RunProgress.Of(g0).Left;
            File.WriteAllLines(Path.Combine(dir, "descriptions", "mg_rec.info.txt"), new[]
            {
                $"made={DateTime.Now.AddDays(-1):O}", "scratch=1", $"players={g0.ScratchPlayers}", $"minutes={g0.Request.TimeMinutes}",
                "stage.scratch=400", "stage.attempt=100",
            });
            RunHistory.Forget();
            var g1 = FreshRun("scratch");
            var e1 = RunProgress.Expected(g1, "scratch");
            var left1 = RunProgress.Of(g1).Left;
            File.Delete(Path.Combine(dir, "descriptions", "mg_rec.info.txt"));
            RunHistory.Forget();
            Row(e0 == RunProgress.Builtin["scratch"] && e1 == 400 && left1 > left0,
                $"a record of the same kind: the skeleton expected {e0:0} s built-in, {e1:0} s by the record; the time left {left0?.TotalSeconds:0} → {left1?.TotalSeconds:0} s",
                $"a record of the same kind: expected {e0:0} → {e1:0} s (want {RunProgress.Builtin["scratch"]:0} → 400), left {left0?.TotalSeconds:0} → {left1?.TotalSeconds:0} s");

            // the stages' seconds a run writes into its record: canonical keys, the whole run
            var gd = FreshRun("gates");
            gd.StageBegan["redeal"] = gd.StageBegan["attempt"].AddSeconds(10);
            var sec = gd.StageSeconds();
            var whole = (int)Math.Round(gd.Worked(gd.Began, DateTime.Now).TotalSeconds);
            Row(!sec.ContainsKey("redeal") && sec.ContainsKey("attempt") && Math.Abs(sec.Values.Sum() - whole) <= sec.Count,
                $"the stages' seconds for the record: {string.Join(", ", sec.Select(kv => $"{kv.Key} {kv.Value}"))} (the whole run {whole} s)",
                $"the stages' seconds: {string.Join(", ", sec.Select(kv => $"{kv.Key} {kv.Value}"))}, sum {sec.Values.Sum()} of {whole} s");

            // (v) the strip over the other pages: the percent and the stage, no difference
            var strip = new RunStrip();
            strip.Update(FreshRun("attempt"));
            var line2 = strip.Line2;
            Row(line2.StartsWith("Ход работы ", StringComparison.Ordinal) && line2.Contains("этап ") && !line2.Contains("тличи"),
                $"the strip of a new map's run: «{line2}»",
                $"the strip of a new map's run says «{line2}» (want the progress, no difference)");

            // (vi) a map from a ready one keeps its difference and has no «Ход работы»
            s.ScratchMode = false;
            var bw = RunPage(FreshRun("attempt", fromScratch: false));
            var bProg = bw.GetLogicalDescendants().OfType<Border>().FirstOrDefault(x => x.Tag as string == "run-progress");
            var bWords = WordsOf(bw);
            var bCut = CutTexts(bw);
            Row(bProg is { IsVisible: false } && bWords.Contains(Loc.T("run.diff.head")) && bCut.Count == 0,
                $"a map from a ready one: «{Loc.T("run.diff.head")}» and its bar as before, no «Ход работы»",
                $"a map from a ready one: progress card {(bProg == null ? "missing" : bProg.IsVisible ? "SHOWN" : "hidden")}, «{Loc.T("run.diff.head")}» {bWords.Contains(Loc.T("run.diff.head"))}, cut short: {string.Join("; ", bCut.Take(4))}");
            s.ScratchMode = true;

            // (vii) the edits' clock is the engine's: it started a minute ago, the run five minutes ago
            var ge = FreshRun("attempt");
            ge.StageBegan["start"] = DateTime.Now.AddSeconds(-70);
            ge.Began = DateTime.Now.AddMinutes(-5);
            var ew = RunPage(ge);
            var eWords = WordsOf(ew);
            Row(eWords.Contains(Loc.F("run.time.of", 1, 60)) && !eWords.Contains(Loc.F("run.time.of", 5, 60)),
                $"the edits' time by the engine's clock: «{Loc.F("run.time.of", 1, 60)}» (the run began 5 minutes ago, the engine 1)",
                $"the edits' time: {string.Join(" | ", eWords.Where(x => x.StartsWith("Время:", StringComparison.Ordinal)))} (want «{Loc.F("run.time.of", 1, 60)}»)");

            // D2: the load box says the ceiling in threads - the job mask's bits - not «80 %» alone
            var gl = FreshRun("attempt");
            gl.ApplyShare();
            var share = gl.CpuShare;
            var bits = System.Numerics.BitOperations.PopCount(NativeJob.Mask(Math.Max(1, (int)Math.Floor(Environment.ProcessorCount * share / 100.0))));
            var lw = RunPage(gl);
            var head = lw._runView?.LoadHeader ?? "";
            // and it fits its column: wrapped, nothing cut (the PO 06.11, his picture: «…80 % (12 из» cut at the edge)
            var loadCut = CutTexts(lw);
            Row(gl.CpuThreads == bits && head == Loc.F("run.load.head.wait", share, bits, Environment.ProcessorCount) && loadCut.Count == 0,
                $"the load box: «{head}» - {bits} the job's mask gives at {share} %; no text of the run page cut short",
                $"the load box: «{head}», the job's threads {gl.CpuThreads}, the mask's {bits} at {share} %; cut short: {string.Join("; ", loadCut.Take(4))}");

            // brief 25 A4: «Открытый космос» - its six rows only when it is the shape, the page's texts whole, a preset of it
            {
                var keepScratch = s.Scratch;
                var labels = new[] { "scr.space.islands", "scr.space.padonly", "scr.space.edges", "scr.space.spread", "scr.space.reach",
                                     "scr.space.bridges" }.Select(Loc.T).ToList();
                Generation.Current = null;
                s.ScratchMode = true;
                s.Scratch = new ScratchParams { Shape = "arena" };
                var aw = new MainWindow { _page = "generate" };
                aw.Rebuild();
                LayOut(aw, ScreenSizes[0], unfold: false);
                var shownArena = WordsOf(aw).Where(labels.Contains).Distinct().Count();
                var yard = Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == "space_yard");
                var sw = new MainWindow { _page = "generate" };
                sw.Rebuild();
                sw.LoadPreset(yard);
                var spaceCut = new List<string>();
                var spaceOver = new List<string>();
                foreach (var size in ScreenSizes)
                {
                    LayOut(sw, size, unfold: false);
                    spaceCut.AddRange(CutTexts(sw));
                    spaceOver.AddRange(TextOverlaps(sw));
                }
                var shownSpace = WordsOf(sw).Where(labels.Contains).Distinct().Count();
                var py = s.Scratch.ToPython();
                var asks = py.Contains("\"shape\":\"space\"") && py.Contains("\"islands\":12") && py.Contains("\"pad_reach\":\"long\"");
                Row(shownArena == 0 && shownSpace == 6 && spaceCut.Count == 0 && spaceOver.Count == 0 && asks
                    && sw._presetLabel?.Text == yard.Name,
                    $"«{Loc.T("scr.form.space")}»: its 6 rows only with that shape, the preset «{yard.Name}» asks its values, nothing cut or overlapping at both widths",
                    $"«{Loc.T("scr.form.space")}»: rows with arena {shownArena}, with space {shownSpace} of 6; asks {asks}; label «{sw._presetLabel?.Text}»; "
                    + $"cut {string.Join("; ", spaceCut.Take(3))}; over {string.Join("; ", spaceOver.Take(3))}");
                s.Scratch = keepScratch;
            }
            // brief 25 B: «Башня» - its four rows only when it is the shape (none of the space's), the page's texts whole
            // at both widths, a preset of it asks its values
            {
                var keepScratch = s.Scratch;
                var labels = new[] { "scr.tower.storeys", "scr.tower.height", "scr.tower.shafts", "scr.tower.perches" }.Select(Loc.T).ToList();
                var spaceLabels = new[] { "scr.space.islands", "scr.space.padonly", "scr.space.edges", "scr.space.spread", "scr.space.reach",
                                          "scr.space.bridges" }.Select(Loc.T).ToList();
                Generation.Current = null;
                s.ScratchMode = true;
                s.Scratch = new ScratchParams { Shape = "arena" };
                var aw = new MainWindow { _page = "generate" };
                aw.Rebuild();
                LayOut(aw, ScreenSizes[0], unfold: false);
                var shownArena = WordsOf(aw).Where(labels.Contains).Distinct().Count();
                var atrium = Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == "tower_atrium");
                var tw = new MainWindow { _page = "generate" };
                tw.Rebuild();
                tw.LoadPreset(atrium);
                var towerCut = new List<string>();
                var towerOver = new List<string>();
                foreach (var size in ScreenSizes)
                {
                    LayOut(tw, size, unfold: false);
                    towerCut.AddRange(CutTexts(tw));
                    towerOver.AddRange(TextOverlaps(tw));
                }
                var shownTower = WordsOf(tw).Where(labels.Contains).Distinct().Count();
                var shownSpaceRows = WordsOf(tw).Where(spaceLabels.Contains).Distinct().Count();
                var py = s.Scratch.ToPython();
                var asks = py.Contains("\"shape\":\"tower\"") && py.Contains("\"shafts\":1") && py.Contains("\"perches\":3");
                Row(shownArena == 0 && shownTower == 4 && shownSpaceRows == 0 && towerCut.Count == 0 && towerOver.Count == 0 && asks
                    && tw._presetLabel?.Text == atrium.Name,
                    $"«{Loc.T("scr.form.tower")}»: its 4 rows only with that shape, the preset «{atrium.Name}» asks its values, nothing cut or overlapping at both widths",
                    $"«{Loc.T("scr.form.tower")}»: rows with arena {shownArena}, with the tower {shownTower} of 4, the space's {shownSpaceRows}; asks {asks}; "
                    + $"label «{tw._presetLabel?.Text}»; cut {string.Join("; ", towerCut.Take(3))}; over {string.Join("; ", towerOver.Take(3))}");
                s.Scratch = keepScratch;
            }
            // 3.53 (brief 26): a map from scratch in the library with a jump pad or a teleporter - its covers look at
            // them (a view of each kind it holds, before the spawns'); none such in the library: SKIP
            {
                var withFx = Library.Scan(s).Where(m => m.Scratch != null && File.Exists(m.BspPath)).Select(m =>
                {
                    var ents = Covers.Entities(File.ReadAllBytes(m.BspPath));
                    return (m, pad: ents.Any(e => e.GetValueOrDefault("classname") == "trigger_push"),
                            tele: ents.Any(e => e.GetValueOrDefault("classname") == "misc_teleporter"));
                }).Where(x => x.pad || x.tele).ToList();
                if (withFx.Count == 0)
                    b.AppendLine("SKIP the covers of a map from scratch look at its pads and teleporters: no such map in the library");
                else
                {
                    var found = withFx.Select(x => (x.m, x.pad, x.tele, views: Covers.Fixtures(x.m.BspPath))).ToList();
                    var seen = found.Count(x => x.views.Count > 0);
                    var first = found.FirstOrDefault(x => x.views.Count > 0);
                    var inCovers = first.m != null && Covers.Viewpoints(first.m, s).Any(v => v.What is "pad" or "teleporter");
                    Row(seen > 0 && inCovers,
                        $"the covers look at the pads and teleporters: {seen} of {found.Count} maps from scratch holding them have such a view, and «{first.m?.Name}»'s covers take it",
                        $"the covers' fixture views: {seen} of {found.Count} maps; in «{first.m?.Name}»'s covers {inCovers}");
                }
            }
            // 3.52: the tower's four rows and «Корабли в небе» with every group open (the screens' check lays the page
            // out folded), both languages, both widths - shown, nothing cut, nothing over another
            {
                var keepScratch = s.Scratch;
                var keepLang352 = Loc.Language;
                var misses = new List<string>();
                var bad = new List<string>();
                foreach (var lang in new[] { "ru", "en" })
                {
                    Loc.Language = lang;
                    Generation.Current = null;
                    s.ScratchMode = true;
                    s.Scratch = new ScratchParams { Shape = "tower", Ships = 2, Players = 4 };
                    foreach (var size in ScreenSizes)
                    {
                        var ow = new MainWindow { _page = "generate" };
                        ow.Rebuild();
                        LayOut(ow, size, unfold: true);
                        var words = WordsOf(ow);
                        foreach (var key in new[] { "scr.tower.storeys", "scr.tower.height", "scr.tower.shafts", "scr.tower.perches", "scr.ships" })
                            if (!words.Contains(Loc.T(key)))
                                misses.Add($"{lang} {size.Width}: {Loc.T(key)}");
                        bad.AddRange(CutTexts(ow).Select(x => $"{lang} {size.Width} cut: {x}"));
                        bad.AddRange(TextOverlaps(ow).Select(x => $"{lang} {size.Width} over: {x}"));
                    }
                }
                Loc.Language = keepLang352;
                Row(misses.Count == 0 && bad.Count == 0,
                    "3.52's rows (the tower's four, «Корабли в небе») shown with every group open, both languages, both widths, nothing cut or over another",
                    $"3.52's rows: missing {string.Join("; ", misses.Take(4))}; {string.Join("; ", bad.Take(4))}{(bad.Count > 4 ? $" (+{bad.Count - 4})" : "")}");
                s.Scratch = keepScratch;
            }
            // the PO 06.11: «Случайный вариант» - on by default and the number's row hidden; off shows it; on again draws
            // a new number; the settings file keeps the switch
            {
                var keepRandom = s.SeedRandom;
                var keepSeed = s.Seed;
                s.SeedRandom = true;
                Generation.Current = null;
                var fw = new MainWindow { _page = "generate" };
                fw.Rebuild();
                var hiddenOn = fw._seedRow is { IsVisible: false } && fw._seedRandom?.IsChecked == true;
                if (fw._seedRandom != null)
                    fw._seedRandom.IsChecked = false;
                var shownOff = fw._seedRow is { IsVisible: true } && !s.SeedRandom;
                var before = s.Seed;
                if (fw._seedRandom != null)
                    fw._seedRandom.IsChecked = true;
                var drawn = s.SeedRandom && fw._seedRow is { IsVisible: false } && s.Seed != before && s.Seed is >= 1 and < 100000;
                var ini = Path.Combine(dir, "seed.ini");
                new Settings { SeedRandom = false }.Save(ini);
                var kept = !Settings.Load(ini).SeedRandom;
                Row(hiddenOn && shownOff && drawn && kept && new Settings().SeedRandom,
                    $"«{Loc.T("gen.seed.random")}»: on by default, the number hidden; off shows it; on again a new number ({before} → {s.Seed}); kept in the settings",
                    $"«{Loc.T("gen.seed.random")}»: hidden when on {hiddenOn}, shown when off {shownOff}, a new number when on again {drawn} ({before} → {s.Seed}), kept {kept}");
                s.SeedRandom = keepRandom;
                s.Seed = keepSeed;
            }
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the progress check threw: {ex.GetType().Name}: {ex.Message}");
        }
        finally
        {
            Generation.Current = keepCurrent;
            Loc.Language = keepLang;
            s.ScratchMode = keepMode;
            RunHistory.PathOverride = null;
            RunHistory.Forget();
            try
            {
                Directory.Delete(dir, true);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
            }
        }
    }
}
