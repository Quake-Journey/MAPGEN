using System.Diagnostics;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using Avalonia.Platform.Storage;
using Avalonia.VisualTree;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// The shell (phase P1): navigation - Home, Generate, Maps, Settings, About - themes, RU/EN, a tooltip on every
/// element, the ini, folders and the client chosen by dialogs, the map library with its detail card.
/// The whole window is rebuilt from the string table when the language changes.
/// </summary>
public sealed partial class MainWindow : Window
{
    private readonly SideNav _nav;
    private readonly ContentControl _content = new();
    private readonly FAInfoBar _notice = new() { IsOpen = false, IsClosable = true, Margin = new Thickness(40, 12, 40, 0) };
    /* the PO, 11.10: the run over every page but its own */
    private readonly RunStrip _strip = new();
    private Generation? _stripSeen;
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
        Icon = App.Icon();
        _chosen.AddRange(S.Bases.Distinct());
        _graftMode = S.GraftMode;
        var dock = new DockPanel();
        DockPanel.SetDock(_strip, Dock.Top);
        dock.Children.Add(_strip);
        DockPanel.SetDock(_notice, Dock.Top);
        dock.Children.Add(_notice);
        dock.Children.Add(_content);
        _strip.Open += () => Go("generate");
        _nav = new SideNav(dock);
        _nav.Chosen += page =>
        {
            if (page == _page && _openMap == null)
                return;
            if (page != "generate")
                _formName = null;
            _page = page;
            _openMap = null;
            _nav.Select(page);
            ShowPage();
        };
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
        {
            _strip.IsVisible = false;
            return;
        }
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
        UpdateStrip(g);
    }

    /// <summary>
    /// The strip over the pages: shown while a run goes on and, once it is over, until its page has been seen; never on
    /// the run's page itself.
    /// </summary>
    private void UpdateStrip(Generation? g)
    {
        if (g != null && _page == "generate" && !g.Running)
            _stripSeen = g;
        var show = g != null && _page != "generate" && (g.Running || !ReferenceEquals(_stripSeen, g));
        _strip.IsVisible = show;
        if (!show || !Monitor.TryEnter(g!.Sync, 20))
            return;
        try
        {
            _strip.Update(g);
        }
        finally
        {
            Monitor.Exit(g.Sync);
        }
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

    /// <summary>Set by `--startup-test`: the window is built and shown off screen, nothing asked of the network.</summary>
    public static bool StartupTesting { get; set; }

    private string? _formName;
    private bool _suggesting;

    /// <summary>The form's likeness, seed, families and options into the settings (never from the self-test).</summary>
    /// <summary>A line of what a button got (press, release, click) into ui_clicks.txt beside the program, kept
    /// small - the evidence for a click that «did not take».</summary>
    internal static void ClickLog(string what)
    {
        try
        {
            var f = Path.Combine(Settings.ProgramDir, "ui_clicks.txt");
            if (File.Exists(f) && new FileInfo(f).Length > 65536)
                File.Delete(f);
            File.AppendAllText(f, $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} {what}\n");
        }
        catch (Exception)
        {
            // a log that cannot be written is no reason to stop
        }
    }

    private void KeepForm()
    {
        if (!SelfTesting)
            S.Save();
    }

    private static readonly int[] CountChoices = { 0, 1, 2, 3, 4, 6, 8 };
    /* the map's size, percent of the base's area - the PO, 10.10: «бегунок ... в пределах 10-1000% от оригинала» */
    private static readonly int[] WarpSizes = { 10, 25, 50, 75, 100, 125, 150, 200, 300, 400, 600, 800, 1000 };

    /// <summary>
    /// The base's frame, changed before the first edit (the PO, 10.10: «хочется именно менять донора и уже к нему
    /// пристраивать»; «размеры карты могут меняться как угодно»): the map's size and how unequally its parts stretch.
    /// Open by default - it is the first thing a generation does to the base.
    /// </summary>
    private Control FramePicker()
    {
        var ex = new OptionGroup("gen.warp", "gen.warp.desc", FASymbol.FullScreen, Look.TealC, "gen.warp.tip");
        void SliderRow(string key, int steps, int index, Func<int, string> show, Action<int> set)
        {
            var slider = new Slider
            {
                Minimum = 0, Maximum = steps - 1, Value = index, Width = 220, SmallChange = 1, LargeChange = 1,
                IsSnapToTickEnabled = true, TickFrequency = 1, VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(8, 0, 8, 0),
            };
            var said = new TextBlock { MinWidth = 64, VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(16, 0, 0, 0) };
            said.Text = show(index);
            slider.PropertyChanged += (_, e) =>
            {
                if (e.Property != Avalonia.Controls.Primitives.RangeBase.ValueProperty)
                    return;
                set((int)slider.Value);
                said.Text = show((int)slider.Value);
                KeepForm();
            };
            var footer = new StackPanel { Orientation = Orientation.Horizontal, Children = { slider, said } };
            ex.Add(Loc.T(key), Loc.T($"{key}.tip"), footer, $"{key}.tip");
        }
        var o = S.Options;
        var sizeAt = Array.IndexOf(WarpSizes, o.WarpSize);
        if (sizeAt < 0)
            sizeAt = Array.IndexOf(WarpSizes, 100);
        SliderRow("gen.warp.size", WarpSizes.Length, sizeAt, i => Loc.F("gen.warp.size.value", WarpSizes[i]),
                  i => S.Options = S.Options with { WarpSize = WarpSizes[i] });
        SliderRow("gen.warp.shape", 11, Math.Clamp(o.WarpShape / 10, 0, 10), i => Loc.F("gen.warp.shape.value", i * 10),
                  i => S.Options = S.Options with { WarpShape = i * 10 });
        // the parts slid sideways against each other: rooms of one part stand beside the next one's moved over
        SliderRow("gen.warp.shift", 11, Math.Clamp(o.WarpShift / 10, 0, 10), i => Loc.F("gen.warp.shift.value", i * 10),
                  i => S.Options = S.Options with { WarpShift = i * 10 });
        // the base turned or mirrored whole: «Как в основе», 90°, 180°, 270°, mirrored, or by the seed
        var turns = new[] { 0, 1, 2, 3, 4, 8 };
        var turnBox = new ComboBox
        {
            MinWidth = 220, SelectedIndex = Math.Max(0, Array.IndexOf(turns, o.WarpTurn)),
            ItemsSource = new[] { "gen.warp.turn.none", "gen.warp.turn.90", "gen.warp.turn.180", "gen.warp.turn.270",
                                  "gen.warp.turn.mirror", "gen.warp.turn.seed" }.Select(Loc.T).ToArray(),
        }.Tip("gen.warp.turn.tip");
        turnBox.SelectionChanged += (_, _) =>
        {
            S.Options = S.Options with { WarpTurn = turns[Math.Max(0, turnBox.SelectedIndex)] };
            KeepForm();
        };
        ex.Add(Loc.T("gen.warp.turn"), Loc.T("gen.warp.turn.tip"), turnBox, "gen.warp.turn.tip");
        // the ceilings above the highest place a player stands: 100 (as they are) .. 200 %
        SliderRow("gen.warp.height", 11, Math.Clamp((o.WarpHeight - 100) / 10, 0, 10), i => Loc.F("gen.warp.height.value", 100 + i * 10),
                  i => S.Options = S.Options with { WarpHeight = 100 + i * 10 });
        return ex.Card;
    }
    private static readonly string[] Liquids =
        { "", "water-lava", "water-slime", "lava-water", "slime-water", "lava-slime", "slime-lava", "mix" };

    /// <summary>
    /// Row 410 (the PO, 05.10: «какие еще параметры добавить ... чтобы получать больше вариаций творчества»): the
    /// plan's own counts and sizes and the liquids, each «По умолчанию» first - the likeness decides.
    /// </summary>
    private (Control rooms, Control liquids, Control basis, Control ruin) CreativePicker()
    {
        // the PO, 12.10: by group, each a card with its name - what is built anew, the liquids, what is changed in the
        // base's own rooms, the ruin
        var rooms = new OptionGroup("gen.grp.rooms", "gen.grp.rooms.desc", FASymbol.Library, Look.VioletC);
        var liquids = new OptionGroup("gen.grp.liquids", "gen.grp.liquids.desc", FASymbol.Globe, Look.BlueC);
        var basis = new OptionGroup("gen.grp.base", "gen.grp.base.desc", FASymbol.Repair, Look.AmberC);
        var ruin = new OptionGroup("gen.grp.ruin", "gen.grp.ruin.desc", FASymbol.Important, Look.RedC);
        var ex = rooms;
        void Row(string key, string[] items, int index, Action<int> set)
        {
            var box = new ComboBox { MinWidth = 260, ItemsSource = items, SelectedIndex = Math.Max(0, index) }.Tip($"{key}.tip");
            box.SelectionChanged += (_, _) =>
            {
                set(Math.Max(0, box.SelectedIndex));
                KeepForm();
            };
            ex.Add(Loc.T(key), Loc.T($"{key}.tip"), box, $"{key}.tip");
        }
        string[] Counts(int[] values) => values.Select(v => v == 0 ? Loc.T("gen.default") : v.ToString()).ToArray();
        var o = S.Options;
        Row("gen.opt.digs", Counts(CountChoices), Array.IndexOf(CountChoices, o.Digs), i => S.Options = S.Options with { Digs = CountChoices[i] });
        Row("gen.opt.annexes", Counts(CountChoices), Array.IndexOf(CountChoices, o.Annexes), i => S.Options = S.Options with { Annexes = CountChoices[i] });
        Row("gen.opt.annex_size", new[] { "gen.default", "gen.size.small", "gen.size.medium", "gen.size.large", "gen.size.halls", "gen.size.niches" }.Select(Loc.T).ToArray(),
            o.AnnexSize, i => S.Options = S.Options with { AnnexSize = i });
        Row("gen.opt.storeys", Counts(CountChoices), Array.IndexOf(CountChoices, o.Storeys), i => S.Options = S.Options with { Storeys = CountChoices[i] });
        Row("gen.opt.spans", Counts(CountChoices), Array.IndexOf(CountChoices, o.Spans), i => S.Options = S.Options with { Spans = CountChoices[i] });
        Row("gen.opt.halls", Counts(CountChoices), Array.IndexOf(CountChoices, o.Halls), i => S.Options = S.Options with { Halls = CountChoices[i] });
        // the PO, 05.10: «замена воды на лаву или кислоту и наоборот ... и визуал меняем и свойства»
        ex = liquids;
        Row("gen.opt.liquids", Liquids.Select(l => Loc.T(l.Length == 0 ? "gen.default.liquids" : $"gen.liquids.{l}")).ToArray(),
            Array.IndexOf(Liquids, o.Liquids), i => S.Options = S.Options with { Liquids = Liquids[i] });
        // row 412, the PO: «украшения на стенах ... Можно также это вынести в параметры»
        ex = basis;
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
            ex.Add(Loc.T(key), Loc.T($"{key}.tip"), footer, $"{key}.tip");
        }
        ex = liquids;
        LiquidRow("gen.opt.new_water", o.NewWater, v => S.Options = S.Options with { NewWater = v });
        LiquidRow("gen.opt.new_slime", o.NewSlime, v => S.Options = S.Options with { NewSlime = v });
        LiquidRow("gen.opt.new_lava", o.NewLava, v => S.Options = S.Options with { NewLava = v });
        // brief 11 D1, the PO: «пристройки-лестницы», 0..10, default 0 - «Нет», not «По умолчанию»
        ex = rooms;
        Row("gen.opt.stairways", Enumerable.Range(0, 11).Select(n => n == 0 ? Loc.T("gen.stairways.none") : n.ToString()).ToArray(),
            o.Stairways, i => S.Options = S.Options with { Stairways = i });
        // brief 15 D6, the PO: «почему вы не меняете форму стандартного уровня» - the base's own walls moved in,
        // turned, terraces raised along them: «По умолчанию» (by the likeness), «Нет», 1..16
        ex = basis;
        Row("gen.opt.remodels",
            new[] { Loc.T("gen.default"), Loc.T("gen.remodels.none") }.Concat(Enumerable.Range(1, 16).Select(n => n.ToString())).ToArray(),
            o.Remodels + 1, i => S.Options = S.Options with { Remodels = i - 1 });
        // brief 15 D6, the PO: «ящики впереди другой формы, другого размера, ширины, длины»
        Row("gen.opt.blocks",
            new[] { Loc.T("gen.default"), Loc.T("gen.remodels.none") }.Concat(Enumerable.Range(1, 16).Select(n => n.ToString())).ToArray(),
            o.Blocks + 1, i => S.Options = S.Options with { Blocks = i - 1 });
        // brief 15 D6, the PO: «пол опускать или приподнимать, делать в нём проходы и лестницы»
        Row("gen.opt.floor_shifts",
            new[] { Loc.T("gen.default"), Loc.T("gen.remodels.none") }.Concat(Enumerable.Range(1, 12).Select(n => n.ToString())).ToArray(),
            o.FloorShifts + 1, i => S.Options = S.Options with { FloorShifts = i - 1 });
        // brief 15 D6, the PO: «лестницу не угловую, а полу-угловую, полу-закруглённую»
        Row("gen.opt.stair_reshapes",
            new[] { Loc.T("gen.default"), Loc.T("gen.remodels.none") }.Concat(Enumerable.Range(1, 8).Select(n => n.ToString())).ToArray(),
            o.StairReshapes + 1, i => S.Options = S.Options with { StairReshapes = i - 1 });
        // brief 11 D2, the PO: «разрушаемость» 0..100, default 0 - a slider, no «По умолчанию»: 0 is the default
        {
            var slider = new Slider
            {
                /* the PO, 07.10: past 100 % up to a hundred times its ruin («мелкие карты ... до 100 раз больше») -
                   the slider's right half is the factor, ×1 to ×100 on a log scale; the map takes what its format holds */
                // the PO, 12.10: under its words the slider runs the card's width, what it says on its right
                Minimum = 0, Maximum = 200, Value = DestructionToSlider(o.Destruction), SmallChange = 1,
                LargeChange = 10, HorizontalAlignment = HorizontalAlignment.Stretch,
                IsSnapToTickEnabled = true, TickFrequency = 1, VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(0, 0, 12, 0),
            };
            var said = new TextBlock { MinWidth = 130, VerticalAlignment = VerticalAlignment.Center };
            void Show()
            {
                var pct = SliderToDestruction(slider.Value);
                said.Text = pct == 0 ? Loc.T("gen.destruction.none")
                          : pct > 100 ? $"{pct} % (×{pct / 100.0:0.#})" : $"{pct} %";
            }
            slider.PropertyChanged += (_, e) =>
            {
                if (e.Property != Avalonia.Controls.Primitives.RangeBase.ValueProperty)
                    return;
                S.Options = S.Options with { Destruction = SliderToDestruction(slider.Value) };
                Show();
                KeepForm();
            };
            Show();
            var across = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
            across.Children.Add(slider);
            Grid.SetColumn(said, 1);
            across.Children.Add(said);
            ruin.AddUnder(Loc.T("gen.opt.destruction"), Loc.T("gen.opt.destruction.tip"), across, "gen.opt.destruction.tip");
        }
        return (rooms.Card, liquids.Card, basis.Card, ruin.Card);
    }

    /// <summary>The destruction slider: 0..100 the percent as it was, 100..200 the factor ×1..×100 (log).</summary>
    private static int SliderToDestruction(double v) =>
        v <= 100 ? (int)Math.Round(v) : (int)Math.Round(100 * Math.Pow(100, (v - 100) / 100.0) / 10.0) * 10;

    private static double DestructionToSlider(int pct) =>
        pct <= 100 ? pct : 100 + 100 * Math.Log(pct / 100.0) / Math.Log(100);

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
        /* the PO, 08.10: several games side by side are no trouble - a map is played whatever else is open */
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

    /// <summary>
    /// The PO, 11.10: a name already taken, asked before the run starts - write over it, correct the name, or not
    /// start. A run going on or queued under the name cannot be written over: then only the name or not starting.
    /// 1 write over, 2 correct the name, 0 not start. The window test writes over.
    /// </summary>
    private async Task<int> AskTaken(string names, string said, bool busy)
    {
        if (UiTesting)
            return busy ? 2 : 1;
        var dialog = new FAContentDialog
        {
            Title = Loc.F("gen.taken.title", names),
            Content = new TextBlock
            {
                Text = said + "\n\n" + Loc.T(busy ? "gen.taken.question.busy" : "gen.taken.question"),
                TextWrapping = TextWrapping.Wrap, MaxWidth = 520,
            },
            PrimaryButtonText = busy ? "" : Loc.T("gen.taken.overwrite"),
            IsPrimaryButtonEnabled = !busy,
            SecondaryButtonText = Loc.T("gen.taken.rename"),
            CloseButtonText = Loc.T("gen.taken.cancel"),
            DefaultButton = FAContentDialogButton.Secondary,
        };
        return await dialog.ShowAsync(this) switch
        {
            FAContentDialogResult.Primary => 1,
            FAContentDialogResult.Secondary => 2,
            _ => 0,
        };
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
        // the PO, 11.10: large signs in colour and large words, lit under the mouse
        _nav.Set(Loc.T("app.title"), new[]
                 {
                     ("home", Loc.T("nav.home"), Loc.T("nav.home.tip"), FASymbol.Home, Look.BlueC, false),
                     ("generate", Loc.T("nav.generate"), Loc.T("nav.generate.tip"), FASymbol.Play, Look.GreenC, false),
                     ("library", Loc.T("nav.library"), Loc.T("nav.library.tip"), FASymbol.Library, Look.AmberC, false),
                     ("settings", Loc.T("nav.settings"), Loc.T("nav.settings.tip"), FASymbol.Settings, Look.VioletC, true),
                     ("about", Loc.T("nav.about"), Loc.T("nav.about.tip"), FASymbol.Help, Look.TealC, true),
                 }, _page);
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
        _nav.Select(_page);
        UpdateStrip(Generation.Current);
    }

    // ---- Home -----------------------------------------------------------------------------------------------

    /// <summary>
    /// The PO, 11.10 («главная страница выглядит как калл ... вставить там что то действительно важное и полезное +
    /// локальные ссылки на открытие документации ... + вводные слова про студию и генератор на пару абзацев»): what the
    /// Studio and its generator are, in two paragraphs; the three ways on - a new map, the maps, the guide; what goes on
    /// now (the run, or the last map made); whether everything is ready; the guide shipped with the program; the steps of
    /// a map in short.
    /// </summary>
    private Control HomePage()
    {
        var version = Versions.Said(typeof(MainWindow).Assembly.GetName().Version);
        var maps = Library.Scan(S);
        var page = new StackPanel { Spacing = 18 };
        page.Children.Add(Look.PageHead(Loc.T("home.title"), Loc.F("home.sub", version)));
        page.Children.Add(Look.Card(new StackPanel
        {
            Spacing = 12, MaxWidth = 1000, HorizontalAlignment = HorizontalAlignment.Left,
            Children =
            {
                new TextBlock { Text = Loc.T("home.intro1"), FontSize = 16, LineHeight = 25, TextWrapping = TextWrapping.Wrap },
                new TextBlock { Text = Loc.T("home.intro2"), FontSize = 16, LineHeight = 25, TextWrapping = TextWrapping.Wrap, Opacity = 0.85 },
                HomeCommunity(),
            },
        }, 24));
        var actions = new Avalonia.Controls.Primitives.UniformGrid { Columns = 3 };
        foreach (var a in new[]
                 {
                     Look.ActionCard(FASymbol.Play, Look.GreenC, Loc.T("home.act.generate"), Loc.T("home.act.generate.desc"), () => Go("generate")),
                     Look.ActionCard(FASymbol.Library, Look.AmberC, Loc.T("home.act.library"), Loc.F("home.act.library.desc", maps.Count), () => Go("library")),
                     Look.ActionCard(FASymbol.Help, Look.BlueC, Loc.T("home.act.guide"), Loc.T("home.act.guide.desc"), () => OpenDoc(GuidePath("html"))),
                 })
        {
            a.Margin = new Thickness(0, 0, 14, 0);
            actions.Children.Add(a);
        }
        page.Children.Add(actions);
        page.Children.Add(Look.Columns(Look.Stack(HomeNow(maps), HomeReady()), Look.Stack(HomeDocs(), HomeSteps())));
        return Look.Page(page, 1500);
    }

    /// <summary>The guide shipped beside the program: doc\MAPGEN_Studio_Guide_RU.html (.docx), in the language chosen.</summary>
    private static string GuidePath(string ext, string? lang = null) =>
        Path.Combine(Settings.ProgramDir, "doc", $"MAPGEN_Studio_Guide_{((lang ?? Loc.Language) == "en" ? "EN" : "RU")}.{ext}");

    private void OpenDoc(string path)
    {
        if (!path.StartsWith("https://") && !File.Exists(path) && !Directory.Exists(path))
        {
            Notice(Loc.F("home.docs.missing", path), FAInfoBarSeverity.Warning);
            return;
        }
        try
        {
            Process.Start(new ProcessStartInfo(path) { UseShellExecute = true });
        }
        catch (Exception ex)
        {
            Notice(ex.Message, FAInfoBarSeverity.Error);
        }
    }

    /// <summary>What goes on now: the run with the way to it, else the last map made with the way to it.</summary>
    private Control HomeNow(List<MapEntry> maps)
    {
        if (Generation.Current is { } g)
        {
            var open = Ui.Button("strip.open", "strip.open.tip", FASymbol.Forward, accent: true);
            open.Click += (_, _) => Go("generate");
            var state = g.Running ? (g.Paused ? Look.AmberC : Look.BlueC) : g.Error.Length > 0 ? Look.RedC : Look.GreenC;
            return Look.Card(new StackPanel
            {
                Spacing = 10,
                Children =
                {
                    Look.CardHead(g.Running ? FASymbol.Play : FASymbol.Accept, state,
                                  Loc.F("home.now.run", g.Request.Name, g.Request.Donor), GenerationView.NowLine(g), open),
                },
            });
        }
        if (maps.Count == 0)
            return Look.Card(Look.CardHead(FASymbol.Map, Look.AmberC, Loc.T("home.now.none"), Loc.T("home.now.none.desc")));
        var m = maps[0];
        var see = Ui.Button("home.now.open", "home.now.open.tip", FASymbol.Forward);
        see.Click += (_, _) =>
        {
            _page = "library";
            _openMap = m;
            Rebuild();
        };
        var cover = CoverImage(m, 300, 169);
        var facts = new StackPanel { Spacing = 8, VerticalAlignment = VerticalAlignment.Center };
        facts.Children.Add(new TextBlock { Text = m.Name, FontSize = 20, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap });
        facts.Children.Add(new TextBlock { Text = Loc.F("lib.made", m.Made.ToString("g")), FontSize = 13, Opacity = 0.7 });
        facts.Children.Add(MapChips(m));
        facts.Children.Add(see);
        var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 18 };
        row.Children.Add(new Border { CornerRadius = new CornerRadius(8), ClipToBounds = true, Child = cover, VerticalAlignment = VerticalAlignment.Top });
        Grid.SetColumn(facts, 1);
        row.Children.Add(facts);
        return Look.Card(new StackPanel
        {
            Spacing = 14,
            Children = { Look.CardHead(FASymbol.Map, Look.AmberC, Loc.T("home.now.last"), Loc.T("home.now.last.desc")), row },
        });
    }

    /// <summary>Whether everything is ready: the game, the generator, Python and the checks - each with what to do.</summary>
    private Control HomeReady()
    {
        var (clientOk, exe) = Settings.CheckClient(S.ClientDir);
        var engine = File.Exists(Path.Combine(Settings.ProgramDir, "engine", "pipeline.exe"));
        var python = Engine.Python != null;
        var checks = Engine.Repo != null;
        Control Line(bool ok, string text, Control? fix = null)
        {
            var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 12, Margin = new Thickness(0, 8, 0, 8) };
            g.Children.Add(new FASymbolIcon { Symbol = ok ? FASymbol.Accept : FASymbol.Important, FontSize = 18,
                                              Foreground = ok ? Look.Green : Look.Amber, VerticalAlignment = VerticalAlignment.Top });
            var words = new StackPanel { Spacing = 8 };
            words.Children.Add(new TextBlock { Text = text, FontSize = 14, TextWrapping = TextWrapping.Wrap });
            if (fix != null)
                words.Children.Add(fix);
            Grid.SetColumn(words, 1);
            g.Children.Add(words);
            return g;
        }
        Control? clientFix = null;
        if (!clientOk)
        {
            var go = Ui.Button("home.go.settings", "home.go.settings.tip", FASymbol.Settings);
            go.Click += (_, _) => Go("settings");
            clientFix = go;
        }
        var all = clientOk && engine && python && checks;
        return Look.Group(all ? FASymbol.Accept : FASymbol.Important, all ? Look.GreenC : Look.AmberC, Loc.T("home.status"),
                          Loc.T(all ? "home.status.all" : "home.status.some"),
                          Line(clientOk, clientOk ? Loc.F("home.client.ok", exe) : Loc.T("home.client.missing"), clientFix),
                          Line(engine, engine ? Loc.T("home.engine.ok") : Loc.T("home.engine.missing")),
                          Line(python && checks, !python ? Loc.T("home.python.missing") : !checks ? Loc.T("home.checks.missing")
                                                                                            : Loc.T("home.checks.ok"),
                               python ? null : PythonButtons(null)));
    }

    /// <summary>A line of the home page's lists: a sign, a name in the accent colour, a line under it.</summary>
    private static Control HomeLink(FASymbol symbol, string text, string desc, Action open)
    {
        var b = new Button
        {
            HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Background = Brushes.Transparent, BorderThickness = new Thickness(0), Padding = new Thickness(8, 8, 8, 8),
            CornerRadius = new CornerRadius(8),
            Content = new Grid
            {
                ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 12,
                Children =
                {
                    new FASymbolIcon { Symbol = symbol, FontSize = 18, Foreground = Look.Blue, VerticalAlignment = VerticalAlignment.Top,
                                       Margin = new Thickness(0, 2, 0, 0) },
                },
            },
        };
        var words = new StackPanel { Spacing = 1 };
        words.Children.Add(new TextBlock { Text = text, FontSize = 14.5, FontWeight = FontWeight.SemiBold, Foreground = Look.Blue });
        words.Children.Add(new TextBlock { Text = desc, FontSize = 12.5, Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        Grid.SetColumn(words, 1);
        ((Grid)b.Content).Children.Add(words);
        b.Click += (_, _) => open();
        return b;
    }

    /// <summary>The guide shipped with the program, in both languages and both forms, and what is new.</summary>
    private Control HomeDocs()
    {
        var other = Loc.Language == "en" ? "ru" : "en";
        Control Link(FASymbol s, string t, string d, Action o) => HomeLink(s, t, d, o);
        return Look.Group(FASymbol.Help, Look.BlueC, Loc.T("home.docs"), Loc.T("home.docs.desc"),
                          Link(FASymbol.Globe, Loc.T("home.docs.html"), Loc.T("home.docs.html.desc"), () => OpenDoc(GuidePath("html"))),
                          Link(FASymbol.Document, Loc.T("home.docs.docx"), Loc.T("home.docs.docx.desc"), () => OpenDoc(GuidePath("docx"))),
                          Link(FASymbol.Globe, Loc.T("home.docs.other"), Loc.T("home.docs.other.desc"), () => OpenDoc(GuidePath("html", other))),
                          Link(FASymbol.Bullets, Loc.T("home.docs.news"), Loc.F("home.docs.news.desc", Versions.Current), () => Go("about")),
                          Link(FASymbol.OpenFolder, Loc.T("home.docs.folder"), Loc.T("home.docs.folder.desc"),
                               () => OpenInExplorer(Path.Combine(Settings.ProgramDir, "doc"))));
    }

    /// <summary>The PO, 12.10: the project's news channel, its community group and its site, opened in the browser.</summary>
    public static readonly (string key, string url, FASymbol symbol)[] Community =
    {
        ("home.link.news", "https://t.me/Q2RTX", FASymbol.Message),
        ("home.link.group", "https://t.me/Q2PROX", FASymbol.People),
        ("home.link.site", "https://q2pro-x.com/", FASymbol.Globe),
    };

    /// <summary>A row under the two paragraphs, seen at once: each link its sign, its name and its address.</summary>
    private Control HomeCommunity()
    {
        var row = new WrapPanel { Margin = new Thickness(-8, 4, 0, 0) };
        foreach (var c in Community)
        {
            var link = HomeLink(c.symbol, Loc.T(c.key), c.url.Replace("https://", "").TrimEnd('/'), () => OpenDoc(c.url));
            ToolTip.SetTip(link, Loc.T(c.key + ".desc"));
            link.MinWidth = 200;
            link.Margin = new Thickness(0, 0, 18, 0);
            row.Children.Add(link);
        }
        return row;
    }

    /// <summary>A map in four steps, in short.</summary>
    private Control HomeSteps()
    {
        Control Step(int n, string text)
        {
            var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 12, Margin = new Thickness(0, 8, 0, 8) };
            g.Children.Add(new Border
            {
                Width = 28, Height = 28, CornerRadius = new CornerRadius(14), Background = Look.Soft(Look.VioletC, 0x40),
                VerticalAlignment = VerticalAlignment.Top,
                Child = new TextBlock { Text = n.ToString(), FontWeight = FontWeight.SemiBold, Foreground = Look.Violet,
                                        HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center },
            });
            var t = new TextBlock { Text = text, FontSize = 14, TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center };
            Grid.SetColumn(t, 1);
            g.Children.Add(t);
            return g;
        }
        return Look.Group(FASymbol.List, Look.VioletC, Loc.T("home.steps"), Loc.T("home.steps.desc"),
                          Step(1, Loc.T("home.step1")), Step(2, Loc.T("home.step2")), Step(3, Loc.T("home.step3")),
                          Step(4, Loc.T("home.step4")));
    }

    /// <summary>A map's chips: its base, how far it went from it, its checks.</summary>
    private static Control MapChips(MapEntry m)
    {
        var chips = new WrapPanel();
        void Add(Border c)
        {
            c.Margin = new Thickness(0, 0, 6, 6);
            chips.Children.Add(c);
        }
        if ((m.Donor ?? m.Base) is { Length: > 0 } donor)
            Add(Look.Chip(Loc.F("lib.chip.base", donor), Look.BlueC, FASymbol.Map));
        if (m.Difference >= 0)
            Add(Look.Chip(Loc.F("lib.chip.diff", m.Difference / 10), m.Target > 0 && m.Difference >= m.Target ? Look.GreenC : Look.VioletC));
        if (m.Gates.Count > 0)
            Add(m.GatesPassed == m.Gates.Count
                    ? Look.Chip(Loc.T("lib.chip.checks.ok"), Look.GreenC, FASymbol.Accept)
                    : Look.Chip(Loc.F("lib.chip.checks.bad", m.Gates.Count - m.GatesPassed), Look.RedC, FASymbol.Cancel));
        return chips;
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
            return Ui.FillPage(_runView, 1800);
        }
        _runView = null;
        // the PO, 11.10: the form as the run's page - its head, cards in two columns, the start always in sight
        var p = new StackPanel { Spacing = 10 };
        p.Children.Add(Look.PageHead(Loc.T("gen.title"), Loc.T("gen.sub")));
        var mapRows = new List<Control>();
        var doneRows = new List<Control>();
        var summary = new TextBlock { FontSize = 14.5, TextWrapping = TextWrapping.Wrap, VerticalAlignment = VerticalAlignment.Center };
        void Summarise() => summary.Text = Loc.F("gen.summary",
                                                 _chosen.Count == 0 ? Loc.T("gen.summary.nobase") : string.Join(", ", _chosen),
                                                 S.Fidelity, S.TimeMinutes, _formName ?? $"mg_{S.Fidelity}_{S.Seed}");
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
            // brief 13 W4: its map made, the checks or the ruin cut short - resumed from the checks, said so
            var afterEngine = Generation.EngineDone(runDir);
            // row 411: a run whose steps never reached the disk is said so - nothing to resume from
            if (!afterEngine && !Generation.KeptCheckpoints(runDir))
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
                Message = afterEngine ? Loc.F("gen.interrupted.after", when.ToString("g"), req.Fidelity, req.Seed)
                                      : Loc.F("gen.interrupted.text", when.ToString("g"), req.Fidelity, req.Seed, attempts),
                ActionButton = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Children = { resume, drop } },
                Margin = new Thickness(0, 0, 0, 8),
            });
        }
        var fidelity = new FANumberBox
        {
            Minimum = 1, Maximum = 100, Value = S.Fidelity, SmallChange = 1, LargeChange = 10, MinWidth = 140,
            SpinButtonPlacementMode = FANumberBoxSpinButtonPlacementMode.Inline,
        };
        mapRows.Add(Ui.Setting("gen.fidelity", "gen.fidelity.desc", FASymbol.Target, fidelity, "gen.fidelity.tip"));
        // the PO, 07.10: «Быстрее ↔ Точнее»; brief 16 D6: the minutes a run may take - 15, 30, 60 or 120
        {
            var speed = new Slider
            {
                Minimum = 0, Maximum = Settings.MinuteSteps.Length - 1, Value = S.Minutes, Width = 220, SmallChange = 1,
                LargeChange = 1, IsSnapToTickEnabled = true, TickFrequency = 1, VerticalAlignment = VerticalAlignment.Center,
                Margin = new Thickness(8, 0, 8, 0),
            };
            /* the PO, 10.10: «Точнеедо 120 мин» - the minutes stood glued to the word, a gap of their own */
            var said = new TextBlock { MinWidth = 150, VerticalAlignment = VerticalAlignment.Center, Opacity = 0.85,
                                       Margin = new Thickness(16, 0, 0, 0) };
            void ShowSpeed() => said.Text = Loc.F("gen.speed.value", S.TimeMinutes);
            speed.PropertyChanged += (_, e) =>
            {
                if (e.Property != Avalonia.Controls.Primitives.RangeBase.ValueProperty)
                    return;
                S.Minutes = (int)speed.Value;
                ShowSpeed();
                KeepForm();
                Summarise();
            };
            ShowSpeed();
            var row = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Children =
                {
                    new TextBlock { Text = Loc.T("gen.speed.fast"), VerticalAlignment = VerticalAlignment.Center },
                    speed,
                    new TextBlock { Text = Loc.T("gen.speed.precise"), VerticalAlignment = VerticalAlignment.Center },
                    said,
                },
            };
            mapRows.Add(Ui.Setting("gen.speed", "gen.speed.desc", FASymbol.Clock, row, "gen.speed.tip"));
        }
        var seed = new FANumberBox
        {
            Minimum = 0, Maximum = 2147483647, Value = S.Seed, SmallChange = 1, MinWidth = 140,
            SpinButtonPlacementMode = FANumberBoxSpinButtonPlacementMode.Inline,
        };
        mapRows.Add(Ui.Setting("gen.seed", "gen.seed.desc", FASymbol.Refresh, seed, "gen.seed.tip"));
        // row 410: the form keeps what was set - every redraw (ticking a base is one) rebuilt it to 20 / 42 /
        // mg_20_42 / every family; the name typed by hand is kept until the page is left
        var name = new TextBox { MinWidth = 200, Text = _formName ?? $"mg_{S.Fidelity}_{S.Seed}" };
        name.TextChanged += (_, _) =>
        {
            if (!_suggesting)
                _formName = name.Text;
            Summarise();
        };
        void SuggestName()
        {
            S.Fidelity = (int)Math.Clamp(double.IsNaN(fidelity.Value) ? 20 : fidelity.Value, 1, 100);
            S.Seed = (long)(double.IsNaN(seed.Value) ? 0 : seed.Value);
            KeepForm();
            Summarise();
            if (_formName != null)
                return;
            _suggesting = true;
            name.Text = $"mg_{S.Fidelity}_{S.Seed}";
            _suggesting = false;
        }
        fidelity.ValueChanged += (_, _) => SuggestName();
        seed.ValueChanged += (_, _) => SuggestName();
        mapRows.Add(Ui.Setting("gen.name", "gen.name.desc", FASymbol.Edit, name, "gen.name.tip"));
        var families = new OptionGroup("gen.families", "gen.families.desc", FASymbol.Repair, Look.PinkC, "gen.families.tip");
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
            families.Add(Loc.T($"fam.{fam}"), Loc.T($"fam.{fam}.tip"), box, $"fam.{fam}.tip");
        }
        var saveMap = new ToggleSwitch { IsChecked = S.SaveMapSource };
        saveMap.IsCheckedChanged += (_, _) =>
        {
            S.SaveMapSource = saveMap.IsChecked == true;
            S.Save();
        };
        doneRows.Add(Ui.Setting("gen.save_map", "gen.save_map.desc", FASymbol.Document, saveMap, "gen.save_map.tip"));
        var autoCovers = new ToggleSwitch { IsChecked = S.AutoCovers };
        autoCovers.IsCheckedChanged += (_, _) =>
        {
            S.AutoCovers = autoCovers.IsChecked == true;
            S.Save();
        };
        doneRows.Add(Ui.Setting("set.auto_covers", "set.auto_covers.desc", FASymbol.Camera, autoCovers, "set.auto_covers.tip"));
        var start = Ui.Button("gen.start", "gen.start.tip", FASymbol.Play, accent: true);
        start.IsEnabled = missing == null;
        start.Padding = new Thickness(28, 11, 28, 11);
        start.FontSize = 16;
        start.Click += async (_, _) =>
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
                      new(mapName, _chosen[0], fid, sd, skip, S.SaveMapSource, MaxAttempts: S.Builds, TimeMinutes: S.TimeMinutes,
                          Grafts: _chosen.Skip(1).ToList(), Options: S.Options),
                  }
                : _chosen.Select(d => new GenerationRequest($"{mapName}_{d}", d, fid, sd, skip, S.SaveMapSource,
                                                         MaxAttempts: S.Builds, Options: S.Options,
                                                         TimeMinutes: S.TimeMinutes)).ToList();
            // the PO, 11.10: a name already taken is asked about first - write over, correct the name, or not start
            var taken = new List<string>();
            var takenSaid = new List<string>();
            var busy = false;
            foreach (var rq in requests)
            {
                var said = Generation.NameTaken(S, rq.Name, out var held);
                if (said.Length == 0)
                    continue;
                taken.Add(rq.Name);
                takenSaid.Add(said);
                busy |= held;
            }
            if (taken.Count > 0)
            {
                var answer = await AskTaken(string.Join(", ", taken), string.Join("\n", takenSaid), busy);
                if (answer == 0)
                    return;
                if (answer == 2)
                {
                    // straight to the name: on the screen, the cursor in it, its text selected
                    name.BringIntoView();
                    name.Focus();
                    name.SelectAll();
                    return;
                }
            }
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
        // the PO, 07.10: «только с третьего раза нажалась кнопка» - the button's tip and its frame's tip (the frame
        // carries one so a DISABLED button still says why) were both open over it; the frame's tip is now there only
        // while the button is disabled. And every press, release and click of it goes to ui_clicks.txt beside the
        // program: should it ever miss again, the file says whether the press reached it
        var startHost = new Border { Child = start, HorizontalAlignment = HorizontalAlignment.Left };
        if (!start.IsEnabled)
            startHost.Tip("gen.start.tip");
        start.AddHandler(Avalonia.Input.InputElement.PointerPressedEvent, (_, _) => ClickLog("start pressed"), Avalonia.Interactivity.RoutingStrategies.Tunnel, true);
        start.AddHandler(Avalonia.Input.InputElement.PointerReleasedEvent, (_, _) => ClickLog("start released"), Avalonia.Interactivity.RoutingStrategies.Tunnel, true);
        start.Click += (_, _) => ClickLog("start clicked");
        // the PO, 12.10: the new map and the finished map beside the bases, where they stay put whatever the list of
        // bases grows to (it scrolls inside its card past eight); the generation's options in two columns under them
        // second edition, the same evening: the bases' card as tall as the two beside it, whatever its list holds (the
        // list scrolls inside it); the options as cards by group, each pair one height
        var top = new ColumnsPanel
        {
            LeftFollowsRight = true,
            Children =
            {
                DonorPicker(),
                Look.Stack(Look.Group(FASymbol.Target, Look.BlueC, Loc.T("gen.card.map"), Loc.T("gen.card.map.desc"), null, mapRows),
                           Look.Group(FASymbol.Save, Look.TealC, Loc.T("gen.card.done"), Loc.T("gen.card.done.desc"), null, doneRows)),
            },
        };
        var creative = CreativePicker();
        p.Children.Add(Look.Stack(top,
                                  Look.Pair(FramePicker(), creative.rooms),
                                  Look.Pair(creative.basis, creative.liquids),
                                  Look.Pair(creative.ruin, families.Card)));
        // the start at the page's foot, in sight however far the page is scrolled: what will be made, and the button
        Summarise();
        var footGrid = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 20 };
        footGrid.Children.Add(summary);
        startHost.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(startHost, 1);
        footGrid.Children.Add(startHost);
        var foot = new Border
        {
            Padding = new Thickness(40, 14, 40, 14), BorderBrush = Look.Line, BorderThickness = new Thickness(0, 1, 0, 0),
            Background = Look.Soft(Color.FromRgb(0x80, 0x80, 0x80), 0x14), Child = footGrid,
        };
        DockPanel.SetDock(foot, Dock.Bottom);
        return new DockPanel { Children = { foot, Look.Page(p) } };
    }

    /// <summary>
    /// Row 399: the bases. Every map in the engine's donors folder, ticked or not (the order of ticking kept, the first
    /// is the base); «Выбрать карты…» adds any Quake II .bsp - several at once - by the system's file dialog. With
    /// more than one ticked, a map from each one after another, or one map with rooms offered from the others.
    /// </summary>
    private Control DonorPicker()
    {
        var rows = new List<Control>();
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
            rows.Add(Look.Row(d, (d == "q2dm1" ? Loc.T("gen.donors.proven") : Loc.T("gen.donors.trial")) + (role.Length > 0 ? " — " + role : ""),
                              box, Loc.T("gen.donors.box.tip")));
        }
        var after = new List<Control>();
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
            after.Add(Look.Row(Loc.T("gen.donors.mode"),
                              _graftMode ? Loc.F("gen.donors.mode.graft.desc", _chosen[0], string.Join(", ", _chosen.Skip(1)))
                                         : Loc.F("gen.donors.mode.each.desc", _chosen.Count), mode, Loc.T("gen.donors.mode.tip")));
        }
        // the PO, 12.10: the card is as tall as the two cards beside it; its list takes what the head and the mode
        // leave and scrolls there. Where it was scrolled to is kept: ticking a base builds the page again.
        var list = new StackPanel { Margin = new Thickness(0, 0, 14, 0) };      // the checkboxes clear of the scroll bar
        Look.Fill(list, rows);
        var scroll = new ScrollViewer
        {
            Content = list, Margin = new Thickness(0, 10, 0, 0),
            VerticalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Auto,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
        };
        var placed = false;
        scroll.LayoutUpdated += (_, _) =>
        {
            if (placed || scroll.Extent.Height <= 0)
                return;
            placed = true;
            scroll.Offset = new Vector(0, Math.Min(_donorScroll, Math.Max(0, scroll.Extent.Height - scroll.Viewport.Height)));
        };
        scroll.ScrollChanged += (_, _) =>
        {
            if (placed)
                _donorScroll = scroll.Offset.Y;
        };
        var dock = new DockPanel();
        var head = Look.CardHead(FASymbol.Map, Look.AmberC, Loc.T("gen.donor"), Loc.T("gen.donor.desc"), pick);
        DockPanel.SetDock(head, Dock.Top);
        dock.Children.Add(head);
        if (after.Count > 0)
        {
            var foot = new StackPanel();
            foot.Children.Add(new Border { Height = 1, Background = Look.Line, Margin = new Thickness(0, 2, 0, 2) });
            Look.Fill(foot, after);
            DockPanel.SetDock(foot, Dock.Bottom);
            dock.Children.Add(foot);
        }
        dock.Children.Add(scroll);
        return Look.Card(dock).Tip("gen.donor.tip");
    }

    private double _donorScroll;

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
        var maps = Library.Scan(S);
        var add = Ui.Button("lib.add", "lib.add.tip", FASymbol.Add, accent: true);
        // the PO, 11.10: the page's head as the others', the maps counted
        p.Children.Add(Look.PageHead(Loc.T("lib.title"), Loc.F("lib.sub", maps.Count, S.BspPath), add));
        var bar = new WrapPanel();
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
        // a name typed narrows the tiles to the maps whose name holds it
        var search = new TextBox { Watermark = Loc.T("lib.search"), Width = 280, Margin = new Thickness(0, 0, 12, 8) }.Tip("lib.search.tip");
        bar.Children.Add(search);
        foreach (var b in new[] { refresh, folder, missingCovers })
        {
            b.Margin = new Thickness(0, 0, 8, 8);
            bar.Children.Add(b);
        }
        p.Children.Add(bar);
        if (maps.Count == 0)
        {
            p.Children.Add(Ui.Text(Loc.T("lib.empty"), 15, 0.75));
            return Ui.Page(p);
        }
        // the PO, 05.10: the tiles across the whole window, their size by Ctrl+wheel or the slider; the top stays put
        var wall = new TileWall { BaseWidth = 240 };
        foreach (var m in maps)
            wall.Children.Add(TileWall.Card(MapCard(m)));
        search.TextChanged += (_, _) =>
        {
            var want = (search.Text ?? "").Trim();
            wall.Children.Clear();
            foreach (var m in maps.Where(x => want.Length == 0 || x.Name.Contains(want, StringComparison.OrdinalIgnoreCase)
                                              || (x.Donor ?? "").Contains(want, StringComparison.OrdinalIgnoreCase)))
                wall.Children.Add(TileWall.Card(MapCard(m)));
        };
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

    /// <summary>
    /// A map's tile (the PO, 11.10): its cover with its base and how far it went from it laid over the picture's corner,
    /// its name large, when it was made and its size, and its checks as a chip - green all passed, red how many failed.
    /// </summary>
    private Control MapCard(MapEntry m)
    {
        var cover = CoverImage(m, 240, 135);
        var over = new WrapPanel { Margin = new Thickness(8), VerticalAlignment = VerticalAlignment.Top };
        if ((m.Donor ?? m.Base) is { Length: > 0 } donor)
            over.Children.Add(Shade(Loc.F("lib.chip.base", donor)));
        if (m.Difference >= 0)
            over.Children.Add(Shade(Loc.F("lib.chip.diff", m.Difference / 10)));
        var picture = new Grid { Children = { cover, over } };
        var checks = m.Gates.Count == 0 ? null
                   : m.GatesPassed == m.Gates.Count ? Look.Chip(Loc.T("lib.chip.checks.ok"), Look.GreenC, FASymbol.Accept)
                   : Look.Chip(Loc.F("lib.chip.checks.bad", m.Gates.Count - m.GatesPassed), Look.RedC, FASymbol.Cancel);
        var line = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), ColumnSpacing = 6 };
        line.Children.Add(new TextBlock { Text = $"{m.Made:dd.MM.yyyy HH:mm} · {Ui.Size(m.Bytes)}", FontSize = 11.5, Opacity = 0.7,
                                          VerticalAlignment = VerticalAlignment.Center, TextTrimming = TextTrimming.CharacterEllipsis });
        if (checks != null)
        {
            checks.Padding = new Thickness(6, 1, 6, 2);
            Grid.SetColumn(checks, 1);
            line.Children.Add(checks);
        }
        var text = new StackPanel
        {
            Margin = new Thickness(12, 8, 12, 10), Spacing = 4,
            Children =
            {
                new TextBlock { Text = m.Name, FontSize = 16, FontWeight = FontWeight.SemiBold, TextTrimming = TextTrimming.CharacterEllipsis },
                line,
            },
        };
        var card = new Button
        {
            Padding = new Thickness(0),
            Width = 240,
            CornerRadius = new CornerRadius(10),
            ClipToBounds = true,
            HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Content = new StackPanel { Children = { picture, text } },
        }.Tip("lib.card.tip");
        card.Click += (_, _) =>
        {
            _openMap = m;
            ShowPage();
        };
        return card;
    }

    /// <summary>A few words over a picture: white on a dark rounded ground, readable on any cover.</summary>
    private static Border Shade(string text) => new()
    {
        Background = new SolidColorBrush(Color.FromArgb(0xb0, 0x10, 0x10, 0x14)), CornerRadius = new CornerRadius(8),
        Padding = new Thickness(7, 2, 7, 3), Margin = new Thickness(0, 0, 5, 5),
        Child = new TextBlock { Text = text, FontSize = 11.5, FontWeight = FontWeight.SemiBold, Foreground = Brushes.White },
    };

    private Control CoverImage(MapEntry m, double width, double height)
    {
        if (m.CoverPath != null)
        {
            try
            {
                // a cover is the client's own screenshot: a small copy twice the tile's width (sharp on a 200 % screen),
                // kept on disk - the whole 7 MB picture held the Studio's start for seconds (the PO, 12.10)
                if (TilePage.Thumb(m.CoverPath, (int)Math.Ceiling(width * 2)) is { } bmp)
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
        p.Children.Add(new StackPanel
        {
            Spacing = 8, Margin = new Thickness(0, 6, 0, 12),
            Children = { new TextBlock { Text = m.Name, FontSize = 30, FontWeight = FontWeight.SemiBold }, MapChips(m) },
        });
        var top = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,24,*") };
        var cover = CoverImage(m, 480, 270);
        var coverButton = new Button { Content = cover, Padding = new Thickness(0), Background = Brushes.Transparent,
                                       CornerRadius = new CornerRadius(12), ClipToBounds = true, VerticalAlignment = VerticalAlignment.Top }
            .Tip("shots.open.tip");
        coverButton.Click += (_, _) => OpenShots(m, m.CoverPath);
        Grid.SetColumn(coverButton, 0);
        top.Children.Add(coverButton);
        var facts = new StackPanel { Spacing = 14 };
        Control Fact(string name, string value)
        {
            var g = new Grid { ColumnDefinitions = new ColumnDefinitions("150,*"), Margin = new Thickness(0, 4, 0, 4) };
            g.Children.Add(new TextBlock { Text = name, FontSize = 13.5, Opacity = 0.65 });
            var v = new TextBlock { Text = value, FontSize = 14, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap };
            Grid.SetColumn(v, 1);
            g.Children.Add(v);
            return g;
        }
        var factRows = new List<Control>
        {
            Fact(Loc.T("lib.fact.made"), m.Made.ToString("f")),
            Fact(Loc.T("lib.fact.size"), Ui.Size(m.Bytes)),
        };
        if ((m.Donor ?? m.Base) is { Length: > 0 } baseName)
            factRows.Add(Fact(Loc.T("lib.fact.base"), baseName));
        if (m.Difference >= 0)
            factRows.Add(Fact(Loc.T("lib.fact.diff"), m.Target > 0 ? Loc.F("lib.fact.diff.of", m.Difference / 10, m.Target / 10)
                                                                    : $"{m.Difference / 10} %"));
        if (m.Gates.Count > 0)
            factRows.Add(Fact(Loc.T("lib.fact.checks"), Loc.F("lib.fact.checks.of", m.GatesPassed, m.Gates.Count)));
        var factCard = new StackPanel();
        foreach (var f in factRows)
            factCard.Children.Add(f);
        facts.Children.Add(Look.Card(factCard));
        var actions = new WrapPanel { Margin = new Thickness(0, 0, 0, 0) };
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
        /* the PO, 07.10: the map for a server in one zip - baseq2/maps and baseq2/textures, everything it needs */
        var zip = Ui.Button("lib.zip", "lib.zip.tip", FASymbol.Save);
        zip.Click += async (_, _) =>
        {
            if (!Settings.CheckClient(S.ClientDir).ok)
            {
                Notice(Loc.T("lib.to_client.noclient"), FAInfoBarSeverity.Warning);
                return;
            }
            // the PO, 07.10: «как пользователь должен про это догадаться?» - he says where it goes, the usual way
            var file = await StorageProvider.SaveFilePickerAsync(new FilePickerSaveOptions
            {
                Title = Loc.T("lib.zip"),
                SuggestedFileName = m.Name + ".zip",
                DefaultExtension = "zip",
                ShowOverwritePrompt = true,
                FileTypeChoices = new[] { new FilePickerFileType("ZIP") { Patterns = new[] { "*.zip" } } },
            });
            var target = file?.TryGetLocalPath();
            if (target == null)
                return;
            zip.IsEnabled = false;
            Notice(Loc.F("lib.zip.running", m.Name), FAInfoBarSeverity.Informational);
            try
            {
                var r = await Task.Run(() => MapZip.Build(S, m, target));
                Notice(Loc.F("lib.zip.done", r.ZipPath, r.Textures, Ui.Size(r.Bytes))
                       + (r.Missing.Count > 0 ? " " + Loc.F("lib.zip.missing", r.Missing.Count,
                                                             string.Join(", ", r.Missing.Take(5))) : ""),
                       r.Missing.Count > 0 ? FAInfoBarSeverity.Warning : FAInfoBarSeverity.Success);
                ShowFileInExplorer(r.ZipPath);
            }
            catch (Exception ex)
            {
                Notice(ex.Message, FAInfoBarSeverity.Error);
            }
            finally
            {
                zip.IsEnabled = true;
            }
        };
        foreach (var c in new Control[] { toClient, play, shoot, fromFile, show, zip })
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
        /* S-5: a map made elsewhere says so, and names its base when its checks report does */
        var described = m.Description ?? (m.Base != null ? Loc.F("lib.desc.imported.base", m.Base) : Loc.T("lib.desc.imported"));
        var descCard = Look.Group(FASymbol.Document, Look.BlueC, Loc.T("lib.desc"), null,
                                  new TextBlock { Text = described, FontSize = 14.5, LineHeight = 22, TextWrapping = TextWrapping.Wrap,
                                                  Opacity = m.Description == null ? 0.7 : 1.0 });
        var gateRows = new List<Control>();
        if (m.Gates.Count == 0)
            gateRows.Add(Ui.Text(Loc.T("lib.gates.none"), 14, 0.7));
        foreach (var (pass, what) in m.Gates)
        {
            var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 10, Margin = new Thickness(0, 4, 0, 4) };
            g.Children.Add(new FASymbolIcon { Symbol = pass ? FASymbol.Accept : FASymbol.Cancel, FontSize = 15,
                                              Foreground = pass ? Look.Green : Look.Red, VerticalAlignment = VerticalAlignment.Top,
                                              Margin = new Thickness(0, 2, 0, 0) });
            var t = new TextBlock { Text = $"{Loc.Gate(what)} — {(pass ? Loc.T("lib.gates.pass") : Loc.T("lib.gates.fail"))}",
                                    TextWrapping = TextWrapping.Wrap, FontSize = 14 };
            Grid.SetColumn(t, 1);
            g.Children.Add(t);
            gateRows.Add(g);
        }
        var allPassed = m.Gates.Count > 0 && m.GatesPassed == m.Gates.Count;
        var gateCard = Look.Group(allPassed ? FASymbol.Accept : FASymbol.Important, allPassed ? Look.GreenC : m.Gates.Count == 0 ? Look.GreyC : Look.RedC,
                                  Loc.T("lib.gates"), m.Gates.Count > 0 ? Loc.F("lib.fact.checks.of", m.GatesPassed, m.Gates.Count) : null,
                                  null, gateRows);
        p.Children.Add(new Border { Height = 8 });
        p.Children.Add(Look.Columns(descCard, gateCard, 420));
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
        var look = new List<Control>();
        var game = new List<Control>();
        var folders = new List<Control>();
        var cpu = new List<Control>();
        var memory = new List<Control>();
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
        look.Add(Ui.Setting("set.language", "set.language.desc", FASymbol.Globe, language, "set.language.tip"));
        var themes = new[] { "system", "light", "dark" };
        var theme = new ComboBox { MinWidth = 180, ItemsSource = themes.Select(t => Loc.T($"theme.{t}")).ToArray(),
                                   SelectedIndex = Math.Max(0, Array.IndexOf(themes, S.Theme)) };
        theme.SelectionChanged += (_, _) =>
        {
            S.Theme = themes[Math.Max(0, theme.SelectedIndex)];
            App.ApplyTheme(S.Theme);
            S.Save();
        };
        look.Add(Ui.Setting("set.theme", "set.theme.desc", FASymbol.Image, theme, "set.theme.tip"));
        /* the PO, 2026-10-03: «выбор раздела по умолчанию, который открывается при старте программы» */
        var starts = new[] { "home", "generate", "library" };
        var start = new ComboBox { MinWidth = 180, ItemsSource = starts.Select(t => Loc.T($"nav.{t}")).ToArray(),
                                   SelectedIndex = Math.Max(0, Array.IndexOf(starts, S.StartPage)) };
        start.SelectionChanged += (_, _) =>
        {
            S.StartPage = starts[Math.Max(0, start.SelectedIndex)];
            S.Save();
        };
        look.Add(Ui.Setting("set.start_page", "set.start_page.desc", FASymbol.Home, start, "set.start_page.tip"));

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
        game.Add(Ui.Setting("set.client", "set.client.desc", FASymbol.Games,
                                  new StackPanel { Orientation = Orientation.Horizontal, Children = { clientText, chooseClient } },
                                  "set.client.tip"));
        // the PO, 06.10: Python for the checks - where it is, chosen or installed from here
        var pyNow = Engine.Python;
        var pyText = new TextBlock
        {
            Text = pyNow ?? Loc.T("set.python.none"), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 420,
            TextTrimming = TextTrimming.CharacterEllipsis, Margin = new Thickness(0, 0, 8, 0),
        };
        game.Add(Ui.Setting("set.python", "set.python.desc", FASymbol.Code,
                                  new StackPanel { Orientation = Orientation.Horizontal, Children = { pyText, PythonButtons(null) } },
                                  "set.python.tip"));

        folders.Add(FolderSetting("set.bsp", () => S.BspDir, v => S.BspDir = v, @"data\bsp"));
        folders.Add(FolderSetting("set.maps", () => S.MapsDir, v => S.MapsDir = v, @"data\maps"));
        folders.Add(FolderSetting("set.temp", () => S.TempDir, v => S.TempDir = v, "temp"));

        cpu.Add(Ui.Setting("set.cpu_day", "set.cpu_day.desc", FASymbol.Clock,
                                  Number(S.CpuDayShare, 5, 100, v => S.CpuDayShare = v), "set.cpu_day.tip"));
        cpu.Add(Ui.Setting("set.cpu_night", "set.cpu_night.desc", FASymbol.Clock,
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
        cpu.Add(Ui.Setting("set.day_hours", "set.day_hours.desc", FASymbol.CalendarDay, hours, "set.day_from.tip"));
        var prios = new[] { "idle", "below_normal", "normal" };
        var prio = new ComboBox { MinWidth = 180, ItemsSource = prios.Select(x => Loc.T($"prio.{x}")).ToArray(),
                                  SelectedIndex = Math.Max(0, Array.IndexOf(prios, S.Priority)) };
        prio.SelectionChanged += (_, _) =>
        {
            S.Priority = prios[Math.Max(0, prio.SelectedIndex)];
            S.Save();
        };
        cpu.Add(Ui.Setting("set.priority", "set.priority.desc", FASymbol.Filter, prio, "set.priority.tip"));

        // row 411 (Fable's brief 8): the generator's working files in memory, and its steps on the disk
        memory.Add(Ui.Setting("set.memory_percent", "set.memory_percent.desc", FASymbol.Library,
                                  Number(S.MemoryPercent, 0, 90, v => S.MemoryPercent = v), "set.memory_percent.tip"));
        var keep = new ToggleSwitch { IsChecked = S.KeepCheckpoints };
        keep.IsCheckedChanged += (_, _) =>
        {
            S.KeepCheckpoints = keep.IsChecked == true;
            S.Save();
        };
        memory.Add(Ui.Setting("set.keep_checkpoints", "set.keep_checkpoints.desc", FASymbol.Save, keep,
                              "set.keep_checkpoints.tip"));
        p.Children.Add(Look.PageHead(Loc.T("set.title"), Loc.T("set.sub")));
        var left = Look.Stack(Look.Group(FASymbol.Globe, Look.VioletC, Loc.T("set.look"), Loc.T("set.look.sub"), null, look),
                              Look.Group(FASymbol.Games, Look.GreenC, Loc.T("set.client"), Loc.T("set.client.sub"), null, game),
                              Look.Group(FASymbol.Folder, Look.AmberC, Loc.T("set.folders"), Loc.T("set.folders.sub"), null, folders));
        var right = Look.Stack(Look.Group(FASymbol.Clock, Look.BlueC, Loc.T("set.cpu"), Loc.T("set.cpu.sub"), null, cpu),
                               Look.Group(FASymbol.Library, Look.TealC, Loc.T("set.memory"), Loc.T("set.memory.sub"), null, memory),
                               Look.Group(FASymbol.Sync, Look.PinkC, Loc.T("set.updates"), Loc.T("set.updates.sub"), null, UpdateRows()));
        p.Children.Add(Look.Columns(left, right));
        p.Children.Add(new TextBlock { Text = Loc.F("set.saved", Settings.IniPath), FontSize = 12.5, Opacity = 0.6,
                                       Margin = new Thickness(0, 16, 0, 0), TextWrapping = TextWrapping.Wrap });
        return Look.Page(p);
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
            Text = Settings.Resolve(get()), VerticalAlignment = VerticalAlignment.Center, MaxWidth = 300,
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
        var p = new StackPanel { Spacing = 16 };
        var version = Versions.Said(typeof(MainWindow).Assembly.GetName().Version);
        p.Children.Add(Look.PageHead(Loc.T("about.title"), Loc.F("about.version", version), UpdateButton()));     // brief 10 (D3)
        p.Children.Add(Look.Card(new StackPanel
        {
            Spacing = 10,
            Children =
            {
                new TextBlock { Text = Loc.T("about.what"), FontSize = 15, LineHeight = 23, TextWrapping = TextWrapping.Wrap },
                new TextBlock { Text = Loc.T("about.folder") + ": " + Settings.ProgramDir, FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap },
                new TextBlock { Text = Loc.T("about.ini") + ": " + Settings.IniPath, FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap },
            },
        }, 22));
        // the PO, 05.10: the versions with what each brought, newest first - a card each, the newest in colour
        p.Children.Add(new TextBlock { Text = Loc.T("about.history"), FontSize = 20, FontWeight = FontWeight.SemiBold, Margin = new Thickness(0, 8, 0, 0) });
        var first = true;
        foreach (var v in Versions.All)
        {
            var lines = new StackPanel { Spacing = 6, Margin = new Thickness(0, 10, 0, 0) };
            foreach (var line in Loc.Language == "en" ? v.En : v.Ru)
            {
                var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), ColumnSpacing = 10 };
                g.Children.Add(new Border { Width = 6, Height = 6, CornerRadius = new CornerRadius(3), Margin = new Thickness(0, 8, 0, 0),
                                            Background = first ? Look.Green : Look.Muted, VerticalAlignment = VerticalAlignment.Top });
                var t = new TextBlock { Text = line, FontSize = 14, LineHeight = 21, TextWrapping = TextWrapping.Wrap, Opacity = 0.9 };
                Grid.SetColumn(t, 1);
                g.Children.Add(t);
                lines.Children.Add(g);
            }
            var head = new StackPanel
            {
                Orientation = Orientation.Horizontal, Spacing = 10,
                Children =
                {
                    Look.Chip(v.Number, first ? Look.GreenC : Look.GreyC),
                    new TextBlock { Text = Loc.F("about.history.version", v.Number, v.Date), FontSize = 15, FontWeight = FontWeight.SemiBold,
                                    VerticalAlignment = VerticalAlignment.Center },
                },
            };
            p.Children.Add(Look.Card(new StackPanel { Children = { head, lines } }));
            first = false;
        }
        return Look.Page(p, 1200);
    }

    /// <summary>
    /// `--selftest`: each page in each language and theme, built and laid out at the window's size without the
    /// window being shown; a missing string shows as [key]. One line per page, PASS or FAIL.
    /// </summary>
    /// <summary>Brief 15 D9: the plan's own account of the PO's options on q2dm1, seed 6675 (08.10).</summary>
    private const string D9Fixture = """
dig storeys dealt: 1 of 4 wanted; 0 pairs qualify, 0 not rock, 0 meet a dig, 0 would wall somebody in, 0 without a pickup
dig storeys pairs refused: 48 same way, 83 rise not 96..256, 0 closer than 384, 25 a doorway not on the room's wall, 0 wider than allowed, 0 too steep, 0 a doorway under the terrace or the flight
dig annexes: 2 dealt of 6 wanted; 39 sites proved, 8 meet a dig, 0 would wall somebody in, 3 without a pickup walked both ways; 0 places on sky; 0 hold ammunition or health (no weapon or armour left)
spans: 0 dealt of 3 wanted (the test seam); 6545 edges looked across, 79 gaps 192..1024 open under and over
spans refused: 59 too narrow for the deck, 0 floors at two heights, 12 an entity near, 0 a pad's flight, 0 ends off the walk, 8 ends no start reaches, 0 no shortcut, 0 crossing
remodels: 10 dealt of 10 wanted (walls moved 5, turned 4, terraces 1; 6 in the arena, room 0)
remodels refused: 19 sites of 291 walls; 57 runs too short, 40 too narrow, 1 too low
floor-shifts: 4 dealt of 6 wanted (daises 3, channels 1; 2 in the arena, room 0)
floor-shifts refused: 56 places of 4771 looked at; 810 not reached from a start, 27727 floor not flat, 1602 no head room, 337 crowded, 484 a pickup, start or trigger near, 771 another edit, 556 a room under the floor
stair-reshapes: 1 dealt of 4 wanted (half-round feet 1, side flights 0) of the base's 6 stairs; refused: 1 rise not 32..256, 9 no open floor in front, 5 a pickup, start or trigger near, 2 another edit
blocks: 10 dealt of 10 wanted (boxes 2, Ls 2, crosses 0, octagons 4, round 2; 1 in the arena, room 0)
blocks refused: 76 places of 3800 looked at; 687 not reached from a start, 5333 floor not flat, 1333 no head room, 1040 crowded, 1214 a pickup, start or trigger near, 842 another edit
stairways: 5 dealt of 10 wanted (0 on a ledge, 5 holding a pickup); 242 sites of 3384 looked at; 11574 walkway edges met
floods by kind: water 0 of 6, slime 0 of 6, lava 2 of 17; kept off starts: 0 rooms gave up a hazard, 2 hazards retreated from a start
reshaping families dropped at the plan (their own rules refuse them on this map): widen 186 of 192 - FLUSH 115 BACKFACE 57 TOO_THIN 14; reshape 40 of 41 - FLUSH 15 BACKFACE 7 TOO_THIN 12 INTRUDER 6; turn 24 of 25 (the shell changes shape)
""";

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
        /* the PO, 12.10: the loading window says its steps; the home page carries the news, the group and the site; a
           picture of the game is kept as a JPEG, its cover's choice following it */
        try
        {
            var splash = new Splash(test: true);
            splash.Measure(new Size(520, 190));
            splash.Arrange(new Rect(0, 0, 520, 190));
            var said = Splash.Steps.Where(st => !Loc.Has(st.key)).Select(st => st.key).ToList();
            b.AppendLine(said.Count == 0 && splash.DesiredSize.Width > 0
                         ? $"PASS the loading window says each of its {Splash.Steps.Length} steps"
                         : $"FAIL the loading window says each of its steps -- no words for {string.Join(", ", said)}");
            var home = new MainWindow { _page = "home" };
            home.Rebuild();
            home.Measure(new Size(1180, 780));
            home.Arrange(new Rect(0, 0, 1180, 780));
            var texts = home.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text ?? "").ToList();
            var lost = Community.Where(c => !texts.Any(t => t.Contains(c.url.Replace("https://", "").TrimEnd('/')))).Select(c => c.url).ToList();
            b.AppendLine(lost.Count == 0 ? "PASS the home page links the news, the community group and the site"
                                         : $"FAIL the home page links the news, the community group and the site -- missing {string.Join(", ", lost)}");
            var dir = Path.Combine(App.Settings.TempPath, $"selftest_jpeg_{Environment.ProcessId}");
            Directory.CreateDirectory(dir);
            var png = Path.Combine(dir, "cover_00.png");
            using (var sk = new SkiaSharp.SKBitmap(640, 360))
            {
                using (var c = new SkiaSharp.SKCanvas(sk))
                    c.Clear(new SkiaSharp.SKColor(90, 60, 30));
                using var data = sk.Encode(SkiaSharp.SKEncodedImageFormat.Png, 100);
                using var f = File.Create(png);
                data.SaveTo(f);
            }
            File.WriteAllText(Path.Combine(dir, "cover.txt"), "cover_00.png");
            var made = Library.ToJpeg(png);
            var jpg = Path.ChangeExtension(png, ".jpg");
            var ok = made && File.Exists(jpg) && !File.Exists(png)
                     && File.ReadAllText(Path.Combine(dir, "cover.txt")).Trim() == "cover_00.jpg";
            b.AppendLine(ok ? "PASS a picture of the game is kept as a JPEG and stays the cover"
                            : $"FAIL a picture of the game is kept as a JPEG and stays the cover -- made {made}, jpg {File.Exists(jpg)}, png {File.Exists(png)}");
            Directory.Delete(dir, true);
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the loading window, the home links or the JPEG: {ex.GetType().Name}: {ex.Message}");
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
                    // brief 15, the PO: «любой текст в любой окне ... скопировать» - every text of the page offers itself
                    /* a window of its own for the page: a rebuilt window measured again at the same size keeps the
                       first page's visual tree (8 text blocks were found on every page after the first) */
                    var cw = new MainWindow { _page = w._page, _openMap = w._openMap, _graftMode = w._graftMode };
                    cw._chosen.AddRange(w._chosen);
                    cw.Rebuild();
                    cw.Measure(new Size(1180, 780));
                    cw.Arrange(new Rect(0, 0, 1180, 780));
                    var (askedCopy, failedCopy) = CopyText.CheckPage(cw);
                    b.AppendLine(failedCopy.Count == 0 && askedCopy > 0
                        ? $"PASS {lang} {theme} {page} copy: {askedCopy} texts offer themselves ({CopyText.LastNote})"
                        : $"FAIL {lang} {theme} {page} copy: {askedCopy} asked; {string.Join("; ", failedCopy.Take(5))}");
                }
                catch (Exception ex)
                {
                    b.AppendLine($"FAIL {lang} {theme} {page}: {ex.GetType().Name}: {ex.Message}");
                }
            }
        }
        Loc.Language = keepLang;
        App.ApplyTheme(keepTheme);
        /*
         * Brief 15 D9: when the asked difference is not reached, the description says which family found no more room.
         * The plan's account of the PO's options on q2dm1 (seed 6675, the recut driver's listing of 08.10), with the
         * ledger's counts of a run that built what it dealt: every family short of its order is named with its reason.
         */
        try
        {
            var said = Path.Combine(App.Settings.TempPath, $"selftest_plan_said_{Environment.ProcessId}.txt");
            File.WriteAllText(said, "# round 0\n" + D9Fixture + "\n");
            var fam = new Dictionary<string, int> { ["span"] = 0, ["remodel"] = 10, ["block"] = 10, ["floor-shift"] = 4, ["stair-reshape"] = 1 };
            var shp = new Dictionary<string, int> { ["annex"] = 2, ["storeys"] = 1 };
            foreach (var ru in new[] { true, false })
            {
                var lines = Describe.AskedAndMadeFrom(said, fam, shp, ru);
                var want = ru
                    ? new[] { "Пристройки: сделано 2 из 6; в плане 2 — ", "Комнаты в два этажа: сделано 1 из 4; в плане 1 — ",
                              "Мосты над ареной: сделано 0 из 3; в плане 0 — ", "Перестройка основы: сделано 10 из 10.",
                              "Блоки в комнатах: сделано 10 из 10.", "Пол: помосты и каналы: сделано 4 из 6; в плане 4 — ",
                              "Переделка лестниц основы: сделано 1 из 4; в плане 1 — ", "Не предлагались" }
                    : new[] { "Annexes: 2 made of 6; 2 in the plan - ", "Two-storey rooms: 1 made of 4; 1 in the plan - ",
                              "Bridges over the arena: 0 made of 3; 0 in the plan - ", "Remodels of the base: 10 made of 10.",
                              "Floor: daises and channels: 4 made of 6; 4 in the plan - ", "Not offered" };
                var missing = want.Where(w => !lines.Any(l => l.StartsWith(w, StringComparison.Ordinal))).ToList();
                b.AppendLine(missing.Count == 0
                    ? $"PASS {(ru ? "ru" : "en")} the description names every family short of its order and why ({lines.Count} lines)"
                    : $"FAIL {(ru ? "ru" : "en")} the description names every family short of its order and why -- missing "
                      + string.Join(" | ", missing) + " -- got " + string.Join(" | ", lines));
            }
            File.Delete(said);
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the asked-and-made description: {ex.GetType().Name}: {ex.Message}");
        }
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
            /* the folds' heads are controls of words (the PO, 11.10: a card's head on each fold) */
            if (o is Avalonia.Controls.Primitives.HeaderedContentControl hc)
                Walk(hc.Header);
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

    /// <summary>The folder a file is in, opened with the file selected.</summary>
    private static void ShowFileInExplorer(string file)
    {
        try
        {
            Process.Start(new ProcessStartInfo("explorer.exe", $"/select,\"{file}\"") { UseShellExecute = true });
        }
        catch (Exception) { }
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
