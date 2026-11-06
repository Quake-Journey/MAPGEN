namespace MapgenStudio;

/// <summary>One map of the library: its file, cover, description and checks report, all by its name.</summary>
public sealed record MapEntry(string Name, string BspPath, DateTime Made, long Bytes, string? CoverPath,
                              string? Description, IReadOnlyList<(bool pass, string what)> Gates)
{
    /// <summary>Every picture in the map's cover folder, in name order (S-2).</summary>
    public IReadOnlyList<string> Shots { get; init; } = Array.Empty<string>();

    /// <summary>The base the checks report names, for a map made outside the program (S-5).</summary>
    public string? Base { get; init; }

    /// <summary>The PO, 11.10 (the library's tiles): the base its run was made from, from the run's record.</summary>
    public string? Donor { get; init; }

    /// <summary>Brief 19 D8: «с нуля» (and the style's maps) for a map made from scratch; null otherwise.</summary>
    public string? Scratch { get; init; }

    /// <summary>How far its run took it from the base and what was asked, tenths of a percent; -1 unknown.</summary>
    public int Difference { get; init; } = -1;
    public int Target { get; init; } = -1;

    /// <summary>Brief 24 D1.5: how long its run took, the stages' seconds of its record summed; -1 for a map without them.</summary>
    public int BuiltSeconds { get; init; } = -1;

    /// <summary>The checks passed, of those run.</summary>
    public int GatesPassed => Gates.Count(g => g.pass);

    /// <summary>Brief 27: what each check measured (the gates file's words after « -- »), in the checks' order.</summary>
    public IReadOnlyList<string> Said { get; init; } = Array.Empty<string>();

    /// <summary>Brief 27: the failed checks that mean the map cannot be played (<see cref="Library.Blocking"/>).</summary>
    public int GatesBlocking => Gates.Count(g => !g.pass && Library.Blocking(g.what));
}

public static class Library
{
    /// <summary>Every .bsp in the maps folder, newest first, with what lies beside it under data\.</summary>
    public static List<MapEntry> Scan(Settings s)
    {
        var list = new List<MapEntry>();
        if (!Directory.Exists(s.BspPath))
            return list;
        foreach (var bsp in Directory.GetFiles(s.BspPath, "*.bsp"))
        {
            var name = Path.GetFileNameWithoutExtension(bsp);
            var info = new FileInfo(bsp);
            var (donor, difference, target, scratch) = RunFacts(s, name);
            var gates = GateLines(s, name);
            list.Add(new MapEntry(name, bsp, Made(s, name) ?? info.LastWriteTime, info.Length, Cover(s, name),
                                  Description(s, name), gates.Select(g => (g.pass, g.what)).ToList())
            {
                Said = gates.Select(g => g.said).ToList(),
                Shots = Shots(s, name),
                Base = BaseOf(s, name),
                Donor = donor,
                Scratch = scratch,
                Difference = difference,
                Target = target,
                BuiltSeconds = BuiltSeconds(s, name),
            });
        }
        return list.OrderByDescending(m => m.Made).ToList();
    }

    /// <summary>
    /// The map's run, from its record in data\runs: the base (request.txt) and the difference it reached of the one
    /// asked (the ledger's last «divergence N of target M»). Nothing known for a map made elsewhere.
    /// </summary>
    private static (string? donor, int difference, int target, string? scratch) RunFacts(Settings s, string name)
    {
        var dir = Path.Combine(s.RunsPath, name);
        string? donor = null, scratch = null;
        int difference = -1, target = -1;
        try
        {
            var request = Path.Combine(dir, "request.txt");
            if (File.Exists(request))
                foreach (var line in File.ReadLines(request))
                    if (line.StartsWith("donor="))
                        donor = line[6..].Trim();
                    else if (line.StartsWith("scratch=") && line.Length > 9)
                        scratch = ScratchParams.LabelOf(line[8..]);
            var ledger = Path.Combine(dir, "ledger.txt");
            if (File.Exists(ledger))
            {
                var m = System.Text.RegularExpressions.Regex.Matches(File.ReadAllText(ledger), @"divergence (\d+) of target (\d+)");
                if (m.Count > 0)
                {
                    difference = int.Parse(m[^1].Groups[1].Value);
                    target = int.Parse(m[^1].Groups[2].Value);
                }
            }
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or FormatException)
        {
        }
        return (donor, difference, target, scratch);
    }

    /// <summary>Every picture of the map, in name order.</summary>
    public static IReadOnlyList<string> Shots(Settings s, string name)
    {
        var dir = Path.Combine(s.CoversPath, name);
        if (!Directory.Exists(dir))
            return Array.Empty<string>();
        return Directory.GetFiles(dir).Where(f => f.EndsWith(".png", StringComparison.OrdinalIgnoreCase)
                                                 || f.EndsWith(".jpg", StringComparison.OrdinalIgnoreCase)
                                                 || f.EndsWith(".jpeg", StringComparison.OrdinalIgnoreCase))
                        .OrderBy(f => f, StringComparer.OrdinalIgnoreCase).ToList();
    }

