using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// The shell (phase P1): navigation - Home, Generate, Maps, Settings, About - themes, RU/EN, a tooltip on every
/// element, the ini, folders and the client chosen by dialogs, the map library with its detail card.
/// The whole window is rebuilt from the string table when the language changes.
/// </summary>
public sealed partial class MainWindow : Window
{
    private readonly FANavigationView _nav = new();
    private readonly ContentControl _content = new();
    private readonly FAInfoBar _notice = new() { IsOpen = false, IsClosable = true, Margin = new Thickness(36, 12, 36, 0) };
    private string _page = App.Settings.StartPage;
    private MapEntry? _openMap;

    private Settings S => App.Settings;

    public MainWindow()
    {
        Width = 1180;
        Height = 780;
        MinWidth = 900;
        MinHeight = 600;
        WindowStartupLocation = WindowStartupLocation.CenterScreen;
        _chosen.AddRange(S.Bases.Distinct());
        _graftMode = S.GraftMode;
        _nav.PaneDisplayMode = FANavigationViewPaneDisplayMode.Left;
        _nav.IsSettingsVisible = false;
        _nav.IsBackButtonVisible = false;
        _nav.OpenPaneLength = 230;
        _nav.SelectionChanged += (_, e) =>
        {
            if (e.SelectedItem is FANavigationViewItem item && item.Tag is string page && page != _page)
            {
                if (page != "generate")
                    _formName = null;
                _page = page;
                _openMap = null;
                ShowPage();
            }
        };
        var dock = new DockPanel();
        DockPanel.SetDock(_notice, Dock.Top);
        dock.Children.Add(_notice);
        dock.Children.Add(_content);
        _nav.Content = dock;
        Content = _nav;
        Rebuild();
        // the run is polled, never waited on (R6): the window stays live whatever the generator does
        var timer = new Avalonia.Threading.DispatcherTimer { Interval = TimeSpan.FromMilliseconds(500) };
        timer.Tick += (_, _) => Tick();
        timer.Start();
        Closing += OnClosing;
        Opened += OnFirstOpened;            // brief 10 (D3): «what's new» after an update, the update check
        // a cover launch still open when the window goes: that one client closed, the map copies taken back
        Closed += (_, _) =>
        {
            if (_cover != null)
                Covers.Finish(_cover, S, timeout: true);
        };
    }

    private bool _closeConfirmed;

    private void Tick()
    {
        TickClient();
        var g = Generation.Current;
        if (g == null)
            return;
        // row 410 (the PO 05.10: «интерфейс студии вешается когда запущена генерация»): the run is polled off this
        // thread; the window only reads what the last poll left, and an end is seen on the tick after it happened
        g.PollAsync();
        if (_watched == g && _watchedRunning && !g.Running && g.LibraryName.Length > 0)
            Notice(Loc.F("run.done.notice", g.LibraryName));
        _watched = g;
        _watchedRunning = g.Running;
        // row 399: a map from each chosen base - the next one as soon as this one has ended, whatever its outcome
        if (!g.Running)
        {
            try
            {
                if (Generation.StartNext(S))
                    g = Generation.Current!;
            }
            catch (Exception ex)
            {
                Generation.Queue.Clear();
                Notice(ex.Message, FAInfoBarSeverity.Error);
            }
        }
        if (_page == "generate")
            UpdateRun(g);
    }

    private Generation? _watched;
    private bool _watchedRunning;

    /// <summary>The run's page from what the last poll left - skipped this beat while a poll holds the run.</summary>
    private void UpdateRun(Generation g)
    {
        if (_runView == null || !Monitor.TryEnter(g.Sync, 20))
            return;
        try
        {
            _runView.Update(g);
        }
        finally
        {
            Monitor.Exit(g.Sync);
        }
    }

    private GenerationView? _runView;

    /// <summary>Set by the self-test: nothing it does on a page is kept in the settings.</summary>
    public static bool SelfTesting { get; private set; }

    private string? _formName;
    private bool _suggesting;

    /// <summary>The form's likeness, seed, families and options into the settings (never from the self-test).</summary>
    private void KeepForm()
    {
        if (!SelfTesting)
            S.Save();
    }

    private static readonly int[] CountChoices = { 0, 1, 2, 3, 4, 6, 8 };
    private static readonly string[] Liquids =
        { "", "water-lava", "water-slime", "lava-water", "slime-water", "lava-slime", "slime-lava", "mix" };

    /// <summary>
    /// Row 410 (the PO, 05.10: «какие еще параметры добавить ... чтобы получать больше вариаций творчества»): the
    /// plan's own counts and sizes and the liquids, each «По умолчанию» first - the likeness decides.
    /// </summary>
    private Control CreativePicker()
    {
        var ex = new FASettingsExpander
        {
            Header = Loc.T("gen.creative"), Description = Loc.T("gen.creative.desc"),
            IconSource = Ui.Icon(FASymbol.Library), IsExpanded = false, Margin = new Thickness(0, 0, 0, 4),
        }.Tip("gen.creative.tip");
        void Row(string key, string[] items, int index, Action<int> set)
        {
            var box = new ComboBox { MinWidth = 260, ItemsSource = items, SelectedIndex = Math.Max(0, index) }.Tip($"{key}.tip");
            box.SelectionChanged += (_, _) =>
            {
                set(Math.Max(0, box.SelectedIndex));
                KeepForm();
            };
            ex.Items.Add(new FASettingsExpanderItem { Content = Loc.T(key), Description = Loc.T($"{key}.tip"), Footer = box }.Tip($"{key}.tip"));
        }
        string[] Counts(int[] values) => values.Select(v => v == 0 ? Loc.T("gen.default") : v.ToString()).ToArray();
        var o = S.Options;
        Row("gen.opt.digs", Counts(CountChoices), Array.IndexOf(CountChoices, o.Digs), i => S.Options = S.Options with { Digs = CountChoices[i] });
        Row("gen.opt.annexes", Counts(CountChoices), Array.IndexOf(CountChoices, o.Annexes), i => S.Options = S.Options with { Annexes = CountChoices[i] });
        Row("gen.opt.annex_size", new[] { "gen.default", "gen.size.small", "gen.size.medium", "gen.size.large", "gen.size.halls" }.Select(Loc.T).ToArray(),
            o.AnnexSize, i => S.Options = S.Options with { AnnexSize = i });
        Row("gen.opt.storeys", Counts(CountChoices), Array.IndexOf(CountChoices, o.Storeys), i => S.Options = S.Options with { Storeys = CountChoices[i] });
        Row("gen.opt.spans", Counts(CountChoices), Array.IndexOf(CountChoices, o.Spans), i => S.Options = S.Options with { Spans = CountChoices[i] });
        Row("gen.opt.halls", Counts(CountChoices), Array.IndexOf(CountChoices, o.Halls), i => S.Options = S.Options with { Halls = CountChoices[i] });
        // the PO, 05.10: «замена воды на лаву или кислоту и наоборот ... и визуал меняем и свойства»
        Row("gen.opt.liquids", Liquids.Select(l => Loc.T(l.Length == 0 ? "gen.default.liquids" : $"gen.liquids.{l}")).ToArray(),
            Array.IndexOf(Liquids, o.Liquids), i => S.Options = S.Options with { Liquids = Liquids[i] });
        // row 412, the PO: «украшения на стенах ... Можно также это вынести в параметры»
        Row("gen.opt.decor", new[] { "gen.default", "gen.decor.none", "gen.decor.few", "gen.decor.many", "gen.decor.most" }.Select(Loc.T).ToArray(),
            o.Decor, i => S.Options = S.Options with { Decor = i });
        // row 412, the PO: «нужен такой слайдер» - new water, slime and lava, each «По умолчанию» or 0..100 % of the
        // rooms a flood may take
        void LiquidRow(string key, int value, Action<int> set)
        {
            var auto = new CheckBox { Content = Loc.T("gen.default"), IsChecked = value < 0, VerticalAlignment = VerticalAlignment.Center };
            var slider = new Slider
            {
                Minimum = 0, Maximum = 100, Value = value < 0 ? 50 : value, Width = 200, SmallChange = 5, LargeChange = 25,
                IsSnapToTickEnabled = true, TickFrequency = 5, IsEnabled = value >= 0,
                VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(12, 0, 8, 0),
            };
            var said = new TextBlock { MinWidth = 48, VerticalAlignment = VerticalAlignment.Center };
            void Show() => said.Text = auto.IsChecked == true ? "" : $"{(int)slider.Value} %";
            void Keep()
            {
                set(auto.IsChecked == true ? -1 : (int)slider.Value);
                slider.IsEnabled = auto.IsChecked != true;
                Show();
                KeepForm();
            }
            auto.IsCheckedChanged += (_, _) => Keep();
            slider.PropertyChanged += (_, e) =>
            {
                if (e.Property == Avalonia.Controls.Primitives.RangeBase.ValueProperty)
                    Keep();
            };
            Show();
            var footer = new StackPanel { Orientation = Orientation.Horizontal, Children = { auto, slider, said } };
            ex.Items.Add(new FASettingsExpanderItem { Content = Loc.T(key), Description = Loc.T($"{key}.tip"), Footer = footer }.Tip($"{key}.tip"));
        }
        LiquidRow("gen.opt.new_water", o.NewWater, v => S.Options = S.Options with { NewWater = v });
        LiquidRow("gen.opt.new_slime", o.NewSlime, v => S.Options = S.Options with { NewSlime = v });
        LiquidRow("gen.opt.new_lava", o.NewLava, v => S.Options = S.Options with { NewLava = v });
        return ex;
    }

