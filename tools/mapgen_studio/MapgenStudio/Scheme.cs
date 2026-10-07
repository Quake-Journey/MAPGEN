using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform;
using Avalonia.Rendering.SceneGraph;
using Avalonia.Skia;
using Avalonia.Threading;
using FluentAvalonia.UI.Controls;
using SkiaSharp;

namespace MapgenStudio;

/// <summary>
/// The run's plan, drawn as it is built (ledger row 410; the PO, 05.10: «визуализировать графически схему того, что
/// происходит ... мигающим синеньким что то пробуется, потом оно становится красным если отклоняется и исчезает через
/// секунд 10, а зеленым то что принято, а потом зеленое становится коричневым ... как стабильное»; then «3D схему
/// рисовать? чтобы её вращать можно было, увеличивать уменьшать - BSP то вся есть»). The map in 3D from its compiled
/// file - the one the last accepted edit left (its try's own), else the rebuilt base, the finished file at the end -
/// its floors shaded by height, walls, water, lava and slime, lifts and doors, the pickups and spawns; over it the
/// edits from the job's ledger and the one being tried from the run's «stage=try» line. Read on a pool thread.
/// </summary>
public sealed class SchemeModel
{
    public sealed class Face
    {
        public Vector3[] V = Array.Empty<Vector3>();
        public Vector3 N;
        public byte Kind;          // 0 floor, 1 wall, 2 ceiling, 3 water, 4 lava, 5 slime, 6 a mover (lift, door)
        /* row 411: the face's own light, the mean of its lightmap (0..1 a channel); null for a map not lit yet */
        public Vector3? Light;
        public float ZLo, ZHi;
    }

    public sealed class Snapshot
    {
        public readonly List<Face> Faces = new();
        public readonly List<(string what, Vector3 at)> Marks = new();
        /// <summary>Row 411: the map carries its light (the light pass has run) - the plan draws it lit.</summary>
        public bool Lit;
        public Vector3 Min, Max;
        /// <summary>
        /// Where play happens: the highest pickup or spawn and a storey over it. Above it are the roofs under the
        /// sky - the PO's mg_10_42 (koldduel1): roofs at 1152..1328 over the whole plan seen from above.
        /// </summary>
        public float PlayTop;
        public string Source = "";
        public int Floors => Faces.Count(f => f.Kind == 0);
    }

    /// <summary>Row 411: an edit of the plan (plan.txt), drawn faint until it is tried.</summary>
    public sealed record Planned(int Index, string Family, string Shape, float[]? Box);

    /// <summary>The run's plan as the generator wrote it, this round's.</summary>
    public List<Planned> Plan { get; private set; } = new();
    private DateTime _planTime;

    public sealed class Edit
    {
        public int Index;
        public string Family = "";
        public string Verdict = "";
        public float[]? Box;       // x, y, z low then high
        public DateTime Seen;
        public bool Old;           // there before this view looked, or replayed: drawn as settled
    }

    public Snapshot? Current { get; private set; }
    public readonly List<Edit> Edits = new();
    public readonly object Sync = new();
    private string _jobDir = "";
    private long _ledgerRead;
    private long _ruinRead;
    private string _base = "";
    private DateTime _baseTime;
    private Task? _refresh;
    private bool _first = true;

    private static readonly Regex Row = new(
        @"^\s*(\d+)\s+(\S+)\s+(\S+)\s+\d+(?:\s+(-?\d+) (-?\d+) (-?\d+)\s+(-?\d+) (-?\d+) (-?\d+))?", RegexOptions.Compiled);

    /// <summary>Read what the run wrote since, on a pool thread, one refresh at a time; never waits.</summary>
    public void RefreshAsync(Generation g)
    {
        if (_refresh is { IsCompleted: false })
            return;
        var job = g.JobDir;
        var replaying = g.Replaying || g.Stage == "resume";
        // row 411: the finished map as soon as it is named (lit, through the checks and the cover), not only at the end
        var artifact = File.Exists(g.Artifact) ? g.Artifact : "";
        var memory = g.Running ? g.MemoryRoot : "";
        _refresh = Task.Run(() =>
        {
            try
            {
                Refresh(job, replaying, artifact, memory);
            }
            catch (Exception)
            {
                // a file half written: the next beat reads it
            }
        });
    }

    /// <summary>One refresh on this thread (the plan test).</summary>
    public void RefreshNow(string job, string memory = "") => Refresh(job, false, "", memory);

