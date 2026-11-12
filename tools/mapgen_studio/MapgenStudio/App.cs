using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Platform;
using Avalonia.Styling;
using FluentAvalonia.Styling;

namespace MapgenStudio;

public sealed class App : Application
{
    public static Settings Settings { get; private set; } = new();

    /// <summary>A plain start (no test, no command): the loading window opens first and loads the window look itself.</summary>
    private static bool PlainStart =>
        !Environment.GetCommandLineArgs().Skip(1).Any(a => a.StartsWith("--") && a != "--startup-test");

    public override void Initialize()
    {
        CopyText.Install();         // brief 15, the PO: any text of any window copied by the right mouse button
        TipPlace.Install();         // the PO 06.11: a tooltip never lies under the pointer (the start button's first press)
        Settings = Settings.Load();
        Settings.EnsureFolders();
        Loc.Language = Settings.Language;
        // the PO, 12.10: the window look (the Fluent theme) is the slowest part of a start - a plain start loads it
        // under the loading window (Splash), every other use of the program at once
        if (!PlainStart)
            LoadTheme();
    }

    private static bool s_themed;

    /// <summary>The height a list opens to at most (the self-test holds every list of the pages within it).</summary>
    public const double ComboRowsHigh = 880;

    /// <summary>The window look: the Fluent theme and the light or dark one chosen. Once.</summary>
    public static void LoadTheme()
    {
        if (s_themed || Current == null)
            return;
        s_themed = true;
        Current.Styles.Add(new FluentAvaloniaTheme());
        // the PO 12.11 («в меню скроллбар - так недопустимо»): a list opens with every row shown - the theme's 504 px
        // scrolled the spawn points' 24 and the item practice's 18; 880 holds 24 rows and stays inside a 1080 screen
        Current.Styles.Add(new Avalonia.Styling.Style(x => x.OfType<Avalonia.Controls.ComboBox>())
        {
            Setters = { new Avalonia.Styling.Setter(Avalonia.Controls.ComboBox.MaxDropDownHeightProperty, ComboRowsHigh) },
        });
        ApplyTheme(Settings.Theme);
    }

    private static WindowIcon? s_icon;

    /// <summary>Brief 13 W6: the Studio's own icon (Assets/mapgen_studio.ico), for every window's title bar and Alt-Tab.</summary>
    public static WindowIcon? Icon()
    {
        try
        {
            return s_icon ??= new WindowIcon(AssetLoader.Open(new Uri("avares://MapgenStudio/Assets/mapgen_studio.ico")));
        }
        catch (Exception)
        {
            return null;
        }
    }

