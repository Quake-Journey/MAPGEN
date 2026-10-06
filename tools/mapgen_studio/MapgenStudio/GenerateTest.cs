using System.Text;

namespace MapgenStudio;

/// <summary>
/// `--generate-test` (ledger row 394, phase P2's proof, run by <c>tools/check_mapgen_studio.py</c>): one short
/// generation driven exactly as the window drives it - a draft of q2dm1 at likeness 50, two builds, no checks - with
/// the run paused for three seconds once it is building edits: the job's CPU time must stand still and no progress
/// line may be added while paused. Then the end: the stages seen in order, the map in the library with its source and
/// its description in both languages. One PASS / FAIL line per question.
/// </summary>
public static class GenerateTest
{
    public static string Run(Settings s)
    {
        var b = new StringBuilder();
        void Check(string what, bool ok, string detail = "") =>
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));

        var missing = Generation.Missing(s, "q2dm1");
        Check("the engine and the client are there", missing == null, missing ?? "");
        if (missing != null)
            return b.ToString();
        const string name = "studio_generate_test";
        foreach (var old in new[] { Path.Combine(s.BspPath, name + ".bsp"), Path.Combine(s.MapsPath, name + ".map"),
                                    Path.Combine(s.DescriptionsPath, name + ".ru.txt"), Path.Combine(s.DescriptionsPath, name + ".en.txt") })
            File.Delete(old);
        var noCover = Environment.GetCommandLineArgs().Contains("--no-cover");
        var coverDir = Path.Combine(s.CoversPath, name);
        if (Directory.Exists(coverDir))
            Directory.Delete(coverDir, true);
        var g = Generation.Start(new GenerationRequest(name, "q2dm1", 50, 1, Array.Empty<string>(), SaveMapSource: true,
                                                       Draft: true, MaxAttempts: 2, RunGates: false, Cover: !noCover), s);
        var seen = new List<string>();
        var paused = false;
        long cpuBefore = 0, cpuAfter = 0;
        int linesBefore = 0, linesAfter = 0;
        var deadline = DateTime.Now.AddMinutes(40);
        while (g.Running && DateTime.Now < deadline)
        {
            g.Poll();
            if (seen.Count == 0 || seen[^1] != g.Stage)
                seen.Add(g.Stage);
            if (!paused && g.Stage == "attempt")
            {
                paused = true;
                g.Pause(true);
                Thread.Sleep(500);              // what was in flight settles
                g.Poll();
                cpuBefore = g.CpuTime();
                linesBefore = g.Log.Count;
                Thread.Sleep(3000);
                g.Poll();
                cpuAfter = g.CpuTime();
                linesAfter = g.Log.Count;
                g.Pause(false);
                if (Environment.GetCommandLineArgs().Contains("--pause-only"))
                {
                    // the RED's short form: the pause is the question, the rest of the run is not
                    g.Stop();
                    Check("and paused, the job's CPU time stood still and no progress line was added",
                          cpuBefore >= 0 && cpuAfter - cpuBefore < 500_000 && linesAfter == linesBefore,
                          $"cpu {cpuBefore} -> {cpuAfter}, lines {linesBefore} -> {linesAfter}");
                    return b.ToString();
                }
            }
            Thread.Sleep(200);
        }
        if (g.Running)
        {
            g.Stop();
            Check("the short generation ends within 40 minutes", false);
            return b.ToString();
        }
        Check("the run was paused while building edits", paused, string.Join(" ", seen));
        // 100 ns units: 0.05 s of CPU across the job's processes is noise, three seconds of work is not
        Check("and paused, the job's CPU time stood still and no progress line was added",
              paused && cpuBefore >= 0 && cpuAfter - cpuBefore < 500_000 && linesAfter == linesBefore,
              $"cpu {cpuBefore} -> {cpuAfter}, lines {linesBefore} -> {linesAfter}");
        // every stage the run went through, by when it began - a poll can read several lines at once, so the
        // stages the window saw are not the measure; the run's own account is
        var stages = g.StageBegan.OrderBy(kv => kv.Value).Select(kv => kv.Key).ToList();
        var order = new[] { "start", "baseline", "plan", "attempt", "judge", "finish" };
        Check("the run went through start, baseline, plan, attempt, judge and finish, in that order",
              order.All(stages.Contains) && order.Select(st => stages.IndexOf(st)).SequenceEqual(
                  order.Select(st => stages.IndexOf(st)).OrderBy(i => i)),
              string.Join(" ", stages));
        Check("it ended without an error", g.Error.Length == 0, g.Error);
        Check("the map is in the library", File.Exists(Path.Combine(s.BspPath, name + ".bsp")));
        Check("with its source", File.Exists(Path.Combine(s.MapsPath, name + ".map")));
        var ru = Path.Combine(s.DescriptionsPath, name + ".ru.txt");
        var en = Path.Combine(s.DescriptionsPath, name + ".en.txt");
        Check("and its description in Russian and English",
              File.Exists(ru) && File.Exists(en) && File.ReadAllText(ru).Contains("q2dm1") && File.ReadAllText(en).Contains("q2dm1"),
              File.Exists(ru) ? File.ReadAllText(ru).Split('\n')[0] : "");
        // S-4 (brief 4, row 401): the generation ended with its own cover launch - one watched launch of the client
        if (!noCover)
        {
            var shots = Library.Shots(s, name);
            Check("and a cover shot by the generation itself, its stage «cover» passed through",
                  g.StageBegan.ContainsKey("cover") && g.CoverShots > 0 && shots.Count > 0,
                  $"stage {(g.StageBegan.ContainsKey("cover") ? "yes" : "no")}, shots {g.CoverShots}, files {shots.Count}");
        }
        // P5 (row 396): the same generation stopped once it has kept an edit, found among the interrupted ones,
        // resumed - and the map it makes is the uninterrupted run's map, byte for byte
        if (!Environment.GetCommandLineArgs().Contains("--no-resume") && File.Exists(g.Artifact))
        {
            var whole = Sha(g.Artifact);
            var r = Generation.Start(new GenerationRequest("studio_resume_test", "q2dm1", 50, 1, Array.Empty<string>(),
                                                           SaveMapSource: true, Draft: true, MaxAttempts: 2, RunGates: false,
                                                           Cover: false), s);
            var stopDeadline = DateTime.Now.AddMinutes(20);
            while (r.Running && r.Accepted < 1 && DateTime.Now < stopDeadline)
            {
                r.Poll();
                Thread.Sleep(200);
            }
            var stoppedAfter = r.Accepted;
            r.Stop();
            var listed = Generation.Interrupted(s).Any(x => string.Equals(x.runDir, r.RunDir, StringComparison.OrdinalIgnoreCase));
            Check("stopped after it kept an edit, the run is listed as interrupted", stoppedAfter >= 1 && listed,
                  $"accepted {stoppedAfter}, listed {listed}");
            var resumed = Generation.Resume(s, r.RunDir);
            var until = DateTime.Now.AddMinutes(40);
            while (resumed.Running && DateTime.Now < until)
            {
                resumed.Poll();
                Thread.Sleep(200);
            }
            Check("resumed, it ends without an error, its ledger replayed",
                  !resumed.Running && resumed.Error.Length == 0 && resumed.StageBegan.ContainsKey("resume"),
                  resumed.Error);
            // row 410: but its visibility lump - full vis on several threads is not the same from run to run (row 404,
            // MAPCOMPILE_LIGHT_THREADS: conservative either way); the bsp stage, which varied the planes and the
            // nodes too, now runs on the pinned one thread
            var wholeNoVis = ShaButVis(g.Artifact);
            Check("and makes the uninterrupted run's map, byte for byte but the visibility lump",
                  File.Exists(resumed.Artifact) && ShaButVis(resumed.Artifact) == wholeNoVis,
                  $"{(File.Exists(resumed.Artifact) ? ShaButVis(resumed.Artifact)[..16] : "none")} vs {wholeNoVis[..16]}"
                  + $" (whole files {(File.Exists(resumed.Artifact) ? Sha(resumed.Artifact)[..16] : "none")} vs {whole[..16]})");
        }
        b.AppendLine("LOG");
        foreach (var line in g.Log)
            b.AppendLine("  " + line);
        return b.ToString();
    }

    private static string Sha(string path) =>
        Convert.ToHexString(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();

    /// <summary>The sha256 of every lump's content but the visibility lump's (IBSP lump 3) - by content, since a
    /// visibility lump of another length moves every lump after it.</summary>
    private static string ShaButVis(string path)
    {
        var d = File.ReadAllBytes(path);
        using var h = System.Security.Cryptography.IncrementalHash.CreateHash(
            System.Security.Cryptography.HashAlgorithmName.SHA256);
        for (var i = 0; i < 19; i++)
        {
            if (i == 3)
                continue;
            var off = BitConverter.ToInt32(d, 8 + 8 * i);
            var len = BitConverter.ToInt32(d, 8 + 8 * i + 4);
            if (off < 0 || len < 0 || off + len > d.Length)
                return Sha(path);
            h.AppendData(BitConverter.GetBytes(len));
            h.AppendData(d, off, len);
        }
        return Convert.ToHexString(h.GetHashAndReset()).ToLowerInvariant();
    }
}