    private void Refresh(string job, bool replaying, string artifact, string memory = "")
    {
        if (job != _jobDir)
        {
            _jobDir = job;
            _ledgerRead = 0;
            _base = "";
            _first = true;
            lock (Sync)
                Edits.Clear();
        }
        // row 411: the plan, again when the generator rewrites it (a new round)
        var planFile = Path.Combine(job, "plan.txt");
        if (File.Exists(planFile) && File.GetLastWriteTimeUtc(planFile) != _planTime)
        {
            _planTime = File.GetLastWriteTimeUtc(planFile);
            var plan = new List<Planned>();
            using var pf = new FileStream(planFile, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            using var pr = new StreamReader(pf);
            while (pr.ReadLine() is { } line)
            {
                var w = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (w.Length < 3 || line.StartsWith('#') || !int.TryParse(w[0], out var idx))
                    continue;
                float[]? box = null;
                if (w.Length >= 9 && w.Skip(3).Take(6).All(x => float.TryParse(x, NumberStyles.Float, CultureInfo.InvariantCulture, out _)))
                    box = Box(w.Skip(3).Take(6).Select(x => float.Parse(x, CultureInfo.InvariantCulture)).ToArray());
                plan.Add(new Planned(idx, w[1], w[2], box));
            }
            Plan = plan;
        }
        var ledger = Path.Combine(job, "ledger.txt");
        var newest = -1;
        if (File.Exists(ledger))
        {
            using var f = new FileStream(ledger, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete);
            if (f.Length > _ledgerRead)
            {
                f.Seek(_ledgerRead, SeekOrigin.Begin);
                using var r = new StreamReader(f, Encoding.UTF8);
                var text = r.ReadToEnd();
                var cut = text.LastIndexOf('\n');
                if (cut >= 0)
                {
                    _ledgerRead += Encoding.UTF8.GetByteCount(text[..(cut + 1)]);
                    var now = DateTime.Now;
                    var added = new List<Edit>();
                    foreach (var line in text[..cut].Split('\n'))
                    {
                        var m = Row.Match(line);
                        if (!m.Success)
                            continue;
                        var e = new Edit
                        {
                            Index = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture),
                            Family = m.Groups[2].Value,
                            Verdict = m.Groups[3].Value,
                            Seen = now,
                            Old = _first || replaying,
                        };
                        if (m.Groups[4].Success)
                            e.Box = Box(Enumerable.Range(4, 6)
                                .Select(k => float.Parse(m.Groups[k].Value, CultureInfo.InvariantCulture)).ToArray());
                        added.Add(e);
                    }
                    lock (Sync)
                        Edits.AddRange(added);
                }
            }
            _first = false;
        }
        // the PO, 07.10: the ruin on the scheme as it is built - what the destroy driver made, a box each
        var ruin = Path.Combine(job, "ruin.txt");
        if (File.Exists(ruin) && new FileInfo(ruin).Length != _ruinRead)
        {
            _ruinRead = new FileInfo(ruin).Length;
            var now = DateTime.Now;
            var added = new List<Edit>();
            foreach (var line in File.ReadAllLines(ruin))
            {
                var p = line.Split(' ', StringSplitOptions.RemoveEmptyEntries);
                if (p.Length != 7 || !p.Skip(1).All(v => float.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out _)))
                    continue;
                added.Add(new Edit
                {
                    Index = -1, Family = "ruin." + p[0], Verdict = "ACCEPTED", Seen = now,
                    Box = Box(p.Skip(1).Select(v => float.Parse(v, NumberStyles.Float, CultureInfo.InvariantCulture)).ToArray()),
                });
            }
            lock (Sync)
            {
                Edits.RemoveAll(e => e.Family.StartsWith("ruin.", StringComparison.Ordinal));
                Edits.AddRange(added);
            }
        }
        /*
         * Row 411: a try's folder is numbered by the ATTEMPT - the ledger's row, counted from 0 - not by the edit's
         * index in the plan (row 142 of a run is edit 142 of its plan, try_0020 its 21st attempt). Taking the edit's
         * index named a folder that was never made, and the plan drew the base through the whole run.
         */
        lock (Sync)
            for (var row = 0; row < Edits.Count; row++)
                if (Edits[row].Verdict == "ACCEPTED" && Edits[row].Index >= 0)   /* the ruin's boxes are no try */
                    newest = row;
        /*
         * Row 411 (Fable's brief 8): a run in memory keeps the map being built there - its last accepted try's and its
         * base are sections the engine holds, read while it holds them; the disk has only the steps it was asked to
         * keep (and the finished map).
         */
        if (artifact.Length == 0 && memory.Length > 0
            && !(newest >= 0 && File.Exists(Path.Combine(job, $"try_{newest:0000}", "q2mg.bsp"))))
        {
            foreach (var rel in new[] { newest >= 0 ? $"try_{newest:0000}/q2mg.bsp" : "", "baseline/q2mg.bsp" })
            {
                if (rel.Length == 0)
                    continue;
                var key = $"mem:{memory}/{rel}";
                if (key == _base)
                    return;
                var bytes = MemFiles.Read(memory, rel);
                if (bytes == null)
                    continue;
                var shot = Read(bytes);
                shot.Source = key;
                _base = key;
                _baseTime = DateTime.MinValue;
                Current = shot;
                return;
            }
        }
        // the map as it stands: the finished file, else the last accepted try's, else the rebuilt base
        var source = artifact.Length > 0 ? artifact
                   : newest >= 0 && File.Exists(Path.Combine(job, $"try_{newest:0000}", "q2mg.bsp"))
                       ? Path.Combine(job, $"try_{newest:0000}", "q2mg.bsp")
                   : Path.Combine(job, "baseline", "q2mg.bsp");
        if (!File.Exists(source))
            return;
        var stamp = File.GetLastWriteTime(source);
        if (source == _base && stamp == _baseTime)
            return;
        var snap = Read(File.ReadAllBytes(source));
        snap.Source = source;
        _base = source;
        _baseTime = stamp;
        Current = snap;
    }

    /// <summary>A box at least 32 on each axis, so a widened doorway's two-unit box is still seen.</summary>
    public static float[] Box(float[] b)
    {
        var r = new float[6];
        for (var a = 0; a < 3; a++)
        {
            float lo = Math.Min(b[a], b[a + 3]), hi = Math.Max(b[a], b[a + 3]);
            if (hi - lo < 32)
            {
                var c = (lo + hi) / 2;
                (lo, hi) = (c - 16, c + 16);
            }
            (r[a], r[a + 3]) = (lo, hi);
        }
        return r;
    }

    // ---- the map, from its BSP (Quake II, IBSP 38) ----------------------------------------------------------------

    private const int SurfSky = 0x4, SurfWarp = 0x8, SurfNodraw = 0x80;

    public static Snapshot Read(byte[] d)
    {
        var s = new Snapshot();
        if (d.Length < 160 || Encoding.ASCII.GetString(d, 0, 4) != "IBSP")
            return s;
        (int off, int len) L(int n) => (BitConverter.ToInt32(d, 8 + 8 * n), BitConverter.ToInt32(d, 12 + 8 * n));
        var (po, pl) = L(1);
        var (vo, vl) = L(2);
        var (to, tl) = L(5);
        var (fo, fl) = L(6);
        var (eo, _) = L(11);
        var (so, _) = L(12);
        var (mo, ml) = L(13);
        var (lo, ll) = L(7);
        float F(int at) => BitConverter.ToSingle(d, at);
        var verts = new Vector3[vl / 12];
        for (var i = 0; i < verts.Length; i++)
            verts[i] = new Vector3(F(vo + 12 * i), F(vo + 12 * i + 4), F(vo + 12 * i + 8));
        // the entities first: a brush model with an origin is stored around it (row 410), and the marks
        var origins = ReadEntities(d, L(0), s);
        s.Min = new Vector3(float.MaxValue);
        s.Max = new Vector3(float.MinValue);
        for (var m = 0; m < ml / 48; m++)
        {
            var first = BitConverter.ToInt32(d, mo + 48 * m + 40);
            var count = BitConverter.ToInt32(d, mo + 48 * m + 44);
            var shift = origins.TryGetValue(m, out var o) ? o : Vector3.Zero;
            for (var fi = first; fi < first + count && fi < fl / 20; fi++)
            {
                var f = fo + 20 * fi;
                int plane = BitConverter.ToUInt16(d, f), side = BitConverter.ToInt16(d, f + 2);
                int firstEdge = BitConverter.ToInt32(d, f + 4), numEdges = BitConverter.ToInt16(d, f + 8);
                int tex = BitConverter.ToInt16(d, f + 10);
                if (plane * 20 >= pl || tex < 0 || tex * 76 >= tl || numEdges < 3)
                    continue;
                var flags = BitConverter.ToInt32(d, to + 76 * tex + 32);
                if ((flags & (SurfSky | SurfNodraw)) != 0)
                    continue;
                var n = new Vector3(F(po + 20 * plane), F(po + 20 * plane + 4), F(po + 20 * plane + 8)) * (side != 0 ? -1 : 1);
                var pts = new Vector3[numEdges];
                var ok = true;
                for (var k = 0; k < numEdges && ok; k++)
                {
                    var se = BitConverter.ToInt32(d, so + 4 * (firstEdge + k));
                    var v = se >= 0 ? BitConverter.ToUInt16(d, eo + 4 * se) : BitConverter.ToUInt16(d, eo + 4 * -se + 2);
                    ok = v < verts.Length;
                    if (ok)
                        pts[k] = verts[v] + shift;
                }
                if (!ok)
                    continue;
                byte kind;
                if ((flags & SurfWarp) != 0)
                {
                    var name = Encoding.ASCII.GetString(d, to + 76 * tex + 40, 32).TrimEnd('\0').ToLowerInvariant();
                    kind = (byte)(name.Contains("lava") ? 4 : name.Contains("slime") ? 5 : 3);
                }
                else
                    kind = (byte)(m > 0 ? 6 : n.Z > 0.7f ? 0 : n.Z < -0.7f ? 2 : 1);
                var face = new Face { V = pts, N = n, Kind = kind, ZLo = pts.Min(p => p.Z), ZHi = pts.Max(p => p.Z) };
                // row 411: its light - the mean of its lightmap's first style, sized as the engine sizes it
                var lightOfs = BitConverter.ToInt32(d, f + 16);
                if (ll > 0 && lightOfs >= 0 && d[f + 12] != 255 && (flags & SurfWarp) == 0)
                {
                    var t0 = to + 76 * tex;
                    float sMin = float.MaxValue, sMax = float.MinValue, tMin = float.MaxValue, tMax = float.MinValue;
                    foreach (var p in pts.Select(q => q - shift))
                    {
                        var sv = p.X * F(t0) + p.Y * F(t0 + 4) + p.Z * F(t0 + 8) + F(t0 + 12);
                        var tv = p.X * F(t0 + 16) + p.Y * F(t0 + 20) + p.Z * F(t0 + 24) + F(t0 + 28);
                        (sMin, sMax, tMin, tMax) = (Math.Min(sMin, sv), Math.Max(sMax, sv), Math.Min(tMin, tv), Math.Max(tMax, tv));
                    }
                    var w = (int)(Math.Ceiling(sMax / 16) - Math.Floor(sMin / 16)) + 1;
                    var h = (int)(Math.Ceiling(tMax / 16) - Math.Floor(tMin / 16)) + 1;
                    var luxels = w * h;
                    if (w > 0 && h > 0 && luxels < 65536 && lightOfs + 3L * luxels <= ll)
                    {
                        long r = 0, gg = 0, b = 0;
                        for (var k = 0; k < luxels; k++)
                        {
                            var at = lo + lightOfs + 3 * k;
                            r += d[at];
                            gg += d[at + 1];
                            b += d[at + 2];
                        }
                        face.Light = new Vector3(r, gg, b) / (255f * luxels);
                        s.Lit = true;
                    }
                }
                s.Faces.Add(face);
                foreach (var p in pts)
                {
                    s.Min = Vector3.Min(s.Min, p);
                    s.Max = Vector3.Max(s.Max, p);
                }
            }
        }
        if (s.Faces.Count == 0)
        {
            s.Min = s.Max = Vector3.Zero;
            return s;
        }
        s.PlayTop = s.Marks.Count > 0 ? Math.Min(s.Max.Z, s.Marks.Max(x => x.at.Z) + 160) : s.Max.Z;
        return s;
    }

    /// <summary>The marks (pickups, spawns, teleporters) into the snapshot; the brush models' origins, by model.</summary>
    private static Dictionary<int, Vector3> ReadEntities(byte[] d, (int off, int len) lump, Snapshot s)
    {
        var origins = new Dictionary<int, Vector3>();
        var text = Encoding.Latin1.GetString(d, lump.off, Math.Max(0, lump.len)).TrimEnd('\0');
        foreach (Match e in Regex.Matches(text, @"\{([^{}]*)\}"))
        {
            var keys = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
            foreach (Match kv in Regex.Matches(e.Groups[1].Value, "\"([^\"]*)\"\\s+\"([^\"]*)\""))
                keys[kv.Groups[1].Value] = kv.Groups[2].Value;
            var cls = keys.GetValueOrDefault("classname", "");
            var at = keys.TryGetValue("origin", out var o) ? Parse3(o) : null;
            if (keys.TryGetValue("model", out var model) && model.StartsWith('*') && int.TryParse(model[1..], out var mi))
            {
                if (at is { } shift)
                    origins[mi] = shift;
                continue;
            }
            if (at is not { } p)
                continue;
            var kind = cls.StartsWith("weapon_") ? "weapon"
                     : cls.StartsWith("item_armor") ? "armor"
                     : cls.StartsWith("item_health") ? (cls.Contains("mega") ? "mega" : "health")
                     : cls.StartsWith("ammo_") ? "ammo"
                     : cls is "item_quad" or "item_invulnerability" or "item_power_shield" or "item_power_screen"
                              or "item_adrenaline" or "item_silencer" or "item_breather" or "item_enviro"
                         ? "power"
                     : cls.StartsWith("info_player") ? "spawn"
                     : cls == "misc_teleporter" ? "teleport"
                     : "";
            if (kind.Length > 0)
                s.Marks.Add((kind, p));
        }
        return origins;
    }

    private static Vector3? Parse3(string v)
    {
        var parts = v.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 3)
            return null;
        var r = new float[3];
        for (var i = 0; i < 3; i++)
            if (!float.TryParse(parts[i], NumberStyles.Float, CultureInfo.InvariantCulture, out r[i]))
                return null;
        return new Vector3(r[0], r[1], r[2]);
    }
}

