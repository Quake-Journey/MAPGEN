using System.Diagnostics;
using System.Globalization;
using System.Text.RegularExpressions;

namespace MapgenStudio;

/// <summary>What a run is asked to make.</summary>
public sealed record GenerationRequest(string Name, string Donor, int Fidelity, long Seed, IReadOnlyList<string> SkipFamilies,
                                       bool SaveMapSource, bool Draft = false, int MaxAttempts = 0, bool RunGates = true,
                                       IReadOnlyList<string>? Grafts = null, bool Cover = true,
                                       GenerationOptions? Options = null);

/// <summary>
/// Row 410 (the PO, 05.10: «какие еще параметры добавить в генератор ... чтобы получать больше вариаций
/// творчества»): the plan's own counts and sizes, 0 each for «По умолчанию» - the likeness decides.
/// AnnexSize 0 default, 1 small, 2 medium, 3 large, 4 halls.
/// Decor (row 412, the PO: «украшения на стенах ... Можно также это вынести в параметры»): the base's own wall pieces
/// - its lamps and the ornaments it repeats - on the generator's tunnels: 0 default, 1 none, 2 few, 3 many, 4 most.
/// </summary>
/// NewWater / NewSlime / NewLava (row 412, the PO: «А добавление новых жидкостей можно регулировать? ... вообще
/// выключать или менять количество», «аналогичные параметры для заливки лавой и кислотой»): the share of the rooms the
/// floods may take that each liquid fills, 0..100 - or -1, «По умолчанию», the generator's own say.
/// Stairways (brief 11 D1): stairways up the rooms' walls, 0..10 - 0 «Нет», the default.
/// Destruction (brief 11 D2): the finished map D percent in ruins, 0..100 - 0 (the default) nothing; a step after the
/// map's checks (tools/mapgen_destroy.py), not a word of the pipeline's.
public sealed record GenerationOptions(int Digs = 0, int Annexes = 0, int AnnexSize = 0, int Storeys = 0, int Spans = 0,
                                       int Halls = 0, string Liquids = "", int Decor = 0, int NewWater = -1,
                                       int NewSlime = -1, int NewLava = -1, int Stairways = 0, int Destruction = 0)
{
    /// <summary>The engine's percent of its rule for each Decor level.</summary>
    public static readonly int[] DecorPercent = { 100, 0, 50, 150, 200 };

    public static readonly float[][] AnnexSizes =
    {
        new[] { 0f, 0f, 0f }, new[] { 256f, 256f, 192f }, new[] { 384f, 384f, 256f }, new[] { 512f, 512f, 288f },
        new[] { 768f, 768f, 320f },
    };

    /// <summary>The pipeline's words for them - none for a default.</summary>
    public IEnumerable<string> Args()
    {
        if (Digs > 0)
            yield return "--digs"; 
        if (Digs > 0)
            yield return Digs.ToString(CultureInfo.InvariantCulture);
        if (Annexes > 0 || AnnexSize > 0)
        {
            var size = AnnexSizes[Math.Clamp(AnnexSize, 0, AnnexSizes.Length - 1)];
            yield return "--annexes";
            yield return Annexes.ToString(CultureInfo.InvariantCulture);
            foreach (var v in size)
                yield return v.ToString(CultureInfo.InvariantCulture);
        }
        if (Storeys > 0)
        {
            yield return "--storeys";
            yield return Storeys.ToString(CultureInfo.InvariantCulture);
        }
        if (Spans > 0)
        {
            yield return "--spans";
            yield return Spans.ToString(CultureInfo.InvariantCulture);
        }
        if (Halls > 0)
        {
            yield return "--halls";
            yield return Halls.ToString(CultureInfo.InvariantCulture);
        }
        if (Liquids.Length > 0)
        {
            yield return "--liquids";
            yield return Liquids;
        }
        if (Decor > 0 && Decor < DecorPercent.Length)
        {
            yield return "--decor";
            yield return DecorPercent[Decor].ToString(CultureInfo.InvariantCulture);
        }
        if (Stairways > 0)
        {
            yield return "--stairways";
            yield return Math.Min(Stairways, 10).ToString(CultureInfo.InvariantCulture);
        }
        foreach (var (flag, value) in new[] { ("--new-water", NewWater), ("--new-slime", NewSlime), ("--new-lava", NewLava) })
            if (value >= 0)
            {
                yield return flag;
                yield return Math.Min(value, 100).ToString(CultureInfo.InvariantCulture);
            }
    }
}

/// <summary>
/// One generation (phase P2): the engine's <c>pipeline.exe</c> in a job object (<see cref="NativeJob"/>), its
/// <c>progress.txt</c> read as it grows (G1), the CPU share re-applied by the clock (R5), pause / resume / stop (R7),
/// then the map's checks and the map moved into the library (P3). Polled by the window's timer - never blocks it.
/// </summary>
public sealed class Generation
{
    public static Generation? Current { get; set; }

    /// <summary>
    /// Generations still to run, one after another (row 399: a map from each chosen base) - never two at once,
    /// the machine's share is one generation's.
    /// </summary>
    public static List<GenerationRequest> Queue { get; } = new();

    /// <summary>The next queued generation started once the current one has ended; true when one was.</summary>
    public static bool StartNext(Settings s)
    {
        if (Current is { Running: true } || Queue.Count == 0)
            return false;
        var next = Queue[0];
        Queue.RemoveAt(0);
        Start(next, s);
        return true;
    }

    public GenerationRequest Request { get; }
    public string RunDir { get; }
    public string JobDir => Path.Combine(RunDir, "job");
    public DateTime Began { get; } = DateTime.Now;
    public DateTime? Ended { get; private set; }

    public string Stage { get; private set; } = "start";          // start baseline plan attempt judge light finish gates done
    public Dictionary<string, DateTime> StageBegan { get; } = new();
    public int Offered { get; private set; }
    public int Budget { get; private set; }
    public int Target { get; private set; }
    public int Accepted { get; private set; }
    public int Compiles { get; private set; }
    public int Attempts { get; private set; }
    public int Divergence { get; private set; }
    public string LastFamily { get; private set; } = "";
    public string LastVerdict { get; private set; } = "";
    public string Result { get; private set; } = "";
    /// <summary>Row 412 (the PO: «пусть пишет точные причины»): why the engine refused the base at its first step -
    /// the parts of the copy that differ from the original (the engine's axis names) and its own words.</summary>
    public string BaselineAxes { get; private set; } = "";
    public string BaselineWhat { get; private set; } = "";

