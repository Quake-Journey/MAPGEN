using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace MapgenStudio;

/// <summary>
/// Cover screenshots (R10, phase P4). The client has no command that puts the camera somewhere, so each viewpoint
/// becomes a copy of the map whose single <c>info_player_start</c> stands there facing the right way; ONE launch of
/// the client (windowed, its configs read-only, <c>net_clientport -1</c>, S5) loads them in turn from a generated
/// config, takes a PNG of each with the gun, the HUD and the console notices off, and quits. The PNGs go to
/// <c>data\covers\NAME\</c>, the copies and the config are removed, and the user's configs are hashed before and after.
/// Viewpoints: the corners of the new rooms the run's ledger names (inset, at eye height, looking at the room's middle),
/// then the map's own deathmatch spawns.
/// </summary>
public static class Covers
{
    public sealed record View(float X, float Y, float Z, float Yaw, string What);

    public static List<View> Viewpoints(MapEntry map, Settings s, int max = 4)
    {
        var views = new List<View>();
        // the new rooms, from the generation's ledger when the map was made here
        var ledger = Directory.Exists(s.TempPath)
            ? Directory.GetDirectories(s.TempPath, map.Name + "_*").Select(d => Path.Combine(d, "job", "ledger.txt"))
                       .Where(File.Exists).OrderByDescending(File.GetLastWriteTime).FirstOrDefault()
            : null;
        if (ledger != null)
        {
            var dig = new Regex(@"^\s*\d+\s+dig\s+ACCEPTED\s+\d+\s+(-?\d+) (-?\d+) (-?\d+)\s+(-?\d+) (-?\d+) (-?\d+).*shape (annex|storeys|hall)");
            foreach (var line in File.ReadLines(ledger))
            {
                var m = dig.Match(line);
                if (!m.Success)
                    continue;
                float F(int i) => float.Parse(m.Groups[i].Value, CultureInfo.InvariantCulture);
                float x0 = F(1), y0 = F(2), z0 = F(3), x1 = F(4), y1 = F(5);
                var cx = (x0 + x1) / 2; var cy = (y0 + y1) / 2;
                var px = x0 + 64; var py = y0 + 64;              // a corner, inset
                var yaw = (float)(Math.Atan2(cy - py, cx - px) * 180 / Math.PI);
                views.Add(new View(px, py, z0 + 40, yaw, m.Groups[7].Value));
                if (views.Count >= max)
                    return views;
            }
        }
        foreach (var (x, y, z, yaw) in Spawns(map.BspPath))
        {
            views.Add(new View(x, y, z, yaw, "spawn"));
            if (views.Count >= max)
                break;
        }
        return views;
    }

    private static IEnumerable<(float, float, float, float)> Spawns(string bsp)
    {
        foreach (var e in Entities(File.ReadAllBytes(bsp)))
        {
            if (e.GetValueOrDefault("classname") != "info_player_deathmatch" || !e.TryGetValue("origin", out var o))
                continue;
            var p = o.Split(' ').Select(v => float.Parse(v, CultureInfo.InvariantCulture)).ToArray();
            var yaw = float.TryParse(e.GetValueOrDefault("angle", "0"), NumberStyles.Float, CultureInfo.InvariantCulture, out var a) ? a : 0;
            if (p.Length == 3)
                yield return (p[0], p[1], p[2], yaw);
        }
    }

    // ---- the BSP's entity lump (lump 0): read, and written back as a new lump appended to a copy ---------------

    private static (int ofs, int len) Lump0(byte[] d) => (BitConverter.ToInt32(d, 8), BitConverter.ToInt32(d, 12));

    public static List<Dictionary<string, string>> Entities(byte[] d)
    {
        var (ofs, len) = Lump0(d);
        var text = Encoding.Latin1.GetString(d, ofs, len).TrimEnd('\0');
        var list = new List<Dictionary<string, string>>();
        foreach (Match block in Regex.Matches(text, @"\{([^}]*)\}"))
            list.Add(Regex.Matches(block.Groups[1].Value, "\"([^\"]*)\"\\s+\"([^\"]*)\"")
                          .GroupBy(m => m.Groups[1].Value).ToDictionary(g => g.Key, g => g.First().Groups[2].Value));
        return list;
    }

    public static bool IsSpawn(Dictionary<string, string> e) =>
        e.GetValueOrDefault("classname") is "info_player_start" or "info_player_deathmatch";