/// <summary>
/// The plan in 3D: an orbit about the map - the left button turns it, the right moves it, the wheel brings it nearer,
/// a double click goes back to the view from above. Drawn with Skia, faces far to near (each face is one plane of the
/// map, seen only from the side it faces - from above, the floors and the walls' inner sides; the ceilings never
/// hide what is under them). Floors above <see cref="Cut"/> are left out: the roofs over where play happens.
/// </summary>
public sealed class SchemeView : Control
{
    private readonly SchemeModel _model;
    private readonly Func<Generation?> _run;
    private readonly DispatcherTimer _timer;
    private SchemeModel.Snapshot? _fitted;
    private float _yaw = -90, _pitch = 89, _dist = 3000;
    private Vector3 _target;
    private Point? _drag;
    private bool _panning;

    public double? Cut { get; set; }

    public SchemeView(SchemeModel model, Func<Generation?> run)
    {
        _model = model;
        _run = run;
        ClipToBounds = true;
        Focusable = true;
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _timer.Tick += (_, _) => InvalidateVisual();
        AttachedToVisualTree += (_, _) => _timer.Start();
        DetachedFromVisualTree += (_, _) => _timer.Stop();
        PointerWheelChanged += (_, e) =>
        {
            _dist = Math.Clamp(_dist * (e.Delta.Y > 0 ? 1 / 1.15f : 1.15f), 100, 100000);
            e.Handled = true;
            InvalidateVisual();
        };
        PointerPressed += (_, e) =>
        {
            if (e.ClickCount == 2)
            {
                Top();
                return;
            }
            var pt = e.GetCurrentPoint(this);
            _panning = pt.Properties.IsRightButtonPressed || pt.Properties.IsMiddleButtonPressed;
            _drag = pt.Position;
            e.Pointer.Capture(this);
        };
        PointerMoved += (_, e) =>
        {
            if (_drag is not { } from)
                return;
            var p = e.GetPosition(this);
            var dx = (float)(p.X - from.X);
            var dy = (float)(p.Y - from.Y);
            _drag = p;
            if (_panning)
            {
                var (_, right, up, _) = Camera();
                var k = _dist / Focal();
                _target += (-right * dx + up * dy) * k;
            }
            else
            {
                _yaw -= dx * 0.4f;
                _pitch = Math.Clamp(_pitch + dy * 0.4f, 5, 89.5f);
            }
            InvalidateVisual();
        };
        PointerReleased += (_, e) =>
        {
            _drag = null;
            e.Pointer.Capture(null);
        };
    }

