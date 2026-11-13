using System.Text;

namespace MapgenStudio;

/// <summary>
/// Brief 27 D3 (the PO 06.11, his space map red for «space: its own measure - not measured»: «кто мешает в космосе строить
/// что хочешь?»): «Перепроверить» - a map from scratch measured again by THIS Studio's tools, as its run measured it
/// (`check_mapgen_new_map.py` on its .bsp with its run's request and skeleton: the survey only, no engine, the CPU share
/// of the hour), its gates file's from-scratch section replaced by the new words. The engine's own checks of the run
/// stay as they were - they are the run's.
/// </summary>
public static class Recheck
{
    private const string Head = "FROM SCRATCH";
    private const string Next = "NOT A COPY";

    private static string RunDir(Settings s, MapEntry m) => Path.Combine(s.RunsPath, m.Name);

    /// <summary>A map from scratch whose run left its request and skeleton, with the tools and a python to measure it.</summary>
    public static bool CanRun(Settings s, MapEntry m) =>
        m.Scratch != null && Engine.Python != null && Engine.Repo != null && File.Exists(m.BspPath)
        && File.Exists(Path.Combine(RunDir(s, m), "scratch_request.json"))
        && File.Exists(Path.Combine(RunDir(s, m), "scratch_skeleton.txt"));

    /// <summary>The measure started in a job of the hour's CPU share; its words go to <paramref name="outFile"/>.</summary>
    public static NativeJob Start(Settings s, MapEntry m, out string outFile)
    {
        Directory.CreateDirectory(s.TempPath);
        outFile = Path.Combine(s.TempPath, $"recheck_{m.Name}.txt");
        if (File.Exists(outFile))
            File.Delete(outFile);
        var helpers = Path.Combine(Engine.Dir, "helpers");
        // 3.68 (his library after a recheck of mg_new_368_mach13: «mechanic �dead-end stack�»): the check writes UTF-8 whatever
        // the console's code page - its «» came back as the replacement character and the row lost its words
        var env = "import os;os.environ['PYTHONIOENCODING']='utf-8';os.environ['PYTHONUTF8']='1';" +
                  $"os.environ['MAPGEN_GAME']=r'{Path.Combine(s.ClientDir, "baseq2")}';" +
                  $"os.environ['MAPGEN_DONORS']=r'{Engine.DonorsDir}';" +
                  (Directory.Exists(helpers) ? $"os.environ['MAPGEN_HELPERS']=r'{helpers}';" : "") +
                  $"os.environ['MAPGEN_Q2TOOL']=r'{Path.Combine(Engine.Dir, "q2tool.exe")}';" +
                  (File.Exists(Path.Combine(Engine.Dir, "textures", "mapgen", "catalogue.json"))
                      ? $"os.environ['MAPGEN_TEXTURE_PACK']=r'{Engine.Dir}';" : "");
        var script = Path.Combine(Engine.Repo!, "tools", "check_mapgen_new_map.py");
        var run = RunDir(s, m);
        var code = env + "import subprocess,sys;" +
                   $"r=subprocess.run([sys.executable,r'{script}',r'{m.BspPath}','--asked',r'{Path.Combine(run, "scratch_request.json")}'," +
                   $"'--plan',r'{Path.Combine(run, "scratch_skeleton.txt")}'],capture_output=True,text=True,encoding='utf-8',errors='replace');" +
                   $"open(r'{outFile}','w',encoding='utf-8').write(r.stdout+r.stderr);sys.exit(0)";
        var job = new NativeJob();
        var hour = DateTime.Now.Hour;
        var share = hour >= s.DayFrom && hour < s.DayTo ? s.CpuDayShare : s.CpuNightShare;
        job.Limit(Math.Max(1, (int)Math.Floor(Environment.ProcessorCount * share / 100.0)), s.Priority);
        job.Start(Engine.Python!, new[] { "-c", code }, Settings.ProgramDir);
        return job;
    }

    /// <summary>
    /// The measure's words into the map's gates file (its from-scratch section replaced, or added); null when done, else
    /// what went wrong - the old file then stays as it was.
    /// </summary>
    public static string? Finish(Settings s, MapEntry m, string outFile)
    {
        var said = File.Exists(outFile) ? File.ReadAllText(outFile) : "";
        if (!said.Contains("SUMMARY from scratch"))
            return said.Length == 0 ? "no output" : said.Trim().Split('\n').LastOrDefault() ?? "no summary";
        var path = Path.Combine(s.DescriptionsPath, $"{m.Name}.gates.txt");
        var old = File.Exists(path) ? File.ReadAllText(path) : "";
        var lines = old.Split('\n').ToList();
        var at = lines.FindIndex(l => l.Trim() == Head);
        var b = new StringBuilder();
        if (at < 0)
        {
            b.Append(old.TrimEnd('\n')).Append("\n\n").Append(Head).Append('\n').Append(said.TrimEnd('\n')).Append('\n');
        }
        else
        {
            var next = lines.FindIndex(at + 1, l => l.Trim() == Next);
            b.Append(string.Join('\n', lines.Take(at + 1))).Append('\n').Append(said.TrimEnd('\n')).Append("\n\n");
            if (next >= 0)
                b.Append(string.Join('\n', lines.Skip(next)));
        }
        Directory.CreateDirectory(s.DescriptionsPath);
        if (File.Exists(path) && !File.Exists(path + ".before_recheck"))
            File.Copy(path, path + ".before_recheck");
        File.WriteAllText(path, b.ToString());
        try { File.Delete(outFile); } catch (IOException) { }
        return null;
    }
}
