namespace MapgenStudio;

/// <summary>«Ход работы» at a moment: the whole build's percent, the time left, the stage k of n and what it is doing.</summary>
public sealed record ProgressNow(double Percent, TimeSpan? Left, bool Soon, int At, int Count, string Stage, string Inner,
                                 TimeSpan InStage, bool Over = false, TimeSpan Usual = default);

/// <summary>
/// Brief 24 D1 (the PO 06.11, his run page of a new map: «какой для меня как пользователя глубокий смысл про этот блок
/// отличия от каркаса? Мы строим новую карту … тут нужно рисовать общий прогресс построения, процент текущий до конца,
/// сколько осталось времени»). The whole build as stages, each weighed by the seconds it is expected to take: the
/// stages passed count whole, the one under way by how far it is (the skeleton by its own log, the edits by the time
/// they have left, the rest by their time against their expectation). Never backwards within a run; a stage past its
/// expectation stays at 95 % of its weight until it ends.
/// </summary>
public static class RunProgress
{
    /// <summary>
    /// The expected seconds of a stage before any record of the kind: the PO's run mg_new_6730 of 06.11 (8 players,
    /// 30 minutes, the Studio's textures, destruction, the cover; tools/fable_oracles/mapgen_2026-11-06_run_stage_times),
    /// the skeleton as brief 24 D3 made it (measured by tools/check_mapgen_scratch_parallel.py, 8 players).
    /// </summary>
    public static readonly IReadOnlyDictionary<string, double> Builtin = new Dictionary<string, double>
    {
        ["scratch"] = 90, ["start"] = 5, ["warp"] = 120, ["baseline"] = 150, ["plan"] = 15, ["attempt"] = 240,
        ["judge"] = 20, ["light"] = 30, ["gates"] = 140, ["destruction"] = 15, ["relight"] = 95, ["cover"] = 120,
    };

    /// <summary>The stage a progress line belongs to: a new deal and a resume are the edits', the engine's finish the light's.</summary>
    public static string Canonical(string stage) => stage switch
    {
        "resume" or "redeal" => "attempt",
        "finish" => "light",
        _ => stage,
    };

    /// <summary>
    /// Brief 35 (the PO 11.11, mg_new_91126: «Правки — идёт 0 с» beside «Новый круг правок — идёт 33 с»): when a stage
    /// began - the earliest of the keys it is made of (a new deal, a resume are the edits'); null when it has not.
    /// </summary>
    public static DateTime? BeganOf(Generation g, string stage)
    {
        DateTime? best = null;
        foreach (var kv in g.StageBegan)
            if (Canonical(kv.Key) == stage && (best == null || kv.Value < best))
                best = kv.Value;
        return best;
    }

    /// <summary>
    /// Brief 35 (the PO 11.11: no «шёл …» under «Составление плана отделки» and «Правки»): a stage ends when any later
    /// stage of the list begins - the edits a run went past without beginning do not hold the plan's end back.
    /// </summary>
    public static DateTime? EndOf(Generation g, string[] stages, int k)
    {
        DateTime? best = null;
        for (var j = k + 1; j < stages.Length; j++)
            if (BeganOf(g, stages[j]) is { } t && (best == null || t < best))
                best = t;
        return best;
    }

    /// <summary>
    /// Brief 35 (the PO 11.11: «пройденные этапы все стали с песочными часами»): the row of the stage under way - the
    /// line's stage by <see cref="Canonical"/>, else the last stage begun (a stage the list does not name never leaves
    /// every row waiting).
    /// </summary>
    public static int AtOf(Generation g, string[] stages)
    {
        var at = Array.IndexOf(stages, Canonical(g.Stage));
        if (at >= 0)
            return at;
        var reached = 0;
        for (var k = 0; k < stages.Length; k++)
            if (BeganOf(g, stages[k]) != null)
                reached = k;
        return reached;
    }

    /// <summary>The 3.60 reading of the stages (the next ROW's begin, no Canonical in the list), for the self-test's RED.</summary>
    internal static bool OldStages;

    /// <summary>The 3.60 time left past a stage's expectation (frozen), for the self-test's RED.</summary>
    internal static bool OldTimeLeft;

    /// <summary>Past its expectation a stage is counted to take this much more of the time it has already taken.</summary>
    public const double OverrunShare = 0.25;