    /// <summary>The ticked bases and the mode into the settings, so a restart keeps them.</summary>
    private void KeepBases()
    {
        if (SelfTesting)
            return;
        if (S.Bases.SequenceEqual(_chosen) && S.GraftMode == _graftMode)
            return;
        S.Bases = _chosen.ToList();
        S.GraftMode = _graftMode;
        S.Save();
    }

    /// <summary>The bases ticked on the Generate page, in the order they were ticked: the first is THE base.</summary>
    private readonly List<string> _chosen = new();
    private bool _graftMode;

    // ---- the game client, one launch at a time (S5) -----------------------------------------------------------

    private Client.Run? _play;
    private Covers.Run? _cover;
    /* S-4: maps waiting for a cover from the library's button, shot one at a time */
    private readonly List<string> _coverQueue = new();

    private void LaunchClient(Action launch)
    {
        if (_play is { Process.HasExited: false } || _cover is { Game.Process.HasExited: false } || Client.Busy(S))
        {
            Notice(Loc.T("cover.busy"), FAInfoBarSeverity.Warning);
            return;
        }
        if (!Settings.CheckClient(S.ClientDir).ok)
        {
            Notice(Loc.T("lib.to_client.noclient"), FAInfoBarSeverity.Warning);
            return;
        }
        try
        {
            launch();
        }
        catch (Exception ex)
        {
            Notice(ex.Message, FAInfoBarSeverity.Error);
        }
    }

    /// <summary>The launched client watched: when it closes, its configs compared; the cover's shots collected.</summary>
    private void TickClient()
    {
        if (_cover == null && _coverQueue.Count > 0 && Generation.Current is not { Running: true } && !Client.Busy(S))
        {
            var name = _coverQueue[0];
            _coverQueue.RemoveAt(0);
            var entry = Library.Scan(S).FirstOrDefault(x => x.Name == name);
            if (entry != null)
            {
                try
                {
                    _cover = Covers.Start(entry, S);
                    Notice(Loc.F("cover.running", name), FAInfoBarSeverity.Informational);
                }
                catch (Exception ex)
                {
                    Notice(ex.Message, FAInfoBarSeverity.Warning);
                }
            }
        }
        if (_play is { Process.HasExited: true } p)
        {
            _play = null;
            var kept = Client.ConfigsKept(p, S);
            Notice(Loc.T(kept ? "lib.play.kept" : "lib.play.changed"), kept ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Warning);
        }
        if (_cover is { } c && (c.Game.Process.HasExited || DateTime.Now - c.Game.Began > TimeSpan.FromMinutes(3)))
        {
            _cover = null;
            var (n, kept, note) = Covers.Finish(c, S, timeout: !c.Game.Process.HasExited);
            var text = (n > 0 ? Loc.F("cover.done", n) : Loc.T("cover.none"))
                       + (note.Length > 0 ? ". " + note : "")
                       + (kept ? "" : ". " + Loc.T("lib.play.changed"));
            Notice(text, n > 0 && kept && note.Length == 0 ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Warning);
            if (_page == "library")
            {
                if (_openMap != null)
                    _openMap = Library.Scan(S).FirstOrDefault(x => x.Name == _openMap.Name) ?? _openMap;
                ShowPage();
            }
        }
    }

    /// <summary>
    /// «Удалить» on a stopped generation (the PO, 05.10): asks, says how much goes, deletes its folder, redraws the page.
    /// </summary>
    private Button DeleteButton(string runDir, string name)
    {
        var drop = Ui.Button("gen.interrupted.delete", "gen.interrupted.delete.tip", FASymbol.Delete);
        drop.Click += async (_, _) =>
        {
            var bytes = Generation.FolderBytes(runDir);
            if (!await Confirm(Loc.F("delete.title", name), Loc.F("delete.text", Generation.Size(bytes)), "delete.yes", "delete.no"))
                return;
            var why = Generation.Delete(S, runDir);
            Notice(why.Length == 0 ? Loc.F("delete.done", name, Generation.Size(bytes)) : Loc.F("delete.failed", why),
                   why.Length == 0 ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Error);
            ShowPage();
        };
        return drop;
    }

    /// <summary>A question with two answers, the second the safe one; true for the first.</summary>
    public async Task<bool> Confirm(string title, string text, string yesKey, string noKey)
    {
        if (UiTesting)
            return true;
        var dialog = new FAContentDialog
        {
            Title = title, Content = text, PrimaryButtonText = Loc.T(yesKey), CloseButtonText = Loc.T(noKey),
            DefaultButton = FAContentDialogButton.Close,
        };
        return await dialog.ShowAsync(this) == FAContentDialogResult.Primary;
    }

    /// <summary>The window test answers its own questions «yes».</summary>
    public static bool UiTesting { get; set; }

    /// <summary>R8: quitting while a generation runs asks first; stopping ends it at the current step.</summary>
    private async void OnClosing(object? sender, WindowClosingEventArgs e)
    {
        if (_closeConfirmed || Generation.Current is not { Running: true } g)
            return;
        e.Cancel = true;
        var dialog = new FAContentDialog
        {
            Title = Loc.T("quit.title"),
            Content = Loc.T("quit.text"),
            PrimaryButtonText = Loc.T("quit.stop"),
            CloseButtonText = Loc.T("quit.keep"),
            DefaultButton = FAContentDialogButton.Close,
        };
        if (await dialog.ShowAsync(this) == FAContentDialogResult.Primary)
        {
            g.Stop();
            _closeConfirmed = true;
            Close();
        }
    }

    /// <summary>The navigation and the current page, in the current language.</summary>
    private void Rebuild()
    {
        Title = Loc.T("app.title");
        _nav.PaneTitle = Loc.T("app.title");
        _nav.MenuItems.Clear();
        _nav.FooterMenuItems.Clear();
        FANavigationViewItem? selected = null;
        foreach (var (tag, key, symbol, footer) in new[]
                 {
                     ("home", "nav.home", FASymbol.Home, false),
                     ("generate", "nav.generate", FASymbol.Play, false),
                     ("library", "nav.library", FASymbol.Library, false),
                     ("settings", "nav.settings", FASymbol.Settings, true),
                     ("about", "nav.about", FASymbol.Help, true),
                 })
        {
            var item = new FANavigationViewItem { Content = Loc.T(key), Tag = tag, IconSource = Ui.Icon(symbol) };
            item.Tip(key + ".tip");
            (footer ? _nav.FooterMenuItems : _nav.MenuItems).Add(item);
            if (tag == _page)
                selected = item;
        }
        _nav.SelectedItem = selected;
        ShowPage();
    }

    private void Go(string page)
    {
        if (page != "generate")
            _formName = null;
        _page = page;
        _openMap = null;
        Rebuild();
    }

