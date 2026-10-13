using System.IO.Compression;
using System.Text;

namespace MapgenStudio;

/// <summary>
/// The PO, 07.10: «сделай там где готовые карты кнопочку - подготовить zip с картой ... внутри архива должно быть
/// baseq2/maps - тут карта, baseq2/textures - текстуры и тд, и там все лежать что нужно». A map made with destruction
/// wears copies of walls with cracks and the generator's pack (textures/mgd, textures/mapgen) - files beside the game,
/// not in its paks; a server's players need them. The zip holds the map and every texture (and sky) it names that the
/// game's own paks do not hold, as loose files of the client's baseq2, laid out as in baseq2.
/// </summary>
public static class MapZip
{
    public sealed record Result(string ZipPath, int Textures, int Files, long Bytes, IReadOnlyList<string> Missing);

    private static readonly string[] TextureKinds = { ".wal", ".png", ".jpg", ".tga" };
    private static readonly string[] SkySides = { "rt", "bk", "lf", "ft", "up", "dn" };
    private static readonly string[] SkyKinds = { ".pcx", ".tga", ".png", ".jpg" };

    /// <summary>The zip of the map for a server at `zip` (where the user chose); what went in, and the names found nowhere.</summary>
    public static Result Build(Settings s, MapEntry map, string zip)
    {
        var game = Path.Combine(s.ClientDir, "baseq2");
        var bsp = File.ReadAllBytes(map.BspPath);
        var inPaks = PakNames(game);
        var files = new List<(string entry, string path)> { ($"baseq2/maps/{map.Name}.bsp", map.BspPath) };
        var missing = new List<string>();
        var textures = 0;
        foreach (var name in TextureNames(bsp))
        {
            var rel = $"textures/{name}";
            if (inPaks.Contains(rel + ".wal"))
                continue;                       // the game's own: every player has it
            var found = TextureKinds.Select(k => rel + k).Where(r => File.Exists(Path.Combine(game, r)))
                                    .Concat(TextureKinds.Select(k => rel + k.ToUpperInvariant())
                                                        .Where(r => File.Exists(Path.Combine(game, r))))
                                    .Distinct(StringComparer.OrdinalIgnoreCase).ToList();
            if (found.Count == 0)
            {
                missing.Add(name);
                continue;
            }
            textures++;
            files.AddRange(found.Select(r => ($"baseq2/{r}", Path.Combine(game, r))));
        }
        var sky = WorldspawnValue(bsp, "sky");
        if (!string.IsNullOrWhiteSpace(sky))
            foreach (var side in SkySides)
            {
                var rel = $"env/{sky}{side}";
                if (SkyKinds.Any(k => inPaks.Contains(rel + k)))
                    continue;
                files.AddRange(SkyKinds.Select(k => rel + k).Where(r => File.Exists(Path.Combine(game, r)))
                                       .Select(r => ($"baseq2/{r}", Path.Combine(game, r))));
            }
        Directory.CreateDirectory(Path.GetDirectoryName(zip) ?? ".");
        var temp = zip + ".part";
        if (File.Exists(temp))
            File.Delete(temp);
        long bytes = 0;
        using (var z = ZipFile.Open(temp, ZipArchiveMode.Create))
            foreach (var (entry, path) in files.DistinctBy(f => f.entry, StringComparer.OrdinalIgnoreCase))
            {
                z.CreateEntryFromFile(path, entry, CompressionLevel.Fastest);
                bytes += new FileInfo(path).Length;
            }
        File.Move(temp, zip, true);
        return new Result(zip, textures, files.Count, bytes, missing);
    }

    /// <summary>The texture names of the map's texinfo (lump 5), lower case, each once.</summary>
    private static IEnumerable<string> TextureNames(byte[] bsp)
    {
        var ofs = BitConverter.ToInt32(bsp, 8 + 8 * 5);
        var len = BitConverter.ToInt32(bsp, 8 + 8 * 5 + 4);
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        for (var i = 0; i + 76 <= len; i += 76)
        {
            var raw = Encoding.Latin1.GetString(bsp, ofs + i + 40, 32);
            var name = raw.Split('\0')[0].Trim().Replace('\\', '/');      // its own case: a Linux server is not lenient
            if (name.Length > 0 && seen.Add(name))
                yield return name;
        }
    }

    /// <summary>A key of the worldspawn (the entity lump's first block).</summary>
    private static string? WorldspawnValue(byte[] bsp, string key)
    {
        var ofs = BitConverter.ToInt32(bsp, 8);
        var len = BitConverter.ToInt32(bsp, 12);
        var text = Encoding.Latin1.GetString(bsp, ofs, Math.Max(0, Math.Min(len, bsp.Length - ofs)));
        var end = text.IndexOf('}');
        var first = end > 0 ? text[..end] : text;
        var m = System.Text.RegularExpressions.Regex.Match(first, "\"" + key + "\"\\s+\"([^\"]*)\"");
        return m.Success ? m.Groups[1].Value : null;
    }

    /// <summary>Every file name the game's paks (pak*.pak) and archives (*.pkz, *.zip) hold, lower case.</summary>
    private static HashSet<string> PakNames(string game)
    {
        var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (!Directory.Exists(game))
            return names;
        foreach (var pak in Directory.GetFiles(game, "*.pak"))
            try
            {
                using var f = File.OpenRead(pak);
                using var r = new BinaryReader(f);
                if (Encoding.ASCII.GetString(r.ReadBytes(4)) != "PACK")
                    continue;
                var dirOfs = r.ReadInt32();
                var dirLen = r.ReadInt32();
                f.Seek(dirOfs, SeekOrigin.Begin);
                for (var i = 0; i < dirLen / 64; i++)
                {
                    var name = Encoding.Latin1.GetString(r.ReadBytes(56)).Split('\0')[0];
                    r.ReadInt64();
                    names.Add(name.Replace('\\', '/'));
                }
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException or EndOfStreamException)
            {
            }
        foreach (var pkz in Directory.GetFiles(game, "*.pkz").Concat(Directory.GetFiles(game, "*.zip")))
            try
            {
                using var z = ZipFile.OpenRead(pkz);
                foreach (var e in z.Entries)
                    names.Add(e.FullName.Replace('\\', '/'));
            }
            catch (Exception e) when (e is IOException or InvalidDataException or UnauthorizedAccessException)
            {
            }
        return names;
    }
}