    /// <summary>The cover: the picture `cover.txt` names when it is still there, else the first (S-2).</summary>
    private static string? Cover(Settings s, string name)
    {
        var shots = Shots(s, name);
        var chosen = Path.Combine(s.CoversPath, name, "cover.txt");
        if (File.Exists(chosen))
        {
            var file = File.ReadAllText(chosen).Trim();
            var hit = shots.FirstOrDefault(f => string.Equals(Path.GetFileName(f), file, StringComparison.OrdinalIgnoreCase));
            if (hit != null)
                return hit;
        }
        return shots.FirstOrDefault();
    }

    /// <summary>
    /// A picture of the game kept as a JPEG of quality 90 beside where its PNG was, the PNG gone, the cover's choice
    /// following it (the PO, 12.10: «с какого хуя нужно грузить 1.1 гб?» - the client's PNG screenshots are 6-7 MB
    /// each, four a map; a JPEG looks the same at a tenth). False when the picture could not be read.
    /// </summary>
    public static bool ToJpeg(string png)
    {
        try
        {
            var jpg = Path.ChangeExtension(png, ".jpg");
            using (var bmp = SkiaSharp.SKBitmap.Decode(png))
            {
                if (bmp == null)
                    return false;
                using var data = bmp.Encode(SkiaSharp.SKEncodedImageFormat.Jpeg, 90);
                using (var f = File.Create(jpg + ".part"))
                    data.SaveTo(f);
            }
            File.Move(jpg + ".part", jpg, true);
            var chosen = Path.Combine(Path.GetDirectoryName(png)!, "cover.txt");
            if (File.Exists(chosen) && string.Equals(File.ReadAllText(chosen).Trim(), Path.GetFileName(png),
                                                     StringComparison.OrdinalIgnoreCase))
                File.WriteAllText(chosen, Path.GetFileName(jpg));
            File.Delete(png);
            return true;
        }
        catch (Exception)
        {
            return false;
        }
    }

    /// <summary>Every map's PNG pictures made JPEGs (ToJpeg) - once, on a background thread after the Studio opens.</summary>
    public static int CompactCovers(Settings s)
    {
        var n = 0;
        if (!Directory.Exists(s.CoversPath))
            return 0;
        foreach (var dir in Directory.GetDirectories(s.CoversPath))
            foreach (var png in Directory.GetFiles(dir, "*.png"))
                n += ToJpeg(png) ? 1 : 0;
        return n;
    }

    /// <summary>Make a shot of the map its cover; no file is renamed.</summary>
    public static void ChooseCover(Settings s, string name, string shot)
    {
        var dir = Path.Combine(s.CoversPath, name);
        Directory.CreateDirectory(dir);
        File.WriteAllText(Path.Combine(dir, "cover.txt"), Path.GetFileName(shot));
    }

    /// <summary>A picture of the user's own as the cover (S-3): copied in as custom_NN and chosen.</summary>
    public static string AddCover(Settings s, string name, string picture)
    {
        var dir = Path.Combine(s.CoversPath, name);
        Directory.CreateDirectory(dir);
        var ext = Path.GetExtension(picture).ToLowerInvariant();
        if (ext is not (".png" or ".jpg" or ".jpeg"))
            throw new InvalidOperationException(Path.GetFileName(picture));
        var n = 1;
        string target;
        do
            target = Path.Combine(dir, $"custom_{n++:00}{ext}");
        while (File.Exists(target));
        File.Copy(picture, target);
        ChooseCover(s, name, target);
        return target;
    }

    /// <summary>Brief 24 D1.5: the seconds its run's stages took (`stage.KEY=SECONDS` of NAME.info.txt); -1 without them.</summary>
    private static int BuiltSeconds(Settings s, string name)
    {
        var p = Path.Combine(s.DescriptionsPath, $"{name}.info.txt");
        if (!File.Exists(p))
            return -1;
        var sum = 0;
        var any = false;
        foreach (var line in File.ReadAllLines(p))
            if (line.StartsWith("stage.", StringComparison.Ordinal) && line.IndexOf('=') is var eq && eq > 0
                && int.TryParse(line[(eq + 1)..], out var sec))
            {
                sum += sec;
                any = true;
            }
        return any ? sum : -1;
    }