    /// <summary>The refusal of the base said plainly: which parts differ, then the engine's exact words.</summary>
    public string BaselineSaid()
    {
        var parts = BaselineAxes.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                                .Select(a => Loc.Has($"baseline.axis.{a}") ? Loc.T($"baseline.axis.{a}") : a).ToList();
        return parts.Count == 0 ? Loc.T("result.ERR_BASELINE")
                                : Loc.F("result.ERR_BASELINE.why", string.Join(", ", parts), BaselineWhat);
    }
    public string Artifact { get; private set; } = "";
    public bool Paused { get; private set; }
    /// <summary>A resumed run replaying its ledger (its attempt lines say pass=replay): builds that cost nothing.</summary>
    public bool Replaying { get; private set; }
    /// <summary>Row 410: the plan's new building in words, from its «stage=plan» line; empty before it.</summary>
    public string PlanMade { get; private set; } = "";
    /// <summary>
    /// Row 410: when each NEW build was seen (an attempt line whose build count rose, not a replayed one) - the pace
    /// the window's estimate is taken from. The PO, 05.10: the estimate stood at 16-18 minutes for a quarter of an
    /// hour - it averaged over a start that held the replay's instant builds, so it crept up as fast as time went.
    /// </summary>
    public readonly List<(DateTime at, int divergence)> BuildsSeen = new();
    /* row 410: the edit being tried now, from its «stage=try» line, until its verdict's line - the plan of the build */
    public int TryEdit { get; private set; } = -1;
    /* row 411 (the PO, 05.10: «доп параметры - это как то учитывается тоже в прогрессе?»): what the plan holds of each
       kind the creative options change, and how many of them were accepted; the edit the run is at */
    public Dictionary<string, int> Planned { get; } = new();
    public Dictionary<string, int> Done { get; } = new();
    public int AtEdit { get; private set; } = -1;
    /* row 411: the light compile's step - «vis» or «rad», its pass, the tenths of it done */
    public string LightStep { get; private set; } = "";
    public int LightPass { get; private set; }
    public int LightTenths { get; private set; }
    /* row 411 (the PO, 05.10: «лог похоже не изменяется уже давно ... у нас уже совсем другая стадия идет»): the
       run's own events - each stage begun, each step of the light pass - for the plan's feed beside the edits */
    private readonly List<(DateTime when, string what)> _events = new();

    public List<(DateTime when, string what)> Events()
    {
        lock (_events)
            return _events.ToList();
    }

    private void Event(string what)
    {
        lock (_events)
            _events.Add((DateTime.Now, what));
    }

    /// <summary>The kind of edit a plan line counts: a dig by its shape, the rest by family; "" for the others.</summary>
    public static string Category(string family, string shape) => family switch
    {
        "dig" => shape switch { "annex" => "annexes", "storeys" => "storeys", "room-of" => "rooms_from", "room-copy" => "rooms_copy", _ => "digs" },
        "span" => "spans",
        "flood" => "floods",
        "window" => "windows",
        "reliquid" => "reliquids",
        "stairway" => "stairways",
        _ => "",
    };

    /// <summary>The plan's kinds as done of planned, in the plan line's order: "" when the plan held none.</summary>
    public string PlanDone()
    {
        var parts = new List<string>();
        foreach (var k in new[] { "digs", "annexes", "storeys", "spans", "floods", "windows", "reliquids", "stairways", "rooms_from", "rooms_copy", "skins_from" })
            if (Planned.GetValueOrDefault(k) > 0)
                parts.Add(Loc.F($"plan.cat.{k}", Done.GetValueOrDefault(k), Planned[k], SecondName));
        return parts.Count > 0 ? Loc.F("run.plan.done", string.Join(", ", parts)) : "";
    }

    /* brief 9 D4: the second map - its name and what the plan dealt of it and why not more */
    public string SecondName { get; private set; } = "";
    public Dictionary<string, int> Second { get; } = new();

    /// <summary>
    /// Brief 9 D4 (the PO, 05.10: «Генератор сказал, что ничего из koldduel1 не подошло - как так?»): what the second
    /// map gave the finished map, in words - its rooms built and the rooms in its skin; when nothing, the reasons by
    /// count. "" when no second map was given.
    /// </summary>
    public string SecondSaid()
    {
        if (Request.Grafts is not { Count: > 0 } grafts)
            return "";
        var name = SecondName.Length > 0 ? SecondName : grafts[0];
        var rooms = Done.GetValueOrDefault("rooms_from") + Done.GetValueOrDefault("exchanges");
        var skins = Done.GetValueOrDefault("skins_from");
        if (rooms + skins > 0)
            return Loc.F("second.gave", name, rooms, skins);
        var why = new List<string>();
        if (Second.GetValueOrDefault("nosite") > 0) why.Add(Loc.F("second.why.nosite", Second["nosite"]));
        if (Second.GetValueOrDefault("empty") > 0) why.Add(Loc.F("second.why.empty", Second["empty"]));
        if (Second.GetValueOrDefault("size") > 0) why.Add(Loc.F("second.why.size", Second["size"]));
        if (Second.GetValueOrDefault("nopickup") > 0) why.Add(Loc.F("second.why.nopickup", Second["nopickup"]));
        if (Second.GetValueOrDefault("rooms") + Second.GetValueOrDefault("skins") > 0)
            why.Add(Loc.F("second.why.rejected", Second.GetValueOrDefault("rooms") + Second.GetValueOrDefault("skins")));
        return Loc.F("second.none", name, why.Count > 0 ? string.Join("; ", why) : Loc.T("second.why.unknown"));
    }

    /// <summary>The light compile's step in words with its share done, "" when none is known.</summary>
    public string LightNow() => LightStep.Length == 0 ? "" : Loc.F("light.step", LightStep switch
    {
        "bsp" => Loc.T("light.step.bsp"),
        "vis" => LightPass switch { 0 => Loc.T("light.step.vis0"), 1 => Loc.T("light.step.vis1"), _ => Loc.T("light.step.vis2") },
        "rad" => LightPass == 0 ? Loc.T("light.step.rad0") : Loc.F("light.step.radn", LightPass),
        _ => LightStep,
    }, LightTenths * 10);
    public string TryFamily { get; private set; } = "";
    public float[]? TryBox { get; private set; }
    public DateTime TryAt { get; private set; }
    public bool Running => Ended == null;
    public bool Crashed { get; private set; }
    public string CrashText { get; private set; } = "";
    public string Error { get; private set; } = "";
    public List<(bool pass, string what)> Gates { get; } = new();
    public string LibraryName { get; private set; } = "";
    public List<string> Log { get; } = new();

    private readonly Settings _s;
    private NativeJob? _job;
    private long _read;
    private int _sharePercent = -1;
    private NativeJob? _gatesJob;
    private string _gatesOut = "";

    private Generation(GenerationRequest r, Settings s, string? runDir = null)
    {
        Request = r;
        _s = s;
        RunDir = runDir ?? Path.Combine(s.TempPath, $"{r.Name}_{DateTime.Now:yyyyMMdd_HHmmss}");
        StageBegan["start"] = DateTime.Now;
    }

    public string EndedBy { get; private set; } = "";
    public bool Resumed { get; private set; }
    /* row 411: where the engine keeps the run's working files in memory ("" - in files), and the run page's line
       when it had to work in files for want of memory */
    public string MemoryRoot { get; private set; } = "";
    public string MemoryNote { get; private set; } = "";
    /// <summary>The ceiling given to the engine at the launch, MB (0 - files).</summary>
    public ulong MemoryAllowedMb { get; private set; }

    // ---- the request kept beside the run, so a run stopped part way can be resumed exactly (P5, G3) ----------

