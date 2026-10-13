using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// A run, live (R6). The PO, 11.10, on the old page: «читать там можно разве что с лупой и то мозг выедает», «сейчас
/// то уже ахулиард инфы в окне генерации», «нужно сделать компактно - самое важное в развернутом виде, а что менее
/// важно в свернутых секциях, и с нормальными шрифтами, разными цветами». So:
///   the head - the map's name, its base, the stage under way as a coloured badge with its time, the buttons;
///   the left column - the difference from the base (a big number, the bar, what the plan promises), the edits (the
///     accepted / built / tried as numbers, the time bar, the last edit in its colour), the plan as a table of kinds
///     done of planned - always open; the stages and the machine's load folded, their headers saying the gist;
///   the right - the scheme and the log as tabs, the whole height.
/// Built once, updated in place by the window's timer, so nothing flickers and nothing loses its scroll.
/// </summary>
public sealed class GenerationView : DockPanel
{
    private static readonly string[] AllStages = { "start", "warp", "baseline", "plan", "attempt", "judge", "light", "gates", "destruction",
                                                   "relight", "cover", "done" };

    /// <summary>The run's stages: the ruin's only when the run asked for one (the PO, 07.10), and the base's frame only
    /// when it is to change.</summary>
    private static string[] StagesOf(Generation g) =>
        AllStages.Where(s => (s != "destruction" || (g.Request.Options?.Destruction ?? 0) > 0)
                          && (s != "warp" || (g.Request.Options is { } o && (o.WarpSize != 100 || o.WarpShape > 0))))
                 .ToArray();

    /* the colours the page speaks in */
    private static readonly Color GreenC = Color.FromRgb(0x22, 0xc5, 0x5e), RedC = Color.FromRgb(0xef, 0x44, 0x44),
                                  BlueC = Color.FromRgb(0x3b, 0x82, 0xf6), AmberC = Color.FromRgb(0xf5, 0x9e, 0x0b);
    private static readonly IBrush Green = new SolidColorBrush(GreenC), Red = new SolidColorBrush(RedC),
                                   Blue = new SolidColorBrush(BlueC), Amber = new SolidColorBrush(AmberC),
                                   Muted = new SolidColorBrush(Color.FromRgb(0x8b, 0x8b, 0x94));
    private static readonly IBrush CardBack = new SolidColorBrush(Color.FromArgb(0x1c, 0x80, 0x80, 0x80));
    private static readonly IBrush CardEdge = new SolidColorBrush(Color.FromArgb(0x40, 0x80, 0x80, 0x80));

