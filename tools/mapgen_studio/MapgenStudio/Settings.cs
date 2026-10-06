using System.Globalization;
using System.Text;

namespace MapgenStudio;

/// <summary>
/// The settings, kept in <c>MapgenStudio.ini</c> beside the program (R14: portable - the folder can be moved
/// anywhere). Relative folders are relative to the program's folder.
/// </summary>
public sealed class Settings
{
    public static string ProgramDir { get; } = AppContext.BaseDirectory;
    public static string IniPath => Path.Combine(ProgramDir, "MapgenStudio.ini");

    public string Language { get; set; } = "ru";          // ru | en
    public string Theme { get; set; } = "system";         // system | light | dark
    public string StartPage { get; set; } = "home";       // home | generate | library: the page the program opens on
    public string MapsDir { get; set; } = @"data\maps";
    public string BspDir { get; set; } = @"data\bsp";
    public string TempDir { get; set; } = "temp";
    public string ClientDir { get; set; } = "";
    /* the PO, 06.10: «предложить указать к нему путь» - a python.exe chosen by the user, first before any other */
    public string PythonPath { get; set; } = "";
    public bool SaveMapSource { get; set; } = true;
    public bool AutoCovers { get; set; } = true;          // S-4: a cover launch after every generation
    public bool Scheme { get; set; } = true;              // row 410: the run's plan drawn as it is built
    /* row 410 (the PO 05.10: «я не выбирал q2dm1 в качестве донора»): the bases ticked on the Generate page, the
       first THE base, kept across starts - a restart put q2dm1 back as the base and his two maps after it */
    public List<string> Bases { get; set; } = new();
    public bool GraftMode { get; set; }
    /* row 410: the rest of the Generate page, kept the same way - it was rebuilt to 20 / 42 / every family on each
       redraw (ticking a base redraws it) */
    public int Fidelity { get; set; } = 20;
    public long Seed { get; set; } = 42;
    public List<string> SkipFamilies { get; set; } = new();
    public GenerationOptions Options { get; set; } = new();
    public int CpuDayShare { get; set; } = 60;            // percent of the logical CPUs, 09:00-23:00
    public int CpuNightShare { get; set; } = 30;          // percent at night
    public int DayFrom { get; set; } = 9;
    public int DayTo { get; set; } = 23;
    public string Priority { get; set; } = "below_normal"; // idle | below_normal | normal
    /* row 411 (Fable's brief 8): the generator's working files in memory - at most this share of the memory free at
       the start (0: on the disk, as before); and each accepted step written to the disk once, so a stopped run resumes */
    public int MemoryPercent { get; set; } = 50;
    /* the PO, 05.10: the size of the library's tiles and of a map's shots (Ctrl+wheel or the slider), kept */
    public int LibraryTile { get; set; } = 240;
    public int ShotTile { get; set; } = 160;
    public bool KeepCheckpoints { get; set; } = true;

    public static string Resolve(string dir) =>
        string.IsNullOrWhiteSpace(dir) ? "" : Path.IsPathRooted(dir) ? dir : Path.GetFullPath(Path.Combine(ProgramDir, dir));

    public string MapsPath => Resolve(MapsDir);
    public string BspPath => Resolve(BspDir);
    public string TempPath => Resolve(TempDir);
    public string CoversPath => Resolve(@"data\covers");
    public string DescriptionsPath => Resolve(@"data\descriptions");
    /// <summary>Brief 9 D5: each finished run's small evidence (ledger, progress, plan ...), kept beside its map.</summary>
    public string RunsPath => Resolve(@"data\runs");