    private void SaveRequest()
    {
        var r = Request;
        File.WriteAllLines(Path.Combine(RunDir, "request.txt"), new[]
        {
            $"name={r.Name}", $"donor={r.Donor}", $"fidelity={r.Fidelity}", $"seed={r.Seed}",
            $"skip={string.Join(',', r.SkipFamilies)}", $"save_map={(r.SaveMapSource ? 1 : 0)}",
            $"draft={(r.Draft ? 1 : 0)}", $"max_attempts={r.MaxAttempts}", $"gates={(r.RunGates ? 1 : 0)}",
            $"grafts={string.Join(',', r.Grafts ?? Array.Empty<string>())}",
            // row 410: every field of the request - a resumed run took the cover it was started without (the window
            // test's run, stopped and resumed, sat in «cover» waiting to launch the game)
            $"cover={(r.Cover ? 1 : 0)}",
            $"digs={r.Options?.Digs ?? 0}", $"annexes={r.Options?.Annexes ?? 0}", $"annex_size={r.Options?.AnnexSize ?? 0}",
            $"storeys={r.Options?.Storeys ?? 0}", $"spans={r.Options?.Spans ?? 0}", $"halls={r.Options?.Halls ?? 0}",
            $"liquids={r.Options?.Liquids ?? ""}", $"decor={r.Options?.Decor ?? 0}",
            $"new_water={r.Options?.NewWater ?? -1}", $"new_slime={r.Options?.NewSlime ?? -1}",
            $"new_lava={r.Options?.NewLava ?? -1}",
            $"stairways={r.Options?.Stairways ?? 0}", $"destruction={r.Options?.Destruction ?? 0}",
            // row 411: whether the run's accepted steps reach the disk - without them it cannot be resumed
            $"checkpoints={(_s.KeepCheckpoints ? 1 : 0)}",
            $"began={DateTime.Now:O}",
        });
    }

    private static GenerationRequest? LoadRequest(string runDir)
    {
        var p = Path.Combine(runDir, "request.txt");
        if (!File.Exists(p))
            return null;
        var kv = File.ReadAllLines(p).Select(l => l.Split('=', 2)).Where(a => a.Length == 2)
                     .ToDictionary(a => a[0], a => a[1]);
        int I(string k) => int.TryParse(kv.GetValueOrDefault(k), out var n) ? n : 0;
        int L(string k) => int.TryParse(kv.GetValueOrDefault(k), out var n) ? n : -1;     // row 412: -1 the default
        return new GenerationRequest(kv.GetValueOrDefault("name", "map"), kv.GetValueOrDefault("donor", "q2dm1"),
                                     I("fidelity"), long.TryParse(kv.GetValueOrDefault("seed"), out var sd) ? sd : 0,
                                     (kv.GetValueOrDefault("skip") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries),
                                     I("save_map") == 1, I("draft") == 1, I("max_attempts"), I("gates") == 1,
                                     (kv.GetValueOrDefault("grafts") ?? "").Split(',', StringSplitOptions.RemoveEmptyEntries),
                                     kv.GetValueOrDefault("cover", "1") != "0",
                                     new GenerationOptions(I("digs"), I("annexes"), I("annex_size"), I("storeys"), I("spans"),
                                                           I("halls"), kv.GetValueOrDefault("liquids", ""), I("decor"),
                                                           L("new_water"), L("new_slime"), L("new_lava"), I("stairways"),
                                                           I("destruction")));
    }

    /// <summary>
    /// Row 411: were the run's accepted steps written to the disk? A run started with «Сохранять принятые шаги на диск»
    /// off kept them in memory only, and a stopped one cannot be resumed (runs from before the setting: yes).
    /// </summary>
    public static bool KeptCheckpoints(string runDir)
    {
        try
        {
            var p = Path.Combine(runDir, "request.txt");
            return !File.Exists(p) || !File.ReadAllLines(p).Contains("checkpoints=0");
        }
        catch (IOException)
        {
            return true;
        }
    }

    /// <summary>The bytes a run's folder holds (0 when it is gone).</summary>
    public static long FolderBytes(string runDir)
    {
        try
        {
            return Directory.Exists(runDir)
                ? new DirectoryInfo(runDir).EnumerateFiles("*", SearchOption.AllDirectories).Sum(f => f.Length)
                : 0;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            return 0;
        }
    }

    /// <summary>
    /// The PO, 05.10: a generation not wanted any more is deleted from the Studio with everything it left - its run
    /// folder in the temp folder (its tries, logs, request). Never a folder outside the temp folder, never one a live
    /// Studio is carrying or this one is running; the maps in the library are not touched. Returns "" or why not.
    /// </summary>
    public static string Delete(Settings s, string runDir, bool forget = true)
    {
        var temp = Path.GetFullPath(s.TempPath).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
        var dir = Path.GetFullPath(runDir);
        if (!dir.StartsWith(temp, StringComparison.OrdinalIgnoreCase) || dir.Length <= temp.Length)
            return Loc.T("delete.outside");
        if (Current is { Running: true } c && string.Equals(Path.GetFullPath(c.RunDir), dir, StringComparison.OrdinalIgnoreCase))
            return Loc.T("delete.running");
        if (LiveElsewhere(dir))
            return Loc.T("run.resume.live");
        for (var attempt = 0; ; attempt++)
        {
            try
            {
                if (Directory.Exists(dir))
                    Directory.Delete(dir, true);
                if (forget && Current != null && string.Equals(Path.GetFullPath(Current.RunDir), dir, StringComparison.OrdinalIgnoreCase))
                    Current = null;
                return "";
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
                // a process that has just ended may still hold a file for a moment
                if (attempt >= 20)
                    return e.Message;
                Thread.Sleep(250);
            }
        }
    }

    /// <summary>Runs in the temp folder that stopped before their end (a crash, the Studio closed) - newest first.</summary>
    public static List<(string runDir, GenerationRequest request, DateTime when, int attempts)> Interrupted(Settings s) =>
        Unfinished(s).Where(x => !LiveElsewhere(x.runDir)).ToList();

    /// <summary>
    /// Row 404: the unfinished runs another Studio process is carrying right now - a generation started without a
    /// window, or in a second window. The PO opened the Studio while one ran from the command line and was offered to
    /// «Продолжить» it: two engines writing one job folder. Shown as running, never offered to resume.
    /// </summary>
    public static List<(string runDir, GenerationRequest request, DateTime when, int attempts)> RunningElsewhere(Settings s) =>
        Unfinished(s).Where(x => LiveElsewhere(x.runDir)).ToList();

    private static List<(string runDir, GenerationRequest request, DateTime when, int attempts)> Unfinished(Settings s)
    {
        var list = new List<(string, GenerationRequest, DateTime, int)>();
        if (!Directory.Exists(s.TempPath))
            return list;
        foreach (var dir in Directory.GetDirectories(s.TempPath))
        {
            if (Current is { Running: true } c && string.Equals(c.RunDir, dir, StringComparison.OrdinalIgnoreCase))
                continue;
            var req = LoadRequest(dir);
            var progress = Path.Combine(dir, "job", "progress.txt");
            var ledger = Path.Combine(dir, "job", "ledger.txt");
            if (req == null || !File.Exists(ledger))
                continue;
            string text;
            int rows;
            try
            {
                text = File.Exists(progress) ? ReadShared(progress) : "";
                rows = ReadShared(ledger).Split('\n').Count(l => LedgerRow.IsMatch(l));
            }
            catch (IOException)
            {
                continue;
            }
            if (text.Contains("stage=finish"))
                continue;
            list.Add((dir, req, Directory.GetLastWriteTime(dir), rows));
        }
        return list.OrderByDescending(x => x.Item3).ToList();
    }

    /// <summary>A file another process may still be writing, read without asking it to stop.</summary>
    private static string ReadShared(string path)
    {
        using var f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
        using var r = new StreamReader(f);
        return r.ReadToEnd();
    }

    /*
     * Row 404: who carries a run - the Studio process and the moment it started, in the run's folder from the launch
     * to the end or the stop. A Studio that dies leaves the file naming a process that is gone (or another process
     * that reused its number - hence the start time), and the run is interrupted; one that is alive is carrying it.
     */
    private const string OwnerFile = "owner.txt";

