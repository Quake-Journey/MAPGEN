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
        Settings = Settings.Load();
        Settings.EnsureFolders();
        Loc.Language = Settings.Language;
        // the PO, 12.10: the window look (the Fluent theme) is the slowest part of a start - a plain start loads it
        // under the loading window (Splash), every other use of the program at once
        if (!PlainStart)
            LoadTheme();
    }

    private static bool s_themed;

    /// <summary>The window look: the Fluent theme and the light or dark one chosen. Once.</summary>
    public static void LoadTheme()
    {
        if (s_themed || Current == null)
            return;
        s_themed = true;
        Current.Styles.Add(new FluentAvaloniaTheme());
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
