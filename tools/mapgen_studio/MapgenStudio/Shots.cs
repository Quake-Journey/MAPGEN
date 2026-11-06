using Avalonia;
using Avalonia.Controls;
using Avalonia.Media.Imaging;
using Avalonia.VisualTree;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// `--shots DIR` (Fable's brief 10, D1): the guide's screenshots, made by the program itself - every page, in Russian
/// and in English, the light theme, 1600 x 900 - into DIR/ru and DIR/en under fixed names the guides refer to
/// (`home.png`, `generate.png`, `generate_options.png`, `library.png`, `map.png`, `settings.png`, `about.png`), and
/// `DIR/build.txt` naming the version they were made by. The run's page and the map on the whole screen need a live
/// generation: the window walk (`--ui-test`) makes `run.png` and `run_full.png` into the same folders when
/// MAPGEN_SHOTS names DIR. The guide guard (`tools/check_mapgen_studio_guide.py`) holds the guides to these files.
/// </summary>
public sealed partial class MainWindow
{
    // brief 20 D1: the Generate page in its third mode and the card of a map made from scratch (mg_new_duel)
    // brief 30 (3.57): the new map's form for an open space (generate_scratch) and for a tower (generate_scratch_tower)
    public static readonly string[] ShotPages = { "home", "generate", "generate_options", "generate_scratch", "generate_scratch_tower",
                                                  "library", "map", "map_scratch", "settings", "about" };