    public static void ApplyTheme(string theme)
    {
        if (Current == null)
            return;
        Current.RequestedThemeVariant = theme switch
        {
            "light" => ThemeVariant.Light,
            "dark" => ThemeVariant.Dark,
            _ => ThemeVariant.Default,
        };
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            if (Environment.GetCommandLineArgs().Contains("--selftest"))
            {
                // every page, both languages, both themes - built and laid out, never shown; the answer in a file
                var report = MainWindow.SelfTest();
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "selftest.txt"), report);
                // the lifetime has not started yet; its Shutdown from here throws - leave directly
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            // brief 27 D3: «Перепроверить» without the window (`--recheck NAME`): the result in recheck.txt beside the program
            if (Environment.GetCommandLineArgs().Contains("--recheck"))
            {
                var argv = Environment.GetCommandLineArgs();
                var at = Array.IndexOf(argv, "--recheck");
                var name = at + 1 < argv.Length ? argv[at + 1] : "";
                var report = new System.Text.StringBuilder();
                var map = Library.Scan(Settings).FirstOrDefault(m => m.Name == name);
                if (map == null || !Recheck.CanRun(Settings, map))
                    report.AppendLine($"FAIL {name}: not in the library or not a map from scratch with its run");
                else
                {
                    report.AppendLine($"before: {map.GatesPassed} of {map.Gates.Count}, blocking {map.GatesBlocking}");
                    var job = Recheck.Start(Settings, map, out var outFile);
                    while (!job.Exited(out _))
                        Thread.Sleep(500);
                    job.Dispose();
                    var why = Recheck.Finish(Settings, map, outFile);
                    var now = Library.Scan(Settings).First(m => m.Name == name);
                    report.AppendLine(why == null ? $"after: {now.GatesPassed} of {now.Gates.Count}, blocking {now.GatesBlocking}" : $"FAIL {why}");
                    foreach (var (i, g) in now.Gates.Select((g, i) => (i, g)).Where(x => !x.g.pass))
                        report.AppendLine($"  failed: {g.what} -- {(i < now.Said.Count ? now.Said[i] : "")}");
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "recheck.txt"), report.ToString());
                Environment.Exit(0);
            }
            // brief 28: pictures of the pages as laid out (`--layout-shots DIR`), for the report
            if (Environment.GetCommandLineArgs().Contains("--layout-shots"))
            {
                var argv = Environment.GetCommandLineArgs();
                var at = Array.IndexOf(argv, "--layout-shots");
                var dir = at + 1 < argv.Length ? argv[at + 1] : Path.Combine(Settings.TempPath, "layout_shots");
                File.WriteAllLines(Path.Combine(dir.Length > 0 ? dir : ".", "..", "layout_shots.txt"), MainWindow.LayoutShots(dir));
                Environment.Exit(0);
            }
            // brief 26: the cover views of a map's jump pad and teleporter (`--fixture-views BSP OUT`), for
            // tools/check_mapgen_fixtures.py - one line per view: what x y z yaw
            if (Environment.GetCommandLineArgs().Contains("--fixture-views"))
            {
                var argv = Environment.GetCommandLineArgs();
                var at = Array.IndexOf(argv, "--fixture-views");
                var bsp = at + 1 < argv.Length ? argv[at + 1] : "";
                var outFile = at + 2 < argv.Length ? argv[at + 2] : Path.Combine(Settings.TempPath, "fixture_views.txt");
                File.WriteAllLines(outFile, Covers.Fixtures(bsp).Select(v => string.Create(System.Globalization.CultureInfo.InvariantCulture,
                                   $"{v.What} {v.X:0} {v.Y:0} {v.Z:0} {v.Yaw:0}")));
                Environment.Exit(0);
            }
            // brief 23 D2: every factory preset's body as the generator and the engine get it, for
            // tools/check_mapgen_presets.py - scratch/<key>.json (the request), base/<key>.txt (the likeness and the words)
            if (Environment.GetCommandLineArgs().Contains("--presets-dump"))
            {
                var argv = Environment.GetCommandLineArgs();
                var at = Array.IndexOf(argv, "--presets-dump");
                var outDir = at + 1 < argv.Length ? argv[at + 1] : Path.Combine(Settings.TempPath, "presets_dump");
                Directory.CreateDirectory(Path.Combine(outDir, "scratch"));
                Directory.CreateDirectory(Path.Combine(outDir, "base"));
                foreach (var f in Presets.Factory(Presets.Scratch))
                    File.WriteAllText(Path.Combine(outDir, "scratch", Presets.FactoryKey(f) + ".json"), Presets.ScratchOf(f.Body).ToPython());
                foreach (var f in Presets.Factory(Presets.Base))
                    File.WriteAllText(Path.Combine(outDir, "base", Presets.FactoryKey(f) + ".txt"),
                                      $"fidelity={f.Body["fidelity"]}\n" + string.Join(" ", Presets.OptionsOf(f.Body).Args()) + "\n");
                Environment.Exit(0);
            }
            if (Environment.GetCommandLineArgs().Contains("--generate"))
            {
                var report = GenerateCli.Run(Settings, Environment.GetCommandLineArgs());
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "generate.txt"), report);
                Environment.Exit(report.StartsWith("PASS") ? 0 : 1);
            }
            if (Environment.GetCommandLineArgs().Contains("--scheme-test"))
            {
                string report;
                try
                {
                    report = SchemeTest.Run(Environment.GetCommandLineArgs());
                }
                catch (Exception ex)
                {
                    report = "FAIL the plan test threw -- " + ex;
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "scheme_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            if (Environment.GetCommandLineArgs().Contains("--menus-test"))
            {
                string report;
                try
                {
                    report = MainWindow.MenusTest();
                }
                catch (Exception ex)
                {
                    report = "FAIL the menus' test threw -- " + ex;
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "menus_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            if (Environment.GetCommandLineArgs().Contains("--tries-test"))
            {
                string report;
                try
                {
                    report = SchemeTest.TriesTest(Environment.GetCommandLineArgs());
                }
                catch (Exception ex)
                {
                    report = "FAIL the tries' test threw -- " + ex;
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "tries_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            if (Environment.GetCommandLineArgs().Contains("--walk-code-test"))
            {
                string report;
                try
                {
                    report = SchemeTest.WalkCodeTest(Environment.GetCommandLineArgs());
                }
                catch (Exception ex)
                {
                    report = "FAIL the walk code's test threw -- " + ex;
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "walk_code_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            if (Environment.GetCommandLineArgs().Contains("--show-test"))
            {
                string report;
                try
                {
                    report = SchemeTest.ShowTest(Environment.GetCommandLineArgs());
                }
                catch (Exception ex)
                {
                    report = "FAIL the pictures' test threw -- " + ex;
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "show_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            if (Environment.GetCommandLineArgs().Contains("--generate-test"))
            {
                var report = GenerateTest.Run(Settings);
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "generate_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            if (Environment.GetCommandLineArgs().Contains("--cover-test"))
            {
                string report;
                try
                {
                    report = CoverTest.Run(Settings, Environment.GetCommandLineArgs());
                }
                catch (Exception ex)
                {
                    report = "FAIL the cover test threw -- " + ex;
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "cover_test.txt"), report);
                Environment.Exit(report.Contains("FAIL") ? 1 : 0);
            }
            // row 410: the plan in a real window for a few seconds - what a picture cannot catch (the render pass's own
            // rules: the PO's first resume with the plan closed the Studio)
            // brief 10 (D3): `--update-test` - the check and «Да» without a window, the answer in update_test.txt
            if (Environment.GetCommandLineArgs().Contains("--update-test"))
            {
                var said = new System.Text.StringBuilder();
                var code = Task.Run(async () =>
                {
                    var found = await Update.Check();
                    if (found == null)
                    {
                        said.AppendLine("UNREACHABLE");
                        return 2;
                    }
                    said.AppendLine($"FOUND {found.Version} CURRENT {Versions.Current}");
                    if (!Update.Newer(found.Version))
                    {
                        said.AppendLine("LATEST");
                        return 0;
                    }
                    var why = await Update.Fetch(found.Version, t => said.AppendLine("SAY " + t));
                    said.AppendLine(why == null ? "HANDED OVER" : "REFUSED " + why);
                    return why == null ? 0 : 3;
                }).GetAwaiter().GetResult();
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "update_test.txt"), said.ToString());
                Environment.Exit(code);
            }
            // brief 10 (D3): the NEW Studio, from its unpacked folder, puts itself in place of the old one
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "--apply-update") is var upAt and >= 0
                && upAt + 4 < Environment.GetCommandLineArgs().Length)
            {
                var a = Environment.GetCommandLineArgs();
                Environment.Exit(Update.Apply(a[upAt + 1], a[upAt + 2], int.TryParse(a[upAt + 3], out var pid) ? pid : 0, a[upAt + 4]));
            }
            // brief 10 (D1): the map on the whole screen for the guide - `--shots-full DIR JOB LANG`
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "--shots-full") is var fullAt and >= 0
                && fullAt + 3 < Environment.GetCommandLineArgs().Length)
            {
                var a = Environment.GetCommandLineArgs();
                desktop.MainWindow = MainWindow.ShotsFull(a[fullAt + 1], a[fullAt + 2], a[fullAt + 3]);
                base.OnFrameworkInitializationCompleted();
                return;
            }
            // Fable's brief 10 (D1): the guide's screenshots, made by the program - `--shots DIR`
            if (Array.IndexOf(Environment.GetCommandLineArgs(), "--shots") is var shotsAt and >= 0
                && shotsAt + 1 < Environment.GetCommandLineArgs().Length)
            {
                desktop.MainWindow = MainWindow.Shots(Environment.GetCommandLineArgs()[shotsAt + 1]);
                base.OnFrameworkInitializationCompleted();
                return;
            }
            if (Environment.GetCommandLineArgs().Contains("--ui-test"))
            {
                desktop.MainWindow = MainWindow.UiTest();
                base.OnFrameworkInitializationCompleted();
                return;
            }
            if (Environment.GetCommandLineArgs().Contains("--scheme-full-test"))
            {
                desktop.MainWindow = SchemeTest.FullTest(Environment.GetCommandLineArgs());
                base.OnFrameworkInitializationCompleted();
                return;
            }
            if (Environment.GetCommandLineArgs().Contains("--scheme-gl-test"))
            {
                desktop.MainWindow = SchemeTest.GlTest(Environment.GetCommandLineArgs());
                base.OnFrameworkInitializationCompleted();
                return;
            }
            if (Environment.GetCommandLineArgs().Contains("--scheme-window-test"))
            {
                desktop.MainWindow = SchemeTest.InWindow(Environment.GetCommandLineArgs());
                base.OnFrameworkInitializationCompleted();
                return;
            }
            // the PO, 12.10: a loading window with the share done and the step under way; it builds the Studio's
            // window (the faulty cores' read begun on a pool thread there, brief 13 W4) and gives way to it.
            // `--startup-test`: the same start off screen, the steps' times in startup_test.txt
            var test = Environment.GetCommandLineArgs().Contains("--startup-test");
            MainWindow.StartupTesting = test;
            var splash = new Splash(test);
            desktop.MainWindow = splash;
            splash.Opened += async (_, _) => await splash.Run(desktop);
        }
        base.OnFrameworkInitializationCompleted();
    }
}