    /// <summary>From above, north up, the whole map in view.</summary>
    public void Top()
    {
        _yaw = -90;
        _pitch = 89;
        Fit();
    }

    /// <summary>From the south-west, half way up.</summary>
    public void Slant()
    {
        _yaw = -125;
        _pitch = 40;
        Fit();
    }

    /// <summary>
    /// The whole map in view. From <see cref="Render"/> without asking for a new frame - a visual invalidated during
    /// the render pass is fatal (the PO's first resume with the plan, 05.10: the Studio closed at once).
    /// </summary>
    private void Fit(bool invalidate = true)
    {
        if (_model.Current is not { } s)
            return;
        _fitted = s;
        var top = (float)(Cut ?? s.Max.Z);
        _target = new Vector3((s.Min.X + s.Max.X) / 2, (s.Min.Y + s.Max.Y) / 2, Math.Min(top, (s.Min.Z + s.Max.Z) / 2));
        var span = Math.Max(s.Max.X - s.Min.X, s.Max.Y - s.Min.Y);
        _dist = span * 1.2f;
        if (invalidate)
            InvalidateVisual();
    }

    private float Focal() => (float)(Math.Max(1, Bounds.Height) / 2 / Math.Tan(25 * Math.PI / 180));

    private (Vector3 eye, Vector3 right, Vector3 up, Vector3 fwd) Camera()
    {
        double y = _yaw * Math.PI / 180, p = _pitch * Math.PI / 180;
        var dir = new Vector3((float)(Math.Cos(p) * Math.Cos(y)), (float)(Math.Cos(p) * Math.Sin(y)), (float)Math.Sin(p));
        var fwd = -dir;
        var right = new Vector3((float)-Math.Sin(y), (float)Math.Cos(y), 0);
        var up = Vector3.Cross(right, fwd);
        return (_target + dir * _dist, right, up, fwd);
    }

    public override void Render(DrawingContext ctx)
    {
        var s = _model.Current;
        if (s == null || s.Faces.Count == 0)
        {
            ctx.FillRectangle(new SolidColorBrush(Color.FromRgb(0x16, 0x18, 0x1c)), new Rect(Bounds.Size));
            var t = new FormattedText(Loc.T("scheme.wait"), CultureInfo.CurrentUICulture, FlowDirection.LeftToRight,
                                      Typeface.Default, 14, Brushes.Gray);
            ctx.DrawText(t, new Point(16, 16));
            return;
        }
        if (_fitted == null)
            Fit(invalidate: false);
        _fitted = s;
        ctx.Custom(new Frame(this, s, Bounds));
    }