    private static void WriteOwner(string runDir)
    {
        using var me = System.Diagnostics.Process.GetCurrentProcess();
        File.WriteAllText(Path.Combine(runDir, OwnerFile),
                          $"{me.Id}\n{me.StartTime.ToUniversalTime().Ticks}\n");
    }

    private void DropOwner()
    {
        try
        {
            File.Delete(Path.Combine(RunDir, OwnerFile));
        }
        catch (IOException)
        {
        }
        catch (UnauthorizedAccessException)
        {
        }
    }

    /// <summary>Is a live Studio process - this one or another - carrying the run in this folder?</summary>
    public static bool LiveElsewhere(string runDir)
    {
        try
        {
            var f = Path.Combine(runDir, OwnerFile);
            if (!File.Exists(f))
                return false;
            var parts = File.ReadAllText(f).Split('\n', StringSplitOptions.RemoveEmptyEntries);
            if (parts.Length < 2 || !int.TryParse(parts[0], out var pid) || !long.TryParse(parts[1], out var ticks))
                return false;
            using var p = System.Diagnostics.Process.GetProcessById(pid);
            return !p.HasExited && p.StartTime.ToUniversalTime().Ticks == ticks;
        }
        catch (Exception e) when (e is ArgumentException or InvalidOperationException or IOException
                                      or UnauthorizedAccessException or System.ComponentModel.Win32Exception)
        {
            return false;
        }
    }

    /// <summary>Resume a run that stopped part way: the engine replays its ledger and goes on (G3).</summary>
    public static Generation Resume(Settings s, string runDir)
    {
        if (LiveElsewhere(runDir))
            throw new InvalidOperationException(Loc.T("run.resume.live"));
        var r = LoadRequest(runDir) ?? throw new InvalidOperationException(Loc.T("run.resume.norequest"));
        if (!KeptCheckpoints(runDir))
            throw new InvalidOperationException(Loc.T("run.resume.nocheckpoints"));
        var g = new Generation(r, s, runDir) { Resumed = true };
        // the stopped run's account is kept aside: the resumed run writes its own from the first line, and reading
        // the old one first would leave the reader past the new one's start
        var progress = Path.Combine(g.JobDir, "progress.txt");
        if (File.Exists(progress))
            File.Move(progress, Path.Combine(g.JobDir, "progress_before_resume.txt"), true);
        Launch(g, s, resume: true);
        return g;
    }

    /// <summary>The engine's arguments - the same for a run and for its resumption, which is what makes it exact.</summary>
    private static void Launch(Generation g, Settings s, bool resume)
    {
        var r = g.Request;
        var args = new List<string>
        {
            Path.Combine(Engine.Dir, "q2tool.exe"),
            Engine.DonorPath(r.Donor),
            g.JobDir, "q2mg", r.Fidelity.ToString(CultureInfo.InvariantCulture), r.Seed.ToString(CultureInfo.InvariantCulture),
            "--moddir", Path.Combine(s.ClientDir, "baseq2"),
        };
        if (!r.Draft)
            args.Add("--final");
        if (r.MaxAttempts > 0)
            args.AddRange(new[] { "--max-attempts", r.MaxAttempts.ToString(CultureInfo.InvariantCulture) });
        foreach (var f in r.SkipFamilies)
            args.AddRange(new[] { "--skip-family", f });
        // the other maps chosen with the base: rooms may be brought in from them (the generator's graft pass)
        foreach (var d in r.Grafts ?? Array.Empty<string>())
            args.AddRange(new[] { "--donor", Engine.DonorPath(d) });
        /* row 400: a donor whose own walk fails the absolutes is held to itself; on q2dm1 this changes nothing */
        args.Add("--hold-to-donor");
        /* row 405: the donor's light calibration, written beside it by the engine's builder (cor, q3t2) */
        var light = Path.ChangeExtension(Engine.DonorPath(r.Donor), ".light.txt");
        if (File.Exists(light) && File.ReadAllText(light).Trim() is { Length: > 0 } flags)
            args.AddRange(new[] { "--light-flags", flags });
        /* row 410: and the donor's sun as the light tool must be told it (its colour, its angle) */
        var lightKeys = Path.ChangeExtension(Engine.DonorPath(r.Donor), ".light_keys.txt");
        if (File.Exists(lightKeys) && File.ReadAllText(lightKeys).Trim() is { Length: > 0 } keys)
            args.AddRange(new[] { "--light-keys", keys });
        // row 410: the creative options, the same on a resume (the replay must deal the same plan)
        if (r.Options != null)
            args.AddRange(r.Options.Args());
        if (resume)
            args.Add("--resume");
        /* row 411: the working files in memory, at most the setting's share of what is free now; the steps to the disk
           as the setting says - a resumed run was started with them (one without cannot be resumed) */
        g.MemoryAllowedMb = MemFiles.AllowedMb(s.MemoryPercent);
        if (g.MemoryAllowedMb > 0)
            args.AddRange(new[] { "--memory", g.MemoryAllowedMb.ToString(CultureInfo.InvariantCulture) });
        args.AddRange(new[] { "--checkpoints", resume || s.KeepCheckpoints ? "1" : "0" });
        g._job = new NativeJob();
        g.ApplyShare();
        g._job.Start(Path.Combine(Engine.Dir, "pipeline.exe"), args, g.RunDir);
        WriteOwner(g.RunDir);
        g.Log.Add($"pipeline.exe {string.Join(' ', args)}");
        Current = g;
    }

    /// <summary>What the engine needs: its programs, the donor, and a client whose baseq2 holds the textures.</summary>
    public static string? Missing(Settings s, string donor, IEnumerable<string>? grafts = null)
    {
        var engine = Engine.Dir;
        foreach (var f in new[] { "pipeline.exe", "q2tool.exe" }
                     .Concat(new[] { donor }.Concat(grafts ?? Array.Empty<string>()).Select(d => Path.Combine("donors", d + ".bsp"))))
            if (!File.Exists(Path.Combine(engine, f)))
                return Loc.F("run.missing.engine", Path.Combine(engine, f));
        if (!Settings.CheckClient(s.ClientDir).ok)
            return Loc.T("run.missing.client");
        return null;
    }

    public static Generation Start(GenerationRequest r, Settings s)
    {
        var g = new Generation(r, s);
        Directory.CreateDirectory(g.JobDir);
        g.SaveRequest();
        Launch(g, s, resume: false);
        return g;
    }

    /// <summary>The share of the CPU for this hour (day / night, R5), applied to the job when it changes.</summary>
    private void ApplyShare()
    {
        var hour = DateTime.Now.Hour;
        var share = hour >= _s.DayFrom && hour < _s.DayTo ? _s.CpuDayShare : _s.CpuNightShare;
        if (share == _sharePercent)
            return;
        _sharePercent = share;
        var cpus = Math.Max(1, (int)Math.Floor(Environment.ProcessorCount * share / 100.0));
        _job?.Limit(cpus, _s.Priority);
        _gatesJob?.Limit(cpus, _s.Priority);
        // row 404: what the job actually got - performance cores only
        var fast = NativeJob.PerformanceCpus().Count;
        var used = fast > 0 ? Math.Min(cpus, fast) : cpus;
        Log.Add(Loc.F("run.share", share, used, Environment.ProcessorCount));
    }

    public int CpuShare => _sharePercent;

