using System.Numerics;
using System.Text.Json;

namespace MapgenStudio;

/// <summary>
/// The PO 11.11 («на этапе проверка карты мы можем что то визуализировать?»; «было бы круто чтобы карта ходьбы и
/// визуализировалась как ходьба, ножками»; «свет то у нас сейчас именно как свет визуализируется»): the walk the map's
/// check made - the floor it reached and when, and footprints along the way from the nearest spawn point to every major
/// item. Handed over in memory by tools/check_mapgen_new_map.py --show-mem (mapgen_map_survey.write_walk_show; the PO:
/// «SSD не очень любит много записей»), read with <see cref="MemFiles"/>.
/// </summary>
public sealed class WalkShow
{
    public readonly record struct Foot(Vector3 At, float Yaw, float T, int Side);

    public sealed class Move
    {
        public string Kind = "";
        public Vector3 From, To;
        public float T;
        public List<Vector3>? Path;
    }

    public sealed class Trail
    {
        public string Cls = "";
        public Vector3 At;
        public float T;
        public readonly List<Foot> Steps = new();
        public readonly List<Move> Moves = new();
    }

    public float TMax;
    public int Reached, Points;
    public readonly List<Vector3> Spawns = new();
    public readonly List<(Vector3 at, float t)> Floor = new();
    public readonly List<Vector3> Unreached = new();
    public readonly List<Trail> Trails = new();
    /// <summary>The major items no walk from a spawn point reaches.</summary>
    public readonly List<(string cls, Vector3 at)> Lost = new();
    /// <summary>When the Studio got it: the walk's loop counts from here.</summary>
    public DateTime Since = DateTime.Now;
    /// <summary>The walk's whole span: the latest item reached or floor point, whichever is later.</summary>
    public float Span { get; private set; } = 2f;

    private static Vector3 V(JsonElement a) => new(a[0].GetSingle(), a[1].GetSingle(), a[2].GetSingle());

    public static WalkShow? Parse(byte[] json)
    {
        try
        {
            using var d = JsonDocument.Parse(json);
            var r = d.RootElement;
            var w = new WalkShow
            {
                TMax = r.GetProperty("tmax").GetSingle(),
                Reached = r.TryGetProperty("reached", out var re) ? re.GetInt32() : 0,
                Points = r.TryGetProperty("points", out var po) ? po.GetInt32() : 0,
            };
            foreach (var s in r.GetProperty("spawns").EnumerateArray())
                w.Spawns.Add(V(s));
            foreach (var f in r.GetProperty("floor").EnumerateArray())
                w.Floor.Add((V(f), f[3].GetSingle()));
            if (r.TryGetProperty("unreached", out var un))
                foreach (var u in un.EnumerateArray())
                    w.Unreached.Add(V(u));
            foreach (var t in r.GetProperty("trails").EnumerateArray())
            {
                var tr = new Trail { Cls = t.GetProperty("cls").GetString() ?? "", At = V(t.GetProperty("at")), T = t.GetProperty("t").GetSingle() };
                foreach (var s in t.GetProperty("steps").EnumerateArray())
                    tr.Steps.Add(new Foot(V(s), s[3].GetSingle(), s[4].GetSingle(), s[5].GetInt32()));
                foreach (var m in t.GetProperty("moves").EnumerateArray())
                {
                    var mv = new Move { Kind = m.GetProperty("kind").GetString() ?? "", From = V(m.GetProperty("from")),
                                        To = V(m.GetProperty("to")), T = m.GetProperty("t").GetSingle() };
                    if (m.TryGetProperty("path", out var p))
                        mv.Path = p.EnumerateArray().Select(V).ToList();
                    tr.Moves.Add(mv);
                }
                w.Trails.Add(tr);
            }
            if (r.TryGetProperty("lost", out var lost))
                foreach (var l in lost.EnumerateArray())
                    w.Lost.Add((l.GetProperty("cls").GetString() ?? "", V(l.GetProperty("at"))));
            w.Span = Math.Max(2f, Math.Max(w.TMax, w.Floor.Count > 0 ? w.Floor.Max(f => f.t) : 0));
            return w;
        }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException or FormatException
                                      or IndexOutOfRangeException)
        {
            return null;
        }
    }

    /// <summary>The walk's own seconds shown now: the walkers go at a player's pace (slowed past 12 s), then all of it
    /// held 3 s, again and again.</summary>
    public float Now(DateTime now)
    {
        var span = Span;
        var pace = Math.Max(1f, span / 12f);
        var loop = span / pace + 3f;
        var at = (float)((now - Since).TotalSeconds % loop);
        return Math.Min(span, at * pace) + (at * pace > span ? 0.001f : 0f);
    }
}