    /// <summary>One frame: the faces projected and ordered here, drawn by Skia on the render thread.</summary>
    private sealed class Frame : ICustomDrawOperation
    {
        private readonly List<(SKPoint[] pts, SKColor fill, SKColor edge)> _polys = new();
        private readonly List<(string what, SKPoint at)> _marks = new();
        /* row 410 (the PO 05.10: «ничего не анимируется ... а где там анализ построения, применение, отмена?»): the
           edit being tried pinned and named over the map, and the last events in the corner */
        private (SKPoint foot, SKPoint head, string text)? _pin;
        private readonly List<(SKColor color, string text)> _feed = new();

        public Frame(SchemeView v, SchemeModel.Snapshot s, Rect bounds)
        {
            Bounds = new Rect(bounds.Size);
            var (eye, right, up, fwd) = v.Camera();
            var focal = v.Focal();
            float cx = (float)bounds.Width / 2, cy = (float)bounds.Height / 2;
            var cut = v.Cut;
            var light = Vector3.Normalize(new Vector3(0.35f, 0.55f, 0.75f));
            var zspan = Math.Max(1, s.Max.Z - s.Min.Z);
            SKPoint? Project(Vector3 p, out float depth)
            {
                var q = p - eye;
                depth = Vector3.Dot(q, fwd);
                if (depth < 8)
                    return null;
                return new SKPoint(cx + focal * Vector3.Dot(q, right) / depth, cy - focal * Vector3.Dot(q, up) / depth);
            }
            var list = new List<(float depth, SKPoint[] pts, SKColor fill, SKColor edge)>(s.Faces.Count);
            foreach (var f in s.Faces)
            {
                // the roofs over where play happens are left out; a wall rising past the cut is kept
                if (cut is { } c && f.ZLo > c + 1 && f.Kind != 1)
                    continue;
                var liquid = f.Kind is 3 or 4 or 5;
                if (!liquid && Vector3.Dot(f.N, eye - f.V[0]) <= 0)
                    continue;      // seen from behind
                if (f.Kind == 2)
                    continue;      // a ceiling hides what is under it from every view that matters here
                var pts = new SKPoint[f.V.Length];
                float far = 0;
                var ok = true;
                for (var i = 0; i < f.V.Length && ok; i++)
                {
                    var p = Project(f.V[i], out var dep);
                    ok = p != null;
                    if (ok)
                    {
                        pts[i] = p!.Value;
                        far = Math.Max(far, dep);
                    }
                }
                if (!ok)
                    continue;
                var lit = 0.55f + 0.45f * Math.Max(0, Vector3.Dot(f.N, light));
                SKColor fill = f.Kind switch
                {
                    0 => Shade(0x3a + (byte)((f.ZLo - s.Min.Z) / zspan * 0x90), lit, 4, 12),
                    1 => Shade(0x6e, lit, 6, 14),
                    3 => new SKColor(0x2f, 0x7d, 0xf0, 0xb0),
                    4 => new SKColor(0xff, 0x6a, 0x00, 0xd0),
                    5 => new SKColor(0x6b, 0xd1, 0x2f, 0xc0),
                    _ => new SKColor((byte)(0xa8 * lit), (byte)(0x7c * lit), (byte)(0xe8 * lit)),
                };
                list.Add((far, pts, fill, new SKColor(0, 0, 0, f.Kind == 1 ? (byte)70 : (byte)40)));
            }
            list.Sort((a, b) => b.depth.CompareTo(a.depth));
            foreach (var (_, pts, fill, edge) in list)
                _polys.Add((pts, fill, edge));
            // the edits over the map: boxes, translucent, their edges drawn
            var now = DateTime.Now;
            List<SchemeModel.Edit> edits;
            lock (v._model.Sync)
                edits = v._model.Edits.ToList();
            foreach (var e in edits)
            {
                if (e.Box is not { } b || (cut is { } c && b[2] > c + 1))
                    continue;
                var age = (now - e.Seen).TotalSeconds;
                SKColor color;
                double alpha;
                if (e.Verdict == "ACCEPTED")
                {
                    var k = e.Old ? 1 : Math.Clamp((age - 20) / 10, 0, 1);
                    color = Blend(new SKColor(0x22, 0xc5, 0x5e), new SKColor(0x9a, 0x6a, 0x3c), k);
                    alpha = e.Old ? 0.10 : 0.40 - 0.30 * k;
                }
                else if (!e.Old && age < 10)
                {
                    color = new SKColor(0xef, 0x44, 0x44);
                    alpha = 0.45 * (1 - age / 10);
                }
                else
                    continue;
                AddBox(b, color, alpha, Project);
            }
            var run = v._run();
            if (run is { Running: true, TryEdit: >= 0 } g && !g.Paused)
            {
                var since = Clock(now - g.TryAt);
                if (g.TryBox is { } tb)
                {
                    var box = SchemeModel.Box(tb);
                    // never smaller than a room's width: a doorway's box on a whole map is a speck
                    for (var a = 0; a < 3; a++)
                        if (box[a + 3] - box[a] < 96)
                        {
                            var c = (box[a] + box[a + 3]) / 2;
                            (box[a], box[a + 3]) = (c - 48, c + 48);
                        }
                    var blink = 0.35 + 0.55 * (0.5 + 0.5 * Math.Sin((now - g.TryAt).TotalSeconds * Math.PI * 2));
                    AddBox(box, new SKColor(0x3b, 0x82, 0xf6), blink, Project);
                    var top = new Vector3((box[0] + box[3]) / 2, (box[1] + box[4]) / 2, box[5]);
                    if (Project(top, out _) is { } foot && Project(top + new Vector3(0, 0, 420), out _) is { } head)
                        _pin = (foot, head, $"{Kind(g.TryFamily)} — {Loc.T("scheme.trying")} {since}");
                }
                _feed.Add((new SKColor(0x60, 0xa5, 0xfa), $"{Loc.T("scheme.trying")}: {Kind(g.TryFamily)}  {since}"));
            }
            // the last events this view saw: what was built and judged - not the plan's instant «not applied»
            foreach (var e in edits.Where(x => !x.Old && x.Verdict != "REJECTED_NOT_APPLIED").Reverse().Take(7))
            {
                var ok = e.Verdict == "ACCEPTED";
                _feed.Add((ok ? new SKColor(0x4a, 0xde, 0x80) : new SKColor(0xf8, 0x71, 0x71),
                           $"{Loc.T(ok ? "verdict.accepted" : "verdict.rejected")}: {Kind(e.Family)}  {e.Seen:HH:mm:ss}"));
            }
            foreach (var (what, at) in s.Marks)
            {
                if (cut is { } c && at.Z > c + 64)
                    continue;
                if (Project(at, out _) is { } p)
                    _marks.Add((what, p));
            }
        }

