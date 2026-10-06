using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Styling;
using FluentAvalonia.Styling;

namespace MapgenStudio;

public sealed class App : Application
{
    public static Settings Settings { get; private set; } = new();

    public override void Initialize()
    {
        Styles.Add(new FluentAvaloniaTheme());
        Settings = Settings.Load();
        Settings.EnsureFolders();
        Loc.Language = Settings.Language;
        ApplyTheme(Settings.Theme);
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
            desktop.MainWindow = new MainWindow();
        }
        base.OnFrameworkInitializationCompleted();
    }
}