    public static Settings Load()
    {
        var s = new Settings();
        if (!File.Exists(IniPath))
        {
            s.Save();
            return s;
        }
        foreach (var raw in File.ReadAllLines(IniPath, Encoding.UTF8))
        {
            var line = raw.Trim();
            if (line.Length == 0 || line.StartsWith(';') || line.StartsWith('#') || line.StartsWith('['))
                continue;
            var eq = line.IndexOf('=');
            if (eq <= 0)
                continue;
            var key = line[..eq].Trim().ToLowerInvariant();
            var value = line[(eq + 1)..].Trim();
            switch (key)
            {
                case "language": s.Language = value == "en" ? "en" : "ru"; break;
                case "theme": s.Theme = value is "light" or "dark" ? value : "system"; break;
                case "start_page": s.StartPage = value is "generate" or "library" ? value : "home"; break;
                case "maps": s.MapsDir = value; break;
                case "bsp": s.BspDir = value; break;
                case "temp": s.TempDir = value; break;
                case "client": s.ClientDir = value; break;
                case "python": s.PythonPath = value; break;
                case "save_map_source": s.SaveMapSource = value is "1" or "true" or "yes"; break;
                case "auto_covers": s.AutoCovers = value is "1" or "true" or "yes"; break;
                case "scheme": s.Scheme = value is "1" or "true" or "yes"; break;
                case "bases": s.Bases = value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList(); break;
                case "graft_mode": s.GraftMode = value is "1" or "true" or "yes"; break;
                case "fidelity": s.Fidelity = Clamp(value, 1, 100, 20); break;
                case "seed": s.Seed = long.TryParse(value, out var sd) && sd >= 0 ? sd : 42; break;
                case "skip_families": s.SkipFamilies = value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries).ToList(); break;
                case "opt_digs": s.Options = s.Options with { Digs = Clamp(value, 0, 16, 0) }; break;
                case "opt_annexes": s.Options = s.Options with { Annexes = Clamp(value, 0, 16, 0) }; break;
                case "opt_annex_size": s.Options = s.Options with { AnnexSize = Clamp(value, 0, 4, 0) }; break;
                case "opt_storeys": s.Options = s.Options with { Storeys = Clamp(value, 0, 8, 0) }; break;
                case "opt_spans": s.Options = s.Options with { Spans = Clamp(value, 0, 8, 0) }; break;
                case "opt_halls": s.Options = s.Options with { Halls = Clamp(value, 0, 8, 0) }; break;
                case "opt_liquids": s.Options = s.Options with { Liquids = value }; break;
                case "opt_decor": s.Options = s.Options with { Decor = Clamp(value, 0, 4, 0) }; break;
                case "opt_new_water": s.Options = s.Options with { NewWater = Clamp(value, -1, 100, -1) }; break;
                case "opt_new_slime": s.Options = s.Options with { NewSlime = Clamp(value, -1, 100, -1) }; break;
                case "opt_new_lava": s.Options = s.Options with { NewLava = Clamp(value, -1, 100, -1) }; break;
                case "cpu_day": s.CpuDayShare = Clamp(value, 5, 100, 60); break;
                case "cpu_night": s.CpuNightShare = Clamp(value, 5, 100, 30); break;
                case "day_from": s.DayFrom = Clamp(value, 0, 23, 9); break;
                case "day_to": s.DayTo = Clamp(value, 0, 24, 23); break;
                case "priority": s.Priority = value is "idle" or "normal" ? value : "below_normal"; break;
                case "memory_percent": s.MemoryPercent = Clamp(value, 0, 90, 50); break;
                case "library_tile": s.LibraryTile = Clamp(value, 120, 2400, 240); break;
                case "shot_tile": s.ShotTile = Clamp(value, 80, 2400, 160); break;
                case "keep_checkpoints": s.KeepCheckpoints = value is "1" or "true" or "yes"; break;
            }
        }
        return s;
    }

    private static int Clamp(string v, int lo, int hi, int fallback) =>
        int.TryParse(v, NumberStyles.Integer, CultureInfo.InvariantCulture, out var n) ? Math.Clamp(n, lo, hi) : fallback;

    public void Save()
    {
        var b = new StringBuilder();
        b.AppendLine("; MAPGEN Studio settings - edited by the program; safe to edit by hand while it is closed");
        b.AppendLine("[ui]");
        b.AppendLine($"language={Language}");
        b.AppendLine($"theme={Theme}");
        b.AppendLine($"start_page={StartPage}");
        b.AppendLine("[folders]");
        b.AppendLine($"maps={MapsDir}");
        b.AppendLine($"bsp={BspDir}");
        b.AppendLine($"temp={TempDir}");
        b.AppendLine($"client={ClientDir}");
        b.AppendLine($"python={PythonPath}");
        b.AppendLine($"save_map_source={(SaveMapSource ? 1 : 0)}");
        b.AppendLine($"auto_covers={(AutoCovers ? 1 : 0)}");
        b.AppendLine($"scheme={(Scheme ? 1 : 0)}");
        b.AppendLine($"bases={string.Join(",", Bases)}");
        b.AppendLine($"graft_mode={(GraftMode ? 1 : 0)}");
        b.AppendLine($"fidelity={Fidelity}");
        b.AppendLine($"seed={Seed}");
        b.AppendLine($"skip_families={string.Join(",", SkipFamilies)}");
        b.AppendLine($"opt_digs={Options.Digs}");
        b.AppendLine($"opt_annexes={Options.Annexes}");
        b.AppendLine($"opt_annex_size={Options.AnnexSize}");
        b.AppendLine($"opt_storeys={Options.Storeys}");
        b.AppendLine($"opt_spans={Options.Spans}");
        b.AppendLine($"opt_halls={Options.Halls}");
        b.AppendLine($"opt_liquids={Options.Liquids}");
        b.AppendLine($"opt_decor={Options.Decor}");
        b.AppendLine($"opt_new_water={Options.NewWater}");
        b.AppendLine($"opt_new_slime={Options.NewSlime}");
        b.AppendLine($"opt_new_lava={Options.NewLava}");
        b.AppendLine("[cpu]");
        b.AppendLine($"cpu_day={CpuDayShare}");
        b.AppendLine($"cpu_night={CpuNightShare}");
        b.AppendLine($"day_from={DayFrom}");
        b.AppendLine($"day_to={DayTo}");
        b.AppendLine($"priority={Priority}");
        b.AppendLine("[memory]");
        b.AppendLine($"memory_percent={MemoryPercent}");
        b.AppendLine($"keep_checkpoints={(KeepCheckpoints ? 1 : 0)}");
        b.AppendLine("[view]");
        b.AppendLine($"library_tile={LibraryTile}");
        b.AppendLine($"shot_tile={ShotTile}");
        try
        {
            File.WriteAllText(IniPath, b.ToString(), new UTF8Encoding(false));
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    /// <summary>The data folders exist (made on first use, beside the program unless set elsewhere).</summary>
    public void EnsureFolders()
    {
        foreach (var d in new[] { MapsPath, BspPath, TempPath, CoversPath, DescriptionsPath })
        {
            try
            {
                if (d.Length > 0)
                    Directory.CreateDirectory(d);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
        }
    }

    /// <summary>A Quake II client folder: one with a <c>baseq2</c> folder and a program in it.</summary>
    public static (bool ok, string exe) CheckClient(string dir)
    {
        if (string.IsNullOrWhiteSpace(dir) || !Directory.Exists(dir) || !Directory.Exists(Path.Combine(dir, "baseq2")))
            return (false, "");
        // the game itself, not its dedicated server or a tool beside it: the shortest q2pro name first
        var exes = Directory.GetFiles(dir, "*.exe")
                            .Where(e => !Path.GetFileName(e).Contains("dedicated", StringComparison.OrdinalIgnoreCase))
                            .OrderBy(e => Path.GetFileName(e).Length).ToArray();
        var best = exes.FirstOrDefault(e => Path.GetFileName(e).StartsWith("q2pro", StringComparison.OrdinalIgnoreCase))
                   ?? exes.FirstOrDefault(e => Path.GetFileName(e).Contains("quake", StringComparison.OrdinalIgnoreCase))
                   ?? exes.FirstOrDefault();
        return (best != null, best ?? "");
    }
}