/// <summary>
/// The PO 11.11: «было бы неплохо визуализировать построение каркаса - там же наверное тоже есть что показать как он
/// строится в реальном времени». The chosen skeleton's states, step by step as the planner made it (mapgen_scratch
/// show_skeleton: the same seed made again, `mapgen_scratch_plan.RECORD`), handed over in memory while the skeleton's
/// stage runs; drawn on the scheme as the map's own faces - every place's floor at its height in its kind's colour, the
/// rises between them, a low wall round the places, the doorways bright, the liquids, lifts, pads, teleporters, items
/// and spawn points - one step after another.
/// </summary>
public static class SkeletonShow
{
    public const float Cell = 64;

    public sealed class Step
    {
        public string Name = "";
        public string[] Kinds = Array.Empty<string>();
        public readonly List<int[]> Cells = new();          // x, y, z, kind, space
        public readonly List<int[]> Doors = new();          // x, y, z, mover
        public readonly List<(int x, int y, int level, string kind)> Liquids = new();
        public readonly List<int[]> Pits = new();           // x, y, bottom
        public readonly List<int[]> Lifts = new();          // x, y, z low, z high
        public readonly List<int[]> Pads = new();           // x, y, landing x, landing y
        public readonly List<int[]> Teleports = new();      // x, y, other x, other y
        public readonly List<(string cls, int x, int y, int z)> Items = new();
        public readonly List<int[]> Spawns = new();         // x, y, z
        public readonly List<int[]> Tubes = new();          // x, y, the roof's z: a tube under water (the PO 12.11)
    }

    public sealed record Frame(string Step, int K, int N, SchemeModel.Snapshot Snap, int Part = 0, int Parts = 0);