        private delegate SKPoint? Projector(Vector3 p, out float depth);

        private static string Kind(string family) => Loc.Has($"kind.{family}") ? Loc.T($"kind.{family}") : family;

        private static string Clock(TimeSpan t) => $"{(int)t.TotalMinutes}:{t.Seconds:00}";

        private void AddBox(float[] b, SKColor color, double alpha, Projector project)
        {
            var c = new[]
            {
                new Vector3(b[0], b[1], b[2]), new Vector3(b[3], b[1], b[2]), new Vector3(b[3], b[4], b[2]), new Vector3(b[0], b[4], b[2]),
                new Vector3(b[0], b[1], b[5]), new Vector3(b[3], b[1], b[5]), new Vector3(b[3], b[4], b[5]), new Vector3(b[0], b[4], b[5]),
            };
            int[][] sides = { new[] { 0, 1, 2, 3 }, new[] { 4, 5, 6, 7 }, new[] { 0, 1, 5, 4 }, new[] { 2, 3, 7, 6 },
                              new[] { 1, 2, 6, 5 }, new[] { 0, 3, 7, 4 } };
            var fill = color.WithAlpha((byte)(255 * Math.Clamp(alpha, 0, 1) * 0.6));
            var edge = color.WithAlpha((byte)(255 * Math.Clamp(alpha * 2.2, 0, 1)));
            foreach (var side in sides)
            {
                var pts = new SKPoint[4];
                for (var i = 0; i < 4; i++)
                {
                    if (project(c[side[i]], out _) is not { } p)
                        return;
                    pts[i] = p;
                }
                _polys.Add((pts, fill, edge));
            }
        }

        private static SKColor Shade(int g, float lit, int db, int dg) => new(
            (byte)Math.Min(255, g * lit), (byte)Math.Min(255, (g + db) * lit), (byte)Math.Min(255, (g + dg) * lit));

        private static SKColor Blend(SKColor a, SKColor b, double k) => new(
            (byte)(a.Red + (b.Red - a.Red) * k), (byte)(a.Green + (b.Green - a.Green) * k), (byte)(a.Blue + (b.Blue - a.Blue) * k));

        public Rect Bounds { get; }
        public bool HitTest(Point p) => true;
        public bool Equals(ICustomDrawOperation? other) => false;
        public void Dispose() { }

        public void Render(ImmediateDrawingContext context)
        {
            var lease = context.TryGetFeature<ISkiaSharpApiLeaseFeature>();
            if (lease == null)
                return;
            using var l = lease.Lease();
            var canvas = l.SkCanvas;
            canvas.Save();
            canvas.ClipRect(new SKRect(0, 0, (float)Bounds.Width, (float)Bounds.Height));
            canvas.Clear(new SKColor(0x16, 0x18, 0x1c));
            using var fill = new SKPaint { IsAntialias = true, Style = SKPaintStyle.Fill };
            using var stroke = new SKPaint { IsAntialias = true, Style = SKPaintStyle.Stroke, StrokeWidth = 1 };
            using var path = new SKPath();
            foreach (var (pts, color, edge) in _polys)
            {
                path.Reset();
                path.AddPoly(pts, true);
                fill.Color = color;
                canvas.DrawPath(path, fill);
                if (edge.Alpha > 0)
                {
                    stroke.Color = edge;
                    canvas.DrawPath(path, stroke);
                }
            }
            foreach (var (what, at) in _marks)
                Mark(canvas, what, at);
            using var face = SKTypeface.FromFamilyName("Segoe UI") ?? SKTypeface.Default;
            using var font = new SKFont(face, 15);
            using var text = new SKPaint { IsAntialias = true, Color = SKColors.White };
            if (_pin is { } pin)
            {
                using var line = new SKPaint { IsAntialias = true, Style = SKPaintStyle.Stroke, StrokeWidth = 2,
                                               Color = new SKColor(0x60, 0xa5, 0xfa) };
                canvas.DrawLine(pin.foot, pin.head, line);
                canvas.DrawCircle(pin.head, 4, line);
                var w = font.MeasureText(pin.text);
                using var back = new SKPaint { Color = new SKColor(0x1e, 0x3a, 0x8a, 0xd0) };
                canvas.DrawRoundRect(new SKRect(pin.head.X + 8, pin.head.Y - 14, pin.head.X + 20 + w, pin.head.Y + 8), 4, 4, back);
                canvas.DrawText(pin.text, pin.head.X + 14, pin.head.Y + 2, font, text);
            }
            if (_feed.Count > 0)
            {
                using var back = new SKPaint { Color = new SKColor(0, 0, 0, 0x90) };
                var wmax = _feed.Max(f => font.MeasureText(f.text));
                canvas.DrawRoundRect(new SKRect(10, 10, 46 + wmax, 22 + 22 * _feed.Count), 6, 6, back);
                using var dot = new SKPaint { IsAntialias = true };
                for (var i = 0; i < _feed.Count; i++)
                {
                    dot.Color = _feed[i].color;
                    canvas.DrawCircle(26, 28 + 22 * i, 5, dot);
                    text.Color = i == 0 && _pin != null ? new SKColor(0xbf, 0xdb, 0xfe) : SKColors.White;
                    canvas.DrawText(_feed[i].text, 40, 33 + 22 * i, font, text);
                }
            }
            canvas.Restore();
        }

