using Avalonia.LogicalTree;
using System.Text;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Presenters;
using Avalonia.Layout;
using Avalonia.VisualTree;

namespace MapgenStudio;

/// <summary>
/// The PO, 04.11 (Studio 3.40, the Generate page of a map from scratch on his wide screen): «посмотри как залазит текст
/// друг на друга» - the cards «Для кого» and «Размер и форма» were cut to the height of the column beside them and drew
/// under «Переходы»; the self-test laid every page out 1180 wide, where the cards stand in one column, and never saw it.
/// And: «откуда например Переделка основы в новой карте? ... проверяй всё такое». Two questions, asked of every screen:
/// * at 1180 (one column) and 1920 (two) wide, no text is drawn over another;
/// * every screen of a map from scratch - its Generate page, its run at each stage, the strip and the home page while it
///   runs, its tile and its card in the library - says nothing of a base: it has none. Folded sections are opened and
///   the tips read too (the PO opens them).
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>Brief 28 D0 (the PO 06.11: «на других экранах должна быть адаптивная верстка тоже, у нас 27 год на
    /// носу»): the screens people have, in the window's own units - the start, a laptop, 1600, 1920, the PO's 3440 at
    /// 150 %, 4K at 150 %, 5120 at 150 %, 3440 at 100 %.</summary>
    private static readonly Size[] ScreenSizes =
    {
        new(1180, 780), new(1366, 768), new(1600, 900), new(1920, 1080), new(2293, 960), new(2560, 1440), new(3413, 1440), new(3440, 1440),
    };

    /// <summary>A base named: «основа/основы/основе…» (not «основной»), «base», «bases», «donor».</summary>
    private static readonly Regex BaseWord = new(@"основ(?!н)|\bbases?\b|\bdonors?\b", RegexOptions.IgnoreCase);

    /// <summary>The texts of a scratch screen that may name a base: the switch's words for the other way to start.</summary>
    private static IEnumerable<string> BaseWordsAllowed() =>
        new[] { "scratch.mode.desc", "scratch.mode.base", "scratch.mode.base.tip",
                // the program's own words on its home page name both ways to start
                "home.intro1", "home.intro2", "home.step1", "home.step2", "home.step3" }.Select(Loc.T);

    /// <summary>A window laid out at a size, its folded sections opened first when asked.</summary>
    private static void LayOut(Window w, Size size, bool unfold)
    {
        // a window never shown lays itself out at the platform's size (2565 x 1029 here), whatever Measure or Width is
        // given - the first run of this check measured every page 2312 wide at «1180» and «1920» alike; and laying the
        // content out again by hand at another width left rows arranged at the first width (a text 808 wide in a card
        // 733 wide). The window's content goes into a frame of the size asked, and the window lays itself out once
        if (w.Content is Control c && (c as Border)?.Tag as string != "selftest-frame")
        {
            w.Content = null;
            w.Content = new Border
            {
                Tag = "selftest-frame", Width = size.Width, Height = size.Height, Child = c,
                HorizontalAlignment = Avalonia.Layout.HorizontalAlignment.Left,
                VerticalAlignment = Avalonia.Layout.VerticalAlignment.Top,
            };
        }
        void Pass()
        {
            w.Measure(Size.Infinity);
            w.Arrange(new Rect(w.DesiredSize));
        }
        Pass();
        if (!unfold)
            return;
        // an opened fold may hold folds of its own, or a tab's content come only on the next pass: open until none is left
        for (var round = 0; round < 4; round++)
        {
            var any = false;
            foreach (var e in w.GetVisualDescendants().OfType<Expander>().ToList())
                if (!e.IsExpanded)
                {
                    // its reveal is animated, and no frame runs in a window never shown: the content would stay hidden
                    e.ContentTransition = null;
                    e.IsExpanded = true;
                    any = true;
                }
            Pass();
            if (!any)
                break;
        }
    }

    private static bool ShownIn(Visual v, Visual root)
    {
        for (Visual? p = v; p != null && p != root; p = p.GetVisualParent())
            if (!p.IsVisible)
                return false;
        return true;
    }

    /// <summary>Every text a window shows, with its box in the window - cut by the lists it scrolls in, not by the page's
    /// own scroller (a text below the window's foot is still on the page).</summary>
    private static List<(TextBlock t, Rect at)> TextBoxes(Window w) => TextBoxesIn(w).Select(x => (x.t, x.at)).ToList();

    /// <summary>The texts with whether each scrolls with the page (inside its outermost scroller) or stands still over it
    /// (the Generate page's foot, the menu): the page passes under the foot, so a text over it is not a fault.</summary>
    private static List<(TextBlock t, Rect at, bool scrolls)> TextBoxesIn(Window w)
    {
        var all = new List<(TextBlock, Rect, bool)>();
        foreach (var v in w.GetVisualDescendants())
        {
            if (v is not TextBlock tb || !ShownIn(tb, w) || tb.Bounds.Width < 2 || tb.Bounds.Height < 2)
                continue;
            if (string.IsNullOrWhiteSpace(CopyText.TextOf(tb)) || tb.TranslatePoint(new Point(0, 0), w) is not { } o)
                continue;
            var box = new Rect(o, tb.Bounds.Size);
            // the clipping parents below the page's own scroller (the outermost one): a list scrolled inside its card
            // cuts its rows, the page's scroller does not (a text below the window's foot is still on the page)
            var chain = new List<Visual>();
            for (var p = tb.GetVisualParent(); p != null && p != w; p = p.GetVisualParent())
                chain.Add(p);
            var pageScroller = chain.FindLastIndex(p => p is ScrollContentPresenter);
            for (var k = 0; k < (pageScroller < 0 ? chain.Count : pageScroller); k++)
                if (chain[k].ClipToBounds && chain[k].TranslatePoint(new Point(0, 0), w) is { } po)
                    box = box.Intersect(new Rect(po, chain[k].Bounds.Size));
            if (box.Width >= 2 && box.Height >= 2)
                all.Add((tb, box, pageScroller >= 0));
        }
        return all;
    }

    /// <summary>The control a text belongs to when a template draws it (a combo box's chosen item, a number box's
    /// figure): two texts of one such control are its own business.</summary>
    private static Visual? Owner(Visual v)
    {
        for (var p = v.GetVisualParent(); p != null; p = p.GetVisualParent())
            if (p is ComboBox or TextBox or ToggleSwitch or Button or Slider or FluentAvalonia.UI.Controls.FANumberBox)
                return p;
        return null;
    }

    /// <summary>One-line texts cut short by the room they were given (05.11: «Отделка: отличие от кар» in a map's card -
    /// its label column narrower than the label): the text wants more width than it has and neither wraps nor ends
    /// with an ellipsis it chose.</summary>
    internal static List<string> CutTexts(Window w)
    {
        var said = new List<string>();
        foreach (var (t, _) in TextBoxes(w))
        {
            if (t.TextWrapping != Avalonia.Media.TextWrapping.NoWrap || t.TextTrimming != Avalonia.Media.TextTrimming.None)
                continue;
            var text = CopyText.TextOf(t);
            if (text.Contains('\n'))
                continue;
            var probe = new TextBlock { Text = text, FontSize = t.FontSize, FontFamily = t.FontFamily, FontWeight = t.FontWeight };
            probe.Measure(Size.Infinity);
            if (probe.DesiredSize.Width > t.Bounds.Width + 2)
                said.Add($"«{Cut(text)}» wants {probe.DesiredSize.Width:0} px, has {t.Bounds.Width:0}");
        }
        return said;
    }

    /// <summary>Texts drawn over one another (3 px and more each way), named by their words.</summary>
    internal static List<string> TextOverlaps(Window w)
    {
        var boxes = TextBoxesIn(w);
        var said = new List<string>();
        for (var i = 0; i < boxes.Count; i++)
            for (var j = i + 1; j < boxes.Count; j++)
            {
                if (boxes[i].scrolls != boxes[j].scrolls)
                    continue;
                var x = boxes[i].at.Intersect(boxes[j].at);
                if (x.Width < 3 || x.Height < 3)
                    continue;
                var (a, c) = (boxes[i].t, boxes[j].t);
                if (a.IsVisualAncestorOf(c) || c.IsVisualAncestorOf(a))
                    continue;
                if (Owner(a) is { } oa && oa == Owner(c))
                    continue;
                said.Add($"«{Cut(CopyText.TextOf(a))}» over «{Cut(CopyText.TextOf(c))}»");
            }
        return said;
    }

    private static string Cut(string s)
    {
        var one = s.ReplaceLineEndings(" ").Trim();
        return one.Length <= 40 ? one : one[..37] + "…";
    }

    /// <summary>Every word a window offers: its texts and its controls' tips.</summary>
    private static List<string> WordsOf(Window w)
    {
        // every text shown, whatever clips it: a fold opened by the check is still unrolling (its reveal is animated, and
        // no frame runs in a window never shown - the first run of this check read no word inside any fold)
        var words = w.GetVisualDescendants().OfType<TextBlock>().Where(t => ShownIn(t, w))
                     .Select(CopyText.TextOf).Where(s => !string.IsNullOrWhiteSpace(s)).ToList();
        // and what a fold holds: a window never shown does not build a fold's content into what it draws (the scheme's
        // legend read 2 texts of its 20), but the content is there - its own controls, shown unless one of them is hidden
        bool LogicallyShown(ILogical l)
        {
            // up to the window, which is never shown itself
            for (var p = l; p != null && !ReferenceEquals(p, w); p = p.LogicalParent)
                if (p is Visual { IsVisible: false })
                    return false;
            return true;
        }
        foreach (var t in w.GetLogicalDescendants().OfType<TextBlock>())
            if (LogicallyShown(t) && CopyText.TextOf(t) is { Length: > 0 } s && !string.IsNullOrWhiteSpace(s))
                words.Add(s);
        foreach (var c in w.GetLogicalDescendants().OfType<Control>())
            if (LogicallyShown(c) && ToolTip.GetTip(c) is { } lt)
                words.Add(lt switch { string s => s, TextBlock t => CopyText.TextOf(t), _ => "" });
        foreach (var v in w.GetVisualDescendants())
            if (v is Control c && ShownIn(c, w) && ToolTip.GetTip(c) is { } tip)
                words.Add(tip switch { string s => s, TextBlock t => CopyText.TextOf(t), _ => "" });
        return words;
    }

    private static List<string> BaseWords(Window w, string? skip = null)
    {
        var allowed = BaseWordsAllowed().ToHashSet();
        if (skip != null)
            allowed.Add(skip);
        return WordsOf(w).Where(s => s.Length > 0 && !allowed.Contains(s) && BaseWord.IsMatch(s))
                         .Distinct().Select(Cut).ToList();
    }

    /// <summary>A copy of the user's from-scratch parameters with every row a choice shows opened.</summary>
    private static ScratchParams EveryRowShown(ScratchParams p)
    {
        var all = ScratchParams.Load(p.Save());
        all.Style = "generated";
        all.Stack = "custom";
        all.Round = "some";
        all.PowerupAccess = "hard";
        // the PO 12.11: the items' rows at their longest words
        all.PrizeAccess = "exposed";
        all.Underwater = 3;
        all.ItemSpacing = "wide";
        all.ItemPractice = "q2duel+koldduel1";
        return all;
    }

    /// <summary>The two questions of every screen; lines into the self-test's report.</summary>
    private static void ScreensSelfTest(StringBuilder b)
    {
        var keepCurrent = Generation.Current;
        var keepScratch = App.Settings.ScratchMode;
        var keepParams = App.Settings.Scratch;
        try
        {
            foreach (var lang in new[] { "ru", "en" })
            {
                Loc.Language = lang;
                Generation.Current = keepCurrent;       // the run of the language before is not this language's pages'
                var maps = Library.Scan(App.Settings);
                var scratchMap = maps.FirstOrDefault(m => m.Scratch != null);
                // 1. no text over another, every page, both widths
                foreach (var page in new[] { "home", "generate", "generate-scratch", "library", "map", "map-scratch", "settings", "about" })
                    foreach (var size in ScreenSizes)
                    {
                        App.Settings.ScratchMode = page == "generate-scratch";
                        var open = page == "map" ? maps.FirstOrDefault(m => m.Scratch == null) ?? maps.FirstOrDefault()
                                 : page == "map-scratch" ? scratchMap : null;
                        if (page.StartsWith("map") && open == null)
                        {
                            b.AppendLine($"SKIP {lang} {page} {size.Width}: no such map in the library");
                            continue;
                        }
                        var w = new MainWindow { _page = page.StartsWith("map") ? "library" : page.StartsWith("generate") ? "generate" : page, _openMap = open };
                        var donors = Engine.Donors();
                        if (donors.Count > 0)
                            w._chosen.Add(donors[0]);
                        w.Rebuild();
                        LayOut(w, size, unfold: false);
                        var over = TextOverlaps(w);
                        var cut = CutTexts(w);
                        b.AppendLine(over.Count == 0 && cut.Count == 0
                            ? $"PASS {lang} {page} at {size.Width}: no text over another, none cut short ({TextBoxes(w).Count} texts)"
                            : $"FAIL {lang} {page} at {size.Width}: "
                              + (over.Count > 0 ? $"text over text: {string.Join("; ", over.Take(4))}{(over.Count > 4 ? $" (+{over.Count - 4})" : "")} " : "")
                              + (cut.Count > 0 ? $"cut short: {string.Join("; ", cut.Take(4))}{(cut.Count > 4 ? $" (+{cut.Count - 4})" : "")}" : ""));
                    }
                // 1b. the settings page with long paths at every width: his self-test 06.11 (3.54) - a long Python path
                // beside its two buttons ran into the next card at three columns; the side copy's short path never showed it
                {
                    var st = App.Settings;
                    var keepPaths = (st.ClientDir, st.MapsDir, st.BspDir, st.TempDir);
                    const string longDir = @"D:\Games\Quake II\a player's folder with a rather long name\q2pro-release-with-a-long-name";
                    var bad = new List<string>();
                    try
                    {
                        PythonShownForTest = @"C:\Users\someone.with.a.long.name\AppData\Local\Programs\Python\Python314\python.exe";
                        (st.ClientDir, st.MapsDir, st.BspDir, st.TempDir) = (longDir, longDir + @"\maps", longDir + @"\bsp", longDir + @"\temp");
                        foreach (var size in ScreenSizes)
                        {
                            var w = new MainWindow { _page = "settings" };
                            w.Rebuild();
                            LayOut(w, size, unfold: false);
                            var over = TextOverlaps(w);
                            var cut = CutTexts(w);
                            if (over.Count + cut.Count > 0)
                                bad.Add($"{size.Width}: {string.Join("; ", over.Concat(cut).Take(2))}");
                        }
                    }
                    finally
                    {
                        PythonShownForTest = null;
                        (st.ClientDir, st.MapsDir, st.BspDir, st.TempDir) = keepPaths;
                    }
                    b.AppendLine(bad.Count == 0 ? $"PASS {lang} settings with long paths: {ScreenSizes.Length} widths - no text over another, none cut short"
                                                : $"FAIL {lang} settings with long paths: {string.Join(" | ", bad.Take(3))}");
                }
                // 2. a map from scratch says nothing of a base - its Generate page (as the user's settings have it, and with
                // every row a choice shows: the Studio's own textures, a custom stack, round shapes - the PO's own
                // settings showed the English «base - concrete, panels…» of a texture theme the default ones never
                // opened, 05.11), its tile and card
                foreach (var page in new[] { "generate-scratch", "generate-scratch-all", "library", "map-scratch" })
                {
                    App.Settings.Scratch = page == "generate-scratch-all" ? EveryRowShown(keepParams) : keepParams;
                    var pageOf = page == "generate-scratch-all" ? "generate-scratch" : page;
                    if (pageOf != "generate-scratch" && scratchMap == null)
                    {
                        b.AppendLine($"SKIP {lang} {page}: no map from scratch in the library");
                        continue;
                    }
                    App.Settings.ScratchMode = pageOf == "generate-scratch";
                    Window w;
                    if (page == "library")
                    {
                        // its tile alone: the library's own words (its search «по имени или основе») are every map's
                        var mw = new MainWindow();
                        w = new Window { Content = mw.MapCard(scratchMap!) };
                    }
                    else
                    {
                        var mw = new MainWindow { _page = pageOf == "generate-scratch" ? "generate" : "library", _openMap = page == "map-scratch" ? scratchMap : null };
                        mw.Rebuild();
                        w = mw;
                    }
                    LayOut(w, ScreenSizes[1], unfold: true);
                    // the card's description is the file its build wrote; this build's is asked below
                    var said = BaseWords(w, page == "map-scratch" ? scratchMap!.Description : null);
                    b.AppendLine(said.Count == 0 ? $"PASS {lang} {page}: a map from scratch - no word of a base"
                                                 : $"FAIL {lang} {page}: a map from scratch named a base: {string.Join(" | ", said.Take(6))}{(said.Count > 6 ? $" (+{said.Count - 6})" : "")}");
                }
                // ... the description this build writes for one (the record's asked-and-made table aside: it is the run's)
                {
                    var g = Generation.ForSelfTest(App.Settings, "done");
                    var text = Describe.Map(g, lang);
                    var hits = text.Split('\n').Where(l => BaseWord.IsMatch(l)).Select(Cut).ToList();
                    b.AppendLine(hits.Count == 0 ? $"PASS {lang} description of a map from scratch: no word of a base ({text.Split('\n').Length} lines)"
                                                 : $"FAIL {lang} description of a map from scratch named a base: {string.Join(" | ", hits.Take(6))}");
                }
                // ... the scheme's legend as a run from scratch says it (the run page's scheme tab is not built in a window
                // never shown - its legend is asked by itself)
                {
                    var legend = SchemeLegend.Make();
                    SchemeLegend.Say(legend, true);
                    var lw = new Window { Content = legend };
                    LayOut(lw, ScreenSizes[1], unfold: true);
                    var said = BaseWords(lw);
                    var seen = WordsOf(lw).Contains(Loc.T("legend.base.s"));
                    b.AppendLine(said.Count == 0 && seen ? $"PASS {lang} the scheme's legend of a run from scratch: «{Loc.T("legend.base.s")}», no word of a base"
                                                         : $"FAIL {lang} the scheme's legend of a run from scratch: {(seen ? "" : "its own sign not shown; ")}{string.Join(" | ", said.Take(6))}"
                                                           );
                    SchemeLegend.Say(legend, false);
                }
                // 3. the PO, 05.11 («интерфейс перегружается и перекидывает наверх окна»): the generate page built again in
                // its place (a choice that shows or hides rows) stays where it was scrolled to
                {
                    App.Settings.ScratchMode = true;
                    Generation.Current = null;
                    var sw = new MainWindow { _page = "generate" };
                    sw.Rebuild();
                    LayOut(sw, ScreenSizes[0], unfold: false);
                    var first = PageScroller(sw._content.Content as Control);
                    var room = first == null ? 0 : first.Extent.Height - first.Viewport.Height;
                    var asked = Math.Min(600, room / 2);
                    if (first != null)
                        first.Offset = new Vector(0, asked);
                    LayOut(sw, ScreenSizes[0], unfold: false);
                    var before = first?.Offset.Y ?? 0;
                    sw.ShowPage();
                    for (var k = 0; k < 10; k++)
                    {
                        // a window never shown measures nothing new by itself: the swapped page's way up made invalid,
                        // as a shown window's layout pass finds it (its first try read the new page 0 high)
                        for (Visual? v = sw._content; v != null; v = v.GetVisualParent())
                            (v as Layoutable)?.InvalidateMeasure();
                        LayOut(sw, ScreenSizes[0], unfold: false);
                        sw.UpdateLayout();
                    }
                    var again = PageScroller(sw._content.Content as Control);
                    var after = again?.Offset.Y ?? -1;
                    // brief 22 D5: and the form shown after a run's page starts at its top
                    {
                        var g0 = Generation.ForSelfTest(App.Settings, "attempt");
                        Generation.Current = g0;
                        // a low window: the run page's left column has room to scroll
                        var low = new Size(1180, 360);
                        var rw = new MainWindow { _page = "generate" };
                        rw.Rebuild();
                        LayOut(rw, low, unfold: false);
                        var runScroll = PageScroller(rw._content.Content as Control);
                        if (runScroll != null)
                        {
                            var runRoom = runScroll.Extent.Height - runScroll.Viewport.Height;
                            runScroll.Offset = new Vector(0, Math.Max(0, Math.Min(400, runRoom)));
                        }
                        LayOut(rw, low, unfold: false);
                        var runWas = runScroll?.Offset.Y ?? 0;
                        Generation.Current = null;
                        rw.ShowPage();
                        for (var k = 0; k < 6; k++)
                        {
                            for (Visual? v = rw._content; v != null; v = v.GetVisualParent())
                                (v as Layoutable)?.InvalidateMeasure();
                            LayOut(rw, low, unfold: false);
                            rw.UpdateLayout();
                        }
                        var formAt = PageScroller(rw._content.Content as Control)?.Offset.Y ?? -1;
                        // the run's page scrolled first, or the row proves nothing
                        b.AppendLine(runWas > 0 && formAt == 0
                            ? $"PASS {lang} the form shown after a run's page starts at its top"
                            : $"FAIL {lang} the form shown after a run's page (scrolled {runWas:0}) starts at {formAt:0}, not its top");
                    }
                    b.AppendLine(before > 0 && again != null && !ReferenceEquals(again, first) && Math.Abs(after - before) < 2
                        ? $"PASS {lang} the generate page built again keeps its scroll ({before:0} -> {after:0})"
                        : $"FAIL {lang} the generate page built again keeps its scroll: {before:0} -> {after:0} (room {room:0}; {sw._scrollNote}; {sw._scrollLast}; now extent {again?.Extent.Height:0} viewport {again?.Viewport.Height:0} same {ReferenceEquals(again, PageScroller(sw._content.Content as Control))})");
                }
                // ... its run, at each stage, and the strip and home page while it runs
                App.Settings.ScratchMode = true;
                foreach (var stage in new[] { "scratch", "start", "baseline", "plan", "attempt", "light", "gates", "cover", "done" })
                {
                    var g = Generation.ForSelfTest(App.Settings, stage);
                    // the share a real run has from its first poll: the load box's header is its long form (3.50 had the
                    // self-test's runs at «Загрузка» alone, and «…разрешено до 80 % (12 из» was cut on the PO's screen)
                    g.ApplyShare();
                    Generation.Current = g;
                    foreach (var page in new[] { "generate", "home" })
                    {
                        var w = new MainWindow { _page = page };
                        w.Rebuild();
                        LayOut(w, ScreenSizes[1], unfold: true);
                        var said = BaseWords(w);
                        var over = page == "generate" ? TextOverlaps(w) : new List<string>();
                        // the PO 06.11 («и здесь у тебя не помещается»): the run page too has no text cut short - the
                        // check of 05.11 ran on the form's pages only
                        if (page == "generate")
                            over.AddRange(CutTexts(w).Select(c => "cut short: " + c));
                        if (page == "generate" && stage == "scratch")
                        {
                            // the PO, 05.11: the run's parameters on its page - the generate page's cards, to look at only
                            var tab = w.GetLogicalDescendants().OfType<TabItem>().FirstOrDefault(t => t.Header as string == Loc.T("run.params.tab"));
                            // brief 22 D2: every kind of input counted by name - the check boxes (the mechanics, the cycle,
                            // the style's maps, the round kinds) and switches too, not only what derives from a button
                            var inputs = (tab?.Content as Control)?.GetLogicalDescendants().OfType<Control>()
                                         .Where(c => c is ComboBox or Button or CheckBox or ToggleSwitch or RadioButton
                                                     or Avalonia.Controls.Primitives.ToggleButton or Slider or TextBox or NumericUpDown
                                                     or FluentAvalonia.UI.Controls.FANumberBox).ToList() ?? new List<Control>();
                            var combos = inputs.OfType<ComboBox>().Count();
                            var boxes = inputs.OfType<CheckBox>().Count();
                            var live = inputs.Where(c => c.IsEnabled).Select(c => c.GetType().Name).ToList();
                            b.AppendLine(tab != null && combos >= 20 && boxes >= 10 && live.Count == 0
                                ? $"PASS {lang} the run page's «{Loc.T("run.params.tab")}»: the run's parameters, {combos} choices and {boxes} check boxes, none can be changed"
                                : $"FAIL {lang} the run page's parameters: tab {(tab != null ? "shown" : "missing")}, {combos} choices, {boxes} check boxes, "
                                  + $"{live.Count} can be changed ({string.Join(", ", live.GroupBy(n => n).Select(g => $"{g.Key} {g.Count()}"))})");
                        }
                        // brief 24 D1: a new map's run shows «Ход работы», never its difference from the skeleton
                        // the home page's own steps name both kinds of map: there the strip is what the run says
                        var diffSaid = (page == "generate" ? WordsOf(w) : new List<string> { w._strip.Line2 })
                                       .Where(x => x.Contains("тличи", StringComparison.OrdinalIgnoreCase)
                                                   || x.Contains("difference", StringComparison.OrdinalIgnoreCase))
                                       .Distinct().Select(Cut).ToList();
                        var progShown = page != "generate"
                                        || w.GetLogicalDescendants().OfType<Border>().Any(x => x.Tag as string == "run-progress" && x.IsVisible);
                        b.AppendLine(diffSaid.Count == 0 && progShown
                            ? $"PASS {lang} scratch run at «{stage}», {(page == "generate" ? "run page" : "home page and strip")}: "
                              + (page == "generate" ? "«Ход работы» shown, " : "") + "no word of a difference"
                            : $"FAIL {lang} scratch run at «{stage}», {page}: progress card {(progShown ? "shown" : "MISSING")}, "
                              + $"a difference said: {string.Join(" | ", diffSaid.Take(4))}");
                        var where = page == "generate" ? "run page" : "home page and strip";
                        b.AppendLine(said.Count == 0 && over.Count == 0
                            ? $"PASS {lang} scratch run at «{stage}», {where}: no word of a base, no text over another"
                            : $"FAIL {lang} scratch run at «{stage}», {where}: "
                              + (said.Count > 0 ? $"named a base: {string.Join(" | ", said.Take(6))}{(said.Count > 6 ? $" (+{said.Count - 6})" : "")}" : "")
                              + (over.Count > 0 ? $" text over text: {string.Join("; ", over.Take(3))}" : ""));
                    }
                }
            }
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the screens' check threw: {ex.GetType().Name}: {ex.Message}");
        }
        finally
        {
            Generation.Current = keepCurrent;
            App.Settings.ScratchMode = keepScratch;
            App.Settings.Scratch = keepParams;
        }
    }
}