    public static List<Step>? Parse(byte[] json)
    {
        try
        {
            using var d = JsonDocument.Parse(json);
            var steps = new List<Step>();
            foreach (var s in d.RootElement.GetProperty("steps").EnumerateArray())
                steps.Add(StepOf(s));
            return steps;
        }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException or FormatException
                                      or IndexOutOfRangeException)
        {
            return null;
        }
    }

    private static Step StepOf(JsonElement s)
    {
        var st = new Step { Name = s.GetProperty("step").GetString() ?? "",
                            Kinds = s.GetProperty("kinds").EnumerateArray().Select(k => k.GetString() ?? "").ToArray() };
        static int[] Ints(JsonElement a) => a.EnumerateArray().Select(x => x.ValueKind == JsonValueKind.Number ? x.GetInt32() : 0).ToArray();
        foreach (var c in s.GetProperty("cells").EnumerateArray())
            st.Cells.Add(Ints(c));
        foreach (var c in s.GetProperty("doors").EnumerateArray())
            st.Doors.Add(Ints(c));
        foreach (var c in s.GetProperty("liquids").EnumerateArray())
            st.Liquids.Add((c[0].GetInt32(), c[1].GetInt32(), c[2].GetInt32(), c[3].GetString() ?? "water"));
        foreach (var c in s.GetProperty("pits").EnumerateArray())
            st.Pits.Add(Ints(c));
        foreach (var c in s.GetProperty("lifts").EnumerateArray())
            st.Lifts.Add(Ints(c));
        foreach (var c in s.GetProperty("pads").EnumerateArray())
            st.Pads.Add(Ints(c));
        foreach (var c in s.GetProperty("teleports").EnumerateArray())
            st.Teleports.Add(Ints(c));
        foreach (var c in s.GetProperty("items").EnumerateArray())
            st.Items.Add((c[0].GetString() ?? "", c[1].GetInt32(), c[2].GetInt32(), c[3].GetInt32()));
        foreach (var c in s.GetProperty("spawns").EnumerateArray())
            st.Spawns.Add(Ints(c));
        if (s.TryGetProperty("tubes", out var tubes))
            foreach (var c in tubes.EnumerateArray())
                st.Tubes.Add(Ints(c));
        return st;
    }

    /// <summary>A skeleton being tried (the planner's `skeleton_live.json`): how many tried of how many, how many made a
    /// plan, whether the one shown is the best so far, its picture.</summary>
    public sealed record Try(int Done, int Tries, int Made, bool Best, SchemeModel.Snapshot Snap);

    /// <summary>The PO 12.11: the skeleton's stage shown from its first second - the planner's tries as they come.</summary>
    public static Try? ParseTry(byte[] json)
    {
        try
        {
            using var d = JsonDocument.Parse(json);
            var r = d.RootElement;
            var st = StepOf(r.GetProperty("plan"));
            if (st.Cells.Count == 0)
                return null;
            var snap = Snapshot(st, st.Cells);
            var t = new Try(r.GetProperty("done").GetInt32(), r.GetProperty("tries").GetInt32(), r.GetProperty("made").GetInt32(),
                            r.TryGetProperty("best", out var b) && b.ValueKind == JsonValueKind.True, snap);
            snap.ShowCaption = Loc.F(t.Best ? "art.skel.try.best" : "art.skel.try", t.Done, t.Tries, t.Made);
            return t;
        }
        catch (Exception e) when (e is JsonException or KeyNotFoundException or InvalidOperationException or FormatException
                                      or IndexOutOfRangeException)
        {
            return null;
        }
    }

    /// <summary>
    /// The frames shown in turn: each step with a place in it; the first one split by its levels, the lowest first (a
    /// tower's storeys go up one by one, a space's islands rise by height) - every frame framed as the whole skeleton,
    /// so the view holds still.
    /// </summary>
    public static List<Frame> Frames(List<Step> steps)
    {
        var shown = steps.Where(s => s.Cells.Count > 0).ToList();
        var frames = new List<Frame>();
        if (shown.Count == 0)
            return frames;
        var whole = Snapshot(shown[^1], shown[^1].Cells);
        for (var k = 0; k < shown.Count; k++)
        {
            var st = shown[k];
            var levels = st.Cells.Select(c => (int)MathF.Floor(c[2] / 128f)).Distinct().OrderBy(z => z).ToList();
            if (k == 0 && levels.Count > 1 && st.Cells.Count > 40)
            {
                // at most six sub-frames: the levels grouped evenly
                var groups = Math.Min(6, levels.Count);
                for (var g = 1; g <= groups; g++)
                {
                    var top = levels[(int)Math.Ceiling(g * levels.Count / (double)groups) - 1];
                    var part = st.Cells.Where(c => (int)MathF.Floor(c[2] / 128f) <= top).ToList();
                    frames.Add(new Frame(st.Name, k + 1, shown.Count, Framed(Snapshot(st, part, items: false), whole), g, groups));
                }
                continue;
            }
            frames.Add(new Frame(st.Name, k + 1, shown.Count, Framed(Snapshot(st, st.Cells), whole)));
        }
        return frames;
    }

    private static SchemeModel.Snapshot Framed(SchemeModel.Snapshot s, SchemeModel.Snapshot whole)
    {
        s.Min = whole.Min;
        s.Max = whole.Max;
        s.PlayTop = whole.PlayTop;
        return s;
    }

    private static Vector3 KindColour(string kind) => kind switch
    {
        "hall" => new Vector3(0.62f, 0.50f, 0.32f),
        "room" => new Vector3(0.46f, 0.50f, 0.60f),
        "corridor" => new Vector3(0.44f, 0.47f, 0.44f),
        "stair" => new Vector3(0.70f, 0.64f, 0.52f),
        "nook" => new Vector3(0.58f, 0.44f, 0.64f),
        "shaft" => new Vector3(0.36f, 0.50f, 0.62f),
        "perch" => new Vector3(0.66f, 0.58f, 0.36f),
        "island" => new Vector3(0.48f, 0.56f, 0.44f),
        _ => new Vector3(0.50f, 0.50f, 0.50f),
    };

    /// <summary>A colour as the scheme draws a face's own light (0.08 + light * 1.6).</summary>
    private static Vector3 AsLight(Vector3 c) => Vector3.Clamp((c - new Vector3(0.08f)) / 1.6f, Vector3.Zero, Vector3.One);

    /// <summary>One state of the skeleton as the scheme's faces and marks.</summary>
    public static SchemeModel.Snapshot Snapshot(Step st, List<int[]> cells, bool items = true)
    {
        var s = new SchemeModel.Snapshot { Source = "skeleton:" + st.Name };
        // every floor of a column: a lower floor under a higher one (rooms over rooms, a tower's storeys)
        var floors = new Dictionary<(int, int), List<int>>();
        void Floor(int x, int y, int z)
        {
            if (!floors.TryGetValue((x, y), out var l))
                floors[(x, y)] = l = new List<int>();
            l.Add(z);
        }
        foreach (var c in cells)
            Floor(c[0], c[1], c[2]);
        var doors = st.Doors.Where(d => floors.ContainsKey((d[0] + 1, d[1])) || floors.ContainsKey((d[0] - 1, d[1]))
                                        || floors.ContainsKey((d[0], d[1] + 1)) || floors.ContainsKey((d[0], d[1] - 1))).ToList();
        foreach (var d in doors)
            Floor(d[0], d[1], d[2]);
        int? Near(int x, int y, int z)
        {
            if (!floors.TryGetValue((x, y), out var l))
                return null;
            int? best = null;
            foreach (var v in l)
                if (Math.Abs(v - z) <= 96 && (best == null || Math.Abs(v - z) < Math.Abs(best.Value - z)))
                    best = v;
            return best;
        }
        void Quad(Vector3 a, Vector3 b, Vector3 c, Vector3 d, Vector3 n, byte kind, Vector3? light)
        {
            var v = new[] { a, b, c, d };
            s.Faces.Add(new SchemeModel.Face { V = v, N = n, Kind = kind, Light = light, ZLo = v.Min(p => p.Z), ZHi = v.Max(p => p.Z) });
        }
        void Tile(int x, int y, float z, byte kind, Vector3? light, float inset = 0)
        {
            float x0 = x * Cell + inset, y0 = y * Cell + inset, x1 = (x + 1) * Cell - inset, y1 = (y + 1) * Cell - inset;
            Quad(new(x0, y0, z), new(x1, y0, z), new(x1, y1, z), new(x0, y1, z), Vector3.UnitZ, kind, light);
        }
        void Side(int x, int y, int dx, int dy, float zlo, float zhi, Vector3 light)
        {
            if (zhi - zlo < 1)
                return;
            float x0 = x * Cell, y0 = y * Cell, x1 = (x + 1) * Cell, y1 = (y + 1) * Cell;
            var n = new Vector3(dx, dy, 0);
            if (dx == 1)
                Quad(new(x1, y0, zlo), new(x1, y1, zlo), new(x1, y1, zhi), new(x1, y0, zhi), n, 1, light);
            else if (dx == -1)
                Quad(new(x0, y0, zlo), new(x0, y1, zlo), new(x0, y1, zhi), new(x0, y0, zhi), n, 1, light);
            else if (dy == 1)
                Quad(new(x0, y1, zlo), new(x1, y1, zlo), new(x1, y1, zhi), new(x0, y1, zhi), n, 1, light);
            else
                Quad(new(x0, y0, zlo), new(x1, y0, zlo), new(x1, y0, zhi), new(x0, y0, zhi), n, 1, light);
        }
        var dirs = new[] { (1, 0), (-1, 0), (0, 1), (0, -1) };
        void Cliffs(int x, int y, int z, Vector3 colour)
        {
            foreach (var (dx, dy) in dirs)
            {
                var nz = Near(x + dx, y + dy, z);
                if (nz == null)
                    Side(x, y, dx, dy, z - 24, z + 48, AsLight(colour * 0.62f));      // the place's edge: a low wall
                else if (nz.Value < z - 8)
                    Side(x, y, dx, dy, nz.Value, z, AsLight(colour * 0.78f));         // a rise down to the next floor
            }
        }
        foreach (var c in cells)
        {
            var kind = c[3] >= 0 && c[3] < st.Kinds.Length ? st.Kinds[c[3]] : "";
            var shade = 0.86f + 0.14f * ((c[4] * 37 % 7) / 6f);
            var colour = KindColour(kind) * shade;
            Tile(c[0], c[1], c[2], 0, AsLight(colour));
            Cliffs(c[0], c[1], c[2], colour);
        }
        foreach (var d in doors)
        {
            var colour = d[3] != 0 ? new Vector3(0.95f, 0.72f, 0.36f) : new Vector3(0.90f, 0.86f, 0.62f);
            Tile(d[0], d[1], d[2], 0, AsLight(colour));
            Cliffs(d[0], d[1], d[2], colour);
        }
        foreach (var (x, y, level, kind) in st.Liquids.Where(l => floors.ContainsKey((l.x, l.y))))
            Tile(x, y, level, kind switch { "lava" => 4, "slime" => 5, _ => 3 }, null);
        foreach (var p in st.Pits.Where(p => floors.ContainsKey((p[0], p[1]))))
            Tile(p[0], p[1], p[2], 0, AsLight(new Vector3(0.40f, 0.10f, 0.10f)));
        // the PO 12.11: a tube under water, its water to its roof - under the floors it passes under, seen in the rock
        foreach (var t in st.Tubes)
            Tile(t[0], t[1], t[2], 3, null, 12);
        if (!items)
            return Bounded(s);
        float ZAt(int x, int y) => floors.TryGetValue((x, y), out var l) ? l.Max() : 0;
        Vector3 Mid(int x, int y, float z) => new((x + 0.5f) * Cell, (y + 0.5f) * Cell, z);
        foreach (var l in st.Lifts)
        {
            // a lift: its shaft, a cross of two panes from its low stop to its high one
            var m = Mid(l[0], l[1], 0);
            var cy = new Vector3(0.30f, 0.80f, 0.95f);
            Quad(new(m.X - 24, m.Y, l[2]), new(m.X + 24, m.Y, l[2]), new(m.X + 24, m.Y, l[3]), new(m.X - 24, m.Y, l[3]), Vector3.UnitY, 6, AsLight(cy));
            Quad(new(m.X, m.Y - 24, l[2]), new(m.X, m.Y + 24, l[2]), new(m.X, m.Y + 24, l[3]), new(m.X, m.Y - 24, l[3]), Vector3.UnitX, 6, AsLight(cy));
        }
        foreach (var p in st.Pads)
        {
            Tile(p[0], p[1], ZAt(p[0], p[1]) + 4, 0, AsLight(new Vector3(0.35f, 0.90f, 0.45f)), 12);
            Tile(p[2], p[3], ZAt(p[2], p[3]) + 2, 0, AsLight(new Vector3(0.30f, 0.65f, 0.38f)), 20);
        }
        foreach (var t in st.Teleports)
        {
            s.Marks.Add(("teleport", Mid(t[0], t[1], ZAt(t[0], t[1]) + 24)));
            s.Marks.Add(("teleport", Mid(t[2], t[3], ZAt(t[2], t[3]) + 24)));
        }
        foreach (var (cls, x, y, z) in st.Items)
        {
            var kind = cls.StartsWith("weapon_") ? "weapon"
                     : cls.StartsWith("item_armor") ? "armor"
                     : cls.StartsWith("item_health") ? (cls.Contains("mega") ? "mega" : "health")
                     : cls.StartsWith("ammo_") ? "ammo"
                     : cls is "item_quad" or "item_invulnerability" or "item_power_shield" or "item_power_screen" or "item_adrenaline"
                         ? "power" : "";
            if (kind.Length > 0)
                s.Marks.Add((kind, Mid(x, y, z + 24)));
        }
        foreach (var sp in st.Spawns)
            s.Marks.Add(("spawn", Mid(sp[0], sp[1], sp[2] + 24)));
        return Bounded(s);
    }

    private static SchemeModel.Snapshot Bounded(SchemeModel.Snapshot s)
    {
        if (s.Faces.Count == 0)
            return s;
        s.Min = new Vector3(float.MaxValue);
        s.Max = new Vector3(float.MinValue);
        foreach (var f in s.Faces)
            foreach (var p in f.V)
            {
                s.Min = Vector3.Min(s.Min, p);
                s.Max = Vector3.Max(s.Max, p);
            }
        s.PlayTop = s.Marks.Count > 0 ? Math.Min(s.Max.Z, s.Marks.Max(m => m.at.Z) + 160) : s.Max.Z;
        return s;
    }

    /// <summary>The words over a frame: the step's name, its number and the steps' count.</summary>
    public static string Caption(Frame f)
    {
        var name = Loc.Has($"skel.{f.Step}") ? Loc.T($"skel.{f.Step}") : f.Step;
        return f.Parts > 1 ? Loc.F("art.skel.part", name, f.K, f.N, f.Part, f.Parts) : Loc.F("art.skel", name, f.K, f.N);
    }

    /// <summary>A step's time on the scheme: the steps come when the stage has some ten seconds left (the PO 12.11: his
    /// 27 s stage, 15 of them trying) - all eleven of a rooms map within them.</summary>
    public const double FrameSeconds = 0.9;

    /// <summary>The frame shown now: each <see cref="FrameSeconds"/> the next, the whole skeleton held 4 s, then again.</summary>
    public static int At(int frames, DateTime since, DateTime now)
    {
        if (frames <= 1)
            return 0;
        var loop = frames * FrameSeconds + 4;
        var t = (now - since).TotalSeconds % loop;
        return Math.Min(frames - 1, (int)(t / FrameSeconds));
    }
}
