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
        var model = new SchemeModel();
        model.RefreshNow(job);
        var host = new SchemeHost(model, () => null);
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