    /// <summary>
    /// What the window reads and what the polling writes are kept apart by this lock (row 410, the PO 05.10: «студия
    /// не мульти-потоковая... интерфейс вешается когда запущена генерация»): the run is polled off the window's
    /// thread (<see cref="PollAsync"/>), the window reads under <see cref="System.Threading.Monitor.TryEnter(object, int)"/>
    /// and skips a beat rather than wait.
    /// </summary>
    public readonly object Sync = new();
    private Task? _poller;

    /// <summary>One poll on a pool thread unless one is still going; never waits. The window's timer calls this.</summary>
    public void PollAsync()
    {
        if (_poller is { IsCompleted: false } || !Running)
            return;
        _poller = Task.Run(() =>
        {
            try
            {
                Poll();
            }
            catch (Exception ex)
            {
                lock (Sync)
                    Log.Add("poll: " + ex.Message);
            }
        });
    }

    /// <summary>Read what the run wrote since, follow the clock, see whether it ended.</summary>
    public void Poll()
    {
        lock (Sync)
            PollLocked();
    }

    private void PollLocked()
    {
        if (!Running)
            return;
        if (Stage == "cover")
        {
            PollCover();
            return;
        }
        ApplyShare();
        if (_gatesJob != null)
        {
            PollGates();
            return;
        }
        ReadProgress();
        if (_job != null && _job.Exited(out var code))
        {
            ReadProgress();
            var crash = Path.Combine(JobDir, "crash.txt");
            if (File.Exists(crash))
            {
                Crashed = true;
                CrashText = File.ReadAllText(crash);
            }
            _job.Dispose();
            _job = null;
            if (Crashed || string.IsNullOrEmpty(Artifact) || !File.Exists(Artifact))
            {
                if (Error.Length == 0)
                    Error = Crashed ? Loc.F("run.crashed", CrashAttempts())
                                    : Result == "ERR_BASELINE" ? BaselineSaid()
                                    : Loc.Has($"result.{Result}") ? Loc.T($"result.{Result}")
                                    : Loc.F("run.no_map", Result.Length > 0 ? Result : $"0x{code:X8}");
                Finish();
                return;
            }
            StartGates();
        }
    }

    /// <summary>S2: how many attempts the crashed run had made, from its crash record.</summary>
    private string CrashAttempts()
    {
        var m = Regex.Match(CrashText, @"after (\d+) attempts");
        return m.Success ? m.Groups[1].Value : "?";
    }

    private static readonly Regex Field = new(@"(\w+)=(""[^""]*""|\S+)");
    private static readonly Regex LedgerRow = new(@"^\s*\d+ \S+\s+(ACCEPTED|REJECTED_\S+)");

    private void ReadProgress()
    {
        var path = Path.Combine(JobDir, "progress.txt");
        if (!File.Exists(path))
            return;
        try
        {
            using var f = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            if (f.Length <= _read)
                return;
            f.Seek(_read, SeekOrigin.Begin);
            using var r = new StreamReader(f);
            var text = r.ReadToEnd();
            var cut = text.LastIndexOf('\n');
            if (cut < 0)
                return;                       // a line half written: next time
            _read += System.Text.Encoding.UTF8.GetByteCount(text[..(cut + 1)]);
            foreach (var line in text[..cut].Split('\n'))
                Take(line.Trim());
        }
        catch (IOException) { }
    }