    /// <summary>When a map made here was finished (S-5): `NAME.info.txt` beside its description.</summary>
    private static DateTime? Made(Settings s, string name)
    {
        var p = Path.Combine(s.DescriptionsPath, $"{name}.info.txt");
        if (!File.Exists(p))
            return null;
        foreach (var line in File.ReadAllLines(p))
            if (line.StartsWith("made=", StringComparison.Ordinal)
                && DateTime.TryParse(line[5..], null, System.Globalization.DateTimeStyles.RoundtripKind, out var t))
                return t;
        return null;
    }

    /// <summary>The base the checks report was run against («donor q2dm1.bsp» in its first line).</summary>
    private static string? BaseOf(Settings s, string name)
    {
        var p = Path.Combine(s.DescriptionsPath, $"{name}.gates.txt");
        if (!File.Exists(p))
            return null;
        var first = File.ReadLines(p).FirstOrDefault() ?? "";
        var m = System.Text.RegularExpressions.Regex.Match(first, @"donor ([^\s,)]+?)(\.bsp)?[,)]");
        // a map from scratch is checked against its own skeleton's base, named as the map: that is no base (05.11, the
        // home page said «основа mg_new_duel» of mg_new_duel when its run record was not beside it)
        return m.Success && !string.Equals(m.Groups[1].Value, name, StringComparison.OrdinalIgnoreCase) ? m.Groups[1].Value : null;
    }

    private static string? Description(Settings s, string name)
    {
        foreach (var file in new[] { $"{name}.{Loc.Language}.txt", $"{name}.txt" })
        {
            var p = Path.Combine(s.DescriptionsPath, file);
            if (File.Exists(p))
                return File.ReadAllText(p);
        }
        return null;
    }

    /// <summary>
    /// Brief 27 (the PO 06.11: «Карта готова, в неё можно играть … никак не жирный красный статус»): the checks whose
    /// failure means the map cannot be played - a start in the rock, an item lost at a spawn, a place one cannot leave,
    /// a major item no spawn reaches, fewer spawns than asked. Every other failed check is a measure of taste or a
    /// planned edit not built: the map plays. By the check's key (<see cref="Loc.GateKey"/>).
    /// </summary>
    private static readonly HashSet<string> BlockingKeys = new()
    {
        "gate.starts", "gate.pickups.spawn", "gate.traps", "gate.traps-engine",
        "gate.every major item reachable from the spawns", "gate.spawns as asked",
    };

    public static bool Blocking(string what) => BlockingKeys.Contains(Loc.GateKey(what));

    /// <summary>The delivery gates' report kept beside the map (<c>name.gates.txt</c>): each PASS/FAIL line, its
    /// words after « -- » kept (brief 27: the page shows what a failed check measured).</summary>
    public static IReadOnlyList<(bool pass, string what, string said)> GateLines(Settings s, string name)
    {
        var p = Path.Combine(s.DescriptionsPath, $"{name}.gates.txt");
        return File.Exists(p) ? ParseGates(File.ReadAllLines(p)) : Array.Empty<(bool, string, string)>();
    }

    public static IReadOnlyList<(bool pass, string what, string said)> ParseGates(IEnumerable<string> lines)
    {
        var gates = new List<(bool, string, string)>();
        foreach (var raw in lines)
        {
            var line = raw.Trim();
            bool pass = line.StartsWith("PASS"), fail = line.StartsWith("FAIL");
            if (!pass && !fail)
                continue;
            var what = line[4..].Trim();
            var said = "";
            var cut = what.IndexOf(" -- ", StringComparison.Ordinal);
            if (cut > 0)
            {
                said = what[(cut + 4)..].Trim();
                what = what[..cut].Trim();
            }
            gates.Add((pass, what, said));
        }
        return gates;
    }

    /// <summary>Copy a finished map into the library, and its checks report if one lies beside it.</summary>
    public static string Import(Settings s, string source)
    {
        Directory.CreateDirectory(s.BspPath);
        var name = Path.GetFileNameWithoutExtension(source);
        var target = Path.Combine(s.BspPath, name + ".bsp");
        File.Copy(source, target, true);
        var dir = Path.GetDirectoryName(source) ?? "";
        foreach (var report in new[] { Path.Combine(dir, name + ".gates.txt"), Path.Combine(dir, "gates.txt") })
        {
            if (File.Exists(report))
            {
                Directory.CreateDirectory(s.DescriptionsPath);
                File.Copy(report, Path.Combine(s.DescriptionsPath, name + ".gates.txt"), true);
                break;
            }
        }
        return name;
    }

    /// <summary>Copy the map into the client's baseq2\maps; the path written.</summary>
    public static string CopyToClient(Settings s, MapEntry map)
    {
        var maps = Path.Combine(s.ClientDir, "baseq2", "maps");
        Directory.CreateDirectory(maps);
        var target = Path.Combine(maps, map.Name + ".bsp");
        File.Copy(map.BspPath, target, true);
        return target;
    }
}