    // ---- the head ----
    private readonly TextBlock _title = new() { FontSize = 24, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _bases = new() { FontSize = 14, Opacity = 0.75, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _now = new() { FontSize = 14, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap };
    private readonly Border _badge = new() { CornerRadius = new CornerRadius(12), Padding = new Thickness(12, 4, 12, 4) };
    private readonly TextBlock _elapsed = new() { FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _queue = new() { FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap };
    private readonly Button _pause = Ui.Button("run.pause", "run.pause.tip", FASymbol.Pause);
    private readonly Button _stop = Ui.Button("run.stop", "run.stop.tip", FASymbol.Stop);
    /* the PO, 05.10: a generation not wanted is cancelled - stopped and its files deleted; a stopped one deleted */
    private readonly Button _cancel = Ui.Button("run.cancel", "run.cancel.tip", FASymbol.Cancel);
    private readonly Button _delete = Ui.Button("gen.interrupted.delete", "gen.interrupted.delete.tip", FASymbol.Delete);
    private readonly Button _again = Ui.Button("run.again", "run.again.tip", FASymbol.Add, accent: true);
    private readonly Button _continue = Ui.Button("run.continue", "run.continue.tip", FASymbol.Play, accent: true);
    private readonly Button _open = Ui.Button("run.open", "run.open.tip", FASymbol.Library);
    private readonly FAInfoBar _outcome = new() { IsClosable = false, IsOpen = false, Margin = new Thickness(0, 4, 0, 8) };

    // ---- the difference ----
    private readonly TextBlock _diffNow = new() { FontSize = 34, FontWeight = FontWeight.SemiBold, Foreground = Blue };
    private readonly TextBlock _diffGoal = new() { FontSize = 16, Opacity = 0.75, VerticalAlignment = VerticalAlignment.Bottom,
                                                   Margin = new Thickness(8, 0, 0, 6) };
    private readonly ProgressBar _likeness = new() { Minimum = 0, Maximum = 1, Height = 8, Margin = new Thickness(0, 4, 0, 6) };
    /* brief 16 D2: the plan's word, under the bar it is about */
    private readonly TextBlock _planWord = new() { FontSize = 13, Foreground = Amber, TextWrapping = TextWrapping.Wrap };

    // ---- the edits ----
    private readonly TextBlock _nAccepted = Big(Green), _nBuilt = Big(null), _nTried = Big(Muted);
    private readonly TextBlock _builtCaption = Caption("run.stat.built");
    private readonly ProgressBar _attempts = new() { Minimum = 0, Maximum = 1, Height = 6, Margin = new Thickness(0, 10, 0, 4) };
    private readonly TextBlock _time = new() { FontSize = 13, Opacity = 0.8, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _last = new() { FontSize = 13, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 6, 0, 0) };
    private readonly TextBlock _tail = new() { FontSize = 12, Opacity = 0.65, TextWrapping = TextWrapping.Wrap };

    // ---- the plan ----
    private readonly Grid _planRows = new() { ColumnDefinitions = new ColumnDefinitions("*,90,Auto"), RowSpacing = 6, ColumnSpacing = 10 };
    private readonly Border _planCard;
    private readonly TextBlock _ruin = new() { FontSize = 13, Opacity = 0.8, TextWrapping = TextWrapping.Wrap, Margin = new Thickness(0, 8, 0, 0) };
    private string _planShown = "";

    // ---- folded ----
    private readonly StackPanel _stages = new() { Spacing = 6, Margin = new Thickness(0, 4, 0, 4) };
    private readonly Expander _stagesBox = new() { HorizontalAlignment = HorizontalAlignment.Stretch, IsExpanded = false };
    private readonly LoadMeter _meter = new();
    private readonly Expander _loadBox = new() { HorizontalAlignment = HorizontalAlignment.Stretch, IsExpanded = false };
    private readonly TextBlock _memory = new() { FontSize = 13, Foreground = Amber, TextWrapping = TextWrapping.Wrap };

    // ---- the right ----
    private readonly TextBox _log = new() { IsReadOnly = true, AcceptsReturn = true, FontFamily = new FontFamily("Consolas,monospace"),
                                            FontSize = 12, MinHeight = 160, TextWrapping = TextWrapping.NoWrap,
                                            VerticalAlignment = VerticalAlignment.Stretch };
    private readonly SchemePanel _scheme = new(() => Generation.Current);
    public SchemePanel Scheme => _scheme;
    public LoadMeter Meter => _meter;
    private readonly Action<string> _openMap;
    private Generation? _g;

    private static TextBlock Big(IBrush? brush)
    {
        var t = new TextBlock { FontSize = 26, FontWeight = FontWeight.SemiBold };
        if (brush != null)
            t.Foreground = brush;
        return t;
    }

    private static TextBlock Caption(string key) => new() { Text = Loc.T(key), FontSize = 12, Opacity = 0.65 };

    private static Border Card(string titleKey, Control body, string? tipKey = null)
    {
        var p = new StackPanel { Spacing = 2 };
        p.Children.Add(new TextBlock { Text = Loc.T(titleKey), FontSize = 15, FontWeight = FontWeight.SemiBold,
                                       Margin = new Thickness(0, 0, 0, 6) });
        p.Children.Add(body);
        var b = new Border { Background = CardBack, BorderBrush = CardEdge, BorderThickness = new Thickness(1),
                             CornerRadius = new CornerRadius(10), Padding = new Thickness(16, 12, 16, 14), Child = p };
        return tipKey != null ? b.Tip(tipKey) : b;
    }

    private static StackPanel Stat(TextBlock number, TextBlock caption) => new()
    {
        Spacing = 0, MinWidth = 96, Children = { number, caption },
    };

    public GenerationView(Action again, Action<string> openMap)
    {
        _openMap = openMap;
        LastChildFill = true;

        // the head: name, base, the stage now as a badge, the time; the buttons on the right
        _badge.Child = _now;
        var status = new WrapPanel { Margin = new Thickness(0, 6, 0, 0) };
        _badge.Margin = new Thickness(0, 0, 12, 4);
        _elapsed.VerticalAlignment = VerticalAlignment.Center;
        status.Children.Add(_badge);
        status.Children.Add(_elapsed);
        var who = new StackPanel { Spacing = 2, Children = { _title, _bases, status, _queue } };
        var buttons = new WrapPanel { HorizontalAlignment = HorizontalAlignment.Right, VerticalAlignment = VerticalAlignment.Top,
                                      Margin = new Thickness(16, 4, 0, 0) };
        foreach (var b in new[] { _pause, _stop, _cancel, _continue, _delete, _again, _open })
        {
            b.Margin = new Thickness(8, 0, 0, 8);
            buttons.Children.Add(b);
        }
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Margin = new Thickness(0, 0, 0, 8) };
        head.Children.Add(who);
        Grid.SetColumn(buttons, 1);
        head.Children.Add(buttons);
        DockPanel.SetDock(head, Dock.Top);
        Children.Add(head);
        DockPanel.SetDock(_outcome, Dock.Top);
        Children.Add(_outcome);

        // the left column: what matters open, the rest folded
        var diff = new StackPanel
        {
            Children =
            {
                new StackPanel { Orientation = Orientation.Horizontal, Children = { _diffNow, _diffGoal } },
                _likeness.Tip("run.likeness.tip"),
                _planWord.Tip("run.plan.value.tip"),
            },
        };
        var stats = new WrapPanel
        {
            Children = { Stat(_nAccepted, Caption("run.stat.accepted")), Stat(_nBuilt, _builtCaption), Stat(_nTried, Caption("run.stat.tried")) },
        };
        var edits = new StackPanel { Children = { stats, _attempts.Tip("run.attempts.tip"), _time, _last, _tail } };
        _planCard = Card("run.plan.head", new StackPanel { Children = { _planRows, _ruin } });
        _stagesBox.Content = _stages;
        _loadBox.Content = _meter;
        _meter.Width = double.NaN;
        _meter.HorizontalAlignment = HorizontalAlignment.Stretch;
        var left = new StackPanel
        {
            Spacing = 12,
            Margin = new Thickness(0, 0, 16, 12),
            Children =
            {
                Card("run.diff.head", diff),
                Card("run.edits.head", edits),
                _planCard,
                _stagesBox,
                _loadBox,
                _memory,
            },
        };
        var leftScroll = new ScrollViewer
        {
            Content = left, Width = 420,
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
        };
        DockPanel.SetDock(leftScroll, Dock.Left);
        Children.Add(leftScroll);

        // the right: the scheme and the log, the whole height (the PO: the map must not be pushed down)
        var tabs = new TabControl { VerticalAlignment = VerticalAlignment.Stretch };
        tabs.Items.Add(new TabItem { Header = Loc.T("scheme.tab"), Content = _scheme, FontSize = 15 });
        tabs.Items.Add(new TabItem { Header = Loc.T("run.log"), Content = _log, FontSize = 15 }.Tip("run.log.tip"));
        Children.Add(tabs);

        _pause.Click += (_, _) => _g?.Pause(!_g.Paused);
        _stop.Click += (_, _) =>
        {
            Generation.Queue.Clear();
            _g?.Stop();
        };
        _again.Click += (_, _) => again();
        _cancel.Click += async (_, _) =>
        {
            if (_g is not { Running: true } g || TopLevel.GetTopLevel(this) is not MainWindow w)
                return;
            if (!await w.Confirm(Loc.F("cancel.title", g.Request.Name), Loc.T("cancel.text"), "cancel.yes", "cancel.no"))
                return;
            Generation.Queue.Clear();
            g.Stop();
            await Drop(g, w, again);
        };
        _delete.Click += async (_, _) =>
        {
            if (_g is not { Running: false } g || TopLevel.GetTopLevel(this) is not MainWindow w)
                return;
            if (!await w.Confirm(Loc.F("delete.title", g.Request.Name),
                                 Loc.F("delete.text", Generation.Size(Generation.FolderBytes(g.RunDir))), "delete.yes", "delete.no"))
                return;
            await Drop(g, w, again);
        };
        // P5: a run that crashed or was stopped goes on from where it was
        _continue.Click += (_, _) =>
        {
            if (_g == null || _g.Running)
                return;
            try
            {
                Update(Generation.Resume(App.Settings, _g.RunDir));
            }
            catch (Exception ex)
            {
                _outcome.Message = ex.Message;
            }
        };
        _open.Click += (_, _) =>
        {
            if (_g?.LibraryName.Length > 0)
                _openMap(_g.LibraryName);
        };
    }

    /// <summary>The run's folder deleted (off the window's thread), said, and the form shown again.</summary>
    private async Task Drop(Generation g, MainWindow w, Action again)
    {
        var bytes = Generation.FolderBytes(g.RunDir);
        var why = await Task.Run(() => Generation.Delete(App.Settings, g.RunDir));
        if (why.Length > 0)
        {
            _outcome.IsOpen = true;
            _outcome.Severity = FAInfoBarSeverity.Error;
            _outcome.Message = Loc.F("delete.failed", why);
            return;
        }
        if (ReferenceEquals(Generation.Current, g))
            Generation.Current = null;
        w.Notice(Loc.F("delete.done", g.Request.Name, Generation.Size(bytes)), FAInfoBarSeverity.Success);
        again();
    }

    public void Update(Generation g)
    {
        _g = g;
        _meter.Update(g);
        _scheme.Update(g);

        // the head
        _title.Text = Loc.F("run.title", g.Request.Name);
        // row 410: what the map is made from, plainly - the PO's mg_10_42 was q2dm1's without his knowing
        _bases.Text = g.Request.Grafts is { Count: > 0 } grafts
            ? Loc.F("run.base.grafts", g.Request.Donor, string.Join(", ", grafts))
            : Loc.F("run.base", g.Request.Donor);
        _now.Text = NowLine(g);
        var failed = !g.Running && g.Error.Length > 0;
        var tint = failed ? RedC : !g.Running ? GreenC : g.Paused ? AmberC : BlueC;
        _badge.Background = new SolidColorBrush(Color.FromArgb(0x33, tint.R, tint.G, tint.B));
        _badge.BorderBrush = new SolidColorBrush(Color.FromArgb(0x99, tint.R, tint.G, tint.B));
        _badge.BorderThickness = new Thickness(1);
        _now.Foreground = new SolidColorBrush(tint);
        var end = g.Ended ?? DateTime.Now;
        var eta = EditsLeft(g);
        // the time left is the badge's; here the run's own clock
        _elapsed.Text = g.Running ? Loc.F("run.elapsed", Dur(g.Worked(g.Began, end)), g.Began.ToString("HH:mm:ss")) : RunLine(g);
        _queue.Text = Generation.Queue.Count > 0
            ? Loc.F("run.queue", string.Join(", ", Generation.Queue.Select(q => $"{q.Name} ({q.Donor})")))
            : "";
        _queue.IsVisible = _queue.Text.Length > 0;

        // the difference from the base
        _diffNow.Text = Loc.F("run.diff.now", g.Divergence / 10);
        _diffGoal.Text = g.Target > 0 ? Loc.F("run.diff.goal", g.Target / 10) : "";
        _diffNow.Foreground = g.Target > 0 && g.Divergence >= g.Target ? Green : Blue;
        _likeness.Maximum = Math.Max(1, g.Target);
        _likeness.Value = Math.Min(g.Divergence, g.Target);
        _planWord.Text = g.PlanCan < 0 ? "" : Loc.F("run.diff.plan", (g.PlanCan / 10.0).ToString("0.#"), g.PlanBuilds);
        _planWord.IsVisible = _planWord.Text.Length > 0;

        // the edits
        var minutes = g.Request.TimeMinutes;
        _nAccepted.Text = g.Accepted.ToString();
        _nBuilt.Text = g.Compiles.ToString();
        _nTried.Text = g.Attempts.ToString();
        _builtCaption.Text = minutes > 0 || g.Budget <= 0 ? Loc.T("run.stat.built") : Loc.F("run.stat.built.of", g.Budget);
        // brief 16 D6: a run with minutes is measured by them - the bar is its time
        _attempts.Maximum = minutes > 0 ? minutes * 60.0 : Math.Max(1, g.Budget);
        _attempts.Value = minutes > 0 ? Math.Min(g.Worked(g.Began, end).TotalSeconds, minutes * 60.0)
                                      : Math.Min(g.Compiles, g.Budget);
        _time.Text = g.Budget <= 0 ? Loc.T("run.edits.wait")
                   : minutes > 0 ? Loc.F("run.time.of", (int)g.Worked(g.Began, end).TotalMinutes, minutes)
                   : Loc.F("run.builds.of", g.Compiles, g.Budget);
        var accepted = g.LastVerdict == "ACCEPTED";
        _last.Text = g.LastFamily.Length > 0
            ? Loc.F("run.last", Loc.Has($"kind.{g.LastFamily}") ? Loc.T($"kind.{g.LastFamily}") : g.LastFamily,
                    Loc.T(accepted ? "verdict.accepted" : "verdict.rejected"))
            : "";
        _last.Foreground = accepted ? Green : Red;
        _last.IsVisible = _last.Text.Length > 0;
        var (fin, graft) = g.TailPlanned();
        _tail.Text = fin + graft > 0 && g.Budget > 0 && g.Running
            ? Loc.F("run.tail", Math.Min(g.FinishingSeen, fin) + Math.Min(g.GraftSeen, graft), fin + graft) : "";
        _tail.IsVisible = _tail.Text.Length > 0;

        // the plan: kinds done of planned
        var rows = g.PlanRows();
        var shown = string.Join(";", rows.Select(r => $"{r.key}:{r.done}/{r.planned}"));
        if (shown != _planShown)
        {
            _planShown = shown;
            _planRows.Children.Clear();
            _planRows.RowDefinitions.Clear();
            var i = 0;
            foreach (var r in rows)
            {
                _planRows.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
                var name = new TextBlock { Text = r.name, FontSize = 14, VerticalAlignment = VerticalAlignment.Center,
                                           TextWrapping = TextWrapping.Wrap };
                var bar = new ProgressBar { Minimum = 0, Maximum = Math.Max(1, r.planned), Value = Math.Min(r.done, r.planned),
                                            Height = 6, MinWidth = 0, VerticalAlignment = VerticalAlignment.Center,
                                            Foreground = r.done >= r.planned ? Green : Blue };
                var count = new TextBlock { Text = Loc.F("plan.of", r.done, r.planned), FontSize = 14, FontWeight = FontWeight.SemiBold,
                                            VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Right };
                if (r.done >= r.planned)
                    count.Foreground = Green;
                else if (r.done == 0)
                    count.Foreground = Muted;
                Grid.SetRow(name, i);
                Grid.SetRow(bar, i);
                Grid.SetColumn(bar, 1);
                Grid.SetRow(count, i);
                Grid.SetColumn(count, 2);
                _planRows.Children.Add(name);
                _planRows.Children.Add(bar);
                _planRows.Children.Add(count);
                i++;
            }
        }
        _planCard.IsVisible = rows.Count > 0;
        var ruin = g.Request.Options?.Destruction ?? 0;
        _ruin.Text = ruin > 0 ? Loc.F("run.plan.ruin", ruin) : "";
        _ruin.IsVisible = ruin > 0;

        // folded: the stages, their header saying the one under way
        _stagesBox.Header = Loc.F("run.stages.head", Loc.T(g.Running ? $"stage.{(g.Stage == "resume" ? "attempt" : g.Stage)}"
                                                                       : failed ? "run.now.failed" : "run.now.done"));
        _stages.Children.Clear();
        // a resumed run replays its ledger: that is the edits stage, gone through again (the PO 05.10 saw every
        // stage waiting while it replayed)
        var Stages = StagesOf(g);
        var at = Array.IndexOf(Stages, g.Stage is "failed" or "stopped" ? "done" : g.Stage == "resume" ? "attempt" : g.Stage);
        // a run that failed: done is what it passed, the stage it stopped in is crossed out, the rest not reached
        // (the PO's koldduel1, 05.10: refused at its base map's rebuild, every stage showed a tick)
        var reached = -1;
        for (var k = 0; k < Stages.Length - 1; k++)
            if (g.StageBegan.ContainsKey(Stages[k]))
                reached = k;
        for (var k = 0; k < Stages.Length; k++)
        {
            var key = Stages[k];
            var broke = failed && k == reached;
            var done = failed ? k < reached : k < at || (!g.Running && g.Error.Length == 0);
            var now = g.Running && k == at;
            var since = g.StageBegan.TryGetValue(key, out var t) ? t : (DateTime?)null;
            var next = k + 1 < Stages.Length && g.StageBegan.TryGetValue(Stages[k + 1], out var tn) ? tn : (DateTime?)null;
            // a stage's end is the next stage's beginning, or the run's end for the last one it went through
            DateTime? until = next ?? (done && !g.Running ? g.Ended : null);
            var time = since == null ? ""
                     : done && until != null ? Loc.F("run.stage.done", Dur(g.Worked(since.Value, until.Value)),
                                                     until.Value.ToString("dd.MM HH:mm:ss"))
                     : now ? StageNow(g, key, since.Value, eta)
                     : "";
            var row = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*") };
            var icon = new FASymbolIcon
            {
                Symbol = done ? FASymbol.Accept : broke ? FASymbol.Cancel : now ? (g.Paused ? FASymbol.Pause : FASymbol.Play) : FASymbol.Clock,
                FontSize = 14, Opacity = done || now || broke ? 1.0 : 0.4, Margin = new Thickness(0, 2, 8, 0),
                VerticalAlignment = VerticalAlignment.Top,
                Foreground = done ? Green : broke ? Red : now ? Blue : Muted,
            };
            var words = new StackPanel
            {
                Children =
                {
                    new TextBlock { Text = Loc.T($"stage.{key}"), FontSize = 13, Opacity = done || now || broke ? 1.0 : 0.55,
                                    FontWeight = now ? FontWeight.SemiBold : FontWeight.Normal, TextWrapping = TextWrapping.Wrap },
                },
            };
            if (time.Length > 0)
                words.Children.Add(new TextBlock { Text = time, FontSize = 12, Opacity = 0.6, TextWrapping = TextWrapping.Wrap });
            Grid.SetColumn(words, 1);
            row.Children.Add(icon);
            row.Children.Add(words);
            _stages.Children.Add(row.Tip($"stage.{key}.tip"));
        }
        _loadBox.Header = g.CpuShare > 0 ? Loc.F("run.load.head", g.CpuShare) : Loc.T("load.title");
        // the working files in memory is the rule and not news; on the disk is (row 411)
        _memory.Text = g.MemoryNote == Loc.T("run.memory.on") ? "" : g.MemoryNote;
        _memory.IsVisible = _memory.Text.Length > 0;

        // the buttons and the outcome
        _pause.IsVisible = _stop.IsVisible = _cancel.IsVisible = g.Running;
        _delete.IsVisible = !g.Running && g.LibraryName.Length == 0 && Directory.Exists(g.RunDir);
        if (_pause.Content is StackPanel sp && sp.Children.Count == 2)
        {
            ((FASymbolIcon)sp.Children[0]).Symbol = g.Paused ? FASymbol.Play : FASymbol.Pause;
            ((TextBlock)sp.Children[1]).Text = Loc.T(g.Paused ? "run.resume" : "run.pause");
        }
        _again.IsVisible = !g.Running;
        _continue.IsVisible = !g.Running && g.Error.Length > 0 && g.LibraryName.Length == 0
                              && File.Exists(Path.Combine(g.JobDir, "ledger.txt"))
                              && Generation.KeptCheckpoints(g.RunDir)
                              && !g.Error.Contains(Loc.F("run.resume.diverged", "").Trim());
        _open.IsVisible = !g.Running && g.LibraryName.Length > 0;
        _outcome.IsOpen = false;
        if (!g.Running)
        {
            _outcome.IsOpen = true;
            if (g.Error.Length > 0)
            {
                _outcome.Severity = FAInfoBarSeverity.Error;
                _outcome.Title = g.Crashed ? Loc.T("run.crashed.title") : Loc.T("run.failed.title");
                _outcome.Message = g.Crashed ? g.Error + "\n" + Loc.F("run.crashed.where", g.JobDir)
                                               + (_continue.IsVisible ? "\n" + Loc.T("run.crashed.resume")
                                                  : !Generation.KeptCheckpoints(g.RunDir) ? "\n" + Loc.T("run.resume.nocheckpoints") : "")
                                             : g.Error;
            }
            else
            {
                var bad = g.Gates.Count(x => !x.pass);
                _outcome.Severity = bad == 0 ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Warning;
                _outcome.Title = Loc.F("run.done.title", g.LibraryName);
                _outcome.Message = g.Gates.Count == 0 ? Loc.T("run.done.nogates")
                                 : bad == 0 ? Loc.F("run.done.gates", g.Gates.Count)
                                 : Loc.F("run.done.gatesfail", bad, g.Gates.Count);
                // row 410: a map delivered on a result that is not OK says why (koldduel1 with q3t2's rooms offered:
                // «ERR_DONOR_OMITTED» - none of q3t2's rooms fitted, which the run page did not say)
                // brief 9 D4: what the second map gave, or why nothing - never «не подошли» alone
                if (g.SecondSaid() is { Length: > 0 } second)
                    _outcome.Message += "\n" + second;
                else if (g.Result.Length > 0 && g.Result != "OK" && Loc.Has($"result.{g.Result}.delivered"))
                {
                    _outcome.Message += "\n" + Loc.F($"result.{g.Result}.delivered", string.Join(", ", g.Request.Grafts ?? Array.Empty<string>()));
                    _outcome.Severity = FAInfoBarSeverity.Warning;
                }
            }
        }
        var tail = g.Log.Skip(Math.Max(0, g.Log.Count - 200));
        var text = string.Join("\n", tail);
        if (_log.Text != text)
            _log.Text = text;
    }

    /// <summary>The stage under way: how long it has gone, and for the edits how long they have left and when they end.</summary>
    private static string StageNow(Generation g, string key, DateTime since, TimeSpan? eta) =>
        key == "attempt" && eta is { } l
            ? Loc.F("run.stage.eta", Dur(g.Worked(since, DateTime.Now)), Dur(l), (DateTime.Now + l).ToString("HH:mm"))
            : key == "attempt" && g.Running && !g.Paused
            ? Loc.F("run.stage.eta.wait", Dur(g.Worked(since, DateTime.Now)))
            : key == "light" && g.LightNow() is { Length: > 0 } step
            ? Loc.F("run.stage.now", Dur(g.Worked(since, DateTime.Now))) + " — " + step
            : Loc.F("run.stage.now", Dur(g.Worked(since, DateTime.Now)));

    /// <summary>The whole run's time: while it runs, since when and when the edits end; once over, its span.</summary>
    public static string RunLine(Generation g)
    {
        var end = g.Ended ?? DateTime.Now;
        var eta = EditsLeft(g);
        var worked = g.Worked(g.Began, end);
        return !g.Running
            ? Loc.F("run.ended.at", Dur(worked), g.Began.ToString("dd.MM HH:mm:ss"), end.ToString("dd.MM HH:mm:ss"))
            : eta is { } left
                ? Loc.F("run.elapsed.eta", Dur(worked), g.Began.ToString("HH:mm:ss"), Dur(left),
                        (DateTime.Now + left).ToString("HH:mm"))
                : Loc.F("run.elapsed", Dur(worked), g.Began.ToString("HH:mm:ss"));
    }

    /// <summary>
    /// The stage under way in one line - its name and its time (the head's badge, and the full-screen plan's overlay:
    /// the PO, 05.10, «без уже законченных шагов - только текущий»).
    /// </summary>
    public static string NowLine(Generation g)
    {
        if (!g.Running)
            return g.Error.Length > 0 ? Loc.T("run.now.failed") : Loc.T("run.now.done");
        if (g.Paused)
            return Loc.T("run.now.paused");
        var key = g.Stage == "resume" ? "attempt" : g.Stage;
        var head = Loc.T($"stage.{g.Stage}.now");
        return g.StageBegan.TryGetValue(key, out var since) ? $"{head} — {StageNow(g, key, since, EditsLeft(g))}" : head;
    }

    /// <summary>Hours, minutes and seconds in words: «1 ч 02 мин 05 с», «3 мин 07 с», «12 с».</summary>
    public static string Dur(TimeSpan t)
    {
        if (t < TimeSpan.Zero)
            t = TimeSpan.Zero;
        return t.TotalHours >= 1 ? Loc.F("dur.h", (int)t.TotalHours, t.Minutes.ToString("00"), t.Seconds.ToString("00"))
             : t.TotalMinutes >= 1 ? Loc.F("dur.m", t.Minutes, t.Seconds.ToString("00"))
             : Loc.F("dur.s", t.Seconds);
    }

    /// <summary>
    /// How long the edits have left: the builds the budget still allows times the time a build takes NOW - the mean
    /// of the last eight intervals between new builds (one interval: from the edits stage's start to the first new
    /// build) - less what has gone since the last one. Replayed builds are not counted (they cost nothing). Null
    /// before a new build, while paused, or outside the edits. The builds left are the fewer of the budget's and
    /// those the likeness still needs at the recent gain per build (the generator stops at either).
    /// </summary>
    private static TimeSpan? EditsLeft(Generation g)
    {
        if (!g.Running || g.Paused || g.Stage is not ("attempt" or "resume") || g.Budget <= 0)
            return null;
        var seen = g.BuildsSeen;
        if (seen.Count == 0)
            return null;
        double each;
        double builds = Math.Max(0, g.Budget - g.Compiles);
        if (seen.Count >= 2)
        {
            var from = Math.Max(0, seen.Count - 9);
            var n = seen.Count - 1 - from;
            each = g.Worked(seen[from].at, seen[^1].at).TotalSeconds / n;
            // the likeness reached ends the budget's builds too: the builds that takes at the recent gain per build
            var gain = (double)(seen[^1].divergence - seen[from].divergence) / n;
            if (gain > 0 && g.Target > g.Divergence)
                builds = Math.Min(builds, Math.Ceiling((g.Target - g.Divergence) / gain));
        }
        else if (g.StageBegan.TryGetValue("attempt", out var began) && seen[0].at > began)
            each = g.Worked(began, seen[0].at).TotalSeconds;
        else
            return null;
        /*
         * And the edits the budget does not bound, counted from the start (the PO, 09.10: «уже много времени
         * показывает 0 секунд осталось» and «почему просто не рассчитывать заранее сколько будет перестановок»): the
         * plan says how many item swaps and spawn moves (at most six) and rooms of other maps follow the budget's
         * last build - a build each, as long as those seen of them, or as a build of the budget before the first.
         */
        var (fin, graft) = g.TailPlanned();
        var tail = Math.Max(0, fin - g.FinishingSeen) + Math.Max(0, graft - g.GraftSeen);
        var per = g.FinishingSeconds.Count > 0 ? g.FinishingSeconds.Average() : each;
        var inTail = builds <= 0 || g.FinishingSeen > 0 || g.GraftSeen > 0;
        var since = inTail
            ? (g.TryStarted is { } t ? g.Worked(t, DateTime.Now).TotalSeconds : 0.0)
            : g.Worked(seen[^1].at, DateTime.Now).TotalSeconds;
        var left = (inTail ? 0 : builds * each) + tail * per - since;
        /* brief 16 D6: and never past the run's minutes, less what the engine keeps back for after the edits */
        if (g.Request.TimeMinutes > 0)
        {
            var budget = g.Request.TimeMinutes * 60.0;
            var byTime = budget - (240.0 + budget / 30.0) - g.Worked(g.Began, DateTime.Now).TotalSeconds;
            left = Math.Min(left, Math.Max(0.0, byTime) + tail * per);
        }
        return TimeSpan.FromSeconds(Math.Max(tail > 0 ? per * 0.1 : 0, left));
    }
}

/// <summary>
/// The run in two lines over every page but the run's own (the PO, 11.10: «сейчас у меня запущена генерация, но я про
/// это не вижу если нахожусь в библиотеке карт ... вверху сделать общий статус в одну-две строчки над всеми окнами
/// программы»): the stage now and its time in the run's colour, the difference and the edits under it, a thin bar,
/// and the way to the run's page - the button or a click anywhere on it.
/// </summary>
public sealed class RunStrip : Border
{
    private readonly TextBlock _line1 = new() { FontSize = 15, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _line2 = new() { FontSize = 13, Opacity = 0.8, TextWrapping = TextWrapping.Wrap };
    private readonly ProgressBar _bar = new() { Minimum = 0, Maximum = 1, Height = 4, MinHeight = 4, MinWidth = 0,
                                                Margin = new Thickness(0, 6, 0, 0) };
    private readonly Border _sign = new() { Width = 36, Height = 36, CornerRadius = new CornerRadius(9) };
    private readonly FASymbolIcon _icon = new() { FontSize = 18, HorizontalAlignment = HorizontalAlignment.Center,
                                                  VerticalAlignment = VerticalAlignment.Center };
    public event Action? Open;

    public RunStrip()
    {
        _sign.Child = _icon;
        var open = Ui.Button("strip.open", "strip.open.tip", FASymbol.Forward, accent: true);
        open.Click += (_, _) => Open?.Invoke();
        var words = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center, Children = { _line1, _line2, _bar } };
        var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), ColumnSpacing = 14 };
        g.Children.Add(_sign);
        Grid.SetColumn(words, 1);
        g.Children.Add(words);
        open.VerticalAlignment = VerticalAlignment.Center;
        Grid.SetColumn(open, 2);
        g.Children.Add(open);
        Child = g;
        CornerRadius = new CornerRadius(12);
        Padding = new Thickness(14, 10, 14, 10);
        Margin = new Thickness(40, 16, 40, 0);
        BorderThickness = new Thickness(1);
        Cursor = new Avalonia.Input.Cursor(Avalonia.Input.StandardCursorType.Hand);
        IsVisible = false;
        PointerReleased += (_, e) =>
        {
            if (e.InitialPressMouseButton == Avalonia.Input.MouseButton.Left)
                Open?.Invoke();
        };
        this.Tip("strip.open.tip");
    }