    private void Take(string line)
    {
        if (!line.StartsWith("PROGRESS "))
            return;
        Log.Add(line);
        var f = Field.Matches(line).ToDictionary(m => m.Groups[1].Value, m => m.Groups[2].Value.Trim('"'));
        int I(string k) => f.TryGetValue(k, out var v) && int.TryParse(v, out var n) ? n : 0;
        var stage = f.GetValueOrDefault("stage", "");
        if (stage.Length == 0)
            return;
        // row 410: what is about to be tried is not a stage of the run
        if (stage == "try")
        {
            TryEdit = I("edit");
            TryFamily = f.GetValueOrDefault("family", "");
            var box = f.GetValueOrDefault("box", "").Split(',');
            TryBox = box.Length == 6 && box.All(v => float.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out _))
                ? box.Select(v => float.Parse(v, CultureInfo.InvariantCulture)).ToArray() : null;
            TryAt = DateTime.Now;
            return;
        }
        // row 410: only a stage the window can name becomes the stage - the generator's «baseline-faithful» (the base
        // rebuilt with faithful skins: koldduel1, cor, q3t2) and «resume-diverged» / «resume-failed» would have shown
        // as «[stage.baseline-faithful.now]» with every stage waiting
        if (Loc.Has($"stage.{stage}.now"))
        {
            if (stage != Stage)
                Event(Loc.T($"stage.{stage}.now"));
            if (stage != Stage && !StageBegan.ContainsKey(stage))
                StageBegan[stage] = DateTime.Now;
            Stage = stage;
        }
        switch (stage)
        {
            case "start":
                Target = I("target");
                break;
            case "plan":
                foreach (var k in new[] { "digs", "annexes", "storeys", "spans", "floods", "windows", "reliquids", "stairways" })
                    Planned[k] = I(k);
                // row 410: what the plan holds (the creative options change these)
                PlanMade = f.ContainsKey("digs")
                    ? Loc.F("run.plan.made", I("digs"), I("annexes"), I("storeys"), I("spans"), I("floods"), I("windows"))
                      + (I("reliquids") > 0 ? Loc.F("run.plan.reliquids", I("reliquids")) : "")
                      + (I("stairways") > 0 ? Loc.F("run.plan.stairways", I("stairways")) : "")
                    : "";
                Offered = I("offered");
                Budget = I("budget");
                Target = I("target");
                break;
            case "attempt":
                Replaying = f.GetValueOrDefault("pass", "") == "replay";
                if (!Replaying && I("compiles") > Compiles)
                    BuildsSeen.Add((DateTime.Now, I("divergence")));
                if (I("edit") == TryEdit)
                    TryEdit = -1;
                Attempts++;
                AtEdit = I("edit");
                if (f.GetValueOrDefault("verdict", "") == "ACCEPTED"
                    && Category(f.GetValueOrDefault("family", ""), f.GetValueOrDefault("shape", "-")) is { Length: > 0 } cat)
                    Done[cat] = Done.GetValueOrDefault(cat) + 1;
                // brief 9: a dig the second map gave - in its skin (a room of it is counted as such above)
                if (f.GetValueOrDefault("verdict", "") == "ACCEPTED" && f.GetValueOrDefault("from", "").Length > 0
                    && f.GetValueOrDefault("shape", "-") != "room-of")
                    Done["skins_from"] = Done.GetValueOrDefault("skins_from") + 1;
                if (f.GetValueOrDefault("verdict", "") == "ACCEPTED" && f.GetValueOrDefault("family", "") == "graft-bundle")
                    Done["exchanges"] = Done.GetValueOrDefault("exchanges") + 1;
                Accepted = I("accepted");
                Compiles = I("compiles");
                Budget = Math.Max(Budget, I("budget"));
                Divergence = I("divergence");
                Target = I("target");
                LastFamily = f.GetValueOrDefault("family", "");
                LastVerdict = f.GetValueOrDefault("verdict", "");
                break;
            case "finish":
                Result = f.GetValueOrDefault("result", "");
                Accepted = I("accepted");
                Divergence = I("divergence");
                Target = I("target");
                Artifact = f.GetValueOrDefault("bsp", "");
                EndedBy = f.GetValueOrDefault("ended_by", "");
                break;
            case "resume" when f.ContainsKey("replayed"):
                // the ledger replayed: the edits go on from here (the window read «resume» until the next attempt)
                Replaying = false;
                Stage = "attempt";
                break;
            case "baseline-refused":
                BaselineAxes = f.GetValueOrDefault("axes", "");
                BaselineWhat = f.GetValueOrDefault("what", "");
                Log.Add(Loc.F("result.ERR_BASELINE.log", BaselineAxes, BaselineWhat));
                break;
            case "resume-diverged":
                Error = Loc.F("run.resume.diverged", f.GetValueOrDefault("why", ""));
                break;
            case "plan-rooms":
                Planned["rooms_copy"] = I("copies");
                break;
            case "second-map":
                SecondName = Path.GetFileNameWithoutExtension(f.GetValueOrDefault("name", ""));
                foreach (var k in new[] { "rooms", "skins", "tried", "size", "empty", "nosite", "nopickup", "exchanges" })
                    Second[k] = I(k);
                Planned["rooms_from"] = I("rooms");
                Planned["skins_from"] = I("skins");
                break;
            case "redeal":
                AtEdit = -1;               // a new plan: its edits are still to come
                break;
            case "light-step":
                var newStep = f.GetValueOrDefault("step", "") != LightStep || I("pass") != LightPass;
                LightStep = f.GetValueOrDefault("step", "");
                LightPass = I("pass");
                LightTenths = I("tenths");
                if (newStep)
                    Event(Loc.F("scheme.light", LightNow()[..LightNow().LastIndexOf(' ')].TrimEnd(' ', '—', '-')));
                break;
            case "memory":
                // row 411: in memory, or in files - and why, when the share given was not enough
                MemoryRoot = f.GetValueOrDefault("mode", "") == "memory" ? f.GetValueOrDefault("root", "") : "";
                MemoryNote = MemoryRoot.Length > 0 ? Loc.T("run.memory.on")
                           : f.ContainsKey("need_mb") ? Loc.F("run.memory.files", I("need_mb"), I("allowed_mb"))
                           : "";
                break;
        }
    }

    // ---- the map's checks (the delivery gates, Python, from the generator's own tree) -----------------------

    private void StartGates()
    {
        var repo = Engine.Repo;
        var python = Engine.Python;
        if (!Request.RunGates || repo == null || python == null)
        {
            // brief 10: which of the two is missing, said apart - Python is the user's to install, the checks are the build's
            Log.Add(Loc.T(!Request.RunGates ? "run.gates.skipped"
                          : python == null ? "run.gates.nopython" : "run.gates.notools"));
            Deliver();
            return;
        }
        Stage = "gates";
        StageBegan["gates"] = DateTime.Now;
        var candidate = Path.Combine(RunDir, "candidate.bsp");
        File.Copy(Artifact, candidate, true);
        _gatesOut = Path.Combine(RunDir, "gates.txt");
        _gatesJob = new NativeJob();
        _sharePercent = -1;
        ApplyShare();
        // python -c "...": first each new room's lights brought to the light round its door (row 408, Fable's brief 6:
        // the map's own light pass may light a door's surroundings otherwise than the donor the lights were valued
        // from), then the gates script, both outputs into gates.txt, inside the job
        var script = Path.Combine(repo, "tools", "mapgen_delivery_gates.py");
        var rooms = Path.Combine(repo, "tools", "mapgen_room_light.py");
        var donor = Engine.DonorPath(Request.Donor);
        // row 410: a donor never calibrated gets its light fitted ONCE, here, on this first map of it - light-only
        // reruns, no generation (the PO: «каждый раз по 10 раз генерировать карту чтобы подобрать ей свет???»);
        // the fit is kept beside the donor, and this map is relit under it before its rooms are measured
        var fit = Path.Combine(repo, "tools", "mapgen_light_autofit.py");
        var fitWork = Path.Combine(RunDir, "light_fit");
        // brief 9: the second map the run was given - the checks re-deal the plan with it
        var second = Request.Grafts is { Count: > 0 } gr ? $",'--second',r'{Engine.DonorPath(gr[0])}'" : "";
        // brief 10 (D2): the released Studio's own compiler and built helpers, for the checks (a user has no compiler)
        var helpers = Path.Combine(Engine.Dir, "helpers");
        var env = "import os;" +
                  (Directory.Exists(helpers) ? $"os.environ['MAPGEN_HELPERS']=r'{helpers}';" : "") +
                  $"os.environ['MAPGEN_Q2TOOL']=r'{Path.Combine(Engine.Dir, "q2tool.exe")}';" +
                  // brief 11 D2: the released Studio's texture pack (engine/textures/mapgen)
                  (File.Exists(Path.Combine(Engine.Dir, "textures", "mapgen", "catalogue.json"))
                      ? $"os.environ['MAPGEN_TEXTURE_PACK']=r'{Engine.Dir}';" : "");
        // brief 11 D2: the finished map in ruins, after its checks - then the checks a ruin still answers to, asked
        // again of it (lit, visible, its textures, its water, its starts standing), named apart
        var destroy = Path.Combine(repo, "tools", "mapgen_destroy.py");
        var pct = Request.Options?.Destruction ?? 0;
        var game = Path.Combine(_s.ClientDir, "baseq2");
        var after = pct > 0
            ? $"d=subprocess.run([sys.executable,r'{destroy}',r'{candidate}','--donor',r'{donor}','--destruction','{pct}'," +
              $"'--seed','{Request.Seed}','--game',r'{game}'],capture_output=True,text=True);" +
              "os.environ['MAPGEN_GATE_PREFIX']='after destruction: ';" +
              $"r2=subprocess.run([sys.executable,r'{script}',r'{candidate}','--job',r'{JobDir}','--donor',r'{donor}'," +
              "'--only','finished,axes,water,starts'],capture_output=True,text=True);"
            : "d=None;r2=None;";
        var code = env + "import subprocess,sys;" +
                   $"f=subprocess.run([sys.executable,r'{fit}',r'{candidate}',r'{donor}',r'{fitWork}']," +
                   "capture_output=True,text=True);" +
                   "x=['--relight-first'] if 'FITTED' in f.stdout else [];" +
                   $"l=subprocess.run([sys.executable,r'{rooms}',r'{candidate}','--job',r'{JobDir}'," +
                   $"'--donor',r'{donor}'{second}]+x,capture_output=True,text=True);" +
                   // brief 12 L3: the fit asked again of the map as the room step left it, only when the gate reads
                   // it out of band, the better kept
                   $"g=subprocess.run([sys.executable,r'{fit}',r'{candidate}',r'{donor}',r'{fitWork}_after','--after-rooms']," +
                   "capture_output=True,text=True);" +
                   // a refit moves the whole map's level: the rooms brought to their doors once more under it
                   $"l2=subprocess.run([sys.executable,r'{rooms}',r'{candidate}','--job',r'{JobDir}','--donor',r'{donor}'{second}]," +
                   "capture_output=True,text=True) if 'REFITTED' in g.stdout else None;" +
                   $"r=subprocess.run([sys.executable,r'{script}',r'{candidate}','--job',r'{JobDir}'," +
                   $"'--donor',r'{donor}'{second}],capture_output=True,text=True);" +
                   after +
                   $"open(r'{_gatesOut}','w',encoding='utf-8').write(r.stdout+r.stderr+'\\nLIGHT FIT\\n'+f.stdout+f.stderr+'\\nROOM LIGHT\\n'+l.stdout+l.stderr" +
                   "+'\\nLIGHT REFIT\\n'+g.stdout+g.stderr+('\\nROOM LIGHT AGAIN\\n'+l2.stdout+l2.stderr if l2 else '')" +
                   "+('\\nDESTRUCTION\\n'+d.stdout+d.stderr+'\\n'+r2.stdout+r2.stderr if d else ''));" +
                   "sys.exit(r.returncode or (d.returncode if d else 0) or (r2.returncode if r2 else 0))";
        _gatesJob.Start(python, new[] { "-c", code }, RunDir);
    }

    private void PollGates()
    {
        if (_gatesJob == null || !_gatesJob.Exited(out _))
            return;
        _gatesJob.Dispose();
        _gatesJob = null;
        if (File.Exists(_gatesOut))
            foreach (var raw in File.ReadAllLines(_gatesOut))
            {
                var line = raw.Trim();
                if (!line.StartsWith("PASS") && !line.StartsWith("FAIL"))
                    continue;
                var what = line[4..].Trim();
                var cut = what.IndexOf(" -- ", StringComparison.Ordinal);
                Gates.Add((line.StartsWith("PASS"), cut > 0 ? what[..cut] : what));
            }
        Deliver();
    }

    /// <summary>Covers taken by this generation's own cover launch (S-4); -1 before or without one.</summary>
    public int CoverShots { get; private set; } = -1;

    private Covers.Run? _cover;
    private DateTime _coverWaitSince;

    /// <summary>
    /// After the checks (S-4): the map into the library, then - when the settings ask for it and a client is set -
    /// one cover launch, waiting first while any game is open (the user's own too: never two clients at once, ten
    /// minutes at most, then the cover is left for the library's button). Then the end.
    /// </summary>
    private void Deliver()
    {
        IntoLibrary();
        if (Error.Length == 0 && LibraryName.Length > 0 && Request.Cover && _s.AutoCovers
            && Settings.CheckClient(_s.ClientDir).ok)
        {
            Stage = "cover";
            StageBegan["cover"] = DateTime.Now;
            _coverWaitSince = DateTime.Now;
            Log.Add(Loc.T("run.cover.wait"));
            PollCover();
            return;
        }
        Finish();
    }

    private void PollCover()
    {
        if (_cover == null)
        {
            if (Client.Busy(_s))
            {
                if (DateTime.Now - _coverWaitSince < TimeSpan.FromMinutes(10))
                    return;
                Log.Add(Loc.T("run.cover.skipped"));
                Finish();
                return;
            }
            try
            {
                var entry = Library.Scan(_s).First(m => m.Name == LibraryName);
                _cover = Covers.Start(entry, _s);
                Log.Add(Loc.F("cover.running", LibraryName));
            }
            catch (Exception ex)
            {
                Log.Add(ex.Message);
                Finish();
            }
            return;
        }
        var exited = _cover.Game.Process.HasExited;
        if (!exited && DateTime.Now - _cover.Game.Began < TimeSpan.FromMinutes(3))
            return;
        var (n, kept, note) = Covers.Finish(_cover, _s, timeout: !exited);
        _cover = null;
        CoverShots = n;
        Log.Add((n > 0 ? Loc.F("cover.done", n) : Loc.T("cover.none")) + (note.Length > 0 ? ". " + note : "")
                + (kept ? "" : ". " + Loc.T("lib.play.changed")));
        Finish();
    }

    /// <summary>The end, whatever it was.</summary>
    private void Finish()
    {
        DropOwner();
        Stage = Error.Length > 0 ? "failed" : "done";
        Ended = DateTime.Now;
        StageBegan[Stage] = Ended.Value;
        /*
         * The PO, 05.10: a generation that ended well cleans up after itself - its map, description and checks are in
         * the library, so its working folder goes (the plan is drawn from the library's copy from now on).
         */
        if (Error.Length == 0 && LibraryName.Length > 0)
        {
            var kept = Path.Combine(_s.BspPath, LibraryName + ".bsp");
            if (File.Exists(kept))
                Artifact = kept;
            var dir = RunDir;
            var settings = _s;
            KeepEvidence();
            Task.Run(() =>
            {
                var bytes = FolderBytes(dir);
                var why = Delete(settings, dir, forget: false);     // the run's page stays, its result shown
                lock (Sync)
                    Log.Add(why.Length == 0 ? Loc.F("run.cleaned", Size(bytes)) : Loc.F("delete.failed", why));
            });
        }
    }

    /// <summary>
    /// Brief 9 D5 (Fable, 05.10): before a finished run's folder goes, its small evidence is kept with its map in
    /// data/runs/NAME - the ledger, the progress, the plan, the request, the light log, the checks, any crash record.
    /// A few hundred KB; what the PO's «почему так?» is answered from.
    /// </summary>
    private void KeepEvidence()
    {
        try
        {
            var to = Path.Combine(_s.RunsPath, LibraryName);
            Directory.CreateDirectory(to);
            foreach (var (from, name) in new[]
                     {
                         (Path.Combine(JobDir, "ledger.txt"), "ledger.txt"),
                         (Path.Combine(JobDir, "progress.txt"), "progress.txt"),
                         (Path.Combine(JobDir, "progress_before_resume.txt"), "progress_before_resume.txt"),
                         (Path.Combine(JobDir, "plan.txt"), "plan.txt"),
                         (Path.Combine(RunDir, "request.txt"), "request.txt"),
                         (Path.Combine(JobDir, "lit", "rad.log"), "rad.log"),
                         (Path.Combine(RunDir, "gates.txt"), "gates.txt"),
                         (Path.Combine(JobDir, "crash.txt"), "crash.txt"),
                         (Path.Combine(JobDir, "crash_resumed_from.txt"), "crash_resumed_from.txt"),
                     })
                if (File.Exists(from))
                    File.Copy(from, Path.Combine(to, name), true);
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
            lock (Sync)
                Log.Add(e.Message);
        }
    }

    /// <summary>A size in plain words: MB below a GB.</summary>
    public static string Size(long bytes) =>
        bytes >= 1L << 30 ? Loc.F("size.gb", (bytes / 1073741824.0).ToString("0.0")) : Loc.F("size.mb", Math.Max(1, bytes >> 20));

    /// <summary>A made map goes into the library (P3) with what is known of it.</summary>
    private void IntoLibrary()
    {
        if (Error.Length > 0 || string.IsNullOrEmpty(Artifact) || !File.Exists(Artifact))
            return;
        try
        {
            LibraryName = Request.Name;
            Directory.CreateDirectory(_s.BspPath);
            // row 408: the map the checks were asked of - its rooms' lights may have been brought to their doors
            var checkedCopy = Path.Combine(RunDir, "candidate.bsp");
            File.Copy(File.Exists(checkedCopy) ? checkedCopy : Artifact, Path.Combine(_s.BspPath, LibraryName + ".bsp"), true);
            var source = Path.ChangeExtension(Artifact, ".map");
            // brief 11 D2: a map put in ruins keeps the source it was compiled from
            var ruined = Path.Combine(RunDir, "destroy", "q2mg.map");
            if ((Request.Options?.Destruction ?? 0) > 0 && File.Exists(ruined))
                source = ruined;
            if (Request.SaveMapSource && File.Exists(source))
            {
                Directory.CreateDirectory(_s.MapsPath);
                File.Copy(source, Path.Combine(_s.MapsPath, LibraryName + ".map"), true);
            }
            Directory.CreateDirectory(_s.DescriptionsPath);
            if (File.Exists(_gatesOut))
                File.Copy(_gatesOut, Path.Combine(_s.DescriptionsPath, LibraryName + ".gates.txt"), true);
            foreach (var lang in new[] { "ru", "en" })
                File.WriteAllText(Path.Combine(_s.DescriptionsPath, $"{LibraryName}.{lang}.txt"),
                                  Describe.Map(this, lang));
            /* S-5: the card's «made» is when the generation ended, not when a file was last copied */
            File.WriteAllLines(Path.Combine(_s.DescriptionsPath, $"{LibraryName}.info.txt"), new[]
            {
                $"made={(Ended ?? DateTime.Now):O}", $"began={Began:O}", $"donor={Request.Donor}",
            });
        }
        catch (Exception ex)
        {
            Error = ex.Message;
        }
    }

    public void Pause(bool pause)
    {
        lock (Sync)
            PauseLocked(pause);
    }

    private void PauseLocked(bool pause)
    {
        if (!Running || Paused == pause)
            return;
        (_gatesJob ?? _job)?.Suspend(pause);
        Paused = pause;
        if (pause)
            Pauses.Add((DateTime.Now, null));
        else if (Pauses.Count > 0 && Pauses[^1].to == null)
            Pauses[^1] = (Pauses[^1].from, DateTime.Now);
        Log.Add(Loc.T(pause ? "run.paused" : "run.resumed"));
    }

    /// <summary>Row 410: the pauses of this run, the last one open while paused.</summary>
    public readonly List<(DateTime from, DateTime? to)> Pauses = new();

    /// <summary>
    /// The time from A to B that the run was working - its pauses taken out (the PO, 05.10: «при паузе почему то
    /// времена идут дальше»).
    /// </summary>
    public TimeSpan Worked(DateTime a, DateTime b)
    {
        var t = b - a;
        foreach (var (from, to) in Pauses)
        {
            var lo = from > a ? from : a;
            var end = to ?? DateTime.Now;
            var hi = end < b ? end : b;
            if (hi > lo)
                t -= hi - lo;
        }
        return t < TimeSpan.Zero ? TimeSpan.Zero : t;
    }

    public long CpuTime() => (_gatesJob ?? _job)?.CpuTime() ?? -1;

    /// <summary>Row 410: the memory the run's processes hold now; 0 when none runs.</summary>
    public long MemoryBytes() => (_gatesJob ?? _job)?.MemoryBytes() ?? 0;

    public void Stop()
    {
        lock (Sync)
            StopLocked();
    }

    private void StopLocked()
    {
        if (_cover != null)
        {
            Covers.Finish(_cover, _s, timeout: true);
            _cover = null;
        }
        if (!Running)
            return;
        if (Paused)
            PauseLocked(false);
        (_gatesJob ?? _job)?.Stop();
        _job?.Dispose();
        _gatesJob?.Dispose();
        _job = _gatesJob = null;
        Error = Loc.T("run.stopped");
        Stage = "stopped";
        Ended = DateTime.Now;
        DropOwner();
    }
}

