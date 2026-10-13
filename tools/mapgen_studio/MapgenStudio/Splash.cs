using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Controls.Presenters;
using Avalonia.Controls.Templates;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Styling;
using Avalonia.Threading;
using FluentAvalonia.Styling;

namespace MapgenStudio;

/// <summary>
/// The Studio's loading window (the PO, 12.10: «каждый запуск грузится несколько секунд и кажется что просто не
/// открывается - нужно добавить окошко загрузки»; «отображать процент загрузки и описание что сейчас делается - на слабых
/// компьютерах и дисках загрузка может быть долгой»). It opens before the window look (the Fluent theme, the slowest
/// part of starting) is loaded - its own plain template, nothing of a theme - and says each step of the start as it
/// goes, with the share done. The share is weighed by how long each step took at the LAST start (startup_times.txt
/// beside the program), so on a slow disk or a weak machine the bar moves as that machine starts, not as this one did.
/// </summary>
public sealed class Splash : Window
{
    /// <summary>The steps of a start, in order, with the time each is given before a start has been timed (ms).</summary>
    public static readonly (string key, int ms)[] Steps =
    {
        ("splash.runtime", 1500), ("splash.theme", 600), ("splash.cpus", 50), ("splash.library", 300),
        ("splash.cover", 1500), ("splash.tools", 100), ("splash.game", 50), ("splash.window", 800), ("splash.show", 600),
    };

    private static readonly Color Ground = Color.FromRgb(0x17, 0x1b, 0x26), Accent = Color.FromRgb(0x3b, 0x82, 0xf6);
    private readonly TextBlock _step = new() { FontSize = 15, Foreground = Brushes.White, TextTrimming = TextTrimming.CharacterEllipsis };
    private readonly TextBlock _percent = new() { FontSize = 15, Foreground = Brushes.White, FontWeight = FontWeight.SemiBold,
                                                  HorizontalAlignment = HorizontalAlignment.Right };
    private readonly Border _fill = new() { Background = new SolidColorBrush(Accent), CornerRadius = new CornerRadius(3),
                                            HorizontalAlignment = HorizontalAlignment.Left, Width = 0 };
    private const double BarWidth = 440;
    private readonly Dictionary<string, int> _expected;
    private readonly Dictionary<string, int> _took = new();
    private readonly bool _test;

