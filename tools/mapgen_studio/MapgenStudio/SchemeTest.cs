using Avalonia;
using Avalonia.Media.Imaging;

namespace MapgenStudio;

/// <summary>
/// `--scheme-test JOB_DIR OUT` (ledger row 410): the plan of a job read and drawn into two pictures, OUT_top.png and
/// OUT_slant.png, without a window - its faces, marks and the ledger's edits counted. One PASS / FAIL line each.
/// </summary>
public static class SchemeTest
{
    /// <summary>
    /// `--scheme-gl-test JOB_DIR OUT.png`: the plan drawn by the graphics card in a window off the screen's edge, the
    /// size of the PO's screen; a frame read back from the card into OUT.png (bottom row first, turned), the card's
    /// name and the frames' times into scheme_gl_test.txt.
    /// </summary>
    public static Avalonia.Controls.Window GlTest(string[] args)
    {
        var at = Array.IndexOf(args, "--scheme-gl-test");
        var job = at >= 0 && at + 1 < args.Length ? args[at + 1] : "";
        var png = at >= 0 && at + 2 < args.Length ? args[at + 2] : "scheme_gl.png";
        string? Opt(string flag) => Array.IndexOf(args, flag) is var k and >= 0 && k + 1 < args.Length ? args[k + 1] : null;
        var model = new SchemeModel();
        // `--map MAP.bsp`: a finished map; `--walk WALK.json`: its walk on «Проверки карты» (the PO 11.11), the card's floor
        if (Opt("--map") is { } bsp)
            model.RefreshForTest(job, bsp);
        else
            model.RefreshNow(job);
        var walk = Opt("--walk") is { } wf ? WalkShow.Parse(File.ReadAllBytes(wf)) : null;
        Generation? run = null;
        if (walk != null && model.Current is { } cur)
        {
            model.ShowsForSelfTest(null, null, cur.WithWalk(walk));
            run = Generation.ForSelfTest(App.Settings, "gates");
        }
        var host = new SchemeHost(model, () => run);
        var w = new Avalonia.Controls.Window
        {
            Width = 2560, Height = 1080, ShowInTaskbar = false, ShowActivated = false,
            WindowStartupLocation = Avalonia.Controls.WindowStartupLocation.Manual,
            Position = new PixelPoint(-6000, -3000), Content = host,
        };
        var file = Path.Combine(Settings.ProgramDir, "scheme_gl_test.txt");
        File.Delete(file);
        w.Opened += async (_, _) =>
        {
            var b = new System.Text.StringBuilder();
            void Check(string what, bool ok, string detail = "") =>
                b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
            await Task.Delay(1500);
            host.Slant();
            var times = new List<double>();
            for (var i = 0; i < 40; i++)
            {
                host.Camera.Yaw += 3;
                host.Gl.RequestNextFrameRendering();
                await Task.Delay(50);
                if (host.Gl.Frames > 0)
                    times.Add(host.Gl.LastFrameMs);
            }
            // row 411: a lit map's faces carry their own light (the mean of each lightmap) and the plan draws them so
            if (model.Current is { } snap)
            {
                var lit = snap.Faces.Where(x => x.Light != null).ToList();
                var mean = lit.Count > 0 ? lit.Average(x => (x.Light!.Value.X + x.Light.Value.Y + x.Light.Value.Z) / 3) : 0;
                b.AppendLine($"INFO light: lit {snap.Lit}, {lit.Count} of {snap.Faces.Count} faces, mean {mean:0.000},"
                             + $" darkest {(lit.Count > 0 ? lit.Min(x => x.Light!.Value.Length()) : 0):0.000},"
                             + $" brightest {(lit.Count > 0 ? lit.Max(x => x.Light!.Value.Length()) : 0):0.000}");
            }
            Check("the card draws the plan", host.OnCard && host.Gl.Ready && host.Gl.Frames > 10,
                  $"{host.Gl.Info}; frames {host.Gl.Frames}; failed {host.Gl.Failed}");
            if (times.Count > 0)
                Check("a frame costs the window little", times.Average() < 30,
                      $"mean {times.Average():0.0} ms, max {times.Max():0.0} ms over {times.Count}");
            var done = new TaskCompletionSource<bool>();
            host.Gl.Captured = (cw, ch, px) =>
            {
                try
                {
                    using var bmp = new Avalonia.Media.Imaging.WriteableBitmap(new PixelSize(cw, ch), new Vector(96, 96),
                        Avalonia.Platform.PixelFormat.Rgba8888, Avalonia.Platform.AlphaFormat.Opaque);
                    using (var fbuf = bmp.Lock())
                        for (var y = 0; y < ch; y++)
                            System.Runtime.InteropServices.Marshal.Copy(px, (ch - 1 - y) * cw * 4, fbuf.Address + y * fbuf.RowBytes, cw * 4);
                    bmp.Save(png);
                    var lit = 0;
                    for (var i = 0; i < px.Length; i += 4 * 97)
                        if (px[i] > 0x30 || px[i + 1] > 0x30)
                            lit++;
                    Check("the frame read back holds the map", lit > 200, $"{cw}x{ch}, {lit} lit samples, {png}");
                }
                catch (Exception ex)
                {
                    Check("the frame read back", false, ex.Message);
                }
                done.TrySetResult(true);
            };
            // the walk caught at 60 % of its span: the floor reached so far, its front bright
            if (walk != null)
                walk.Since = DateTime.Now - TimeSpan.FromSeconds(walk.Span * 0.6 / Math.Max(1, walk.Span / 12));
            host.Gl.RequestNextFrameRendering();
            await Task.WhenAny(done.Task, Task.Delay(5000));
            if (!done.Task.IsCompleted)
                Check("the frame read back", false, "no frame came");
            // the PO 05.10: on the full screen the map was cut by a rectangle smaller than the screen - the window grows
            // (as it does going full screen), and every frame must be drawn at the size of the surface it goes to
            var seen = new List<string>();
            foreach (var (ww, wh) in new[] { (1200.0, 600.0), (2560.0, 1080.0), (1700.0, 900.0), (2560.0, 1080.0) })
            {
                w.Width = ww;
                w.Height = wh;
                for (var i = 0; i < 12; i++)
                {
                    host.Camera.Yaw += 3;
                    host.Gl.RequestNextFrameRendering();
                    await Task.Delay(40);
                    seen.Add($"{host.Gl.DrawnSize.Width}x{host.Gl.DrawnSize.Height}/{host.Gl.ControlSize.Width}x{host.Gl.ControlSize.Height}");
                }
            }
            Check("grown and shrunk, the last frame is drawn at the control's whole size",
                  host.Gl.DrawnSize == host.Gl.ControlSize && host.Gl.DrawnSize.Width >= 2000,
                  $"drawn {host.Gl.DrawnSize}, control {host.Gl.ControlSize}; frames on a surface not the control's size:"
                  + $" {host.Gl.Mismatched}; " + string.Join(" ", seen.Distinct()));
            File.WriteAllText(file, b.ToString() + "END\n");
            Environment.Exit(b.ToString().Contains("FAIL") ? 1 : 0);
        };
        return w;
    }