/// <summary>Where the engine lives and what it needs beside it.</summary>
public static class Engine
{
    public static string Dir => Path.Combine(Settings.ProgramDir, "engine");

    public static string DonorsDir => Path.Combine(Dir, "donors");

    public static string DonorPath(string name) => Path.Combine(DonorsDir, name + ".bsp");

    /// <summary>The maps a generation may start from: every .bsp in the engine's donors folder, q2dm1 first.</summary>
    public static List<string> Donors() =>
        Directory.Exists(DonorsDir)
            ? Directory.GetFiles(DonorsDir, "*.bsp").Select(f => Path.GetFileNameWithoutExtension(f))
                       .OrderBy(n => n == "q2dm1" ? 0 : 1).ThenBy(n => n, StringComparer.OrdinalIgnoreCase).ToList()
            : new List<string>();

    /// <summary>
    /// Any Quake II map as a base: the .bsp copied into the donors folder under a plain name (the generator takes
    /// it by path; the name goes into the map's description). The same file again is the same donor; another file
    /// with a name already taken gets a number.
    /// </summary>
    public static string AddDonor(string path)
    {
        var bytes = File.ReadAllBytes(path);
        if (bytes.Length < 8 || bytes[0] != (byte)'I' || bytes[1] != (byte)'B' || bytes[2] != (byte)'S' || bytes[3] != (byte)'P'
            || BitConverter.ToInt32(bytes, 4) != 38)
            throw new InvalidOperationException(Loc.F("gen.donor.notq2", Path.GetFileName(path)));
        Directory.CreateDirectory(DonorsDir);
        var stem = new string(Path.GetFileNameWithoutExtension(path).ToLowerInvariant()
                                  .Select(c => char.IsAsciiLetterOrDigit(c) || c is '_' or '-' ? c : '_').ToArray());
        if (stem.Length == 0)
            stem = "donor";
        for (var k = 1; ; k++)
        {
            var name = k == 1 ? stem : $"{stem}_{k}";
            var target = DonorPath(name);
            if (!File.Exists(target))
            {
                File.WriteAllBytes(target, bytes);
                return name;
            }
            if (File.ReadAllBytes(target).AsSpan().SequenceEqual(bytes))
                return name;
        }
    }