    /// <summary>The run's stages, the end aside; the cover only when one is to be taken.</summary>
    public static string[] StagesOf(Generation g) =>
        GenerationView.StagesOf(g).Where(s => s != "done" && (s != "cover" || g.CoverPlanned)).ToArray();

    /// <summary>
    /// The seconds a stage of this run is expected to take: the mean of the last records of the same kind (players and
    /// minutes), else of any map from scratch, else the built-in. The edits never longer than the engine may take them:
    /// the minutes asked less what it keeps back for after the edits (240 s + 1/30) and its own start.
    /// </summary>
    public static double Expected(Generation g, string stage)
    {
        var minutes = g.Request.TimeMinutes;
        var e = RunHistory.Expected(stage, g.ScratchPlayers, minutes) ?? Builtin.GetValueOrDefault(stage, 30);
        if (stage == "attempt" && minutes > 0)
        {
            var before = new[] { "start", "baseline", "plan" }.Sum(s => RunHistory.Expected(s, g.ScratchPlayers, minutes) ?? Builtin[s]);
            var most = minutes * 60.0 - (240 + minutes * 2.0) - before;
            e = Math.Min(e, Math.Max(30, most));
        }
        return Math.Max(1, e);
    }

    /// <summary>The run's «Ход работы» now (for a run that ended: 100, or where it stopped).</summary>
    public static ProgressNow Of(Generation g)
    {
        var stages = StagesOf(g);
        var n = stages.Length;
        var now = DateTime.Now;
        var reached = 0;
        for (var k = 0; k < n; k++)
            if (g.StageBegan.ContainsKey(stages[k]))
                reached = k;
        if (!g.Running)
        {
            if (g.Error.Length == 0)
                return new ProgressNow(100, TimeSpan.Zero, false, n, n, "done", "", TimeSpan.Zero);
            return new ProgressNow(g.ShownPercent, null, false, reached + 1, n, stages[reached], "", TimeSpan.Zero);
        }
        var cur = Canonical(g.Stage);
        var at = Array.IndexOf(stages, cur);
        if (at < 0)
        {
            at = OldStages ? reached : AtOf(g, stages);
            cur = stages[at];
        }
        var exp = stages.Select(s => Expected(g, s)).ToArray();
        var since = OldStages ? (g.StageBegan.TryGetValue(cur, out var t) ? t : now) : BeganOf(g, cur) ?? now;
        var worked = g.Worked(since, now).TotalSeconds;
        double frac, leftCur;
        var counted = false;
        var inner = "";
        switch (cur)
        {
            case "scratch":
                frac = g.ScratchFraction;
                inner = g.ScratchSaid;
                if (frac >= 0.1)
                {
                    // the skeleton's own pace: as long again as its part done took, for the part left
                    leftCur = Math.Max(0, worked / frac - worked);
                    counted = true;
                }
                else
                    leftCur = Math.Max(0, exp[at] - worked);
                break;
            case "attempt":
                inner = g.Compiles > 0 || g.Attempts > 0 ? Loc.F("run.progress.edits", g.Compiles, g.Accepted) : "";
                if (g.PlanExhausted)
                {
                    frac = 0.95;
                    leftCur = 0;
                    counted = true;
                    inner = Loc.T("run.progress.edits.over");
                }
                else if (GenerationView.EditsLeft(g) is { } el)
                {
                    leftCur = el.TotalSeconds;
                    frac = worked / Math.Max(1, worked + leftCur);
                    counted = true;
                }
                else
                {
                    frac = worked / exp[at];
                    leftCur = Math.Max(0, exp[at] - worked);
                }
                break;
            default:
                frac = worked / exp[at];
                leftCur = Math.Max(0, exp[at] - worked);
                break;
        }
        var overran = !counted && worked > exp[at];
        // brief 35 (the PO 11.11: «алгоритм должен понимать что время увеличивается»): past its expectation a stage
        // is not over - what is left of it grows with the time it has taken, and the line says so
        var over = overran && !OldTimeLeft;
        if (over)
            leftCur = worked * OverrunShare;
        frac = Math.Clamp(frac, 0, overran ? 0.95 : 0.99);
        var total = exp.Sum();
        var done = exp.Take(at).Sum() + frac * exp[at];
        var pct = Math.Max(g.ShownPercent, Math.Min(99, 100 * done / total));
        g.ShownPercent = pct;
        var future = exp.Skip(at + 1).Sum();
        var left = TimeSpan.FromSeconds(leftCur + future);
        // the first seconds of a run: nothing measured yet - «считаю…»
        TimeSpan? said = g.Worked(g.Began, now).TotalSeconds < 5 ? null : left;
        return new ProgressNow(pct, said, !over && overran && future < 60, at + 1, n, cur, inner, TimeSpan.FromSeconds(worked), over,
                               TimeSpan.FromSeconds(exp[at]));
    }