    public Splash(bool test = false)
    {
        _test = test;
        _expected = Steps.ToDictionary(s => s.key, s => s.ms);
        foreach (var (key, ms) in ReadTimes())
            if (_expected.ContainsKey(key))
                _expected[key] = Math.Max(1, ms);
        Title = Loc.T("splash.title");
        Icon = App.Icon();
        Width = 520;
        Height = 190;
        CanResize = false;
        WindowDecorations = Avalonia.Controls.WindowDecorations.None;
        WindowStartupLocation = test ? WindowStartupLocation.Manual : WindowStartupLocation.CenterScreen;
        if (test)
        {
            Position = new PixelPoint(-20000, -20000);
            ShowInTaskbar = false;
            ShowActivated = false;
        }
        Background = new SolidColorBrush(Ground);
        // its own template: the window draws before any theme is in the application
        Theme = new ControlTheme(typeof(Window))
        {
            Setters =
            {
                new Setter(TemplateProperty, new FuncControlTemplate<Window>((w, scope) => new ContentPresenter
                {
                    Name = "PART_ContentPresenter",
                    [!ContentPresenter.ContentProperty] = w[!ContentProperty],
                    [!ContentPresenter.BackgroundProperty] = w[!BackgroundProperty],
                }.RegisterInNameScope(scope))),
            },
        };
        var head = new TextBlock { Text = "MAPGEN Studio", FontSize = 26, FontWeight = FontWeight.SemiBold, Foreground = Brushes.White };
        var version = new TextBlock { Text = Versions.Said(typeof(Splash).Assembly.GetName().Version), FontSize = 13,
                                      Foreground = new SolidColorBrush(Color.FromArgb(0xb0, 0xff, 0xff, 0xff)) };
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 12 };
        line.Children.Add(_step);
        Grid.SetColumn(_percent, 1);
        line.Children.Add(_percent);
        var bar = new Border
        {
            Width = BarWidth, Height = 6, CornerRadius = new CornerRadius(3), HorizontalAlignment = HorizontalAlignment.Left,
            Background = new SolidColorBrush(Color.FromArgb(0x40, 0xff, 0xff, 0xff)), Child = _fill,
        };
        var note = new TextBlock { Text = Loc.T("splash.slow"), FontSize = 12, TextWrapping = TextWrapping.Wrap,
                                   Foreground = new SolidColorBrush(Color.FromArgb(0x90, 0xff, 0xff, 0xff)) };
        Content = new Border
        {
            BorderBrush = new SolidColorBrush(Color.FromArgb(0x50, 0x3b, 0x82, 0xf6)), BorderThickness = new Thickness(1),
            Padding = new Thickness(40, 26, 40, 22),
            Child = new StackPanel
            {
                Spacing = 10, Width = BarWidth,
                Children = { new StackPanel { Spacing = 2, Children = { head, version } }, line, bar, note },
            },
        };
    }

    private static string TimesFile => Path.Combine(Settings.ProgramDir, "startup_times.txt");

    private static IEnumerable<(string, int)> ReadTimes()
    {
        string[] lines;
        try
        {
            lines = File.Exists(TimesFile) ? File.ReadAllLines(TimesFile) : Array.Empty<string>();
        }
        catch (Exception)
        {
            yield break;
        }
        foreach (var l in lines)
        {
            var p = l.Split(' ', 2);
            if (p.Length == 2 && int.TryParse(p[1], out var ms))
                yield return (p[0], ms);
        }
    }

    /// <summary>The share of the start done once the steps before `key` have ended, in percent.</summary>
    private int ShareBefore(string key)
    {
        double total = _expected.Values.Sum(), done = 0;
        foreach (var (k, _) in Steps)
        {
            if (k == key)
                break;
            done += _expected[k];
        }
        return (int)Math.Round(100.0 * done / total);
    }

    private void Say(string key, int percent)
    {
        _step.Text = Loc.T(key) + "…";
        _percent.Text = $"{percent} %";
        _fill.Width = BarWidth * percent / 100.0;
    }

    /// <summary>Let the window draw what it was just told before the next step holds the thread.</summary>
    private static async Task Drawn()
    {
        await Dispatcher.UIThread.InvokeAsync(() => { }, DispatcherPriority.Background);
        await Task.Delay(15);
    }

    private async Task Step(string key, Func<Task> work)
    {
        Say(key, ShareBefore(key));
        await Drawn();
        var watch = Stopwatch.StartNew();
        await work();
        _took[key] = (int)watch.ElapsedMilliseconds;
    }

    /// <summary>
    /// The start: the window look, the cores' read begun, the library read, Python and the checks found, the game
    /// found, the Studio's window built and shown - then this window goes. `test`: everything off screen, the steps'
    /// times into startup_test.txt, the program ends.
    /// </summary>
    public async Task Run(IClassicDesktopStyleApplicationLifetime desktop)
    {
        try
        {
            using (var me = Process.GetCurrentProcess())
                _took["splash.runtime"] = (int)Math.Max(1, (DateTime.Now - me.StartTime).TotalMilliseconds);
            await Step("splash.theme", () =>
            {
                App.LoadTheme();
                return Task.CompletedTask;
            });
            await Step("splash.cpus", () =>
            {
                NativeJob.WarmFaultyCpus();
                return Task.CompletedTask;
            });
            var s = App.Settings;
            List<MapEntry> maps = new();
            await Step("splash.library", async () => maps = await Task.Run(() => Library.Scan(s)));
            // the home page shows the newest map's cover: its small copy made (or read) here, off the window's thread
            await Step("splash.cover", () => Task.Run(() =>
            {
                if (maps.FirstOrDefault()?.CoverPath is { } cover)
                    TilePage.Thumb(cover, 600);
            }));
            await Step("splash.tools", () => Task.Run(() =>
            {
                _ = Engine.Python;
                _ = Engine.Repo;
            }));
            await Step("splash.game", () => Task.Run(() => Settings.CheckClient(s.ClientDir)));
            MainWindow? main = null;
            await Step("splash.window", () =>
            {
                main = new MainWindow();
                if (_test)
                {
                    main.WindowStartupLocation = WindowStartupLocation.Manual;
                    main.Position = new PixelPoint(-20000, -20000);
                    main.ShowInTaskbar = false;
                    main.ShowActivated = false;
                }
                return Task.CompletedTask;
            });
            await Step("splash.show", async () =>
            {
                var opened = new TaskCompletionSource();
                main!.Opened += (_, _) => opened.TrySetResult();
                main.Show();
                await opened.Task;
                await Drawn();
            });
            Say("splash.show", 100);
            SaveTimes();
            desktop.MainWindow = main;
            // the library's PNG pictures of earlier versions made JPEGs, once, behind the open window
            if (!_test)
                _ = Task.Run(() =>
                {
                    Thread.CurrentThread.Priority = ThreadPriority.BelowNormal;
                    Library.CompactCovers(s);
                });
            if (_test)
            {
                // the window as it looks part way, for whoever checks the test
                Say("splash.window", ShareBefore("splash.window"));
                Measure(new Size(Width, Height));
                Arrange(new Rect(0, 0, Width, Height));
                using (var shot = new Avalonia.Media.Imaging.RenderTargetBitmap(new PixelSize((int)Width, (int)Height)))
                {
                    shot.Render(this);
                    shot.Save(Path.Combine(Settings.ProgramDir, "startup_splash.png"));
                }
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "startup_test.txt"), Report());
                Environment.Exit(0);
            }
            Close();
        }
        catch (Exception ex)
        {
            if (_test)
            {
                File.WriteAllText(Path.Combine(Settings.ProgramDir, "startup_test.txt"), $"FAIL the start threw -- {ex}\n");
                Environment.Exit(1);
            }
            throw;
        }
    }

    private void SaveTimes()
    {
        if (_test)
            return;
        try
        {
            File.WriteAllLines(TimesFile, Steps.Where(s => _took.ContainsKey(s.key)).Select(s => $"{s.key} {_took[s.key]}"));
        }
        catch (Exception)
        {
            // a start that cannot write its times is still a start
        }
    }

    private string Report()
    {
        var b = new System.Text.StringBuilder();
        var all = Steps.All(s => _took.ContainsKey(s.key));
        foreach (var (key, _) in Steps)
            b.AppendLine($"{key} {(_took.TryGetValue(key, out var ms) ? ms.ToString() : "-")} ms - {Loc.T(key)}");
        b.AppendLine($"total {_took.Values.Sum()} ms");
        b.AppendLine(all ? "PASS every step of the start ran and was said" : "FAIL a step of the start did not run");
        return b.ToString();
    }
}