    public void Update(Generation g)
    {
        var failed = !g.Running && g.Error.Length > 0;
        var colour = failed ? Look.RedC : !g.Running ? Look.GreenC : g.Paused ? Look.AmberC : Look.BlueC;
        Background = Look.Soft(colour, 0x1e);
        BorderBrush = Look.Soft(colour, 0x66);
        _sign.Background = Look.Soft(colour, 0x40);
        _icon.Foreground = new SolidColorBrush(colour);
        _icon.Symbol = failed ? FASymbol.Cancel : !g.Running ? FASymbol.Accept : g.Paused ? FASymbol.Pause : FASymbol.Play;
        _line1.Foreground = new SolidColorBrush(colour);
        _line1.Text = Loc.F("strip.line1", g.Request.Name, g.Request.Donor, GenerationView.NowLine(g));
        var minutes = g.Request.TimeMinutes;
        var time = minutes > 0 ? Loc.F("strip.time", (int)g.Worked(g.Began, g.Ended ?? DateTime.Now).TotalMinutes, minutes)
                               : GenerationView.Dur(g.Worked(g.Began, g.Ended ?? DateTime.Now));
        _line2.Text = g.Target > 0
            ? Loc.F("strip.line2", g.Divergence / 10, g.Target / 10, g.Accepted, g.Compiles, time)
            : Loc.F("strip.line2.early", time);
        _bar.Maximum = Math.Max(1, g.Target);
        _bar.Value = Math.Min(g.Divergence, g.Target);
        _bar.Foreground = new SolidColorBrush(colour);
    }
}
