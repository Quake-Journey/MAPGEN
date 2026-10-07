using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// A run, live (R6): the stages as done / now / next with their times, the attempts and the likeness as bars, the
/// last edit in plain words, pause / resume / stop (R7), and at the end what came out and the way to it. Built once,
/// updated in place by the window's timer, so nothing flickers and nothing loses its scroll.
/// </summary>
public sealed class GenerationView : DockPanel
{
    private static readonly string[] AllStages = { "start", "baseline", "plan", "attempt", "judge", "light", "gates", "destruction",
                                                   "cover", "done" };

    /// <summary>The run's stages: the ruin's only when the run asked for one (the PO, 07.10).</summary>
    private static string[] StagesOf(Generation g) =>
        (g.Request.Options?.Destruction ?? 0) > 0 ? AllStages : AllStages.Where(s => s != "destruction").ToArray();

    private readonly TextBlock _title = Ui.Title("");
    private readonly TextBlock _now = Ui.Text("", 16);
    private readonly TextBlock _elapsed = Ui.Text("", 13, 0.7);
    private readonly TextBlock _queue = Ui.Text("", 13, 0.7);
    private readonly StackPanel _stages = new() { Spacing = 6, Margin = new Thickness(0, 8, 0, 8) };
    private readonly ProgressBar _attempts = new() { Minimum = 0, Maximum = 1, Height = 8, Margin = new Thickness(0, 2, 0, 10) };
    private readonly TextBlock _attemptsText = Ui.Text("", 13, 0.85);
    private readonly ProgressBar _likeness = new() { Minimum = 0, Maximum = 1, Height = 8, Margin = new Thickness(0, 2, 0, 10) };
    private readonly TextBlock _likenessText = Ui.Text("", 13, 0.85);
    private readonly TextBlock _last = Ui.Text("", 13, 0.85);
    private readonly TextBlock _cpu = Ui.Text("", 12, 0.6);
    private readonly Button _pause = Ui.Button("run.pause", "run.pause.tip", FASymbol.Pause);
    private readonly Button _stop = Ui.Button("run.stop", "run.stop.tip", FASymbol.Stop);
    /* the PO, 05.10: a generation not wanted is cancelled - stopped and its files deleted; a stopped one deleted */
    private readonly Button _cancel = Ui.Button("run.cancel", "run.cancel.tip", FASymbol.Cancel);
    private readonly Button _delete = Ui.Button("gen.interrupted.delete", "gen.interrupted.delete.tip", FASymbol.Delete);
    private readonly Button _again = Ui.Button("run.again", "run.again.tip", FASymbol.Add, accent: true);
    private readonly Button _continue = Ui.Button("run.continue", "run.continue.tip", FASymbol.Play, accent: true);
    private readonly Button _open = Ui.Button("run.open", "run.open.tip", FASymbol.Library);
    private readonly FAInfoBar _outcome = new() { IsClosable = false, IsOpen = false };
    private readonly TextBox _log = new() { IsReadOnly = true, AcceptsReturn = true, FontFamily = new FontFamily("Consolas,monospace"),
                                            FontSize = 11, MinHeight = 160, TextWrapping = TextWrapping.NoWrap,
                                            VerticalAlignment = VerticalAlignment.Stretch };
    /* row 410 (the PO 05.10): the log reaches the window's bottom and follows its size - the view is a dock, its
       top the run's account, the log the rest */
    private readonly StackPanel _top = new() { Spacing = 4 };
    private readonly LoadMeter _meter = new();
    private readonly TextBlock _plan = new() { FontSize = 13, Opacity = 0.75, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _memory = new() { FontSize = 13, Opacity = 0.75, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _planDone = new() { FontSize = 13, Opacity = 0.75, TextWrapping = TextWrapping.Wrap };
    private readonly TextBlock _bases = new() { FontSize = 15, Opacity = 0.85, TextWrapping = TextWrapping.Wrap };
    private readonly SchemePanel _scheme = new(() => Generation.Current);
    public SchemePanel Scheme => _scheme;
    private readonly Action<string> _openMap;
    private Generation? _g;

    public GenerationView(Action again, Action<string> openMap)
    {
        _openMap = openMap;
        LastChildFill = true;
        // row 410: the run's account on the left, the machine's load beside it (the PO 05.10)
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto") };
        head.Children.Add(_top);
        _meter.VerticalAlignment = VerticalAlignment.Top;
        _meter.Margin = new Thickness(24, 8, 0, 0);
        Grid.SetColumn(_meter, 1);
        head.Children.Add(_meter);
        DockPanel.SetDock(head, Dock.Top);
        Children.Add(head);
        var top = _top.Children;
        top.Add(_title);
        top.Add(_bases);
        top.Add(_now);
        top.Add(_elapsed);
        top.Add(_queue);
        top.Add(_outcome);
        top.Add(Ui.Section(Loc.T("run.stages")));
        top.Add(_stages);
        top.Add(_plan);
        top.Add(_planDone);
        top.Add(_memory);
        top.Add(_attemptsText);
        top.Add(_attempts.Tip("run.attempts.tip"));
        top.Add(_likenessText);
        top.Add(_likeness.Tip("run.likeness.tip"));
        top.Add(_last);
        top.Add(_cpu);
        var buttons = new WrapPanel { Margin = new Thickness(0, 12, 0, 0) };
        foreach (var b in new[] { _pause, _stop, _cancel, _continue, _delete, _again, _open })
        {
            b.Margin = new Thickness(0, 0, 8, 8);
            buttons.Children.Add(b);
        }
        top.Add(buttons);
        // row 410: the plan of the build and the log, as tabs filling the rest of the window - the plan first
        // (the PO 05.10: «в отдельной вкладке перед подробным журналом»)
        var tabs = new TabControl { Margin = new Thickness(0, 8, 0, 0), VerticalAlignment = VerticalAlignment.Stretch };
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
        _plan.Text = g.PlanMade;
        _plan.IsVisible = g.PlanMade.Length > 0;
        _planDone.Text = g.PlanDone();
        _planDone.IsVisible = _planDone.Text.Length > 0;
        _memory.Text = g.MemoryNote;
        _memory.IsVisible = g.MemoryNote.Length > 0;
        _scheme.Update(g);
        _title.Text = Loc.F("run.title", g.Request.Name);
        // row 410: what the map is made from, plainly - the PO's mg_10_42 was q2dm1's without his knowing
        _bases.Text = g.Request.Grafts is { Count: > 0 } grafts
            ? Loc.F("run.base.grafts", g.Request.Donor, string.Join(", ", grafts))
            : Loc.F("run.base", g.Request.Donor);
        _now.Text = g.Running
            ? (g.Paused ? Loc.T("run.now.paused") : Loc.T($"stage.{g.Stage}.now"))
            : g.Error.Length > 0 ? Loc.T("run.now.failed") : Loc.T("run.now.done");
        var end = g.Ended ?? DateTime.Now;
        // row 410 (the PO 05.10): the time of the whole run and of each stage, hours, minutes and seconds; a
        // finished stage says when it ended and how long it took; the edits say how long they have left, from the
        // pace of the builds so far - recomputed every beat, so it follows a run that slows or speeds up
        var eta = EditsLeft(g);
        _elapsed.Text = RunLine(g);
        _queue.Text = Generation.Queue.Count > 0
            ? Loc.F("run.queue", string.Join(", ", Generation.Queue.Select(q => $"{q.Name} ({q.Donor})")))
            : "";
        _queue.IsVisible = _queue.Text.Length > 0;
        _stages.Children.Clear();
        // a resumed run replays its ledger: that is the edits stage, gone through again (the PO 05.10 saw every
        // stage waiting while it replayed)
        var Stages = StagesOf(g);
        var at = Array.IndexOf(Stages, g.Stage is "failed" or "stopped" ? "done" : g.Stage == "resume" ? "attempt" : g.Stage);
        // a run that failed: done is what it passed, the stage it stopped in is crossed out, the rest not reached
        // (the PO's koldduel1, 05.10: refused at its base map's rebuild, every stage showed a tick)
        var runFailed = !g.Running && g.Error.Length > 0;
        var reached = -1;
        for (var i = 0; i < Stages.Length - 1; i++)
            if (g.StageBegan.ContainsKey(Stages[i]))
                reached = i;
        for (var i = 0; i < Stages.Length; i++)
        {
            var key = Stages[i];
            var broke = runFailed && i == reached;
            var done = runFailed ? i < reached : i < at || (!g.Running && g.Error.Length == 0);
            var now = g.Running && i == at;
            var since = g.StageBegan.TryGetValue(key, out var t) ? t : (DateTime?)null;
            var next = i + 1 < Stages.Length && g.StageBegan.TryGetValue(Stages[i + 1], out var tn) ? tn : (DateTime?)null;
            // a stage's end is the next stage's beginning, or the run's end for the last one it went through
            DateTime? until = next ?? (done && !g.Running ? g.Ended : null);
            var time = since == null ? ""
                     : done && until != null ? Loc.F("run.stage.done", Dur(g.Worked(since.Value, until.Value)),
                                                     until.Value.ToString("dd.MM HH:mm:ss"))
                     : now ? StageNow(g, key, since.Value, eta)
                     : "";
            _stages.Children.Add(new StackPanel
            {
                Orientation = Orientation.Horizontal, Spacing = 10,
                Children =
                {
                    new FASymbolIcon
                    {
                        Symbol = done ? FASymbol.Accept : broke ? FASymbol.Cancel
                               : now ? (g.Paused ? FASymbol.Pause : FASymbol.Play) : FASymbol.Clock,
                        FontSize = 16, Opacity = done || now || broke ? 1.0 : 0.4,
                    },
                    new TextBlock
                    {
                        Text = Loc.T($"stage.{key}"), FontSize = 14, Opacity = done || now || broke ? 1.0 : 0.55,
                        FontWeight = now ? FontWeight.SemiBold : FontWeight.Normal, MinWidth = 280,
                    },
                    new TextBlock { Text = time, FontSize = 12, Opacity = 0.6, VerticalAlignment = VerticalAlignment.Center },
                },
            }.Tip($"stage.{key}.tip"));
        }
        _attempts.Maximum = Math.Max(1, g.Budget);
        _attempts.Value = Math.Min(g.Compiles, g.Budget);
        _attemptsText.Text = g.Budget > 0 ? Loc.F("run.attempts", g.Accepted, g.Compiles, g.Budget, g.Attempts) : Loc.T("run.attempts.wait");
        _likeness.Maximum = Math.Max(1, g.Target);
        _likeness.Value = Math.Min(g.Divergence, g.Target);
        _likenessText.Text = g.Target > 0 ? Loc.F("run.likeness", g.Divergence / 10, g.Target / 10) : "";
        _last.Text = g.LastFamily.Length > 0
            ? Loc.F("run.last", Loc.Has($"kind.{g.LastFamily}") ? Loc.T($"kind.{g.LastFamily}") : g.LastFamily, Loc.T(g.LastVerdict == "ACCEPTED" ? "verdict.accepted" : "verdict.rejected"))
            : "";
        _cpu.Text = g.CpuShare > 0 ? Loc.F("run.cpu", g.CpuShare) : "";
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
                var failed = g.Gates.Count(x => !x.pass);
                _outcome.Severity = failed == 0 ? FAInfoBarSeverity.Success : FAInfoBarSeverity.Warning;
                _outcome.Title = Loc.F("run.done.title", g.LibraryName);
                _outcome.Message = g.Gates.Count == 0 ? Loc.T("run.done.nogates")
                                 : failed == 0 ? Loc.F("run.done.gates", g.Gates.Count)
                                 : Loc.F("run.done.gatesfail", failed, g.Gates.Count);
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
    /// The stage under way in one line - its name and its time (the full-screen plan's overlay: the PO, 05.10, «без
    /// уже законченных шагов - только текущий»).
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
            // the likeness reached ends the edits too: the builds that takes at the recent gain per build
            var gain = (double)(seen[^1].divergence - seen[from].divergence) / n;
            if (gain > 0 && g.Target > g.Divergence)
                builds = Math.Min(builds, Math.Ceiling((g.Target - g.Divergence) / gain));
        }
        else if (g.StageBegan.TryGetValue("attempt", out var began) && seen[0].at > began)
            each = g.Worked(began, seen[0].at).TotalSeconds;
        else
            return null;
        var left = builds * each - g.Worked(seen[^1].at, DateTime.Now).TotalSeconds;
        return TimeSpan.FromSeconds(Math.Max(0, left));
    }
}
