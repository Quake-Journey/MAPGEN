namespace MapgenStudio;

/// <summary>One map of the library: its file, cover, description and checks report, all by its name.</summary>
public sealed record MapEntry(string Name, string BspPath, DateTime Made, long Bytes, string? CoverPath,
                              string? Description, IReadOnlyList<(bool pass, string what)> Gates)
{
    /// <summary>Every picture in the map's cover folder, in name order (S-2).</summary>
    public IReadOnlyList<string> Shots { get; init; } = Array.Empty<string>();

    /// <summary>The base the checks report names, for a map made outside the program (S-5).</summary>
    public string? Base { get; init; }
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
            list.Add(new MapEntry(name, bsp, Made(s, name) ?? info.LastWriteTime, info.Length, Cover(s, name),
                                  Description(s, name), Gates(s, name))
            {
                Shots = Shots(s, name),
                Base = BaseOf(s, name),
            });
        }
        return list.OrderByDescending(m => m.Made).ToList();
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
        return m.Success ? m.Groups[1].Value : null;
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

    /// <summary>The delivery gates' report kept beside the map (<c>name.gates.txt</c>): each PASS/FAIL line.</summary>
    private static IReadOnlyList<(bool, string)> Gates(Settings s, string name)
    {
        var p = Path.Combine(s.DescriptionsPath, $"{name}.gates.txt");
        if (!File.Exists(p))
            return Array.Empty<(bool, string)>();
        var gates = new List<(bool, string)>();
        foreach (var raw in File.ReadAllLines(p))
        {
            var line = raw.Trim();
            bool pass = line.StartsWith("PASS"), fail = line.StartsWith("FAIL");
            if (!pass && !fail)
                continue;
            var what = line[4..].Trim();
            var cut = what.IndexOf(" -- ", StringComparison.Ordinal);
            if (cut > 0)
                what = what[..cut];
            gates.Add((pass, what));
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