    public static Window Shots(string dir)
    {
        // MAPGEN_SHOT_SIZE «1920x1400»: a page looked at on a wider and taller window than the guide's (the PO's screen)
        var (sw, sh) = (1600.0, 900.0);
        if (Environment.GetEnvironmentVariable("MAPGEN_SHOT_SIZE") is { } ss && ss.Split('x') is [var a, var b2]
            && double.TryParse(a, out var aw) && double.TryParse(b2, out var ah))
            (sw, sh) = (aw, ah);
        var w = new MainWindow
        {
            ShowActivated = false, ShowInTaskbar = false, Width = sw, Height = sh,
            WindowStartupLocation = WindowStartupLocation.Manual, Position = new PixelPoint(-4000, -4000),
        };
        SelfTesting = true;        // the pages it builds never write the settings
        // once: the window is hidden behind the full-screen map and shown again (Studio 1.8), and Opened fires again -
        // a second walk ran beside the first and failed it from «resumed» on
        var started = false;
        w.Opened += async (_, _) =>
        {
            if (started)
                return;
            started = true;
            var report = new System.Text.StringBuilder();
            try
            {
                await Task.Delay(400);
                var keepLang = Loc.Language;
                var keepTheme = App.Settings.Theme;
                var keepScratch = App.Settings.ScratchMode;
                var keepScratchParams = App.Settings.Scratch;
                static ScratchParams WithShape(ScratchParams p, string shape)
                {
                    var c = ScratchParams.Load(p.Save());
                    c.Shape = shape;
                    return c;
                }
                App.ApplyTheme("light");
                var donors = Engine.Donors();
                foreach (var lang in new[] { "ru", "en" })
                {
                    Loc.Language = lang;
                    var maps = Library.Scan(App.Settings);     // each language's descriptions
                    var into = Path.Combine(dir, lang);
                    Directory.CreateDirectory(into);
                    // only the pages asked for, when MAPGEN_SHOT_PAGES names them (the PO, 06.10: «нафига все скриншоты
                    // то переснимать?» - a change to «О программе» retakes about.png and nothing else)
                    var wanted = (Environment.GetEnvironmentVariable("MAPGEN_SHOT_PAGES") ?? "")
                                 .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
                    foreach (var page in ShotPages.Where(p => wanted.Length == 0 || wanted.Contains(p)))
                    {
                        w._chosen.Clear();
                        if (donors.Count > 0)
                            w._chosen.Add(donors[0]);
                        w._graftMode = false;
                        App.Settings.ScratchMode = page.StartsWith("generate_scratch");
                        App.Settings.Scratch = page == "generate_scratch" ? WithShape(keepScratchParams, "space")
                                             : page == "generate_scratch_tower" ? WithShape(keepScratchParams, "tower") : keepScratchParams;
                        w._formName = null;          // each page its own way's name, as the switch gives it
                        w._page = page.StartsWith("map") ? "library" : page.StartsWith("generate") ? "generate" : page;
                        if (page.StartsWith("generate_scratch"))
                            w._formName = null;
                        w._openMap = page == "map" ? maps.FirstOrDefault(m => m.Scratch == null) ?? maps.FirstOrDefault()
                                   : page == "map_scratch" ? maps.FirstOrDefault(m => m.Scratch != null) : null;
                        if (page.StartsWith("map") && w._openMap == null)
                        {
                            report.AppendLine($"SKIP {lang} {page}: no map in the library");
                            continue;
                        }
                        w.Rebuild();
                        await Task.Delay(250);
                        // each page from its top: the window keeps a page's scroll (3.46), and the options' page before the
                        // new map's form left it scrolled past the form's head (brief 30, 07.11)
                        if (page != "generate_options")
                        {
                            foreach (var sv in w.GetVisualDescendants().OfType<ScrollViewer>())
                                sv.Offset = default;
                            await Task.Delay(150);
                        }
                        if (page == "generate_options")
                        {
                            // the page scrolled to the options' cards: the frame and the new rooms at the top
                            var frame = w.GetVisualDescendants().OfType<Border>()
                                         .FirstOrDefault(c => c.Tag is OptionGroup { Key: "gen.warp" });
                            frame?.BringIntoView(new Avalonia.Rect(0, 0, 8, Math.Min(frame.Bounds.Height, 700)));
                            await Task.Delay(300);
                        }
                        await Task.Delay(350);
                        var file = Path.Combine(into, page + ".png");
                        Shot(w, file);
                        // MAPGEN_SHOT_FULLPAGE: the page's whole length besides (a page looked at end to end, not for the guide)
                        if (Environment.GetEnvironmentVariable("MAPGEN_SHOT_FULLPAGE") is { Length: > 0 }
                            && w.GetVisualDescendants().OfType<ScrollViewer>().FirstOrDefault() is { Content: Control whole }
                            && whole.Bounds.Height > 0)
                        {
                            using var all = new RenderTargetBitmap(new PixelSize((int)whole.Bounds.Width, (int)whole.Bounds.Height));
                            all.Render(whole);
                            all.Save(Path.Combine(into, page + "_whole.png"));
                        }
                        report.AppendLine($"{(File.Exists(file) ? "PASS" : "FAIL")} {lang} {page} {file}");
                    }
                }
                Loc.Language = keepLang;
                App.ApplyTheme(keepTheme);
                App.Settings.ScratchMode = keepScratch;
                App.Settings.Scratch = keepScratchParams;
                if (Environment.GetEnvironmentVariable("MAPGEN_SHOT_PAGES") is not { Length: > 0 })
                    File.WriteAllText(Path.Combine(dir, "build.txt"), Versions.Current + "\n");
            }
            catch (Exception ex)
            {
                report.AppendLine("FAIL the shots threw -- " + ex);
            }
            File.WriteAllText(Path.Combine(Settings.ProgramDir, "shots.txt"), report.ToString());
            Environment.Exit(report.ToString().Contains("FAIL") ? 1 : 0);
        };
        return w;
    }