    /// <summary>
    /// `--scheme-window-test JOB_DIR`: the plan of a job in a small window off the screen's edge, turned and zoomed
    /// for four seconds with its timer running; then «PASS shown» into scheme_window_test.txt and out. A throw in a
    /// render pass ends the process before that line.
    /// </summary>
    public static Avalonia.Controls.Window FullTest(string[] args)
    {
        // `--scheme-full-test JOB_DIR`: the plan full screen as «На весь экран» opens it, three seconds on the screen,
        // turning; each frame's drawn size against the control's, and a frame read back - the map must reach the
        // right third of the screen, not stop at a smaller rectangle (the PO, 05.10)
        var at = Array.IndexOf(args, "--scheme-full-test");
        var job = at >= 0 && at + 1 < args.Length ? args[at + 1] : "";
        var model = new SchemeModel();
        model.RefreshNow(job);
        var full = new SchemeFullScreen(model, () => null);
        var file = Path.Combine(Settings.ProgramDir, "scheme_full_test.txt");
        File.Delete(file);
        full.Opened += async (_, _) =>
        {
            var b = new System.Text.StringBuilder();
            void Check(string what, bool ok, string detail = "") =>
                b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
            var host = full.View;
            var seen = new List<string>();
            for (var i = 0; i < 60; i++)
            {
                host.Camera.Yaw += 2;
                host.Gl.RequestNextFrameRendering();
                await Task.Delay(50);
                seen.Add($"{host.Gl.DrawnSize.Width}x{host.Gl.DrawnSize.Height}/{host.Gl.ControlSize.Width}x{host.Gl.ControlSize.Height}");
            }
            var screen = full.Screens.ScreenFromWindow(full);
            Check("full screen, the frame is drawn at the control's whole size, the control the screen's",
                  host.Gl.DrawnSize == host.Gl.ControlSize && screen != null
                  && Math.Abs(host.Gl.ControlSize.Width - screen.Bounds.Width) <= 2,
                  $"drawn {host.Gl.DrawnSize}, control {host.Gl.ControlSize}, screen {screen?.Bounds}, scaling"
                  + $" {full.RenderScaling}; mismatched frames {host.Gl.Mismatched}; " + string.Join(" ", seen.Distinct()));
            var done = new TaskCompletionSource<bool>();
            host.Slant();
            host.Gl.Captured = (cw, ch, px) =>
            {
                // the map's lit pixels per third of the width: a frame cut at a smaller rectangle has none on the right
                var thirds = new int[3];
                for (var y = 0; y < ch; y += 7)
                    for (var x = 0; x < cw; x += 7)
                    {
                        var i = (y * cw + x) * 4;
                        if (px[i] > 0x30 || px[i + 1] > 0x30)
                            thirds[Math.Min(2, x * 3 / cw)]++;
                    }
                Check("the map drawn full screen reaches across it", thirds[0] > 50 && thirds[2] > 50,
                      $"{cw}x{ch}; lit by thirds {thirds[0]} {thirds[1]} {thirds[2]}");
                done.TrySetResult(true);
            };
            host.Gl.RequestNextFrameRendering();
            await Task.WhenAny(done.Task, Task.Delay(5000));
            if (!done.Task.IsCompleted)
                Check("a frame read back", false, "no frame came");
            File.WriteAllText(file, b.ToString() + "END\n");
            Environment.Exit(b.ToString().Contains("FAIL") ? 1 : 0);
        };
        return full;
    }

