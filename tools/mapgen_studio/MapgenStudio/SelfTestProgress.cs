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
    private static Generation FreshRun(string stage, bool fromScratch = true, bool deals = true)
    {
        var g = Generation.ForSelfTest(App.Settings, stage, fromScratch, deals);
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

            // brief 35 (the PO 11.11, mg_new_91126): the stages and the time left when no edit is tried
            {
                (List<(string key, bool done, bool now, string time)> rows, ProgressNow p) Look35(Generation g)
                {
                    var w = RunPage(g);
                    return (w._runView?.StageRows.ToList() ?? new(), RunProgress.Of(g));
                }
                Generation Redeal()
                {
                    // a run that deals (the stairway annexes asked): its edits shown (the PO 13.11 hid them on one that
                    // cannot deal)
                    var g = FreshRun("plan", deals: true);
                    g.StageBegan["redeal"] = DateTime.Now.AddSeconds(-33);
                    g.SetStageForSelfTest("redeal");
                    return g;
                }
                bool AllClocks(List<(string key, bool done, bool now, string time)> rows) => rows.Count > 0 && rows.All(r => !r.done && !r.now);
                // (a) a new deal with no edit after it: ticks before, one stage under way
                var (ra, pa) = Look35(Redeal());
                RunProgress.OldStages = true;
                var (ra0, pa0) = Look35(Redeal());
                RunProgress.OldStages = false;
                var nowRow = ra.FirstOrDefault(r => r.now);
                Row(!AllClocks(ra) && ra.Count(r => r.now) == 1 && nowRow.key == "attempt" && ra.TakeWhile(r => !r.now).All(r => r.done)
                    && AllClocks(ra0),
                    $"«Новый круг правок» with no edit after it: the stages before ticked, «{Loc.T("stage.attempt")}» under way (3.60: every stage an hourglass)",
                    $"a new deal with no edit: rows {string.Join(", ", ra.Select(r => $"{r.key}{(r.done ? "+" : r.now ? ">" : "-")}"))}; 3.60's all clocks {AllClocks(ra0)}");
                // (b) its time is the deal's, not 0
                Row(pa.InStage.TotalSeconds >= 30 && pa0.InStage.TotalSeconds < 2,
                    $"the edits' stage under a new deal has gone {GenerationView.Dur(pa.InStage)} (3.60: {GenerationView.Dur(pa0.InStage)})",
                    $"the edits' stage under a new deal: {GenerationView.Dur(pa.InStage)} (want ≥ 30 s), 3.60's {GenerationView.Dur(pa0.InStage)} (want 0)");
                // (c) the plan's and the edits' times once the checks began - a map from scratch with nothing to deal
                Generation Judged()
                {
                    var g = FreshRun("plan", deals: false);
                    g.StageBegan["plan"] = DateTime.Now.AddSeconds(-300);
                    g.StageBegan["judge"] = DateTime.Now.AddSeconds(-17);
                    g.SetStageForSelfTest("judge");
                    return g;
                }
                // the PO 13.11 («зачем в окне генерации новой карты этап Правки и отдельная даже секция для него?»): no
                // «Составление плана правок», no «Правки» - the plan's time is the base's build, ended when the checks
                // began; 3.67 showed both, the edits «нет»
                var (rc, _) = Look35(Judged());
                Generation.OldScratchEdits = true;
                var (rc0, _) = Look35(Judged());
                Generation.OldScratchEdits = false;
                string TimeOf(List<(string key, bool done, bool now, string time)> rows, string key) => rows.FirstOrDefault(r => r.key == key).time ?? "";
                var baseT = TimeOf(rc, "baseline");
                Row(!rc.Any(r => r.key is "plan" or "attempt") && rc.Any(r => r.key == "baseline" && r.done) && baseT.Length > 0
                    && rc0.Any(r => r.key == "attempt") && TimeOf(rc0, "attempt") == Loc.T("run.stage.attempt.none.s"),
                    $"a map from scratch with nothing to deal, after the checks began: no «{Loc.T("stage.plan.s")}», no «{Loc.T("stage.attempt")}»; «{Loc.T("stage.baseline")}» {baseT} (3.67 had both, the edits «{TimeOf(rc0, "attempt")}»)",
                    $"a map from scratch with nothing to deal: rows {string.Join(", ", rc.Select(r => r.key))}, the base «{baseT}»; 3.67's rows {string.Join(", ", rc0.Select(r => r.key))}");
                // and its page has no card «Правки» (the scheme's legend keeps its own word); a run with the stairway
                // annexes asked has it
                bool EditsCardShown(Generation g) =>
                    RunPage(g).GetLogicalDescendants().OfType<Border>().FirstOrDefault(x => x.Tag as string == "run-edits") is { IsVisible: true };
                var hShown = EditsCardShown(FreshRun("judge", deals: false));
                var dShown = EditsCardShown(FreshRun("judge"));
                Row(!hShown && dShown,
                    $"the run page: no card «{Loc.T("run.edits.head")}» on a map from scratch with nothing to deal, its card on one with the stairway annexes asked",
                    $"the run page: card «{Loc.T("run.edits.head")}» shown with nothing to deal {hShown}, with the annexes {dShown}");
                // (d) a stage past its expectation: the left line says so and grows
                Generation Long(int seconds)
                {
                    var g = FreshRun("plan");
                    g.StageBegan["plan"] = DateTime.Now.AddSeconds(-seconds);
                    return g;
                }
                var later = RunProgress.StagesOf(Long(283)).SkipWhile(x => x != "plan").Skip(1).Sum(x => RunProgress.Expected(Long(283), x));
                var p283 = RunProgress.Of(Long(283));
                var p120 = RunProgress.Of(Long(120));
                var line283 = RunProgress.LeftLine(Long(283), p283);
                RunProgress.OldTimeLeft = true;
                var p283old = RunProgress.Of(Long(283));
                var line283old = RunProgress.LeftLine(Long(283), p283old);
                RunProgress.OldTimeLeft = false;
                var over = Loc.T("run.progress.left.over");
                var overHead = over[..over.IndexOf('{')];
                Row(line283.StartsWith(overHead, StringComparison.Ordinal) && p283.Left > p120.Left && p283.Left!.Value.TotalSeconds > later
                    && !line283old.StartsWith(overHead, StringComparison.Ordinal) && Math.Abs(p283old.Left!.Value.TotalSeconds - later) < 1,
                    $"a stage 283 s into its expected {RunProgress.Expected(Long(283), "plan"):0}: «{line283}» - grows with it ({p120.Left?.TotalSeconds:0} → {p283.Left?.TotalSeconds:0} s; 3.60 froze at {later:0})",
                    $"past its expectation: «{line283}», left {p120.Left?.TotalSeconds:0} → {p283.Left?.TotalSeconds:0} s (later stages {later:0}); 3.60 «{line283old}» {p283old.Left?.TotalSeconds:0}");
                // (d2) the PO 11.11 (mg_new_8695): «Осталось не меньше меньше минуты - это как?» - a last stage past its
                // expectation with under a minute left says the seconds
                Generation LongCover()
                {
                    // the run's own last stage (no «Обложка» where covers are off after a generation)
                    var g = FreshRun("gates");
                    var last = RunProgress.StagesOf(g).Last(x => x != "done");
                    g.SetStageForSelfTest(last);
                    g.StageBegan[last] = DateTime.Now.AddSeconds(-(RunProgress.Expected(g, last) + 40));
                    return g;
                }
                var pc = RunProgress.Of(LongCover());
                var lineC = RunProgress.LeftLine(LongCover(), pc);
                RunProgress.OldOverWords = true;
                var lineCold = RunProgress.LeftLine(LongCover(), RunProgress.Of(LongCover()));
                RunProgress.OldOverWords = false;
                var under = Loc.T("run.progress.under.minute");
                Row(pc.Over && pc.Left!.Value.TotalSeconds < 60 && !lineC.Contains(under) && lineC.StartsWith(overHead, StringComparison.Ordinal)
                    && lineCold.Contains(under),
                    $"the last stage past its expectation, {pc.Left?.TotalSeconds:0} s left: «{lineC}» (3.62: «{lineCold}»)",
                    $"under a minute past the expectation: «{lineC}»; 3.62's way «{lineCold}»");
                // (d3) the PO 11.11: «добавить бы визуализации света на готовой карте» - the finished map's lamps drawn
                // and moving while its light is fitted
                var lit = new SchemeModel.Snapshot();
                lit.Lamps.Add(new Lamp(System.Numerics.Vector3.Zero, System.Numerics.Vector3.One, 300, null));
                var relight = FreshRun("cover");
                relight.SetStageForSelfTest("relight");
                var art = StageArt.Now(relight, lit);
                var moving = StageArt.Moving(relight, lit);
                StageArt.OldRelight = true;
                var artOld = StageArt.Now(relight, lit);
                StageArt.OldRelight = false;
                Row(art.Lamps && art.Glow > 0.5f && moving && art.Caption == Loc.F("art.relight", 1) && !artOld.Lamps,
                    $"«{Loc.T("stage.relight")}»: the map's lamps drawn, glowing {art.Glow:0.00}, the picture moving, «{art.Caption}» (3.62: no lamps)",
                    $"«{Loc.T("stage.relight")}»: lamps {art.Lamps}, glow {art.Glow:0.00}, moving {moving}, «{art.Caption}»; 3.62's way lamps {artOld.Lamps}");
                // (e) a stage expected from the nearest player count
                string Rec(string name, int players, int minutes, int plan) => string.Join("\n", new[]
                {
                    $"made={DateTime.Now.AddDays(-1):O}", "scratch=1", $"players={players}", $"minutes={minutes}", $"stage.plan={plan}",
                });
                foreach (var (n, pl, mi, pv) in new[] { ("mg_r2", 2, 30, 10), ("mg_r8", 8, 30, 20), ("mg_r16", 16, 60, 40) })
                    File.WriteAllText(Path.Combine(dir, "descriptions", $"{n}.info.txt"), Rec(n, pl, mi, pv));
                RunHistory.Forget();
                var e12 = RunHistory.Expected("plan", 12, 30);
                var e8 = RunHistory.Expected("plan", 8, 30);
                var e3 = RunHistory.Expected("plan", 3, 30);
                foreach (var n in new[] { "mg_r2", "mg_r8", "mg_r16" })
                    File.Delete(Path.Combine(dir, "descriptions", $"{n}.info.txt"));
                RunHistory.Forget();
                Row(e12 == 40 && e8 == 20 && e3 == 10,
                    $"a stage's expectation from the nearest player count: 12 players → the 16-player record ({e12} s), 8 → its own ({e8}), 3 → the duel's ({e3})",
                    $"the nearest player count: 12 → {e12} (want 40), 8 → {e8} (want 20), 3 → {e3} (want 10)");
                // (f) the plan card of a map from scratch: no family it skips
                var gf = FreshRun("attempt", deals: false);
                foreach (var (k, v) in new[] { ("digs", 5), ("windows", 17), ("rooms_copy", 2) })
                    gf.Planned[k] = v;
                var planRows = gf.PlanRows();
                Row(planRows.Count == 0 && gf.NothingToDeal,
                    "the plan card of a map from scratch: none of «Новые проходы», «Окна», «Комнаты из основы» (families it never deals)",
                    $"the plan card of a map from scratch shows {string.Join(", ", planRows.Select(r => r.name))}");
                // (g) the PO's own run, line by line: at no line every stage waiting
                var his = new[]
                {
                    "PROGRESS stage=start map=q2mg fidelity=70 seed=91126 target=300 resume=0 elapsed=0",
                    "PROGRESS stage=baseline elapsed=0",
                    "PROGRESS stage=plan offered=414 budget=300 target=300 digs=5 annexes=0 storeys=0 spans=0 floods=0 windows=17 reliquids=0 stairways=0 remodels=0 blocks=0 floor_shifts=0 stair_reshapes=0 elapsed=30",
                    "PROGRESS stage=plan-rooms copies=2 elapsed=30",
                    "PROGRESS stage=plan-value round=0 proved=0 worthy=0 declined=7 refused=10 builds=0 can=0 have=0 target=300 large=5 ms=1806 cells=0 summed=0 tried=0/0 elapsed=32",
                    "PROGRESS stage=plan-turns round=0 first=0,1,2,3,4,5,6,7 elapsed=32",
                    "PROGRESS stage=redeal round=1 offered=414 fresh=0 elapsed=313",
                    "PROGRESS stage=plan-value round=1 proved=0 worthy=0 declined=7 refused=10 builds=0 can=0 have=0 target=300 large=5 ms=1891 cells=0 summed=0 tried=0/0 elapsed=315",
                    "PROGRESS stage=plan-exhausted round=1 tried=0 elapsed=315",
                    "PROGRESS stage=ladder not_applied=0 proved=0 tried=0 paint=0 builds=0 whole=0 taken=0 elapsed=315",
                    "PROGRESS stage=judge elapsed=365",
                };
                List<string> Fed(bool old)
                {
                    RunProgress.OldStages = old;
                    var g = FreshRun("scratch", deals: false);
                    var bad = new List<string>();
                    foreach (var line in his)
                    {
                        g.TakeForSelfTest(line);
                        var (rows, _) = Look35(g);
                        if (AllClocks(rows))
                            bad.Add(line[(line.IndexOf("stage=", StringComparison.Ordinal) + 6)..].Split(' ')[0]);
                    }
                    RunProgress.OldStages = false;
                    return bad;
                }
                var badNow = Fed(false);
                var badOld = Fed(true);
                Row(badNow.Count == 0 && badOld.Count > 0,
                    $"the PO's mg_new_91126 fed line by line: at no line every stage waiting (3.60: after «{string.Join("», «", badOld.Distinct())}»)",
                    $"the PO's run fed line by line: every stage waiting after {string.Join(", ", badNow)}; 3.60 after {string.Join(", ", badOld)} (want some)");
                Generation.Current = null;
            }

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