    /// <summary>
    /// `--shots-full DIR JOB LANG`: the map on the whole screen as the guide shows it - the scheme of JOB's map (its
    /// newest build, else `baseline/q2mg.bsp`; its plan and ledger for the edits), at a slant, 1600 x 900, off the
    /// screen. The map is drawn by the GPU, which a window picture does not hold: the frame is read back from it into
    /// `run_full_gl.png` and the window's own picture (the lines, the load, «Назад в студию») into `run_full_ui.png`;
    /// the guide guard lays the second over the first into `run_full.png`.
    /// </summary>
    public static Window ShotsFull(string dir, string job, string lang)
    {
        Loc.Language = lang;
        SelfTesting = true;
        var model = new SchemeModel();
        model.RefreshNow(job);
        // brief 30: the guide's size when MAPGEN_SHOT_SIZE gives one
        var (fw, fh) = (1600.0, 900.0);
        if (Environment.GetEnvironmentVariable("MAPGEN_SHOT_SIZE") is { } fs && fs.Split('x') is [var fa, var fb]
            && double.TryParse(fa, out var faw) && double.TryParse(fb, out var fah))
            (fw, fh) = (faw, fah);
        var full = new SchemeFullScreen(model, () => null)
        {
            WindowState = WindowState.Normal, Width = fw, Height = fh, ShowInTaskbar = false, ShowActivated = false,
            WindowStartupLocation = WindowStartupLocation.Manual, Position = new PixelPoint(-4000, -4000),
        };
        var into = Path.Combine(dir, lang);
        Directory.CreateDirectory(into);
        var started = false;
        full.Opened += async (_, _) =>
        {
            if (started)
                return;
            started = true;
            var report = new System.Text.StringBuilder();
            try
            {
                full.Caption(Loc.F("run.title", new DirectoryInfo(job).Name),
                             Loc.T("stage.light.now"), "", "");
                var host = full.View;
                for (var i = 0; i < 20; i++)
                {
                    host.Gl.RequestNextFrameRendering();
                    await Task.Delay(50);
                }
                host.Slant();
                await Task.Delay(800);
                var done = new TaskCompletionSource<bool>();
                host.Gl.Captured = (cw, ch, px) =>
                {
                    try
                    {
                        using var bmp = new WriteableBitmap(new PixelSize(cw, ch), new Vector(96, 96),
                            Avalonia.Platform.PixelFormat.Rgba8888, Avalonia.Platform.AlphaFormat.Opaque);
                        using (var fb = bmp.Lock())
                            for (var y = 0; y < ch; y++)
                                System.Runtime.InteropServices.Marshal.Copy(px, (ch - 1 - y) * cw * 4, fb.Address + y * fb.RowBytes, cw * 4);
                        bmp.Save(Path.Combine(into, "run_full_gl.png"));
                    }
                    finally
                    {
                        done.TrySetResult(true);
                    }
                };
                host.Gl.RequestNextFrameRendering();
                await Task.WhenAny(done.Task, Task.Delay(8000));
                report.AppendLine(done.Task.IsCompleted ? $"PASS {lang} the map's frame read back" : $"FAIL {lang} no frame came");
                Shot(full, Path.Combine(into, "run_full_ui.png"));
                report.AppendLine($"PASS {lang} the window's picture");
            }
            catch (Exception ex)
            {
                report.AppendLine("FAIL the full-screen shot threw -- " + ex);
            }
            File.WriteAllText(Path.Combine(Settings.ProgramDir, $"shots_full_{lang}.txt"), report.ToString());
            Environment.Exit(report.ToString().Contains("FAIL") ? 1 : 0);
        };
        return full;
    }

    /// <summary>The window's content as it stands, into a PNG (the window itself need not be on the screen).</summary>
    public static void Shot(Window w, string file)
    {
        // the whole window - its menu and its background with it (its content alone came out between black bands)
        var size = new PixelSize((int)Math.Max(1, w.Bounds.Width > 0 ? w.Bounds.Width : w.Width),
                                 (int)Math.Max(1, w.Bounds.Height > 0 ? w.Bounds.Height : w.Height));
        using var bmp = new RenderTargetBitmap(size);
        bmp.Render(w);
        bmp.Save(file);
    }
}