    /// <summary>The time left in round words: «меньше минуты», «6 мин», «1 ч 05 мин».</summary>
    public static string LeftWords(TimeSpan t)
    {
        if (t.TotalSeconds < 60)
            return Loc.T("run.progress.under.minute");
        var m = (int)Math.Ceiling(t.TotalMinutes);
        return m >= 60 ? Loc.F("run.progress.hm", m / 60, (m % 60).ToString("00")) : Loc.F("run.progress.m", m);
    }

    /// <summary>The line of the time left: «Осталось около 6 мин, закончится около 12:36», «… ещё немного», «… считаю…».</summary>
    public static string LeftLine(Generation g, ProgressNow p)
    {
        if (g.Paused)
            return Loc.T("run.progress.paused");
        if (p.Left is not { } left)
            return Loc.T("run.progress.left.wait");
        if (p.Soon)
            return Loc.T("run.progress.left.soon");
        if (p.Over)
            return Loc.F("run.progress.left.over", LeftWords(left), GenerationView.Dur(p.Usual), GenerationView.Dur(p.InStage));
        return Loc.F("run.progress.left", LeftWords(left), (DateTime.Now + left).ToString("HH:mm"));
    }
}

/// <summary>
/// Brief 24 D1: what the stages of the maps made before took - each map's record (data\descriptions\NAME.info.txt) says
/// `scratch=`, `players=`, `minutes=` and a `stage.KEY=SECONDS` line per stage. Read once, forgotten when a run ends.
/// </summary>
public static class RunHistory
{
    /// <summary>The self-test's own folder (never the user's).</summary>
    public static string? PathOverride { get; set; }

    private static List<Dictionary<string, string>>? s_records;

    public static void Forget() => s_records = null;

    private static List<Dictionary<string, string>> Records()
    {
        if (s_records != null)
            return s_records;
        s_records = new List<Dictionary<string, string>>();
        try
        {
            var dir = PathOverride ?? App.Settings.DescriptionsPath;
            if (!Directory.Exists(dir))
                return s_records;
            foreach (var f in Directory.EnumerateFiles(dir, "*.info.txt"))
            {
                var d = new Dictionary<string, string>();
                foreach (var line in File.ReadAllLines(f))
                    if (line.IndexOf('=') is var eq && eq > 0)
                        d[line[..eq]] = line[(eq + 1)..];
                if (d.GetValueOrDefault("scratch") == "1" && d.Keys.Any(k => k.StartsWith("stage.", StringComparison.Ordinal)))
                    s_records.Add(d);
            }
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
        }
        return s_records;
    }

    /// <summary>
    /// The mean seconds of a stage over the last five maps from scratch of these players and minutes; else of these
    /// players; else of the nearest player count that has any (a tie: the larger) - brief 35, the PO's 12-player run was
    /// expected from duels; null when none.
    /// </summary>
    public static double? Expected(string stage, int players, int minutes)
    {
        var key = "stage." + stage;
        var have = Records().Where(r => r.ContainsKey(key) && double.TryParse(r[key], out _)).ToList();
        if (have.Count == 0)
            return null;
        static int PlayersOf(Dictionary<string, string> r) => int.TryParse(r.GetValueOrDefault("players"), out var p) ? p : 0;
        var same = have.Where(r => PlayersOf(r) == players && r.GetValueOrDefault("minutes") == minutes.ToString()).ToList();
        if (same.Count == 0)
            same = have.Where(r => PlayersOf(r) == players).ToList();
        if (same.Count == 0)
        {
            var nearest = have.Select(PlayersOf).Distinct().OrderBy(p => Math.Abs(p - players)).ThenByDescending(p => p).First();
            same = have.Where(r => PlayersOf(r) == nearest).ToList();
        }
        var use = same.OrderByDescending(r => r.GetValueOrDefault("made", "")).Take(5).ToList();
        return use.Average(r => double.Parse(r[key]));
    }
}