    /// <summary>«Установить Python» and «Указать путь к Python…» (the PO, 06.10); `bar`, when given, says the steps.</summary>
    private Control PythonButtons(FAInfoBar? bar)
    {
        var install = Ui.Button("python.install", "python.install.tip", FASymbol.Download);
        var choose = Ui.Button("python.choose", "python.choose.tip", FASymbol.OpenFile);
        choose.Margin = new Thickness(8, 0, 0, 0);
        void Say(string text)
        {
            if (bar != null)
                bar.Message = text;
            else
                Notice(text, FAInfoBarSeverity.Informational);
        }
        install.Click += async (_, _) =>
        {
            install.IsEnabled = choose.IsEnabled = false;
            var got = await PythonSetup.Install(t => Avalonia.Threading.Dispatcher.UIThread.Post(() => Say(t)));
            install.IsEnabled = choose.IsEnabled = true;
            if (got != null)
            {
                Notice(Loc.F("python.done", got));
                ShowPage();
            }
        };
        choose.Click += async (_, _) =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = Loc.T("python.choose"),
                AllowMultiple = false,
                FileTypeFilter = new[] { new FilePickerFileType("python.exe") { Patterns = new[] { "python.exe" } } },
            });
            var path = files.FirstOrDefault()?.TryGetLocalPath();
            if (path == null)
                return;
            var said = PythonSetup.Probe(path);
            if (said == null)
            {
                Notice(Loc.F("python.notpython", path), FAInfoBarSeverity.Warning);
                return;
            }
            S.PythonPath = path;
            S.Save();
            Notice(Loc.F("python.chosen", said, path));
            ShowPage();
        };
        return new StackPanel { Orientation = Orientation.Horizontal, Children = { install, choose } };
    }

    internal void Notice(string text, FAInfoBarSeverity severity = FAInfoBarSeverity.Success)
    {
        _notice.Message = text;
        _notice.Severity = severity;
        _notice.IsOpen = true;
    }

    private void ShowPage()
    {
        _content.Content = _page switch
        {
            "generate" => GeneratePage(),
            "library" => _openMap != null ? MapPage(_openMap) : LibraryPage(),
            "settings" => SettingsPage(),
            "about" => AboutPage(),
            _ => HomePage(),
        };
    }

    // ---- Home -----------------------------------------------------------------------------------------------

    private Control HomePage()
    {
        var p = new StackPanel { Spacing = 8 };
        p.Children.Add(Ui.Title(Loc.T("home.title")));
        p.Children.Add(Ui.Text(Loc.T("home.lead"), 15, 0.85));
        p.Children.Add(Ui.Section(Loc.T("home.status")));
        var (clientOk, exe) = Settings.CheckClient(S.ClientDir);
        p.Children.Add(new FAInfoBar
        {
            IsOpen = true, IsClosable = false,
            Severity = clientOk ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Warning,
            Message = clientOk ? Loc.F("home.client.ok", exe) : Loc.T("home.client.missing"),
        });
        var engine = File.Exists(Path.Combine(Settings.ProgramDir, "engine", "pipeline.exe"));
        p.Children.Add(new FAInfoBar
        {
            IsOpen = true, IsClosable = false,
            Severity = engine ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Informational,
            Message = engine ? Loc.T("home.engine.ok") : Loc.T("home.engine.missing"),
        });
        // brief 10 (D2): the map's checks need Python - said before the first run, not after it; and missing, the Studio
        // offers to install it or to be shown where it is (the PO, 06.10)
        var python = Engine.Python != null;
        var checks = Engine.Repo != null;
        var pyBar = new FAInfoBar
        {
            IsOpen = true, IsClosable = false,
            Severity = python && checks ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Warning,
            Message = !python ? Loc.T("home.python.missing") : !checks ? Loc.T("home.checks.missing") : Loc.T("home.checks.ok"),
        };
        if (!python)
            pyBar.ActionButton = PythonButtons(pyBar);
        p.Children.Add(pyBar);
        p.Children.Add(new FAInfoBar
        {
            IsOpen = true, IsClosable = false, Severity = FAInfoBarSeverity.Informational,
            Message = Loc.F("home.maps", Library.Scan(S).Count),
        });
        var buttons = new WrapPanel { Margin = new Thickness(0, 16, 0, 0) };
        var gen = Ui.Button("home.go.generate", "home.go.generate.tip", FASymbol.Play, accent: true);
        gen.Click += (_, _) => Go("generate");
        var lib = Ui.Button("home.go.library", "home.go.library.tip", FASymbol.Library);
        lib.Click += (_, _) => Go("library");
        var set = Ui.Button("home.go.settings", "home.go.settings.tip", FASymbol.Settings);
        set.Click += (_, _) => Go("settings");
        foreach (var b in new[] { gen, lib, set })
        {
            b.Margin = new Thickness(0, 0, 8, 8);
            buttons.Children.Add(b);
        }
        p.Children.Add(buttons);
        return Ui.Page(p);
    }

    // ---- Generate (P2): the options, then the run's live view -----------------------------------------------

    private Control GeneratePage()
    {
        var g = Generation.Current;
        if (g != null)
        {
            _runView ??= new GenerationView(() =>
            {
                Generation.Current = null;
                _runView = null;
                ShowPage();
            }, name =>
            {
                _page = "library";
                _openMap = Library.Scan(S).FirstOrDefault(m => m.Name == name);
                Rebuild();
            });
            UpdateRun(g);
            // row 410 (the PO 05.10, the Studio vanished): the view kept for the run is still the child of the page
            // it was last shown on - back on this page it was given to a second one, «The Control already has a
            // parent», and the window died with the generation in it
            if (_runView.Parent is Decorator old)
                old.Child = null;
            return Ui.FillPage(_runView);
        }
        _runView = null;
        var p = new StackPanel { Spacing = 4 };
        p.Children.Add(Ui.Title(Loc.T("gen.title")));
        // row 410: no base is put in by itself any more - a base nobody ticked became THE base (q2dm1, 05.10)
        _chosen.RemoveAll(d => !Engine.Donors().Contains(d));
        KeepBases();
        var missing = Generation.Missing(S, _chosen.FirstOrDefault() ?? "q2dm1");
        if (missing != null)
            p.Children.Add(new FAInfoBar
            {
                IsOpen = true, IsClosable = false, Severity = FAInfoBarSeverity.Warning,
                Title = Loc.T("gen.cannot"), Message = missing, Margin = new Thickness(0, 0, 0, 12),
            });
        // row 404: a generation another Studio is carrying is running, not interrupted - and not to be resumed here
        foreach (var (_, req, _, attempts) in Generation.RunningElsewhere(S).Take(3))
            p.Children.Add(new FAInfoBar
            {
                IsOpen = true, IsClosable = false, Severity = FAInfoBarSeverity.Informational,
                Title = Loc.F("gen.live.title", req.Name),
                Message = Loc.F("gen.live.text", req.Fidelity, req.Seed, attempts),
                Margin = new Thickness(0, 0, 0, 8),
            });
        // P5: a generation stopped part way (a crash, the program closed) is resumed from where it was
        foreach (var (runDir, req, when, attempts) in Generation.Interrupted(S).Take(3))
        {
            // row 411: a run whose steps never reached the disk is said so - nothing to resume from
            if (!Generation.KeptCheckpoints(runDir))
            {
                p.Children.Add(new FAInfoBar
                {
                    IsOpen = true, IsClosable = false, Severity = FAInfoBarSeverity.Informational,
                    Title = Loc.F("gen.interrupted.title", req.Name),
                    Message = Loc.F("gen.interrupted.nocheckpoints", when.ToString("g"), req.Fidelity, req.Seed, attempts),
                    ActionButton = DeleteButton(runDir, req.Name),
                    Margin = new Thickness(0, 0, 0, 8),
                });
                continue;
            }
            var resume = Ui.Button("gen.interrupted.resume", "gen.interrupted.resume.tip", FASymbol.Play, accent: true);
            var drop = DeleteButton(runDir, req.Name);
            resume.IsEnabled = missing == null;
            resume.Click += (_, _) =>
            {
                try
                {
                    Generation.Resume(S, runDir);
                }
                catch (Exception ex)
                {
                    Notice(ex.Message, FAInfoBarSeverity.Error);
                    return;
                }
                ShowPage();
            };
            p.Children.Add(new FAInfoBar
            {
                IsOpen = true, IsClosable = false, Severity = FAInfoBarSeverity.Informational,
                Title = Loc.F("gen.interrupted.title", req.Name),
                Message = Loc.F("gen.interrupted.text", when.ToString("g"), req.Fidelity, req.Seed, attempts),
                ActionButton = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Children = { resume, drop } },
                Margin = new Thickness(0, 0, 0, 8),
            });
        }
        p.Children.Add(DonorPicker());
        var fidelity = new FANumberBox
        {
            Minimum = 1, Maximum = 100, Value = S.Fidelity, SmallChange = 1, LargeChange = 10, MinWidth = 140,
            SpinButtonPlacementMode = FANumberBoxSpinButtonPlacementMode.Inline,
        };
        p.Children.Add(Ui.Setting("gen.fidelity", "gen.fidelity.desc", FASymbol.Target, fidelity, "gen.fidelity.tip"));
        var seed = new FANumberBox
        {
            Minimum = 0, Maximum = 2147483647, Value = S.Seed, SmallChange = 1, MinWidth = 140,
            SpinButtonPlacementMode = FANumberBoxSpinButtonPlacementMode.Inline,
        };
        p.Children.Add(Ui.Setting("gen.seed", "gen.seed.desc", FASymbol.Refresh, seed, "gen.seed.tip"));
        // row 410: the form keeps what was set - every redraw (ticking a base is one) rebuilt it to 20 / 42 /
        // mg_20_42 / every family; the name typed by hand is kept until the page is left
        var name = new TextBox { MinWidth = 200, Text = _formName ?? $"mg_{S.Fidelity}_{S.Seed}" };
        name.TextChanged += (_, _) =>
        {
            if (!_suggesting)
                _formName = name.Text;
        };
        void SuggestName()
        {
            S.Fidelity = (int)Math.Clamp(double.IsNaN(fidelity.Value) ? 20 : fidelity.Value, 1, 100);
            S.Seed = (long)(double.IsNaN(seed.Value) ? 0 : seed.Value);
            KeepForm();
            if (_formName != null)
                return;
            _suggesting = true;
            name.Text = $"mg_{S.Fidelity}_{S.Seed}";
            _suggesting = false;
        }
        fidelity.ValueChanged += (_, _) => SuggestName();
        seed.ValueChanged += (_, _) => SuggestName();
        p.Children.Add(Ui.Setting("gen.name", "gen.name.desc", FASymbol.Edit, name, "gen.name.tip"));
        var families = new FASettingsExpander
        {
            Header = Loc.T("gen.families"), Description = Loc.T("gen.families.desc"),
            IconSource = Ui.Icon(FASymbol.Repair), IsExpanded = true, Margin = new Thickness(0, 0, 0, 4),
        }.Tip("gen.families.tip");
        var boxes = new Dictionary<string, CheckBox>();
        foreach (var fam in Families.Keys)
        {
            var box = new CheckBox { IsChecked = !S.SkipFamilies.Contains(fam) }.Tip($"fam.{fam}.tip");
            boxes[fam] = box;
            var key = fam;
            box.IsCheckedChanged += (_, _) =>
            {
                S.SkipFamilies.Remove(key);
                if (box.IsChecked != true)
                    S.SkipFamilies.Add(key);
                KeepForm();
            };
            families.Items.Add(new FASettingsExpanderItem
            {
                Content = Loc.T($"fam.{fam}"), Description = Loc.T($"fam.{fam}.tip"), Footer = box,
            }.Tip($"fam.{fam}.tip"));
        }
        p.Children.Add(families);
        p.Children.Add(CreativePicker());
        var saveMap = new ToggleSwitch { IsChecked = S.SaveMapSource };
        saveMap.IsCheckedChanged += (_, _) =>
        {
            S.SaveMapSource = saveMap.IsChecked == true;
            S.Save();
        };
        p.Children.Add(Ui.Setting("gen.save_map", "gen.save_map.desc", FASymbol.Document, saveMap, "gen.save_map.tip"));
        var autoCovers = new ToggleSwitch { IsChecked = S.AutoCovers };
        autoCovers.IsCheckedChanged += (_, _) =>
        {
            S.AutoCovers = autoCovers.IsChecked == true;
            S.Save();
        };
        p.Children.Add(Ui.Setting("set.auto_covers", "set.auto_covers.desc", FASymbol.Camera, autoCovers, "set.auto_covers.tip"));
        var start = Ui.Button("gen.start", "gen.start.tip", FASymbol.Play, accent: true);
        start.IsEnabled = missing == null;
        start.Margin = new Thickness(0, 16, 0, 0);
        start.Click += (_, _) =>
        {
            var mapName = new string((name.Text ?? "").Trim().ToLowerInvariant()
                                     .Where(c => char.IsAsciiLetterOrDigit(c) || c == '_').ToArray());
            if (mapName.Length == 0)
            {
                Notice(Loc.T("gen.name.bad"), FAInfoBarSeverity.Warning);
                return;
            }
            var skip = Families.Where(kv => boxes[kv.Key].IsChecked != true).SelectMany(kv => kv.Value).ToList();
            if (_chosen.Count == 0)
            {
                Notice(Loc.T("gen.donors.none"), FAInfoBarSeverity.Warning);
                return;
            }
            var fid = (int)Math.Clamp(double.IsNaN(fidelity.Value) ? 20 : fidelity.Value, 1, 100);
            var sd = (long)(double.IsNaN(seed.Value) ? 0 : seed.Value);
            // one base: the map; several: a map from each, one after another - or ONE map from the first with rooms
            // offered from the others
            var requests = _chosen.Count == 1 || _graftMode
                ? new List<GenerationRequest>
                  {
                      new(mapName, _chosen[0], fid, sd, skip, S.SaveMapSource, Grafts: _chosen.Skip(1).ToList(),
                          Options: S.Options),
                  }
                : _chosen.Select(d => new GenerationRequest($"{mapName}_{d}", d, fid, sd, skip, S.SaveMapSource,
                                                         Options: S.Options)).ToList();
            try
            {
                Generation.Queue.Clear();
                Generation.Queue.AddRange(requests.Skip(1));
                Generation.Start(requests[0], S);
                _formName = null;
            }
            catch (Exception ex)
            {
                Notice(ex.Message, FAInfoBarSeverity.Error);
                return;
            }
            ShowPage();
        };
        var startHost = new Border { Child = start, HorizontalAlignment = HorizontalAlignment.Left }.Tip("gen.start.tip");
        p.Children.Add(startHost);
        return Ui.Page(p);
    }

    /// <summary>
    /// Row 399: the bases. Every map in the engine's donors folder, ticked or not (the order of ticking kept, the first
    /// is the base); «Выбрать карты…» adds any Quake II .bsp - several at once - by the system's file dialog. With
    /// more than one ticked, a map from each one after another, or one map with rooms offered from the others.
    /// </summary>
    private Control DonorPicker()
    {
        var expander = new FASettingsExpander
        {
            Header = Loc.T("gen.donor"), Description = Loc.T("gen.donor.desc"), IconSource = Ui.Icon(FASymbol.Map),
            IsExpanded = true, Margin = new Thickness(0, 0, 0, 4),
        }.Tip("gen.donor.tip");
        var pick = Ui.Button("gen.donors.pick", "gen.donors.pick.tip", FASymbol.OpenFile);
        pick.Click += async (_, _) =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = Loc.T("gen.donors.pick"),
                AllowMultiple = true,
                FileTypeFilter = new[] { new FilePickerFileType("Quake II BSP") { Patterns = new[] { "*.bsp" } } },
            });
            var added = new List<string>();
            foreach (var f in files)
            {
                var path = f.TryGetLocalPath();
                if (path == null)
                    continue;
                try
                {
                    var name = Engine.AddDonor(path);
                    if (!_chosen.Contains(name))
                        _chosen.Add(name);
                    added.Add(name);
                }
                catch (Exception ex)
                {
                    Notice(ex.Message, FAInfoBarSeverity.Warning);
                }
            }
            if (added.Count > 0)
            {
                Notice(Loc.F("gen.donors.added", string.Join(", ", added)));
                ShowPage();
            }
        };
        expander.Footer = pick;
        foreach (var d in Engine.Donors())
        {
            var box = new CheckBox { IsChecked = _chosen.Contains(d) }.Tip("gen.donors.box.tip");
            box.IsCheckedChanged += (_, _) =>
            {
                if (box.IsChecked == true && !_chosen.Contains(d))
                    _chosen.Add(d);
                else if (box.IsChecked != true)
                    _chosen.Remove(d);
                ShowPage();
            };
            var role = _chosen.IndexOf(d) switch
            {
                -1 => "",
                0 => Loc.T(_chosen.Count > 1 && _graftMode ? "gen.donors.role.base" : "gen.donors.role.chosen"),
                _ => Loc.T(_graftMode ? "gen.donors.role.rooms" : "gen.donors.role.chosen"),
            };
            expander.Items.Add(new FASettingsExpanderItem
            {
                Content = d,
                Description = (d == "q2dm1" ? Loc.T("gen.donors.proven") : Loc.T("gen.donors.trial")) + (role.Length > 0 ? " — " + role : ""),
                Footer = box,
            }.Tip("gen.donors.box.tip"));
        }
        if (_chosen.Count > 1)
        {
            var mode = new ComboBox
            {
                MinWidth = 260,
                ItemsSource = new[] { Loc.T("gen.donors.mode.each"), Loc.T("gen.donors.mode.graft") },
                SelectedIndex = _graftMode ? 1 : 0,
            }.Tip("gen.donors.mode.tip");
            mode.SelectionChanged += (_, _) =>
            {
                _graftMode = mode.SelectedIndex == 1;
                KeepBases();
                ShowPage();
            };
            expander.Items.Add(new FASettingsExpanderItem
            {
                Content = Loc.T("gen.donors.mode"),
                Description = _graftMode ? Loc.F("gen.donors.mode.graft.desc", _chosen[0], string.Join(", ", _chosen.Skip(1)))
                                         : Loc.F("gen.donors.mode.each.desc", _chosen.Count),
                Footer = mode,
            }.Tip("gen.donors.mode.tip"));
        }
        return expander;
    }

    /// <summary>The Studio's families of change and the generator's edit kinds each one holds.</summary>
    private static readonly Dictionary<string, string[]> Families = new()
    {
        ["dig"] = new[] { "dig", "span" },        /* row 405: a bridge is new building, as a dug room is */
        ["flood"] = new[] { "flood" },
        ["window"] = new[] { "window" },
        ["lift"] = new[] { "stairs-to-lift" },
        ["reshape"] = new[] { "reshape-room", "push-wall", "relevel", "widen-connector", "turn-bundle", "open-connector" },
        ["items"] = new[] { "swap-item", "move-spawn" },
    };

    // ---- Library ---------------------------------------------------------------------------------------------

    private Control LibraryPage()
    {
        var p = new StackPanel { Spacing = 8 };
        p.Children.Add(Ui.Title(Loc.T("lib.title")));
        var bar = new WrapPanel();
        var add = Ui.Button("lib.add", "lib.add.tip", FASymbol.Add, accent: true);
        add.Click += async (_, _) => await ImportMap();
        var refresh = Ui.Button("lib.refresh", "lib.refresh.tip", FASymbol.Refresh);
        refresh.Click += (_, _) => ShowPage();
        var folder = Ui.Button("lib.open_folder", "lib.open_folder.tip", FASymbol.OpenFolder);
        folder.Click += (_, _) => OpenInExplorer(S.BspPath);
        var missingCovers = Ui.Button("lib.covers_missing", "lib.covers_missing.tip", FASymbol.Camera);
        missingCovers.Click += (_, _) =>
        {
            var without = Library.Scan(S).Where(x => x.CoverPath == null && !_coverQueue.Contains(x.Name))
                                         .Select(x => x.Name).ToList();
            if (without.Count == 0)
            {
                Notice(Loc.T("lib.covers_missing.none"));
                return;
            }
            if (!Settings.CheckClient(S.ClientDir).ok)
            {
                Notice(Loc.T("lib.to_client.noclient"), FAInfoBarSeverity.Warning);
                return;
            }
            _coverQueue.AddRange(without);
            Notice(Loc.F("lib.covers_missing.queued", string.Join(", ", _coverQueue)), FAInfoBarSeverity.Informational);
        };
        foreach (var b in new[] { add, refresh, folder, missingCovers })
        {
            b.Margin = new Thickness(0, 0, 8, 8);
            bar.Children.Add(b);
        }
        p.Children.Add(bar);
        var maps = Library.Scan(S);
        if (maps.Count == 0)
        {
            p.Children.Add(Ui.Text(Loc.T("lib.empty"), 15, 0.75));
            return Ui.Page(p);
        }
        // the PO, 05.10: the tiles across the whole window, their size by Ctrl+wheel or the slider; the top stays put
        var wall = new TileWall { BaseWidth = 240 };
        foreach (var m in maps)
            wall.Children.Add(TileWall.Card(MapCard(m)));
        LibraryWall = wall;
        return TilePage.Build(p, wall, wall, 120, () => S.LibraryTile, v =>
        {
            S.LibraryTile = (int)v;
            KeepView();
        });
    }

    /// <summary>The library's tiles as last built (the window test sizes them).</summary>
    internal TileWall? LibraryWall { get; private set; }

    /* the tile sizes saved a moment after the last change, not on every step of a wheel or a slider */
    private Avalonia.Threading.DispatcherTimer? _keepView;

    private void KeepView()
    {
        if (SelfTesting)
            return;
        _keepView ??= new Avalonia.Threading.DispatcherTimer(TimeSpan.FromMilliseconds(600), Avalonia.Threading.DispatcherPriority.Background, (_, _) =>
        {
            _keepView?.Stop();
            S.Save();
        });
        _keepView.Stop();
        _keepView.Start();
    }

    private Control MapCard(MapEntry m)
    {
        var cover = CoverImage(m, 240, 135);
        var text = new StackPanel
        {
            Margin = new Thickness(12, 8, 12, 10),
            Children =
            {
                new TextBlock { Text = m.Name, FontSize = 16, FontWeight = FontWeight.SemiBold },
                new TextBlock { Text = Loc.F("lib.made", m.Made.ToString("g")), FontSize = 12, Opacity = 0.7 },
            },
        };
        var card = new Button
        {
            Padding = new Thickness(0),
            Width = 240,
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Content = new StackPanel { Children = { cover, text } },
        }.Tip("lib.card.tip");
        card.Click += (_, _) =>
        {
            _openMap = m;
            ShowPage();
        };
        return card;
    }

    private Control CoverImage(MapEntry m, double width, double height)
    {
        if (m.CoverPath != null)
        {
            try
            {
                // a cover is the client's own screenshot: decoded once, wide enough to stay sharp on a big tile
                if (TilePage.Picture(m.CoverPath) is { } bmp)
                    return new Image { Source = bmp, Width = width, Height = height, Stretch = Stretch.UniformToFill };
            }
            catch (Exception) { }
        }
        // no cover yet: a calm tile with the map's name
        var hue = (uint)(m.Name.GetHashCode() & 0x3F);
        return new Border
        {
            Width = width, Height = height,
            Background = new LinearGradientBrush
            {
                StartPoint = new RelativePoint(0, 0, RelativeUnit.Relative),
                EndPoint = new RelativePoint(1, 1, RelativeUnit.Relative),
                GradientStops =
                {
                    new GradientStop(Color.FromRgb((byte)(40 + hue), 52, 74), 0),
                    new GradientStop(Color.FromRgb(24, (byte)(30 + hue / 2), 44), 1),
                },
            },
            Child = new StackPanel
            {
                VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Center,
                Children =
                {
                    new TextBlock { Text = m.Name, FontSize = 22, FontWeight = FontWeight.SemiBold, Foreground = Brushes.White,
                                    HorizontalAlignment = HorizontalAlignment.Center },
                    new TextBlock { Text = Loc.T("lib.nocover"), FontSize = 12, Foreground = Brushes.White, Opacity = 0.6,
                                    HorizontalAlignment = HorizontalAlignment.Center },
                },
            },
        };
    }

    private Control MapPage(MapEntry m)
    {
        var p = new StackPanel { Spacing = 8 };
        var back = Ui.Button("lib.back", "lib.back.tip", FASymbol.Back);
        back.Click += (_, _) =>
        {
            _openMap = null;
            ShowPage();
        };
        p.Children.Add(back);
        p.Children.Add(Ui.Title(m.Name));
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,24,*") };
        var cover = CoverImage(m, 420, 236);
        var coverButton = new Button { Content = cover, Padding = new Thickness(0), Background = Brushes.Transparent }
            .Tip("shots.open.tip");
        coverButton.Click += (_, _) => OpenShots(m, m.CoverPath);
        Grid.SetColumn(coverButton, 0);
        top.Children.Add(coverButton);
        var facts = new StackPanel { Spacing = 6 };
        facts.Children.Add(Ui.Text(Loc.F("lib.made", m.Made.ToString("f")), 14, 0.8));
        facts.Children.Add(Ui.Text(Loc.F("lib.size", Ui.Size(m.Bytes)), 14, 0.8));
        var actions = new WrapPanel { Margin = new Thickness(0, 12, 0, 0) };
        var toClient = Ui.Button("lib.to_client", "lib.to_client.tip", FASymbol.Download, accent: true);
        toClient.Click += (_, _) =>
        {
            if (!Settings.CheckClient(S.ClientDir).ok)
            {
                Notice(Loc.T("lib.to_client.noclient"), FAInfoBarSeverity.Warning);
                return;
            }
            try
            {
                Notice(Loc.F("lib.to_client.done", Library.CopyToClient(S, m)));
            }
            catch (Exception ex)
            {
                Notice(ex.Message, FAInfoBarSeverity.Error);
            }
        };
        var play = Ui.Button("lib.play", "lib.play.tip", FASymbol.Play);
        play.Click += (_, _) => LaunchClient(() =>
        {
            _play = Client.Play(S, m);
            Notice(Loc.F("lib.play.running", m.Name), FAInfoBarSeverity.Informational);
        });
        var shoot = Ui.Button("cover.make", "cover.make.tip", FASymbol.Camera);
        shoot.Click += (_, _) => LaunchClient(() =>
        {
            _cover = Covers.Start(m, S);
            Notice(Loc.F("cover.running", m.Name), FAInfoBarSeverity.Informational);
        });
        /* S-3: a cover from a picture of the user's own */
        var fromFile = Ui.Button("cover.file", "cover.file.tip", FASymbol.Image);
        fromFile.Click += async (_, _) =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = Loc.T("cover.file"),
                AllowMultiple = false,
                FileTypeFilter = new[] { new FilePickerFileType("PNG / JPG") { Patterns = new[] { "*.png", "*.jpg", "*.jpeg" } } },
            });
            var path = files.Count > 0 ? files[0].TryGetLocalPath() : null;
            if (path == null)
                return;
            try
            {
                Library.AddCover(S, m.Name, path);
                _openMap = Library.Scan(S).FirstOrDefault(x => x.Name == m.Name) ?? m;
                Notice(Loc.T("cover.file.done"));
                ShowPage();
            }
            catch (Exception ex)
            {
                Notice(ex.Message, FAInfoBarSeverity.Error);
            }
        };
        var show = Ui.Button("lib.show_file", "lib.show_file.tip", FASymbol.OpenFolder);
        show.Click += (_, _) => OpenInExplorer(Path.GetDirectoryName(m.BspPath) ?? S.BspPath);
        foreach (var c in new Control[] { toClient, play, shoot, fromFile, show })
        {
            c.Margin = new Thickness(0, 0, 8, 8);
            actions.Children.Add(c);
        }
        facts.Children.Add(actions);
        Grid.SetColumn(facts, 2);
        top.Children.Add(facts);
        p.Children.Add(top);
        /*
         * S-2: every shot of the map - the PO, 05.10: tiles across the whole width, sized by Ctrl+wheel or the
         * slider, and a click shows the shot as big as the window (where it can be made the cover)
         */
        TileWall? shots = null;
        if (m.Shots.Count > 0)
        {
            p.Children.Add(Ui.Text(Loc.T("cover.strip"), 13, 0.75));
            shots = new TileWall { BaseWidth = 160, Gap = 8 };
            foreach (var shot in m.Shots)
            {
                Control thumb = TilePage.Picture(shot) is { } bmp
                    ? new Image { Source = bmp, Width = 156, Height = 88, Stretch = Stretch.UniformToFill }
                    : new TextBlock { Text = Path.GetFileName(shot), Width = 156, Height = 88 };
                var chosen = string.Equals(shot, m.CoverPath, StringComparison.OrdinalIgnoreCase);
                var button = new Button
                {
                    Content = thumb, Padding = new Thickness(0), Width = 160,
                    BorderThickness = new Thickness(chosen ? 2 : 1),
                    BorderBrush = chosen ? Brushes.MediumPurple : Brushes.Gray,
                }.Tip("shots.open.tip");
                var path = shot;
                button.Click += (_, _) => OpenShots(m, path);
                shots.Children.Add(TileWall.Card(button));
            }
            p.Children.Add(shots);
        }
        ShotsWall = shots;
        p.Children.Add(Ui.Section(Loc.T("lib.desc")));
        /* S-5: a map made elsewhere says so, and names its base when its checks report does */
        var described = m.Description ?? (m.Base != null ? Loc.F("lib.desc.imported.base", m.Base) : Loc.T("lib.desc.imported"));
        p.Children.Add(Ui.Text(described, 14, m.Description == null ? 0.7 : 1.0));
        p.Children.Add(Ui.Section(Loc.T("lib.gates")));
        if (m.Gates.Count == 0)
            p.Children.Add(Ui.Text(Loc.T("lib.gates.none"), 14, 0.7));
        foreach (var (pass, what) in m.Gates)
        {
            p.Children.Add(new StackPanel
            {
                Orientation = Orientation.Horizontal, Spacing = 8,
                Children =
                {
                    new FASymbolIcon { Symbol = pass ? FASymbol.Accept : FASymbol.Cancel, FontSize = 14,
                                       Foreground = pass ? Brushes.SeaGreen : Brushes.IndianRed },
                    new TextBlock { Text = $"{Loc.Gate(what)} — {(pass ? Loc.T("lib.gates.pass") : Loc.T("lib.gates.fail"))}",
                                    TextWrapping = TextWrapping.Wrap, MaxWidth = 900 },
                },
            });
        }
        // the map's page: back and its name stay put; the shots across the whole width, sized like the library's
        var (backControl, nameControl) = (p.Children[0], p.Children[1]);
        p.Children.RemoveRange(0, 2);
        var head = new StackPanel { Spacing = 8, Children = { backControl, nameControl } };
        if (shots == null)
            return new DockPanel { Children = { Docked(head), Ui.Page(p) } };
        return TilePage.Build(head, p, shots, 80, () => S.ShotTile, v =>
        {
            S.ShotTile = (int)v;
            KeepView();
        });
    }

    private static Control Docked(Control top)
    {
        var b = new Border { Padding = new Thickness(36, 28, 36, 0), Child = top };
        DockPanel.SetDock(b, Dock.Top);
        return b;
    }

    /// <summary>A map's shots as last built (the window test sizes them).</summary>
    internal TileWall? ShotsWall { get; private set; }

    /// <summary>The viewer open now (the window test turns it).</summary>
    internal ShotViewer? Viewer { get; private set; }

    /// <summary>A map's shots in the viewer, starting at `at`; a shot made the cover there becomes the cover.</summary>
    private async void OpenShots(MapEntry m, string? at)
    {
        if (m.Shots.Count == 0 || Viewer != null)
            return;
        var start = Math.Max(0, m.Shots.ToList().FindIndex(x => string.Equals(x, at, StringComparison.OrdinalIgnoreCase)));
        Viewer = new ShotViewer(m.Shots, start, m.CoverPath, this);
        try
        {
            await Viewer.ShowDialog(this);
        }
        finally
        {
            var chosen = Viewer.Chosen;
            Viewer = null;
            if (chosen != null)
            {
                Library.ChooseCover(S, m.Name, chosen);
                _openMap = Library.Scan(S).FirstOrDefault(x => x.Name == m.Name) ?? m;
                Notice(Loc.T("cover.chosen"));
                ShowPage();
            }
        }
    }

    private async Task ImportMap()
    {
        var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
        {
            Title = Loc.T("lib.add"),
            AllowMultiple = true,
            FileTypeFilter = new[] { new FilePickerFileType("Quake II BSP") { Patterns = new[] { "*.bsp" } } },
        });
        foreach (var f in files)
        {
            var path = f.TryGetLocalPath();
            if (path == null)
                continue;
            try
            {
                Notice(Loc.F("lib.added", Library.Import(S, path)));
            }
            catch (Exception ex)
            {
                Notice(ex.Message, FAInfoBarSeverity.Error);
            }
        }
        ShowPage();
    }

    // ---- Settings --------------------------------------------------------------------------------------------

    private Control SettingsPage()
    {
        var p = new StackPanel { Spacing = 4 };
        p.Children.Add(Ui.Title(Loc.T("set.title")));

        p.Children.Add(Ui.Section(Loc.T("set.look")));
        var language = new ComboBox { MinWidth = 180, ItemsSource = new[] { "Русский", "English" },
                                      SelectedIndex = S.Language == "en" ? 1 : 0 };
        language.SelectionChanged += (_, _) =>
        {
            var lang = language.SelectedIndex == 1 ? "en" : "ru";
            if (lang == S.Language)
                return;
            S.Language = lang;
            Loc.Language = lang;
            S.Save();
            Rebuild();
        };
        p.Children.Add(Ui.Setting("set.language", "set.language.desc", FASymbol.Globe, language, "set.language.tip"));
        var themes = new[] { "system", "light", "dark" };
        var theme = new ComboBox { MinWidth = 180, ItemsSource = themes.Select(t => Loc.T($"theme.{t}")).ToArray(),
                                   SelectedIndex = Math.Max(0, Array.IndexOf(themes, S.Theme)) };
        theme.SelectionChanged += (_, _) =>
        {
            S.Theme = themes[Math.Max(0, theme.SelectedIndex)];
            App.ApplyTheme(S.Theme);
            S.Save();
        };
        p.Children.Add(Ui.Setting("set.theme", "set.theme.desc", FASymbol.Image, theme, "set.theme.tip"));
        /* the PO, 2026-10-03: «выбор раздела по умолчанию, который открывается при старте программы» */
        var starts = new[] { "home", "generate", "library" };
        var start = new ComboBox { MinWidth = 180, ItemsSource = starts.Select(t => Loc.T($"nav.{t}")).ToArray(),
                                   SelectedIndex = Math.Max(0, Array.IndexOf(starts, S.StartPage)) };
        start.SelectionChanged += (_, _) =>
        {
            S.StartPage = starts[Math.Max(0, start.SelectedIndex)];
            S.Save();
        };
        p.Children.Add(Ui.Setting("set.start_page", "set.start_page.desc", FASymbol.Home, start, "set.start_page.tip"));

        p.Children.Add(Ui.Section(Loc.T("set.client")));
        var (clientOk, _) = Settings.CheckClient(S.ClientDir);
        var clientText = new TextBlock
        {
            Text = string.IsNullOrEmpty(S.ClientDir) ? Loc.T("set.client.none")
                 : clientOk ? S.ClientDir : $"{S.ClientDir} — {Loc.T("set.client.bad")}",
            VerticalAlignment = VerticalAlignment.Center, MaxWidth = 420, TextTrimming = TextTrimming.CharacterEllipsis,
            Margin = new Thickness(0, 0, 8, 0),
        };
        var chooseClient = Ui.Button("set.choose", "set.choose.tip", FASymbol.OpenFolder);
        chooseClient.Click += async (_, _) =>
        {
            var dir = await PickFolder(Loc.T("set.client"));
            if (dir == null)
                return;
            S.ClientDir = dir;
            S.Save();
            if (!Settings.CheckClient(dir).ok)
                Notice(Loc.T("set.client.bad"), FAInfoBarSeverity.Warning);
            ShowPage();
        };
        p.Children.Add(Ui.Setting("set.client", "set.client.desc", FASymbol.Games,
                                  new StackPanel { Orientation = Orientation.Horizontal, Children = { clientText, chooseClient } },
                                  "set.client.tip"));
        // the PO, 06.10: Python for the checks - where it is, chosen or installed from here
        var pyNow = Engine.Python;
        var pyText = new TextBlock
        {
            Text = pyNow ?? Loc.T("set.python.none"), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 420,
            TextTrimming = TextTrimming.CharacterEllipsis, Margin = new Thickness(0, 0, 8, 0),
        };
        p.Children.Add(Ui.Setting("set.python", "set.python.desc", FASymbol.Code,
                                  new StackPanel { Orientation = Orientation.Horizontal, Children = { pyText, PythonButtons(null) } },
                                  "set.python.tip"));

        p.Children.Add(Ui.Section(Loc.T("set.folders")));
        p.Children.Add(FolderSetting("set.bsp", () => S.BspDir, v => S.BspDir = v, @"data\bsp"));
        p.Children.Add(FolderSetting("set.maps", () => S.MapsDir, v => S.MapsDir = v, @"data\maps"));
        p.Children.Add(FolderSetting("set.temp", () => S.TempDir, v => S.TempDir = v, "temp"));

        p.Children.Add(Ui.Section(Loc.T("set.cpu")));
        p.Children.Add(Ui.Setting("set.cpu_day", "set.cpu_day.desc", FASymbol.Clock,
                                  Number(S.CpuDayShare, 5, 100, v => S.CpuDayShare = v), "set.cpu_day.tip"));
        p.Children.Add(Ui.Setting("set.cpu_night", "set.cpu_night.desc", FASymbol.Clock,
                                  Number(S.CpuNightShare, 5, 100, v => S.CpuNightShare = v), "set.cpu_night.tip"));
        var hours = new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 8,
            Children =
            {
                Number(S.DayFrom, 0, 23, v => S.DayFrom = v).Tip("set.day_from.tip"),
                new TextBlock { Text = "—", VerticalAlignment = VerticalAlignment.Center },
                Number(S.DayTo, 0, 24, v => S.DayTo = v).Tip("set.day_to.tip"),
            },
        };
        p.Children.Add(Ui.Setting("set.day_hours", "set.day_hours.desc", FASymbol.CalendarDay, hours, "set.day_from.tip"));
        var prios = new[] { "idle", "below_normal", "normal" };
        var prio = new ComboBox { MinWidth = 180, ItemsSource = prios.Select(x => Loc.T($"prio.{x}")).ToArray(),
                                  SelectedIndex = Math.Max(0, Array.IndexOf(prios, S.Priority)) };
        prio.SelectionChanged += (_, _) =>
        {
            S.Priority = prios[Math.Max(0, prio.SelectedIndex)];
            S.Save();
        };
        p.Children.Add(Ui.Setting("set.priority", "set.priority.desc", FASymbol.Filter, prio, "set.priority.tip"));

        // row 411 (Fable's brief 8): the generator's working files in memory, and its steps on the disk
        p.Children.Add(Ui.Section(Loc.T("set.memory")));
        p.Children.Add(Ui.Setting("set.memory_percent", "set.memory_percent.desc", FASymbol.Library,
                                  Number(S.MemoryPercent, 0, 90, v => S.MemoryPercent = v), "set.memory_percent.tip"));
        var keep = new ToggleSwitch { IsChecked = S.KeepCheckpoints };
        keep.IsCheckedChanged += (_, _) =>
        {
            S.KeepCheckpoints = keep.IsChecked == true;
            S.Save();
        };
        p.Children.Add(Ui.Setting("set.keep_checkpoints", "set.keep_checkpoints.desc", FASymbol.Save, keep,
                                  "set.keep_checkpoints.tip"));
        UpdateRows(p);
        p.Children.Add(Ui.Text(Loc.F("set.saved", Settings.IniPath), 12, 0.6));
        return Ui.Page(p);
    }

    private FANumberBox Number(int value, int min, int max, Action<int> set)
    {
        var box = new FANumberBox
        {
            Minimum = min, Maximum = max, Value = value, SmallChange = 1, MinWidth = 120,
            SpinButtonPlacementMode = FANumberBoxSpinButtonPlacementMode.Inline,
        };
        box.ValueChanged += (_, e) =>
        {
            if (double.IsNaN(e.NewValue))
                return;
            set((int)Math.Round(e.NewValue));
            S.Save();
        };
        return box;
    }

    private Control FolderSetting(string key, Func<string> get, Action<string> set, string fallback)
    {
        var text = new TextBlock
        {
            Text = Settings.Resolve(get()), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 380,
            TextTrimming = TextTrimming.CharacterEllipsis, Margin = new Thickness(0, 0, 8, 0),
        };
        var choose = Ui.Button("set.choose", "set.choose.tip", FASymbol.OpenFolder);
        choose.Click += async (_, _) =>
        {
            var dir = await PickFolder(Loc.T(key));
            if (dir == null)
                return;
            set(dir);
            S.Save();
            S.EnsureFolders();
            ShowPage();
        };
        var reset = Ui.Button("set.default", "set.default.tip");
        reset.Margin = new Thickness(8, 0, 0, 0);
        reset.Click += (_, _) =>
        {
            set(fallback);
            S.Save();
            S.EnsureFolders();
            ShowPage();
        };
        return Ui.Setting(key, key + ".desc", FASymbol.Folder,
                          new StackPanel { Orientation = Orientation.Horizontal, Children = { text, choose, reset } },
                          "set.choose.tip");
    }

    private async Task<string?> PickFolder(string title)
    {
        var picked = await StorageProvider.OpenFolderPickerAsync(new FolderPickerOpenOptions { Title = title });
        return picked.Count > 0 ? picked[0].TryGetLocalPath() : null;
    }

    // ---- About -----------------------------------------------------------------------------------------------

    private Control AboutPage()
    {
        var p = new StackPanel { Spacing = 8 };
        p.Children.Add(Ui.Title(Loc.T("about.title")));
        var version = Versions.Said(typeof(MainWindow).Assembly.GetName().Version);
        p.Children.Add(Ui.Text(Loc.F("about.version", version), 15, 0.8));
        p.Children.Add(Ui.Text(Loc.T("about.what"), 14));
        p.Children.Add(UpdateButton());     // brief 10 (D3)
        // the PO, 05.10: the versions with what each brought, newest first
        p.Children.Add(Ui.Section(Loc.T("about.history")));
        foreach (var v in Versions.All)
        {
            p.Children.Add(new TextBlock
            {
                Text = Loc.F("about.history.version", v.Number, v.Date), FontSize = 14, FontWeight = FontWeight.SemiBold,
                Margin = new Thickness(0, 6, 0, 0),
            });
            foreach (var line in Loc.Language == "en" ? v.En : v.Ru)
                p.Children.Add(Ui.Text("• " + line, 13, 0.85));
        }
        p.Children.Add(Ui.Section(Loc.T("about.folder")));
        p.Children.Add(Ui.Text(Settings.ProgramDir, 13, 0.8));
        p.Children.Add(Ui.Section(Loc.T("about.ini")));
        p.Children.Add(Ui.Text(Settings.IniPath, 13, 0.8));
        return Ui.Page(p);
    }

    /// <summary>
    /// `--selftest`: each page in each language and theme, built and laid out at the window's size without the
    /// window being shown; a missing string shows as [key]. One line per page, PASS or FAIL.
    /// </summary>
    public static string SelfTest()
    {
        // row 410: the pages it builds tick bases - never into the PO's settings (05.10: his ini came out with all four)
        SelfTesting = true;
        var b = new System.Text.StringBuilder();
        var keepLang = Loc.Language;
        var keepTheme = App.Settings.Theme;
        /*
         * Row 404: two unfinished runs, one carried by a live Studio (this one) and one whose Studio is gone - the
         * first is running, never offered to resume, and refuses a resume; the second is interrupted. Both stay in
         * the temp folder while the pages are built, so the Generate page shows both cards in each language.
         */
        var live = Path.Combine(App.Settings.TempPath, $"selftest_live_{Environment.ProcessId}");
        var dead = Path.Combine(App.Settings.TempPath, $"selftest_dead_{Environment.ProcessId}");
        try
        {
            using var me = System.Diagnostics.Process.GetCurrentProcess();
            foreach (var (dir, owner) in new[] { (live, $"{me.Id}\n{me.StartTime.ToUniversalTime().Ticks}\n"),
                                                 (dead, $"{me.Id}\n{me.StartTime.ToUniversalTime().Ticks + 1}\n") })
            {
                Directory.CreateDirectory(Path.Combine(dir, "job"));
                File.WriteAllText(Path.Combine(dir, "request.txt"),
                                  $"name={Path.GetFileName(dir)}\ndonor=q2dm1\nfidelity=20\nseed=42\n");
                File.WriteAllText(Path.Combine(dir, "job", "ledger.txt"), "# q2mg fidelity 20 seed 42\n");
                File.WriteAllText(Path.Combine(dir, "job", "progress.txt"), "PROGRESS stage=baseline elapsed=0\n");
                File.WriteAllText(Path.Combine(dir, "owner.txt"), owner);
            }
            bool Listed(List<(string runDir, GenerationRequest request, DateTime when, int attempts)> l, string d) =>
                l.Any(x => string.Equals(x.runDir, d, StringComparison.OrdinalIgnoreCase));
            var running = Generation.RunningElsewhere(App.Settings);
            var stopped = Generation.Interrupted(App.Settings);
            var refused = false;
            try
            {
                Generation.Resume(App.Settings, live);
            }
            catch (InvalidOperationException)
            {
                refused = true;
            }
            b.AppendLine(Listed(running, live) && !Listed(stopped, live) && refused
                         ? "PASS a run a live Studio carries is shown as running and refuses a resume"
                         : $"FAIL a run a live Studio carries is shown as running and refuses a resume -- running "
                           + $"{Listed(running, live)}, interrupted {Listed(stopped, live)}, refused {refused}");
            b.AppendLine(Listed(stopped, dead) && !Listed(running, dead)
                         ? "PASS a run whose Studio is gone is interrupted"
                         : $"FAIL a run whose Studio is gone is interrupted -- interrupted {Listed(stopped, dead)}");
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the run owner check: {ex.GetType().Name}: {ex.Message}");
        }
        /* row 404: a generation's CPUs are performance cores only, by day and by night (the PO's P-cores) */
        {
            var fast = NativeJob.PerformanceCpus();
            ulong pmask = 0;
            foreach (var i in fast)
                pmask |= 1UL << i;
            var day = NativeJob.Mask((int)Math.Floor(Environment.ProcessorCount * App.Settings.CpuDayShare / 100.0));
            var night = NativeJob.Mask((int)Math.Floor(Environment.ProcessorCount * App.Settings.CpuNightShare / 100.0));
            var ok = fast.Count == 0 || ((day & ~pmask) == 0 && (night & ~pmask) == 0 && day != 0 && night != 0);
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} a generation runs on performance cores only -- "
                         + $"{fast.Count} of {Environment.ProcessorCount}, day {day:X}, night {night:X}");
        }
        foreach (var lang in new[] { "ru", "en" })
        foreach (var theme in new[] { "light", "dark" })
        {
            Loc.Language = lang;
            App.ApplyTheme(theme);
            var w = new MainWindow();
            var maps = Library.Scan(App.Settings);
            foreach (var page in new[] { "home", "generate", "generate-each", "generate-graft", "library", "map", "settings", "about" })
            {
                try
                {
                    // row 399: the Generate page with several bases ticked, in both modes
                    if (page.StartsWith("generate-"))
                    {
                        var donors = Engine.Donors();
                        if (donors.Count < 2)
                        {
                            b.AppendLine($"SKIP {lang} {theme} {page}: fewer than two bases in the engine");
                            continue;
                        }
                        w._chosen.Clear();
                        w._chosen.AddRange(donors);
                        w._graftMode = page == "generate-graft";
                    }
                    w._page = page == "map" ? "library" : page.StartsWith("generate") ? "generate" : page;
                    w._openMap = page == "map" ? maps.FirstOrDefault() : null;
                    if (page == "map" && w._openMap == null)
                    {
                        b.AppendLine($"SKIP {lang} {theme} {page}: no map in the library");
                        continue;
                    }
                    w.Rebuild();
                    w.Measure(new Size(1180, 780));
                    w.Arrange(new Rect(0, 0, 1180, 780));
                    var missing = Missing(w._content.Content as Control);
                    /* S-1: every check of the library's maps has its plain words */
                    if (page == "map")
                        foreach (var mm in maps)
                            foreach (var (_, what) in mm.Gates)
                                if (!Loc.Has(Loc.GateKey(what)))
                                    missing.Add($"[{Loc.GateKey(what)}]");
                    b.AppendLine(missing.Count == 0 ? $"PASS {lang} {theme} {page}"
                                                    : $"FAIL {lang} {theme} {page}: missing {string.Join(", ", missing)}");
                }
                catch (Exception ex)
                {
                    b.AppendLine($"FAIL {lang} {theme} {page}: {ex.GetType().Name}: {ex.Message}");
                }
            }
        }
        Loc.Language = keepLang;
        App.ApplyTheme(keepTheme);
        foreach (var dir in new[] { live, dead })
            try
            {
                Directory.Delete(dir, true);
            }
            catch (IOException)
            {
            }
        return b.ToString();
    }

    /*
     * S-6 (brief 4): on a Russian page a text with Latin words and no Cyrillic at all is English the user was not
     * meant to read - the checks' tool lines were one. Names are not words: a map's or a texture's name, a path, a
     * number, a version are passed (letters, digits and _ - . / \ : only, or the program's own name).
     */
    private static readonly System.Text.RegularExpressions.Regex Cyrillic = new(@"\p{IsCyrillic}");
    private static readonly System.Text.RegularExpressions.Regex Wordy = new(@"[A-Za-z]{3,}[ ,;!?]+[A-Za-z]{2,}");

    private static bool EnglishOnRussian(string text) =>
        Loc.Language == "ru" && !Cyrillic.IsMatch(text) && Wordy.IsMatch(text)
        && !text.StartsWith(Loc.T("app.title"), StringComparison.Ordinal);

    private static List<string> Missing(Control? root)
    {
        var found = new List<string>();
        void Walk(object? o)
        {
            switch (o)
            {
                case TextBlock t when t.Text != null && t.Text.StartsWith('[') && t.Text.EndsWith(']'):
                    found.Add(t.Text);
                    break;
                case TextBlock t when t.Text != null && EnglishOnRussian(t.Text):
                    found.Add($"[english: {t.Text}]");
                    break;
                case FASettingsExpander e:
                    if (e.Header is string h && h.StartsWith('['))
                        found.Add(h);
                    if (e.Header is string he && EnglishOnRussian(he))
                        found.Add($"[english: {he}]");
                    if (e.Description is string de && EnglishOnRussian(de))
                        found.Add($"[english: {de}]");
                    Walk(e.Footer);
                    foreach (var i in e.Items)
                        Walk(i);
                    break;
                case FASettingsExpanderItem item:
                    if (item.Content is string ic && EnglishOnRussian(ic))
                        found.Add($"[english: {ic}]");
                    if (item.Description is string id && EnglishOnRussian(id))
                        found.Add($"[english: {id}]");
                    Walk(item.Footer);
                    break;
            }
            if (o is Panel p)
                foreach (var c in p.Children)
                    Walk(c);
            else if (o is ContentControl cc)
                Walk(cc.Content);
            else if (o is Decorator d)
                Walk(d.Child);
        }
        Walk(root);
        return found;
    }

    private static void OpenInExplorer(string dir)
    {
        try
        {
            Directory.CreateDirectory(dir);
            Process.Start(new ProcessStartInfo("explorer.exe", $"\"{dir}\"") { UseShellExecute = true });
        }
        catch (Exception) { }
    }
}