    public static Avalonia.Controls.Window InWindow(string[] args)
    {
        var at = Array.IndexOf(args, "--scheme-window-test");
        var job = at >= 0 && at + 1 < args.Length ? args[at + 1] : "";
        var model = new SchemeModel();
        model.RefreshNow(job);
        var view = new SchemeView(model, () => null);
        var w = new Avalonia.Controls.Window
        {
            Width = 480, Height = 320, ShowInTaskbar = false, ShowActivated = false,
            WindowStartupLocation = Avalonia.Controls.WindowStartupLocation.Manual,
            Position = new PixelPoint(-3000, -3000), Content = view,
        };
        var file = Path.Combine(Settings.ProgramDir, "scheme_window_test.txt");
        File.Delete(file);
        w.Opened += (_, _) =>
        {
            var t = new Avalonia.Threading.DispatcherTimer { Interval = TimeSpan.FromSeconds(4) };
            var step = 0;
            var turn = new Avalonia.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(300) };
            turn.Tick += (_, _) =>
            {
                if (++step % 2 == 0)
                    view.Slant();
                else
                    view.Top();
            };
            turn.Start();
            t.Tick += (_, _) =>
            {
                File.WriteAllText(file, $"PASS shown -- {model.Current?.Faces.Count ?? 0} faces, {step} turns\n");
                Environment.Exit(0);
            };
            t.Start();
        };
        return w;
    }

    /// <summary>
    /// `--show-test JOB_DIR MAP.bsp WALK.json OUT [SKELETON.json ...]` (the PO 11.11): the two new stage pictures drawn
    /// without a window, on the CPU - the scheme's own overlay (the footprints, the moves, the items named, the stage's
    /// words) over the map, the reached floor as the card draws it - the map's checks at four moments of the walk
    /// (OUT_walk_N.png), and every skeleton's steps frame by frame (OUT_skelK_N.png). PASS / FAIL lines.
    /// </summary>
    public static string ShowTest(string[] args)
    {
        var at = Array.IndexOf(args, "--show-test");
        if (at < 0 || at + 4 >= args.Length)
            return "FAIL usage: --show-test JOB_DIR MAP.bsp WALK.json OUT [SKELETON.json ...]\n";
        var (job, bsp, walkFile, png) = (args[at + 1], args[at + 2], args[at + 3], args[at + 4]);
        var b = new System.Text.StringBuilder();
        void Check(string what, bool ok, string detail = "") =>
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
        var size = new Size(1600, 1000);
        var model = new SchemeModel();
        model.RefreshForTest(job, bsp);
        var s = model.Current;
        Check("the map is read", s is { Faces.Count: > 0 }, s == null ? "none" : $"{s.Faces.Count} faces, {s.Marks.Count} marks");
        var walk = WalkShow.Parse(File.ReadAllBytes(walkFile));
        Check("the walk is read", walk is { Trails.Count: > 0 },
              walk == null ? "none" : $"{walk.Spawns.Count} spawn points, {walk.Trails.Count} ways, "
                                      + $"{walk.Trails.Sum(t => t.Steps.Count)} footprints, {walk.Floor.Count} floor points, "
                                      + $"{walk.Unreached.Count} not reached, {walk.Span:0.0} s");
        if (s == null || walk == null)
            return b.ToString();
        var gates = Generation.ForSelfTest(App.Settings, "gates");
        var walked = s.WithWalk(walk);
        var cut = s.PlayTop < s.Max.Z ? s.PlayTop : (double?)null;
        var k = 0;
        foreach (var part in new[] { 0.06f, 0.3f, 0.65f, 1.05f })
        {
            // the walk's clock set back so that it shows this moment now
            var pace = Math.Max(1f, walk.Span / 12f);
            walk.Since = DateTime.Now - TimeSpan.FromSeconds(walk.Span * part / pace);
            var art = StageArt.Now(gates, walked);
            var file = $"{png}_walk_{++k}.png";
            var words = Draw(model, walked, cut, size, file, gates, art.Walk ? walk : null);
            // the words follow the walk's clock: the overlay's own moment, a few milliseconds on - the head compared
            var head = art.Caption.Split('—', '-')[0].Trim();
            Check($"the checks' walk at {art.WalkT:0.0} s of {walk.Span:0.0}", art.Walk && File.Exists(file)
                  && words.Contains(head) && (part < 0.5f || walk.Trails.Any(t => t.T <= art.WalkT))
                  && (part < 1f || (art.Vis > 1.5f && art.Caption.Contains($" {walk.Trails.Count} "))),
                  $"«{art.Caption}», {walk.Trails.Count(t => t.T <= art.WalkT)} items reached, {walk.Lost.Count} out of reach, {file}");
        }
        // 3.63: «Свет на готовой карте» - the finished map's lamps glowing while its light is fitted
        var relight = Generation.ForSelfTest(App.Settings, "cover");
        relight.SetStageForSelfTest("relight");
        var lit = StageArt.Now(relight, s);
        var relightFile = $"{png}_relight.png";
        var relightWords = Draw(model, s, cut, size, relightFile, relight, null);
        Check("the finished map's lamps while its light is fitted", lit.Lamps && s.Lamps.Count > 0 && File.Exists(relightFile)
              && relightWords.Contains(Loc.F("art.relight", s.Lamps.Count)),
              $"{s.Lamps.Count} lamps, glow {lit.Glow:0.00}, «{lit.Caption}», {relightFile}");
        var n = 0;
        foreach (var sk in args.Skip(at + 5))
        {
            n++;
            var steps = SkeletonShow.Parse(File.ReadAllBytes(sk));
            var frames = steps == null ? new List<SkeletonShow.Frame>() : SkeletonShow.Frames(steps);
            Check($"skeleton {n}: frames", frames.Count > 1 && frames.All(f => f.Snap.Faces.Count > 0),
                  $"{frames.Count} frames: " + string.Join(", ", frames.Select(f => $"{f.Step} {f.Snap.Faces.Count}")));
            var scratch = Generation.ForSelfTest(App.Settings, "scratch");
            var i = 0;
            foreach (var f in frames)
            {
                f.Snap.ShowCaption = SkeletonShow.Caption(f);
                var file = $"{png}_skel{n}_{++i:00}.png";
                var words = Draw(model, f.Snap, null, size, file, scratch, null);
                Check($"skeleton {n} frame {i}", File.Exists(file) && words.Contains(f.Snap.ShowCaption), $"«{f.Snap.ShowCaption}»");
            }
        }
        return b.ToString();
    }

    /// <summary>One picture: the map on the CPU from the south-west, the card's walk floor, the scheme's overlay.</summary>
    private static string Draw(SchemeModel model, SchemeModel.Snapshot snap, double? cut, Size size, string file, Generation run,
                               WalkShow? walk)
    {
        model.ShowsForSelfTest(null, null, snap);
        var cam = new SchemeCamera { Yaw = -125, Pitch = 40, Cut = cut };
        cam.Fit(snap);
        var view = new SchemeView(model, () => null) { Cut = cut };
        var floor = new WalkFloorForTest(model, run, cam);
        var overlay = new SchemeOverlay(model, () => run, cam);
        var panel = new Avalonia.Controls.Panel { Children = { view, floor, overlay } };
        panel.Measure(size);
        panel.Arrange(new Rect(size));
        view.Slant();
        using var bmp = new RenderTargetBitmap(new PixelSize((int)size.Width, (int)size.Height));
        bmp.Render(panel);
        bmp.Save(file);
        return overlay.DrawnText + " " + string.Join(" ", walk?.Trails.Select(t => t.Cls) ?? Array.Empty<string>());
    }

    /// <summary>The floor the walk reached by now as the card draws it (<c>SchemeGlView.WalkFloor</c>'s colours).</summary>
    private sealed class WalkFloorForTest(SchemeModel model, Generation run, SchemeCamera cam) : Avalonia.Controls.Control
    {
        public override void Render(Avalonia.Media.DrawingContext ctx)
        {
            if (model.Current is not { Walk: { } w } s)
                return;
            var art = StageArt.Now(run, s);
            if (!art.Walk)
                return;
            void Square(System.Numerics.Vector3 p, Avalonia.Media.Color colour)
            {
                const float h = 12;
                if (cam.Cut is { } c && p.Z > c + 1)
                    return;
                var corners = new[] { (-h, -h), (h, -h), (h, h), (-h, h) }
                    .Select(d => cam.Project(p + new System.Numerics.Vector3(d.Item1, d.Item2, 2), Bounds.Size)).ToList();
                if (corners.Any(q => q == null))
                    return;
                var geo = new Avalonia.Media.StreamGeometry();
                using (var g = geo.Open())
                {
                    g.BeginFigure(corners[0]!.Value, true);
                    foreach (var q in corners.Skip(1))
                        g.LineTo(q!.Value);
                    g.EndFigure(true);
                }
                ctx.DrawGeometry(new Avalonia.Media.SolidColorBrush(colour), null, geo);
            }
            foreach (var (p, t) in w.Floor)
            {
                var f = Math.Clamp(t / w.Span, 0f, 1f);
                if (f > art.Vis)
                    continue;
                var front = f > art.Vis - 0.03f;
                Square(p, Avalonia.Media.Color.FromArgb((byte)(255 * (front ? 0.92 : 0.42)), (byte)(255 * (0.20f + 0.50f * f)),
                                                        (byte)(255 * (0.85f - 0.45f * f)), 255));
            }
            if (art.Vis > 1.5f)
                foreach (var p in w.Unreached)
                    Square(p, Avalonia.Media.Color.FromArgb(0x8c, 0x4d, 0x4d, 0x57));
        }
    }

    /// <summary>
    /// `--walk-code-test MAP.bsp` (the PO 11.11): the checks' step's walk code (<see cref="Generation.WalkCode"/>) run as
    /// the step runs its Python - the same program, the same quoting - on a map, held a few seconds; its walk read from
    /// memory as the scheme reads it. PASS / FAIL lines.
    /// </summary>
    public static string WalkCodeTest(string[] args)
    {
        var at = Array.IndexOf(args, "--walk-code-test");
        if (at < 0 || at + 1 >= args.Length)
            return "FAIL usage: --walk-code-test MAP.bsp\n";
        var b = new System.Text.StringBuilder();
        void Check(string what, bool ok, string detail = "") =>
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
        var map = Path.GetFullPath(args[at + 1]);
        var tools = Path.Combine(Engine.Repo ?? "", "tools");
        var root = $"mgs_walktest_{Environment.ProcessId}";
        var code = Generation.WalkCode(tools, map, root);
        Check("the code is one line", !code.Contains('\n') && !code.Contains('\r'), code);
        using var job = new NativeJob();
        var since = DateTime.Now;
        job.Start(Engine.Python!, new[] { "-c", "import subprocess,sys;" + code + "import time;time.sleep(6)" }, Path.GetTempPath());
        WalkShow? walk = null;
        while (walk == null && (DateTime.Now - since).TotalSeconds < 30)
        {
            Thread.Sleep(200);
            if (MemFiles.Read(root, "walk_show.json") is { } bytes)
                walk = WalkShow.Parse(bytes);
        }
        Check("the walk is read from memory while the step's Python runs", walk is { Trails.Count: > 0 },
              walk == null ? $"nothing in {(DateTime.Now - since).TotalSeconds:0} s ({Engine.Python})"
                           : $"{(DateTime.Now - since).TotalSeconds:0.0} s: {walk.Spawns.Count} spawn points, {walk.Trails.Count} ways, "
                             + $"{walk.Trails.Sum(t => t.Steps.Count)} footprints, {walk.Lost.Count} out of reach, {walk.Span:0.0} s");
        var broken = Generation.WalkCode(tools, map + ".none", root + "_none");
        // the step's own code after it runs: here an exit of its own (7), not the 1 of an error that got out
        using var bad = new NativeJob();
        bad.Start(Engine.Python!, new[] { "-c", "import subprocess,sys;" + broken + "sys.exit(7)" }, Path.GetTempPath());
        var waited = DateTime.Now;
        uint exit;
        while (!bad.Exited(out exit) && (DateTime.Now - waited).TotalSeconds < 30)
            Thread.Sleep(100);
        Check("a map it cannot read stops nothing: the step's code goes on", exit == 7, $"exit {exit}");
        return b.ToString();
    }

    /// <summary>
    /// `--tries-test PARAMS.json [TRIES] [WORKERS]` (the PO 12.11): the planner's tries over its pool, as the skeleton's
    /// stage runs them (mapgen_scratch.live_tries handed to best_plan), in a Python of their own; the Studio reads the
    /// section on its own beat meanwhile, as the scheme does - how soon the first skeleton is on it, how many it saw.
    /// Nothing is written to the disk.
    /// </summary>
    public static string TriesTest(string[] args)
    {
        var at = Array.IndexOf(args, "--tries-test");
        if (at < 0 || at + 1 >= args.Length)
            return "FAIL usage: --tries-test PARAMS.json [TRIES] [WORKERS]\n";
        var tries = at + 2 < args.Length && int.TryParse(args[at + 2], out var t) ? t : 40;
        var workers = at + 3 < args.Length && int.TryParse(args[at + 3], out var wk) ? wk : 4;
        var b = new System.Text.StringBuilder();
        void Check(string what, bool ok, string detail = "") =>
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
        var tools = Path.Combine(Engine.Repo ?? "", "tools");
        var root = $"mgs_triestest_{Environment.ProcessId}";
        var code = $"_tp=r'{tools}';_pp=r'{Path.GetFullPath(args[at + 1])}';" +
                   "import sys,json,time;sys.path.insert(0,_tp);import mapgen_scratch as sc,mapgen_scratch_plan as pm;" +
                   $"p=json.load(open(_pp,encoding='utf-8'));ps=pm.best_plan(p,7,{tries},workers={workers},seen=sc.live_tries('{root}'));" +
                   "print(len(ps));time.sleep(2)";
        using var job = new NativeJob();
        var since = DateTime.Now;
        job.Start(Engine.Python!, new[] { "-c", code }, Path.GetTempPath());
        double? first = null;
        var seen = new List<int>();
        var faces = 0;
        var caption = "";
        byte[]? last = null;
        uint exit;
        while (!job.Exited(out exit) && (DateTime.Now - since).TotalSeconds < 120)
        {
            Thread.Sleep(100);
            if (MemFiles.Read(root, "skeleton_live.json") is not { } bytes || (last != null && bytes.AsSpan().SequenceEqual(last)))
                continue;
            last = bytes;
            if (SkeletonShow.ParseTry(bytes) is not { } tr)
                continue;
            first ??= (DateTime.Now - since).TotalSeconds;
            seen.Add(tr.Done);
            faces = tr.Snap.Faces.Count;
            caption = tr.Snap.ShowCaption;
        }
        var total = (DateTime.Now - since).TotalSeconds;
        Check("the planner's tries are on the scheme as they come", exit == 0 && first != null && seen.Count >= 3
              && seen.SequenceEqual(seen.OrderBy(x => x)) && seen[^1] == tries && faces > 0,
              $"python exit {exit}; the first skeleton after {first:0.0} s of {total:0.0}; seen {seen.Count} tries: "
              + $"{string.Join(",", seen)}; the last «{caption}», {faces} faces");
        return b.ToString();
    }

    public static string Run(string[] args)
    {
        var at = Array.IndexOf(args, "--scheme-test");
        if (at < 0 || at + 2 >= args.Length)
            return "FAIL usage: --scheme-test JOB_DIR OUT\n";
        var job = args[at + 1];
        var png = args[at + 2];
        var b = new System.Text.StringBuilder();
        void Check(string what, bool ok, string detail = "") =>
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
        var model = new SchemeModel();
        model.RefreshNow(job);
        var s = model.Current;
        Check("the map is read", s != null && s.Floors > 0,
              s == null ? "none" : $"{s.Faces.Count} faces ({s.Floors} floors), {s.Marks.Count} marks, "
                                   + $"z {s.Min.Z:0}..{s.Max.Z:0}, play top {s.PlayTop:0}, from {s.Source}");
        int edits, accepted, boxed;
        lock (model.Sync)
        {
            edits = model.Edits.Count;
            accepted = model.Edits.Count(e => e.Verdict == "ACCEPTED");
            boxed = model.Edits.Count(e => e.Box != null);
        }
        Check("the ledger's edits are read", edits > 0, $"{edits} edits, {accepted} accepted, {boxed} with a place");
        foreach (var (name, slant) in new[] { ("top", false), ("slant", true) })
        {
            var view = new SchemeView(model, () => null) { Cut = s != null && s.PlayTop < s.Max.Z ? s.PlayTop : null };
            var size = new Size(1600, 1000);
            view.Measure(size);
            view.Arrange(new Rect(size));
            if (slant)
                view.Slant();
            else
                view.Top();
            using var bmp = new RenderTargetBitmap(new PixelSize(1600, 1000));
            bmp.Render(view);
            var file = $"{png}_{name}.png";
            bmp.Save(file);
            Check($"drawn {name}", File.Exists(file) && new FileInfo(file).Length > 10_000, file);
        }
        return b.ToString();
    }
}
