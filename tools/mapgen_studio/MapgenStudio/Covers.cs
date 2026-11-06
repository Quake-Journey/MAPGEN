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
        /* brief 21 §3: the PO's own viewpoints («viewpos (x y z) : yaw» from his screenshots), for a shot of the same
           place on a new map - MAPGEN_COVER_VIEWS="x y z yaw; x y z yaw" (the cover test only; the card never sets it) */
        var given = Environment.GetEnvironmentVariable("MAPGEN_COVER_VIEWS");
        if (!string.IsNullOrWhiteSpace(given))
        {
            foreach (var part in given.Split(';', StringSplitOptions.RemoveEmptyEntries))
            {
                var v = part.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries)
                            .Select(t => float.Parse(t, CultureInfo.InvariantCulture)).ToArray();
                if (v.Length == 4)
                    views.Add(new View(v[0], v[1], v[2], v[3], "given"));
            }
            if (views.Count > 0)
                return views;
        }
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
        // brief 26: a jump pad and a teleporter, looked at from their open side - the library card shows them
        foreach (var v in Fixtures(map.BspPath))
        {
            views.Add(v);
            if (views.Count >= max)
                return views;
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

    /// <summary>
    /// Brief 26: one view of a jump pad (a slanted one first: looked at from behind, along its flight) and one of a
    /// teleporter (from the side its «angle» names, else any open side), each from a standing place 96..160 away on
    /// the fixture's floor, with nothing solid between - read from the BSP's own planes, nodes and leafs (IBSP).
    /// </summary>
    public static List<View> Fixtures(string bsp)
    {
        var views = new List<View>();
        byte[] d;
        try { d = File.ReadAllBytes(bsp); } catch (IOException) { return views; }
        if (d.Length < 160 || Encoding.ASCII.GetString(d, 0, 4) != "IBSP")
            return views;
        var w = new World(d);
        var ents = Entities(d);
        var pads = new List<(float x, float y, float z, float yaw, bool steep)>();
        foreach (var e in ents.Where(e => e.GetValueOrDefault("classname") == "trigger_push"))
        {
            var m = e.GetValueOrDefault("model", "");
            if (!m.StartsWith('*') || !int.TryParse(m[1..], out var mi) || !w.Model(mi, out var lo, out var hi))
                continue;
            var ang = (e.GetValueOrDefault("angles", "") ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries)
                       .Select(t => float.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out var f) ? f : 0).ToArray();
            float pitch = ang.Length > 0 ? ang[0] : 0, yaw = ang.Length > 1 ? ang[1] : 0;
            if (e.GetValueOrDefault("angle") is string a1 && float.TryParse(a1, NumberStyles.Float, CultureInfo.InvariantCulture, out var a1f))
            {
                if (a1f == -1) pitch = -90; else yaw = a1f;
            }
            pads.Add(((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, lo[2] - 4, yaw, Math.Abs(pitch) >= 75));
        }
        foreach (var p in pads.OrderBy(p => p.steep ? 1 : 0))
        {
            // behind a slanted pad, against its flight; round a steep one
            var first = p.steep ? 0f : p.yaw + 180;
            if (Look(w, p.x, p.y, p.z, first, "pad", views))
                break;
        }
        // a teleporter in its frame first (solid at both posts: 44 to each side of its facing, 24 behind, waist high) -
        // the first cover of 06.11 looked at a bare disc of an open space and missed the frames
        var teles = new List<(float x, float y, float z, float face, bool framed)>();
        foreach (var e in ents.Where(e => e.GetValueOrDefault("classname") == "misc_teleporter"))
        {
            if (!e.TryGetValue("origin", out var o))
                continue;
            var v = o.Split(' ').Select(t => float.TryParse(t, NumberStyles.Float, CultureInfo.InvariantCulture, out var f) ? f : 0).ToArray();
            if (v.Length != 3)
                continue;
            var face = float.TryParse(e.GetValueOrDefault("angle", "0"), NumberStyles.Float, CultureInfo.InvariantCulture, out var fa) ? fa : 0;
            double a = face * Math.PI / 180;
            float fx = (float)Math.Cos(a), fy = (float)Math.Sin(a);
            bool Post(int side) => w.Solid(v[0] - 24 * fx - side * 44 * fy, v[1] - 24 * fy + side * 44 * fx, v[2] + 36);
            teles.Add((v[0], v[1], v[2], face, Post(1) && Post(-1)));
        }
        foreach (var t in teles.OrderBy(t => t.framed ? 0 : 1))
            if (Look(w, t.x, t.y, t.z - 24, t.face, "teleporter", views))
                break;
        return views;
    }

    /// <summary>A standing place on the fixture's floor 96..160 from it, the directions tried from <paramref name="first"/>
    /// round; the view from there at it. True when one was found.</summary>
    private static bool Look(World w, float x, float y, float floor, float first, string what, List<View> views)
    {
        for (var k = 0; k < 8; k++)
        {
            var a = (first + (k % 2 == 0 ? 1 : -1) * 45 * ((k + 1) / 2)) * Math.PI / 180;
            foreach (var dist in new[] { 128f, 160f, 96f })
            {
                float cx = x + dist * (float)Math.Cos(a), cy = y + dist * (float)Math.Sin(a);
                // a body's room (feet to eye, its corners) and a floor under it within 24
                var room = new[] { 8f, 32f, 56f }.All(h => new[] { (-16f, -16f), (16f, -16f), (-16f, 16f), (16f, 16f) }
                               .All(c => !w.Solid(cx + c.Item1, cy + c.Item2, floor + h)));
                if (!room || !w.Solid(cx, cy, floor - 8) && !w.Solid(cx, cy, floor - 20))
                    continue;
                // nothing solid between the eye and the fixture
                var clear = true;
                // aimed over the fixture's top (a wedge rises 32 over its floor): the line never ends inside it
                for (var t = 0.1f; t < 0.85f && clear; t += 0.05f)
                    clear = !w.Solid(cx + (x - cx) * t, cy + (y - cy) * t, floor + 46 + (40 - 46) * t);
                if (!clear)
                    continue;
                var yaw = (float)(Math.Atan2(y - cy, x - cx) * 180 / Math.PI);
                views.Add(new View(cx, cy, floor + 24, yaw, what));
                return true;
            }
        }
        return false;
    }

    /// <summary>The BSP's solid: planes, nodes and leafs of an IBSP v38 (brief 26's fixture views).</summary>
    private sealed class World
    {
        private readonly byte[] d;
        private readonly (int ofs, int len)[] lumps = new (int, int)[19];

        public World(byte[] data)
        {
            d = data;
            for (var i = 0; i < 19; i++)
                lumps[i] = (BitConverter.ToInt32(d, 8 + i * 8), BitConverter.ToInt32(d, 12 + i * 8));
        }

        public bool Model(int i, out float[] lo, out float[] hi)
        {
            lo = new float[3];
            hi = new float[3];
            var (ofs, len) = lumps[13];
            if (i < 0 || (i + 1) * 48 > len)
                return false;
            for (var k = 0; k < 3; k++)
            {
                lo[k] = BitConverter.ToSingle(d, ofs + i * 48 + k * 4);
                hi[k] = BitConverter.ToSingle(d, ofs + i * 48 + 12 + k * 4);
            }
            return true;
        }

        public bool Solid(float x, float y, float z)
        {
            var (mofs, _) = lumps[13];
            var node = BitConverter.ToInt32(d, mofs + 36);           // model 0's head node
            var (pofs, _) = lumps[1];
            var (nofs, _) = lumps[4];
            var (lofs, llen) = lumps[8];
            for (var guard = 0; node >= 0 && guard < 4096; guard++)
            {
                var at = nofs + node * 28;
                var pl = BitConverter.ToInt32(d, at);
                var pa = pofs + pl * 20;
                var dist = BitConverter.ToSingle(d, pa) * x + BitConverter.ToSingle(d, pa + 4) * y
                         + BitConverter.ToSingle(d, pa + 8) * z - BitConverter.ToSingle(d, pa + 12);
                node = BitConverter.ToInt32(d, at + (dist >= 0 ? 4 : 8));
            }
            var leaf = -1 - node;
            if (leaf < 0 || (leaf + 1) * 28 > llen)
                return true;
            return (BitConverter.ToInt32(d, lofs + leaf * 28) & 1) != 0;   // CONTENTS_SOLID
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
                var to = Path.Combine(target, $"cover_{n++:00}.png");
                File.Move(f, to, true);
                Library.ToJpeg(to);         // the PO, 12.10: a JPEG at a tenth of the PNG's size
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