        private static void Mark(SKCanvas c, string what, SKPoint p)
        {
            using var paint = new SKPaint { IsAntialias = true, Style = SKPaintStyle.Fill };
            using var outline = new SKPaint { IsAntialias = true, Style = SKPaintStyle.Stroke, StrokeWidth = 1.2f, Color = SKColors.Black };
            switch (what)
            {
                case "weapon":
                    paint.Color = new SKColor(0xfa, 0xcc, 0x15);
                    Poly(c, paint, outline, p, (0, -7), (7, 6), (-7, 6));
                    break;
                case "armor":
                    paint.Color = new SKColor(0x22, 0xd3, 0xee);
                    Poly(c, paint, outline, p, (0, -7), (7, 0), (0, 7), (-7, 0));
                    break;
                case "health":
                case "mega":
                    paint.Color = SKColors.White;
                    var w = what == "mega" ? 3.5f : 2.5f;
                    c.DrawRect(p.X - w, p.Y - 7, 2 * w, 14, paint);
                    c.DrawRect(p.X - 7, p.Y - w, 14, 2 * w, paint);
                    break;
                case "ammo":
                    paint.Color = new SKColor(0xa8, 0xa2, 0x9e);
                    c.DrawCircle(p, 3, paint);
                    break;
                case "power":
                    paint.Color = new SKColor(0xd9, 0x46, 0xef);
                    c.DrawCircle(p, 7, paint);
                    outline.Color = SKColors.White;
                    c.DrawCircle(p, 7, outline);
                    break;
                case "spawn":
                    outline.Color = SKColors.White;
                    outline.StrokeWidth = 2;
                    c.DrawCircle(p, 7, outline);
                    paint.Color = SKColors.White;
                    c.DrawCircle(p, 2.5f, paint);
                    break;
                case "teleport":
                    outline.Color = new SKColor(0xf4, 0x72, 0xb6);
                    outline.StrokeWidth = 2.5f;
                    c.DrawCircle(p, 8, outline);
                    break;
            }
        }

        private static void Poly(SKCanvas c, SKPaint fill, SKPaint edge, SKPoint p, params (float x, float y)[] pts)
        {
            using var path = new SKPath();
            path.AddPoly(pts.Select(q => new SKPoint(p.X + q.x, p.Y + q.y)).ToArray(), true);
            c.DrawPath(path, fill);
            c.DrawPath(path, edge);
        }
    }
}

/// <summary>
/// The plan's tab: on/off (kept in the settings), the storeys shown, the view from above or slanting, a legend,
/// «На весь экран»; the plan under them.
/// </summary>
public sealed class SchemePanel : DockPanel
{
    public readonly SchemeModel Model = new();
    private readonly SchemeHost _view;
    private readonly Slider _cut = new() { Minimum = 0, Maximum = 1, Value = 1, Width = 200, VerticalAlignment = VerticalAlignment.Center };
    private readonly TextBlock _cutText = new() { VerticalAlignment = VerticalAlignment.Center, Opacity = 0.75, MinWidth = 70 };
    private readonly ToggleSwitch _on = new() { OnContent = Loc.T("scheme.on"), OffContent = Loc.T("scheme.off") };
    private readonly Func<Generation?> _run;
    private SchemeFullScreen? _full;
    private SchemeModel.Snapshot? _cutFor;
    private bool _cutMoved, _setting;

    public SchemePanel(Func<Generation?> run)
    {
        _run = run;
        _view = new SchemeHost(Model, run);
        _on.IsChecked = App.Settings.Scheme;
        _on.IsCheckedChanged += (_, _) =>
        {
            App.Settings.Scheme = _on.IsChecked == true;
            App.Settings.Save();
            _view.IsVisible = App.Settings.Scheme;
        };
        _view.IsVisible = App.Settings.Scheme;
        _cut.ValueChanged += (_, _) =>
        {
            if (!_setting)
                _cutMoved = true;
            ApplyCut();
        };
        var top = Ui.Button("scheme.top", "scheme.top.tip", FASymbol.Map);
        top.Click += (_, _) => _view.Top();
        var slant = Ui.Button("scheme.slant", "scheme.slant.tip", FASymbol.View);
        slant.Click += (_, _) => _view.Slant();
        var full = Ui.Button("scheme.full", "scheme.full.tip", FASymbol.FullScreen);
        full.Click += (_, _) => FullScreen();
        var bar = new WrapPanel { Margin = new Thickness(0, 8, 0, 8) };
        foreach (var c in new Control[] { _on, top, slant, new TextBlock { Text = Loc.T("scheme.cut"), VerticalAlignment = VerticalAlignment.Center,
                                                                          Margin = new Thickness(8, 0, 0, 0) }, _cut, _cutText, full })
        {
            c.Margin = new Thickness(c.Margin.Left, 0, 12, 4);
            bar.Children.Add(c);
        }
        var legend = new TextBlock { Text = Loc.T("scheme.legend"), FontSize = 12, Opacity = 0.7, TextWrapping = TextWrapping.Wrap,
                                     Margin = new Thickness(0, 0, 0, 6) };
        SetDock(bar, Dock.Top);
        SetDock(legend, Dock.Top);
        Children.Add(bar);
        Children.Add(legend);
        Children.Add(new Border { Child = _view, CornerRadius = new CornerRadius(4), ClipToBounds = true, MinHeight = 240 });
        ApplyCut();
    }

    private void ApplyCut()
    {
        var s = Model.Current;
        // a new map: the cut starts where play happens (the roofs above it hidden), unless the user moved it
        if (s != null && !ReferenceEquals(s, _cutFor))
        {
            var first = _cutFor == null || !_cutMoved;
            _cutFor = s;
            if (first && s.Max.Z > s.Min.Z && s.PlayTop < s.Max.Z)
            {
                _setting = true;
                _cut.Value = (s.PlayTop - s.Min.Z) / (s.Max.Z - s.Min.Z);
                _setting = false;
            }
        }
        if (s == null || _cut.Value >= 0.999)
        {
            _view.Cut = null;
            _cutText.Text = Loc.T("scheme.cut.all");
        }
        else
        {
            _view.Cut = s.Min.Z + _cut.Value * (s.Max.Z - s.Min.Z);
            _cutText.Text = Loc.F("scheme.cut.at", Math.Round(_view.Cut.Value));
        }
        if (_full != null)
            _full.View.Cut = _view.Cut;
    }