    /// <summary>
    /// A copy of the map whose only player spawns - the deathmatch one the cover launch uses and a single-player
    /// start - stand at <paramref name="v"/>. Single player is not used: the user's own single-player mutators may
    /// put monsters on the deathmatch spots (they did on 2026-10-03), a deathmatch has none.
    /// </summary>
    public static byte[] WithStart(byte[] bsp, View v)
    {
        var ents = Entities(bsp).Where(e => !IsSpawn(e)).ToList();
        foreach (var cls in new[] { "info_player_deathmatch", "info_player_start" })
            ents.Add(new Dictionary<string, string>
            {
                ["classname"] = cls,
                ["origin"] = string.Create(CultureInfo.InvariantCulture, $"{v.X:0} {v.Y:0} {v.Z:0}"),
                ["angle"] = string.Create(CultureInfo.InvariantCulture, $"{v.Yaw:0}"),
            });
        var sb = new StringBuilder();
        foreach (var e in ents)
        {
            sb.Append("{\n");
            foreach (var (k, val) in e)
                sb.Append('"').Append(k).Append("\" \"").Append(val).Append("\"\n");
            sb.Append("}\n");
        }
        var lump = Encoding.Latin1.GetBytes(sb.ToString() + "\0");
        var at = (bsp.Length + 3) & ~3;
        var outb = new byte[at + lump.Length];
        Buffer.BlockCopy(bsp, 0, outb, 0, bsp.Length);
        Buffer.BlockCopy(lump, 0, outb, at, lump.Length);
        BitConverter.GetBytes(at).CopyTo(outb, 8);
        BitConverter.GetBytes(lump.Length).CopyTo(outb, 12);
        return outb;
    }

    // ---- the launch -------------------------------------------------------------------------------------------

    public sealed class Run
    {
        public required MapEntry Map { get; init; }
        public required Client.Run Game { get; init; }
        public required List<string> TempFiles { get; init; }
        public required string ScreenshotDir { get; init; }
        public required int Views { get; init; }
    }

    /// <summary>One watched launch of the client that takes a PNG at each viewpoint and quits.</summary>
    public static Run Start(MapEntry map, Settings s)
    {
        if (!Settings.CheckClient(s.ClientDir).ok)
            throw new InvalidOperationException(Loc.T("lib.to_client.noclient"));
        var views = Viewpoints(map, s);
        if (views.Count == 0)
            throw new InvalidOperationException(Loc.T("cover.noviews"));
        var baseq2 = Path.Combine(s.ClientDir, "baseq2");
        var maps = Path.Combine(baseq2, "maps");
        Directory.CreateDirectory(maps);
        var temp = new List<string>();
        var bsp = File.ReadAllBytes(map.BspPath);
        // what a cover should not show; nothing of it is kept (q2prox_config_readonly on the command line). The
        // copies are loaded in turn as a deathmatch: the client runs cl_beginmapcmd once it is in a map, the PNG is
        // taken a moment later and the next copy loaded. `wait` counts frames from when the map is on screen; with
        // the frame rate held at 60, 150 of them are 2.5 s - the spawn's flash long gone
        var cfg = new StringBuilder();
        cfg.AppendLine("cl_gun 0\ncrosshair 0\nscr_draw2d 0\ncon_notifytime 0\ncl_maxfps 60\nr_maxfps 60\ncoop 0\ndeathmatch 1");
        for (var k = 0; k < views.Count; k++)
        {
            var name = $"mgs_cover_{k}";
            var p = Path.Combine(maps, name + ".bsp");
            File.WriteAllBytes(p, WithStart(bsp, views[k]));
            temp.Add(p);
            cfg.AppendLine($"alias mgs_go{k} \"alias mgs_at mgs_at{k}; map {name}\"");
            cfg.AppendLine($"alias mgs_at{k} \"wait 150; screenshotpng; wait 30; mgs_go{k + 1}\"");
        }
        cfg.AppendLine($"alias mgs_go{views.Count} quit");
        cfg.AppendLine("set cl_beginmapcmd mgs_at");
        cfg.AppendLine("mgs_go0");
        var cfgPath = Path.Combine(baseq2, "mgs_cover.cfg");
        File.WriteAllText(cfgPath, cfg.ToString());
        temp.Add(cfgPath);
        var run = MapgenStudio.Client.Launch(s, "+set", "vid_fullscreen", "0", "+exec", "mgs_cover.cfg");
        return new Run
        {
            Map = map, Game = run, TempFiles = temp, ScreenshotDir = Path.Combine(baseq2, "screenshots"),
            Views = views.Count,
        };
    }

    /// <summary>
    /// Done, or given up (<paramref name="timeout"/>: then that one process is ended - never a loop): the PNGs taken
    /// since the launch moved into the cover folder, the copies removed, the configs compared.
    /// </summary>
    public static (int covers, bool configsKept, string note) Finish(Run r, Settings s, bool timeout)
    {
        var note = "";
        if (timeout && !r.Game.Process.HasExited)
        {
            try
            {
                r.Game.Process.Kill();
                r.Game.Process.WaitForExit(5000);
            }
            catch (Exception) { }
            note = Loc.T("cover.timeout");
        }
        var target = Path.Combine(s.CoversPath, r.Map.Name);
        Directory.CreateDirectory(target);
        var n = 0;
        if (Directory.Exists(r.ScreenshotDir))
            foreach (var f in Directory.GetFiles(r.ScreenshotDir, "*.png")
                                       .Where(f => File.GetLastWriteTime(f) >= r.Game.Began.AddSeconds(-1))
                                       .OrderBy(File.GetLastWriteTime))
            {
                File.Move(f, Path.Combine(target, $"cover_{n++:00}.png"), true);
            }
        foreach (var t in r.TempFiles)
        {
            try
            {
                File.Delete(t);
            }
            catch (Exception) { }
        }
        return (n, MapgenStudio.Client.ConfigsKept(r.Game, s), note);
    }
}
