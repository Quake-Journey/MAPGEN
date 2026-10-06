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
    public static readonly string[] ShotPages = { "home", "generate", "generate_options", "library", "map", "settings", "about" };

    public static Window Shots(string dir)
    {
        var w = new MainWindow
        {
            ShowActivated = false, ShowInTaskbar = false, Width = 1600, Height = 900,
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
                        w._page = page == "map" ? "library" : page.StartsWith("generate") ? "generate" : page;
                        w._openMap = page == "map" ? maps.FirstOrDefault() : null;
                        if (page == "map" && w._openMap == null)
                        {
                            report.AppendLine($"SKIP {lang} {page}: no map in the library");
                            continue;
                        }
                        w.Rebuild();
                        await Task.Delay(250);
                        if (page == "generate_options")
                        {
                            // the creative options open, the rest folded, and the page scrolled to them
                            FASettingsExpander? creative = null;
                            foreach (var ex in w.GetVisualDescendants().OfType<FASettingsExpander>())
                            {
                                var mine = Equals(ex.Header, Loc.T("gen.creative"));
                                ex.IsExpanded = mine;
                                if (mine)
                                    creative = ex;
                            }
                            await Task.Delay(300);
                            creative?.BringIntoView();
                        }
                        await Task.Delay(350);
                        var file = Path.Combine(into, page + ".png");
                        Shot(w, file);
                        report.AppendLine($"{(File.Exists(file) ? "PASS" : "FAIL")} {lang} {page} {file}");
                    }
                }
                Loc.Language = keepLang;
                App.ApplyTheme(keepTheme);
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
        var full = new SchemeFullScreen(model, () => null)
        {
            WindowState = WindowState.Normal, Width = 1600, Height = 900, ShowInTaskbar = false, ShowActivated = false,
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