    /// <summary>The window's beat: read on, while the plan is on.</summary>
    public void Update(Generation g)
    {
        if (App.Settings.Scheme)
            Model.RefreshAsync(g);
        if (!ReferenceEquals(Model.Current, _cutFor))
            ApplyCut();
        _full?.Update(g);
    }

    public SchemeFullScreen? Full => _full;

    private WindowState _mainState = WindowState.Normal;

    public void FullScreen()
    {
        // row 410 (the PO, 05.10: «жму на На весь экран и ничего не происходит»): the full screen left open behind the
        // main window (a click on it sends it back) is brought forward, not ignored
        // the PO, 06.10: «когда карта развернута на весь экран то надо окошко основной студии прятать чтобы не висело
        // два окна (чтобы по alt+tab не переключаться в том числе между ними)» - the main window is hidden while the
        // map is on the whole screen, and comes back, in front and active, when it closes («Вернуться в студию», Esc)
        var main = TopLevel.GetTopLevel(this) as Window;
        // the PO, 07.10: the Studio maximised, the map on the whole screen, «Назад в студию» - the Studio came back
        // not maximised: hidden and shown, a window forgets its state; the state it had is kept and given back
        if (main != null && main.IsVisible && main.WindowState != WindowState.Minimized)
            _mainState = main.WindowState;
        if (_full != null)
        {
            _full.WindowState = WindowState.FullScreen;
            _full.Activate();
            main?.Hide();
            return;
        }
        _full = new SchemeFullScreen(Model, _run) { View = { Cut = _view.Cut } };
        _full.Closed += (_, _) =>
        {
            _full = null;
            if (main == null)
                return;
            main.Show();
            // shown again, a maximised window may keep its state's NAME and come up at its normal size: the state is
            // set anew (through Normal - setting the same value changes nothing)
            if (_mainState == WindowState.Maximized)
            {
                main.WindowState = WindowState.Normal;
                main.WindowState = WindowState.Maximized;
            }
            else if (main.WindowState == WindowState.Minimized)
                main.WindowState = WindowState.Normal;
            main.Activate();
        };
        _full.Show();
        _full.Activate();
        main?.Hide();
        if (_run() is { } g)
            _full.Update(g);
    }
}

/// <summary>
/// The plan on the whole screen (the PO, 05.10): over it, half see-through, the run as it stands now - the map, the
/// stage under way with its time and its end, the run's time, the edits, the machine's load - and no finished stage.
/// Esc or «Назад в студию» closes it and brings the Studio back, in front.
/// </summary>
public sealed class SchemeFullScreen : Window
{
    public readonly SchemeHost View;
    private readonly TextBlock _title = new() { FontSize = 26, FontWeight = FontWeight.SemiBold };
    private readonly TextBlock _stage = new() { FontSize = 18 };
    private readonly TextBlock _times = new() { FontSize = 15 };
    private readonly TextBlock _edits = new() { FontSize = 15 };
    private readonly LoadMeter _meter = new(overlay: true);

    public SchemeFullScreen(SchemeModel model, Func<Generation?> run)
    {
        Title = "MAPGEN Studio";
        WindowState = WindowState.FullScreen;
        WindowDecorations = Avalonia.Controls.WindowDecorations.None;
        Background = new SolidColorBrush(Color.FromRgb(0x16, 0x18, 0x1c));
        View = new SchemeHost(model, run);
        var text = new StackPanel { Spacing = 4, Margin = new Thickness(28, 20, 28, 0), Opacity = 0.62, IsHitTestVisible = false,
                                    HorizontalAlignment = HorizontalAlignment.Left, VerticalAlignment = VerticalAlignment.Top };
        foreach (var t in new[] { _title, _stage, _times, _edits })
        {
            t.Foreground = Brushes.White;
            text.Children.Add(t);
        }
        var back = Ui.Button("scheme.back", "scheme.back.tip", FASymbol.BackToWindow);
        back.HorizontalAlignment = HorizontalAlignment.Right;
        back.VerticalAlignment = VerticalAlignment.Top;
        back.Margin = new Thickness(0, 20, 28, 0);
        back.Click += (_, _) => Close();
        _meter.HorizontalAlignment = HorizontalAlignment.Right;
        _meter.VerticalAlignment = VerticalAlignment.Top;
        _meter.Margin = new Thickness(0, 72, 28, 0);
        _meter.Opacity = 0.85;
        _meter.IsHitTestVisible = false;
        Content = new Grid { Children = { View, text, back, _meter } };
        // the events' list under the run's lines, not over them (the PO, 05.10: «одно на другое накладывается»)
        text.LayoutUpdated += (_, _) => View.FeedTop = text.Bounds.Bottom + 12;
        KeyDown += (_, e) =>
        {
            if (e.Key == Key.Escape)
                Close();
        };
        // leaving full screen any other way (the window's own minimise or restore) is going back too
        PropertyChanged += (_, e) =>
        {
            if (e.Property == WindowStateProperty && WindowState != WindowState.FullScreen && IsVisible)
                Close();
        };
    }

    /// <summary>Brief 10 (D1): the lines over the map without a run - for the guide's picture.</summary>
    public void Caption(string title, string stage, string times, string edits)
    {
        _title.Text = title;
        _stage.Text = stage;
        _times.Text = times;
        _edits.Text = edits;
    }

    public void Update(Generation g)
    {
        _meter.Update(g);
        _title.Text = Loc.F("run.title", g.Request.Name);
        _stage.Text = GenerationView.NowLine(g);
        _times.Text = GenerationView.RunLine(g);
        _edits.Text = g.Budget > 0 ? Loc.F("run.attempts", g.Accepted, g.Compiles, g.Budget, g.Attempts)
                      + (g.Target > 0 ? "   " + Loc.F("run.likeness", g.Divergence / 10, g.Target / 10) : "")
                    : "";
    }
}