    /// <summary>
    /// Where the map's checks (Python tools) are: a `tools` folder beside the program - the released Studio (Fable's
    /// brief 10, D2: «чтобы она работала автономно у тех кто скачал») - else the generator's own tree the engine
    /// folder names (this machine's development install).
    /// </summary>
    public static string? Repo
    {
        get
        {
            if (File.Exists(Path.Combine(Settings.ProgramDir, "tools", "mapgen_delivery_gates.py")))
                return Settings.ProgramDir;
            var p = Path.Combine(Dir, "repo.txt");
            if (!File.Exists(p))
                return null;
            var repo = File.ReadAllText(p).Trim();
            return File.Exists(Path.Combine(repo, "tools", "mapgen_delivery_gates.py")) ? repo : null;
        }
    }

    /// <summary>The Python for the checks: the one chosen in the settings, else the system's, if there is one.</summary>
    public static string? Python
    {
        get
        {
            if (App.Settings.PythonPath is { Length: > 0 } chosen && File.Exists(chosen))
                return chosen;
            foreach (var dir in (Environment.GetEnvironmentVariable("PATH") ?? "").Split(';'))
            {
                try
                {
                    var p = Path.Combine(dir.Trim(), "python.exe");
                    if (dir.Length > 0 && File.Exists(p) && !p.Contains("WindowsApps", StringComparison.OrdinalIgnoreCase))
                        return p;
                }
                catch (ArgumentException) { }
            }
            // brief 10: an install without «Add to PATH» - the usual places, the newest first
            var roots = new[]
            {
                Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "Python"),
                Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles),
                Path.GetPathRoot(Environment.SystemDirectory) ?? "C:\\",
            };
            foreach (var root in roots)
            {
                try
                {
                    var found = Directory.Exists(root)
                        ? Directory.GetDirectories(root, "Python3*")
                                   .OrderByDescending(d => int.TryParse(new string(Path.GetFileName(d).Where(char.IsAsciiDigit).ToArray()), out var n) ? n : 0)
                                   .Select(d => Path.Combine(d, "python.exe")).FirstOrDefault(File.Exists)
                        : null;
                    if (found != null)
                        return found;
                }
                catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
            }
            return null;
        }
    }
}
