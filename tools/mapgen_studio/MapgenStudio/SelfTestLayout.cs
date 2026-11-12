using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.LogicalTree;
using Avalonia.VisualTree;

namespace MapgenStudio;

/// <summary>
/// Briefs 27 and 28 (the PO 06.11): «Выглядит как косяк UI, хотя я четко требовал делать диагностику багов UI … у нас 27
/// год на носу» and «вместо "Не пройдено" надо писать кол-во пройденных и кол-во не пройденных». The diagnosis rule: every
/// new control → every page it is on → every width of <see cref="ScreenSizes"/> → the three questions: no text over
/// another, none cut short, no column ending far above its neighbour. Here the columns, the new-map form for every
/// shape, the run view's panes, the window's remembered place and the checks' chips.
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>The blank a balanced panel may leave under its shorter columns, of its whole area.</summary>
    internal const double BlankShareMax = 0.15;

    /// <summary>
    /// The columns of every card panel the window shows: a <see cref="BalancedColumns"/>' own, or the two stacks of a
    /// 3.53 <see cref="ColumnsPanel"/> (its RED). Each: the columns' bottoms and their last cards' heights.
    /// </summary>
    private static List<(string what, double[] bottoms, double[] lastCard)> CardColumns(Window w)
    {
        var all = new List<(string, double[], double[])>();
        foreach (var v in w.GetVisualDescendants())
        {
            if (v is BalancedColumns bc && ShownIn(bc, w) && bc.Columns >= 2)
            {
                var n = bc.Columns;
                var last = new double[n];
                for (var i = 0; i < bc.Children.Count; i++)
                    if (bc.ColumnOf[i] >= 0)
                        last[bc.ColumnOf[i]] = bc.Children[i].Bounds.Height;
                all.Add(($"balanced, {bc.ColumnOf.Count(k => k >= 0)} cards", bc.Bottoms.ToArray(), last));
            }
            else if (v is ColumnsPanel cp && ShownIn(cp, w) && cp.Children.Count == 2
                     && Math.Abs(cp.Children[0].Bounds.Y - cp.Children[1].Bounds.Y) < 1 && cp.Children[1].Bounds.X > cp.Children[0].Bounds.X + 10)
            {
                // brief 29: as arranged - a card that follows its neighbour's height (the bases' card, LeftFollowsRight) is drawn
                // that tall; its own wish (125 on a Studio with no bases) read as a 43 % blank that is not on the screen
                var bottoms = cp.Children.Select(c => c.Bounds.Height).ToArray();
                var last = cp.Children.Select(c => c is StackPanel sp && sp.Children.Count > 0 ? sp.Children[^1].Bounds.Height : c.Bounds.Height).ToArray();
                var cards = cp.Children.Sum(c => c is StackPanel sp ? sp.Children.Count : 1);
                all.Add(($"two columns, {cards} cards", bottoms, last));
            }
        }
        return all;
    }

    /// <summary>Brief 28 D4: no column ends more than its own last card above the tallest one (the dealing's promise),
    /// and the blank under the shorter columns is at most <see cref="BlankShareMax"/> of the panel.</summary>
    private static (bool ok, double worstBlank, string said) ColumnsEven(Window w)
    {
        var bad = new List<string>();
        double worst = 0;
        foreach (var (what, bottoms, last) in CardColumns(w))
        {
            var max = bottoms.Max();
            if (max <= 0)
                continue;
            var tall = Array.IndexOf(bottoms, max);
            var spread = max - bottoms.Min();
            var blank = bottoms.Sum(x => max - x) / (bottoms.Length * max);
            worst = Math.Max(worst, blank);
            // a few big cards side by side (no more than one over the columns) have nothing to deal: the blank is theirs
            var cards = int.Parse(System.Text.RegularExpressions.Regex.Match(what, @"(\d+) cards").Groups[1].Value);
            // a tallest column of one card (the items' card with a stack of its own, the PO's settings 07.11: 2100 against
            // 1635..1752) has nothing to deal - no card can be split; its blank is the card's, not the dealing's
            var alone = last[tall] >= max - 1;
            if (spread > last[tall] + 19 || (blank > BlankShareMax && cards > bottoms.Length + 1 && !alone))
                bad.Add($"{what}: columns end at {string.Join(" / ", bottoms.Select(x => x.ToString("0")))}, blank {blank:P0}");
        }
        return (bad.Count == 0, worst, string.Join("; ", bad.Take(3)));
    }

    /// <summary>
    /// Brief 28 D5: pictures of the pages as the window lays them out (`--layout-shots DIR`): the new-map form for open
    /// space and the tower, the library, a map's page, the run view - at the PO's 2293 wide, tall enough to hold the page.
    /// </summary>
    internal static List<string> LayoutShots(string dir)
    {
        Directory.CreateDirectory(dir);
        var s = App.Settings;
        var keepScratch = s.Scratch;
        var keepMode = s.ScratchMode;
        var said = new List<string>();
        void Shot(string name, MainWindow w, Size size)
        {
            LayOut(w, size, unfold: false);
            if (w.Content is not Control frame)
                return;
            var bmp = new Avalonia.Media.Imaging.RenderTargetBitmap(new PixelSize((int)size.Width, (int)size.Height), new Vector(96, 96));
            bmp.Render(frame);
            var path = Path.Combine(dir, name + ".png");
            bmp.Save(path);
            said.Add(path);
        }
        try
        {
            foreach (var shape in new[] { "space", "tower" })
            {
                s.ScratchMode = true;
                var p = ScratchParams.Load(keepScratch.Save());
                p.Shape = shape;
                s.Scratch = p;
                var w = new MainWindow { _page = "generate" };
                w.Rebuild();
                Shot($"form_{shape}_2293", w, new Size(2293, 2600));
            }
            s.Scratch = keepScratch;
            s.ScratchMode = keepMode;
            var lib = new MainWindow { _page = "library" };
            lib.Rebuild();
            Shot("library_2293", lib, new Size(2293, 960));
            var map = Library.Scan(s).FirstOrDefault(m => m.Scratch != null) ?? Library.Scan(s).FirstOrDefault();
            if (map != null)
            {
                var mw = new MainWindow { _page = "library", _openMap = map };
                mw.Rebuild();
                Shot($"map_{map.Name}_3440", mw, new Size(3440, 1440));
                var nw = new MainWindow { _page = "library", _openMap = map };
                nw.Rebuild();
                Shot($"map_{map.Name}_1180", nw, new Size(1180, 1400));
            }
            Generation.Current = Generation.ForSelfTest(s, "attempt", true);
            var rw = new MainWindow { _page = "generate" };
            rw.Rebuild();
            Shot("run_3440", rw, new Size(3440, 1440));
            Generation.Current = null;
        }
        finally
        {
            s.Scratch = keepScratch;
            s.ScratchMode = keepMode;
        }
        return said;
    }

    internal static void LayoutSelfTest(StringBuilder b)
    {
        var s = App.Settings;
        var keepLang = Loc.Language;
        var keepScratch = s.Scratch;
        var keepMode = s.ScratchMode;
        var keepCurrent = Generation.Current;
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        try
        {
            Generation.Current = null;
            // 1. the new-map form, every shape (and every row a choice shows), every width, both languages
            foreach (var lang in new[] { "ru", "en" })
            {
                Loc.Language = lang;
                foreach (var shape in new[] { "halves", "arena", "ring", "space", "tower", "all" })
                {
                    var bad = new List<string>();
                    double worst = 0;
                    var worstAt = 0.0;
                    foreach (var size in ScreenSizes)
                    {
                        s.ScratchMode = true;
                        var p = ScratchParams.Load(keepScratch.Save());
                        if (shape == "all")
                            p = EveryRowShown(p);
                        else
                            p.Shape = shape;
                        s.Scratch = p;
                        var w = new MainWindow { _page = "generate" };
                        w.Rebuild();
                        LayOut(w, size, unfold: false);
                        var over = TextOverlaps(w);
                        var cut = CutTexts(w);
                        var (even, blank, said) = ColumnsEven(w);
                        if (blank > worst)
                        {
                            worst = blank;
                            worstAt = size.Width;
                        }
                        if (over.Count > 0)
                            bad.Add($"{size.Width}: text over text {string.Join("; ", over.Take(2))}");
                        if (cut.Count > 0)
                            bad.Add($"{size.Width}: cut {string.Join("; ", cut.Take(2))}");
                        if (!even)
                            bad.Add($"{size.Width}: {said}");
                    }
                    Row(bad.Count == 0,
                        $"{lang} the new-map form, shape {shape}: {ScreenSizes.Length} widths - no text over another, none cut, the columns even (the most blank {worst:P0} at {worstAt})",
                        $"{lang} the new-map form, shape {shape}: {string.Join(" | ", bad.Take(4))}{(bad.Count > 4 ? $" (+{bad.Count - 4})" : "")}");
                }
            }
            Loc.Language = keepLang;
            // 2. RED: the 3.53 arrangement with «Открытый космос» at 1920 must fail the columns' row
            {
                s.ScratchMode = true;
                var p = ScratchParams.Load(keepScratch.Save());
                p.Shape = "space";
                s.Scratch = p;
                OldFormLayout = true;
                try
                {
                    var w = new MainWindow { _page = "generate" };
                    w.Rebuild();
                    LayOut(w, new Size(1920, 1080), unfold: false);
                    var (even, blank, said) = ColumnsEven(w);
                    Row(!even, $"RED: the 3.53 form with «Открытый космос» at 1920 fails the columns' row ({said})",
                        $"RED: the 3.53 form with «Открытый космос» at 1920 passes the columns' row (blank {blank:P0}) - the row cannot see the PO's field");
                }
                finally
                {
                    OldFormLayout = false;
                }
            }
            // 3. every page with card columns, every width: the columns even
            {
                var bad = new List<string>();
                var counted = 0;
                var maps = Library.Scan(s);
                foreach (var page in new[] { "home", "generate", "settings", "map" })
                    foreach (var size in ScreenSizes)
                    {
                        s.ScratchMode = false;
                        s.Scratch = keepScratch;
                        var open = page == "map" ? maps.FirstOrDefault() : null;
                        if (page == "map" && open == null)
                            continue;
                        var w = new MainWindow { _page = page == "map" ? "library" : page, _openMap = open };
                        var donors = Engine.Donors();
                        if (donors.Count > 0)
                            w._chosen.Add(donors[0]);
                        w.Rebuild();
                        LayOut(w, size, unfold: false);
                        var (even, _, said) = ColumnsEven(w);
                        counted++;
                        if (!even)
                            bad.Add($"{page} {size.Width}: {said}");
                    }
                Row(bad.Count == 0, $"the card columns of the home, generate, settings and map pages even at every width ({counted} layouts)",
                    $"the card columns: {string.Join(" | ", bad.Take(4))}");
            }
            // 4. the run view (the PO 06.11: «подробный журнал вернуть в таб после параметров, а карту растянуть на свободную
            // область справа»): at every width the log a tab after the parameters, the scheme the right pane's whole width;
            // RED first - the 3.54-3.55 way put the log beside the scheme from 1500 wide
            {
                (GenerationView? view, MainWindow w) Run(Size size)
                {
                    var g = Generation.ForSelfTest(s, "attempt", true);
                    Generation.Current = g;
                    var w = new MainWindow { _page = "generate" };
                    w.Rebuild();
                    LayOut(w, size, unfold: false);
                    return (w.GetVisualDescendants().OfType<GenerationView>().FirstOrDefault(), w);
                }
                try
                {
                    GenerationView.OldBeside = true;
                    var (old, _) = Run(new Size(3440, 1440));
                    Row(old != null && old.Wide, $"RED: the 3.55 run view at 3440 put the log beside the scheme (scheme {old?.SchemeWidth:0})",
                        "RED: the 3.55 run view at 3440 did not put the log beside the scheme - the case is not what the PO saw");
                }
                finally
                {
                    GenerationView.OldBeside = false;
                }
                var bad = new List<string>();
                var said = new List<string>();
                foreach (var size in ScreenSizes)
                {
                    var (view, w) = Run(size);
                    if (view == null)
                    {
                        bad.Add($"{size.Width}: no run view");
                        continue;
                    }
                    var tabs = view.GetVisualDescendants().OfType<TabControl>().FirstOrDefault();
                    var heads = tabs?.Items.OfType<TabItem>().Select(t => t.Header?.ToString() ?? "").ToList() ?? new List<string>();
                    var right = tabs?.Bounds.Width ?? 0;
                    said.Add($"{size.Width}: scheme {view.SchemeWidth:0} of {right:0}");
                    if (view.Wide)
                        bad.Add($"{size.Width}: the log beside the scheme");
                    if (heads.Count == 0 || heads[^1] != Loc.T("run.log"))
                        bad.Add($"{size.Width}: the tabs {string.Join(" | ", heads)} - the log not the last");
                    if (view.SchemeWidth < right - 40)
                        bad.Add($"{size.Width}: the scheme {view.SchemeWidth:0} of the pane's {right:0}");
                    if (size.Width >= 1366 && view.SchemeWidth < 600)
                        bad.Add($"{size.Width}: the scheme {view.SchemeWidth:0} wide");
                    var over = TextOverlaps(w);
                    var cut = CutTexts(w);
                    if (over.Count + cut.Count > 0)
                        bad.Add($"{size.Width}: {string.Join("; ", over.Concat(cut).Take(2))}");
                }
                Generation.Current = null;
                Row(bad.Count == 0, $"the run view at every width: the log a tab after the parameters, the scheme the whole right ({string.Join(", ", said)})",
                    $"the run view: {string.Join(" | ", bad.Take(4))}");
            }
            // 4b. a map's page (the PO 06.11 on his 3440: «вот так бредово абы как все расположено»; at 23:56 of the facts on the
            // right: «какого хрена он справа, когда слева куча места есть???»): the facts and the buttons over the cover - in the
            // head beside the name on a wide window - the cover filling the left stack, the checks beside it from its top;
            // RED first: the 3.56 page (the facts over the checks on the right) at 3440
            {
                var open = Library.Scan(s).FirstOrDefault(m => m.Shots.Count > 0) ?? Library.Scan(s).FirstOrDefault();
                (bool ok, string said) Page(Size size)
                {
                    var w = new MainWindow { _page = "library", _openMap = open };
                    w.Rebuild();
                    LayOut(w, size, unfold: false);
                    var split = w.GetVisualDescendants().OfType<SplitColumns>().FirstOrDefault();
                    if (split == null || w.MapCover == null || w.MapFacts == null || w.MapChecks == null)
                        return (false, $"{size.Width}: no split page");
                    Point At(Control c) => c.TranslatePoint(new Point(0, 0), w) ?? default;
                    var cover = At(w.MapCover);
                    var facts = At(w.MapFacts);
                    var checks = At(w.MapChecks);
                    var cw = w.MapCover.Bounds.Width;
                    var bad = new List<string>();
                    if (split.Two != (split.Bounds.Width >= split.MinTwo))
                        bad.Add($"two stacks {split.Two} at {split.Bounds.Width:0}");
                    if (cw < split.LeftWidth - 8)          // the button's frame round the picture: 3
                        bad.Add($"the cover {cw:0} in a column of {split.LeftWidth:0} (a blank of {split.LeftWidth - cw:0} beside it)");
                    var mode = w.MapFactsMode;
                    var body = split.Bounds.Width;
                    var want = body >= 1500 - 16 ? "head" : split.Two ? "right" : "top";
                    if (OldMapLayout)
                        want = body >= 1500 - 16 ? "head" : want;      // the RED asks what 3.56 could not give
                    if (mode != want)
                        bad.Add($"the facts {(mode.Length == 0 ? "in the right stack" : mode)} at a body of {body:0}, wanted {want}");
                    if (!w.MapFacts.IsVisible)
                        bad.Add("the facts not shown");
                    if (mode is "head" or "top" && facts.Y + w.MapFacts.Bounds.Height > cover.Y + 1)
                        bad.Add($"the facts at {facts.X:0},{facts.Y:0} ({w.MapFacts.Bounds.Height:0} tall), not over the cover at {cover.Y:0}");
                    if (mode == "head" && Math.Abs(checks.Y - cover.Y) > 2)
                        bad.Add($"the checks from {checks.Y:0}, not beside the cover's top {cover.Y:0}");
                    if (mode == "head" && facts.X > cover.X + split.LeftWidth)
                        bad.Add($"the facts at {facts.X:0}, over the right stack - not where the room is");
                    if (mode == "right" && (Math.Abs(facts.Y - cover.Y) > 2 || checks.Y < facts.Y))
                        bad.Add($"the facts at {facts.Y:0} not at the cover's top {cover.Y:0} over the checks {checks.Y:0}");
                    var over = TextOverlaps(w);
                    var cut = CutTexts(w);
                    if (over.Count + cut.Count > 0)
                        bad.Add(string.Join("; ", over.Concat(cut).Take(2)));
                    return (bad.Count == 0, $"{size.Width}: {(split.Two ? "two" : "one")}, facts {(mode.Length == 0 ? "right" : mode)}, cover {cw:0}x{w.MapCover.Bounds.Height:0}"
                                            + (bad.Count > 0 ? " - " + string.Join(", ", bad) : ""));
                }
                if (open == null)
                    Row(false, "", "a map's page: no map in the library");
                else
                {
                    try
                    {
                        OldMapLayout = true;
                        var (redOk, redSaid) = Page(new Size(3440, 1440));
                        Row(!redOk, $"RED: the 3.56 map page at 3440 fails the row ({redSaid})",
                            $"RED: the 3.56 map page at 3440 passes the row - the case is not what the PO saw ({redSaid})");
                    }
                    finally
                    {
                        OldMapLayout = false;
                    }
                    var rows = ScreenSizes.Select(Page).ToList();
                    // and a map from a base with every fact (his library's «Отличие от основы» was cut in the head, 3.56 - a
                    // library without such a map never showed it): the same row with the facts of a base map
                    var keepOpen = open;
                    open = open with { Donor = "q2dm1", Difference = 420, Target = 500, Scratch = null };
                    rows.AddRange(ScreenSizes.Select(size => Page(size) is var r ? (r.ok, "base " + r.said) : r));
                    open = keepOpen;
                    Row(rows.All(r => r.ok), $"a map's page at every width: the facts over the cover (beside the name on a wide window), the cover fills its column, the checks beside it ({string.Join("; ", rows.Select(r => r.said))})",
                        $"a map's page: {string.Join(" | ", rows.Where(r => !r.ok).Select(r => r.said).Take(3))}");
                }
            }
            // 5. the window's place: a size saved opens with it, maximised when it was, nothing saved - 1180 x 780
            {
                var keep = (s.WindowW, s.WindowH, s.WindowX, s.WindowY, s.WindowMax);
                try
                {
                    (s.WindowW, s.WindowH, s.WindowX, s.WindowY, s.WindowMax) = (1700, 950, 120, 80, false);
                    var a = new MainWindow();
                    a.KeepPlace();
                    (s.WindowW, s.WindowH, s.WindowX, s.WindowY, s.WindowMax) = (1700, 950, 120, 80, true);
                    var m = new MainWindow();
                    m.KeepPlace();
                    var other = new MainWindow();     // brief 29 D1: a window that is not THE window takes nothing
                    (s.WindowW, s.WindowH, s.WindowX, s.WindowY, s.WindowMax) = (0, 0, int.MinValue, int.MinValue, false);
                    var n = new MainWindow();
                    n.KeepPlace();
                    var ok = a.Width == 1700 && a.Height == 950 && a.Position == new PixelPoint(120, 80) && a.WindowState == WindowState.Normal
                             && m.WindowState == WindowState.Maximized && n.Width == 1180 && n.Height == 780
                             && other.WindowState == WindowState.Normal && other.Width == 1180;
                    Row(ok, "the window opens as it was closed: 1700 x 950 at 120,80; maximised when it was; 1180 x 780 when nothing was saved; "
                            + "a window of the tests or shots takes none of it",
                        $"the window's place: saved {a.Width}x{a.Height} at {a.Position} {a.WindowState}, maximised {m.WindowState}, "
                        + $"none {n.Width}x{n.Height}, another window {other.Width}x{other.Height} {other.WindowState}");
                }
                finally
                {
                    (s.WindowW, s.WindowH, s.WindowX, s.WindowY, s.WindowMax) = keep;
                }
            }
            // 6. brief 27: the checks' chip - green, a quiet count, red only when the map cannot be played
            {
                MapEntry Made(params string[] lines)
                {
                    var g = Library.ParseGates(lines);
                    return new MapEntry("selftest", "", DateTime.Now, 0, null, null, g.Select(x => (x.pass, x.what)).ToList())
                    { Said = g.Select(x => x.said).ToList() };
                }
                var allPass = Made("  PASS  sky: nothing new is seen through the sky  -- 0", "  PASS  traps: no place one can reach and not leave  -- 0 points");
                var taste = Made("  PASS  traps: no place one can reach and not leave  -- 0 points", "  FAIL  share_corridor  -- 0.37 (band 0.05000000000000002..0.35)",
                                 "  FAIL  lit: floors and walls not burnt white, the floor as bright as people's  -- floor at 255 2.0%");
                var block = Made("  PASS  sky: nothing new is seen through the sky  -- 0", "  FAIL  traps-engine: none by the game's own movement  -- 95 place(s)",
                                 "  FAIL  share_corridor  -- 0.37 (band 0.05..0.35)");
                foreach (var lang in new[] { "ru", "en" })
                {
                    Loc.Language = lang;
                    static (string text, Avalonia.Media.Color colour) Of(Border? chip)
                    {
                        var t = chip?.GetLogicalDescendants().OfType<TextBlock>().FirstOrDefault();
                        var c = (t?.Foreground as Avalonia.Media.SolidColorBrush)?.Color ?? default;
                        return (t?.Text ?? "", c);
                    }
                    var (t1, c1) = Of(ChecksChip(allPass));
                    var (t2, c2) = Of(ChecksChip(taste));
                    var (t3, c3) = Of(ChecksChip(block));
                    var ok = t1 == Loc.T("lib.chip.checks.ok") && c1 == Look.GreenC
                             && t2 == Loc.F("lib.chip.checks.count", 1, 3) && c2 != Look.RedC
                             && t3 == Loc.F("lib.chip.checks.blocking", 1) && c3 == Look.RedC;
                    Row(ok, $"{lang} the checks' chip: «{t1}» green, «{t2}» not red (a map that plays), «{t3}» red",
                        $"{lang} the checks' chip: «{t1}» {c1}, «{t2}» {c2} (RED: a taste-only failure must not be red), «{t3}» {c3}");
                    // the map page: the failed rows first, each with what it measured in words
                    var words = SaidWords("share_corridor", "0.37 (band 0.05000000000000002..0.35)");
                    var nm = SaidWords("space: its own measure", "not measured");
                    Row(words == Loc.F("lib.gates.said.band", "0.37", "0.05", "0.35") && nm == Loc.T("lib.gates.notmeasured"),
                        $"{lang} a failed check says what it measured: «{words}»; the 3.52 space row: «{nm}»",
                        $"{lang} a failed check's words: «{words}», «{nm}»");
                }
                /* brief 29 D3 (brief 27 D2's part 3.54 left): a failed row's measure in words - every pattern from a real line of
                   the PO's gates files (06.11, the map named), both languages; RED first: the 3.54 words (GateSaid.Off) read the
                   check's English for every one */
                var said = new (string map, string what, string said, string[] keep)[]
                {
                    ("mg_new_26301", "lit: floors and walls not burnt white, the floor as bright as people's", "floor at 255 2.0%, median 77, top tenth 82; walls at 255 0.0%", new[] { "2.0", "77", "82" }),
                    ("ly2", "traps-engine: none by the game's own movement", "95 place(s), 0 of them inside the dead end asked", new[] { "95" }),
                    ("ly1", "traps-engine: none by the game's own movement", "3 place(s)", new[] { "3" }),
                    ("ly2", "traps: no place one can reach and not leave", "72 points of 32 u, 0 of them inside the dead end asked", new[] { "72" }),
                    ("mg_b16_q2dm1", "starts: every start stands in air on a floor and can step off", "10 starts, 1 not standing free: 1182 15 705 over no floor", new[] { "10", "1182 15 705" }),
                    ("mg_b16_q2dm3", "pickups: the chaingun is in the map", "none", new string[0]),
                    ("ly1", "lava asked: 5% of the floor (within half of it, never over twice)", "2.2%", new[] { "5%", "2.2%" }),
                    ("ly3", "lava asked: none", "2.4%", new[] { "2.4%" }),
                    ("ly1", "sky asked: over 70% of the standing places (+-15 points)", "47%", new[] { "70%", "15", "47%" }),
                    ("ly1", "major items at height: 67% asked (+-25 points)", "100%", new[] { "67%", "100%" }),
                    ("ly2", "long sight lines over 1000 u: 3 asked", "5 (allowed 3..4)", new[] { "3", "5", "3..4" }),
                    ("mg_new_6730", "water asked: 5% of the floor (within half of it, never over twice)", "0.0%", new[] { "5%", "0.0%" }),
                    ("mg_10_6669", "annex: every annex the plan dealt on an accepted dig is built and holds a pickup worth the walk, at least 2", "2 annexes in the plan, 0 on accepted digs, 0 built, 0 worth the walk:", new[] { "2", "0" }),
                    ("mg_10_6708", "storeys: every storey the plan dealt on an accepted dig is built - its hall, its terrace, its flight - and holds its pickup, at least 1", "2 storeys in the plan, 0 on accepted digs, 0 built:", new[] { "2" }),
                    ("mg_10_6669", "stairways: every stairway the plan dealt and the ledger accepted is built, stands on the floor and holds its pickup", "5 stairways in the plan, 4 accepted, 2 built: 1304 -70 896 up to 1536 -64 992, 5 steps: built (built, solid to the floor; item_health)", new[] { "5", "4", "2" }),
                    ("mg_10_45", "hall: every hall the plan dealt on an accepted dig is built", "no fidelity and seed in O:\\Claude2\\_agent_temp\\claude\\mapgen_studio\\MapgenStudio\\temp\\mg_10_45_20261005_184333\\job\\ledger.txt, or no map in O:\\Claude2\\_agent_temp\\claude\\mapgen_studio", new string[0]),
                    ("mg_10_45", "glass: shot panes, panes on a plate, fixed glass beyond the donor's", "0 shot, 0 on a plate (0 func_button), 0 other moving panes; 2065 fixed glass faces in the world, the donor 2198", new[] { "2065", "2198" }),
                    ("corl", "after destruction: axes: every drawn face wears its texture", "SUMMARY 1 cases asserted, 1 failures", new string[0]),
                    ("corl", "light: the map is lit like its donor - shared faces per orientation, every dug room lit", "shared faces sides 1.37, floors 1.21, ceilings 0.73 (0.8..1.25); 0 dug rooms against their doors", new[] { "1.37", "1.21", "0.73" }),
                    ("mg_b16_q2dm3", "water: no vertical liquid face", "face     1254 e1u1/brlava               -84    462   -128 ..    -84    540    -96", new[] { "e1u1/brlava", "-84 462 -128" }),
                    ("ly3", "rooms over rooms: floor over floor, as people's maps", "0% of the floor over or under another (people's 0..64 %, median 35 %); rooms over rooms 0 of 1", new[] { "64", "35" }),
                    ("ly1", "mechanic «halves»: the key gun and the stack on different halves (RG<->RA >= 7 s, brief 19 §6)", "4.67 s", new[] { "4.67" }),
                    ("ly1", "mechanic «route asymmetry»: one item pair 2.5 times as long one way (brief 19 §6)", "1.56x", new[] { "1.56" }),
                    ("ly2", "mechanic «adrenaline tucked»: on the lowest level, 3 s or more from every major", "height 0, nearest major 1.76 s", new[] { "1.76" }),
                    ("ly2", "mechanic «key gun on a ledge»: 128 up or more (brief 19 §6), an armour within 2.2 s", "128 over the floor around, an armour 4.29 s away", new[] { "128", "4.29" }),
                    ("ly2", "nothing hanging: no piece out of a wall with air under it, none on a rod", "1: stands out of a wall at 800 1469 96", new[] { "800 1469 96" }),
                    ("ly2", "plain rooms: none is a closed box", "1 halls or rooms with nothing but walls and doorways", new[] { "1" }),
                    ("mg_10_45", "digwalls: every accepted dig is dug - no new space open high to the old map, nothing standing in its air", "7 digs: 1 points open high (new 664 1208 184 open to old 648 1208 184, 188 over its floor); 0 points standing in the old air", new[] { "7", "1", "0" }),
                    ("mg_b16b_q2dm1", "static: panes, lifts, sounds and the digs' mouths", "pane in rock: *9 func_door at [297, 1184, 764]: solid -40 off its middle", new[] { "297, 1184, 764" }),
                    ("mg_10_6714", "static: panes, lifts, sounds and the digs' mouths", "dig closed at an end: dig -1456 744 -257 .. -752 1528 95: no way in beside its lower end -1104 1160 -257 (3 open patch(es) elsewhere)", new[] { "-1104 1160 -257" }),
                    ("mg_10_6695", "clips: no player-clip brush beside space the generator opened", "4 found: 240 2561 246 .. 255 2576 264 (opened beside it at 267 2568 255)", new[] { "4" }),
                    ("mg_1_666", "sky: nothing new is seen through the sky", "6 digs, 1088 viewers under the sky, 3469 points of new space, 2 seen through it: new 296 1669 521 seen through the sky from -321 1643 504", new[] { "1088", "3469" }),
                    ("mg_1_666", "stair: from the oracle's own eyes round the stair no pair is lost", "0 eyes, 0 pairs LOST in plain sight", new[] { "0" }),
                    ("mg_new_6730", "long sight lines over 1000 u: as people's maps", "8 (people's: 6 at most)", new[] { "8", "6" }),
                    ("mg_new_style", "not a copy, routes: no route copied (pieces shared <= 0.029, people's maps' own)", "0.031 with cor", new[] { "0.031", "cor" }),
                    ("mg_new_66267", "colour: most of the surface coloured, as on people's maps", "35% coloured (people's 50..100 %)", new[] { "35", "50..100" }),
                    ("mg_new_66267", "round shapes: as asked (rounded corners, apses, podiums)", "corners 0, apses 0, podiums 0 (many: corners, apses, podiums); not made: corners, apses, podiums - the reason in the record", new[] { "0" }),
                    ("check_mapgen_new_map l.334 (its format)", "light colour: tinted, as people's light", "saturation 0.08 (people's 0.13..0.95)", new[] { "0.08", "0.13..0.95" }),
                    ("check_mapgen_new_map l.327 (its format)", "texture brightness: textures no lighter than people's", "mean 61 (people's 20..42)", new[] { "61", "20..42" }),
                    ("check_mapgen_new_map l.329 (its format)", "on screen: as bright as people's maps, not washed out", "median 30, top tenth 70 (people's 7..25, 15..55)", new[] { "30", "70" }),
                    ("check_mapgen_new_map l.339 (its format)", "textures: as many as people's maps", "6 textures over 0.5 % of the surface (people's 9..38)", new[] { "6", "9..38" }),
                    // the PO 12.11: his mg_new_84719 measured by the 3.66 rows (its RED)
                    ("mg_new_84719", "majors apart: no weapon, armour or powerup near another of a class people keep apart", "armor_body/rocketlauncher 286 u 1.03 s (rule 354 u 1.7 s); armor_combat/armor_jacket 231 u 0.82 s (rule 606 u 3.4 s); armor_jacket/hyperblaster 345 u 1.24 s (rule 354 u 1.7 s); railgun/armor_jacket 264 u 0.94 s (rule 354 u 1.7 s)", new[] { "231", "606", "286" }),
                    ("mg_new_84719", "prizes earned: the railgun, mega, quad, body armour need a jump, a swim, a mover or the open under fire", "walked to: armor_body effort 0.00 sides 2; health_mega effort 0.00 sides 0; railgun effort 0.00 sides 2", new string[0]),
                    ("check_mapgen_new_map item_rows_of (its format)", "under water: 1 prize(s) or more taken by a swim", "0: none", new string[0]),
                    ("mg_new_84719_366 (3.66 test map)", "mechanic «key gun on a ledge»: 128 up or more or earned by its way (brief 19 §6, the PO 12.11)", "96 over the floor around, its way: water, the nearest armour 4.25 s away", new[] { "96" }),
                    // the PO 12.11: his mg_new_56432 (3.66) - the powerups' and the clock's measures in English
                    ("mg_new_56432", "powerups: each in a place of its own, marked, as hard to reach as asked", "armor_body hard; weapon_railgun medium (jump in) - one unlit", new string[0]),
                    ("mg_new_56432", "mechanic «clock»: both 64 up or more, each with two ways out (brief 19 §6; one from a nook)", "heights 136/-32, exits 1/1 (nook)", new[] { "136", "-32" }),
                    // the PO 12.11: his mg_new_7775 measured by the 3.67 rows (its RED: the 3.66 dive, one cell)
                    ("mg_new_7775", "deep pool: water one swims in, as on well-known maps", "deepest 152 (from 160), its widest pool 0 cells of 64 (from 12; q2dm1 55)", new[] { "152", "160", "12" }),
                    ("mg_new_7775", "tube under water: one swims along it, as on q2dm1", "the longest 112 u (from 320; q2dm1 368)", new[] { "112", "320" }),
                    ("check_mapgen_new_map water_rows_of (its format)", "water levels: deep water on two heights or more", "1 levels: -32", new[] { "1", "-32" }),
                    // the PO 12.11 on mg_new_7775_367: «приплыл сюда, а там пусто» - the railgun freed at spawn (3.67's
                    // gate: a map from scratch has no donor to excuse it), and a spawn in a lift's column (mg_new_7775)
                    ("mg_new_7775_367", "pickups: none lost at spawn, no spawn in a mover's column", "1 lost, 0 blocked: weapon_railgun at (288, 1184, 16) the world", new[] { "288 1184 16" }),
                    ("mg_new_7775", "pickups: none lost at spawn, no spawn in a mover's column", "1 lost, 1 blocked: weapon_railgun at (288, 992, 16) the world; info_player_deathmatch at (672, 96, 24) func_plat *2", new[] { "288 992 16", "672 96 24" }),
                    // the PO 12.11 on mg_new_7775_367: «вот приплыл сюда, а там пусто» - its second pool held nothing
                    ("mg_new_7775_367", "water worth: every deep water leads to a valuable item", "1 of 2 with none: 1024 1472 56", new[] { "1024 1472 56" }),
                };
                try
                {
                    GateSaid.Off = true;
                    Loc.Language = "ru";
                    var raw = said.Count(c => SaidWords(c.what, c.said) == c.said);
                    Row(raw == said.Length, $"RED: on the 3.54 words {raw} of {said.Length} failed rows of his maps read the check's English",
                        $"RED: on the 3.54 words only {raw} of {said.Length} read English - the cases are not what 3.54 showed");
                }
                finally
                {
                    GateSaid.Off = false;
                }
                foreach (var lang in new[] { "ru", "en" })
                {
                    Loc.Language = lang;
                    var bad = new List<string>();
                    foreach (var c in said)
                    {
                        var w = SaidWords(c.what, c.said);
                        var lost = c.keep.Where(k => !w.Contains(k)).ToList();
                        if (w == c.said || lost.Count > 0 || (lang == "ru" && !System.Text.RegularExpressions.Regex.IsMatch(w, "[а-яё]")))
                            bad.Add($"{c.map} «{c.what[..Math.Min(30, c.what.Length)]}»: «{w}»" + (lost.Count > 0 ? $" lost {string.Join(",", lost)}" : ""));
                    }
                    Row(bad.Count == 0, $"{lang} a failed row's measure in words, {said.Length} patterns from his maps (lit: «{SaidWords(said[0].what, said[0].said)}»)",
                        $"{lang} a failed row's measure: {string.Join(" | ", bad.Take(4))}");
                }
                // a band with one end (the PO's mg_new_66267, spawn_to_stack_s «7.43 (band ..6.0)»; 3.55 said «у карт людей ….6»)
                {
                    var one = new List<string>();
                    foreach (var lang in new[] { "ru", "en" })
                    {
                        Loc.Language = lang;
                        one.Add(SaidWords("spawn_to_stack_s", "7.43 (band ..6.0)"));
                    }
                    Row(one.All(x => x.Contains("7.43") && x.Contains('6') && !x.Contains("…")),
                        $"a band with one end in words: «{one[0]}» / «{one[1]}»", $"a band with one end: «{string.Join("» / «", one)}»");
                }
                // the map page of a map with every one of them failed: nothing over another, nothing cut, at every width
                {
                    var lines = said.Select(c => $"  FAIL  {c.what}  -- {c.said}").ToArray();
                    var every = Made(lines);
                    var bad = new List<string>();
                    foreach (var lang in new[] { "ru", "en" })
                    {
                        Loc.Language = lang;
                        foreach (var size in ScreenSizes)
                        {
                            try
                            {
                                var w = new MainWindow { _page = "library", _openMap = every };
                                w.Rebuild();
                                LayOut(w, size, unfold: false);
                                var over = TextOverlaps(w);
                                var cut = CutTexts(w);
                                var shown = TextBoxes(w).Count(t => CopyText.TextOf(t.Item1).StartsWith(SaidWords(said[0].what, said[0].said)[..12]));
                                if (over.Count + cut.Count > 0 || shown == 0)
                                    bad.Add($"{lang} {size.Width}: {string.Join("; ", over.Concat(cut).Take(2))}{(shown == 0 ? " the words not on the page" : "")}");
                            }
                            catch (Exception ex)
                            {
                                bad.Add($"{lang} {size.Width}: {ex.GetType().Name} {ex.Message}");
                            }
                        }
                    }
                    Row(bad.Count == 0, $"the map page with {said.Length} failed rows in words: {ScreenSizes.Length} widths, ru and en - nothing over another, nothing cut",
                        $"the map page with the failed rows' words: {string.Join(" | ", bad.Take(3))}");
                }
                Loc.Language = keepLang;
                // on this library: a red chip only where a check that stops play failed
                var maps = Library.Scan(s);
                var wrong = maps.Where(m => (ChecksChip(m) is { } c && c.GetLogicalDescendants().OfType<TextBlock>().FirstOrDefault()?.Foreground is
                                                 Avalonia.Media.SolidColorBrush br && br.Color == Look.RedC) != (m.GatesBlocking > 0)).Select(m => m.Name).ToList();
                var red = maps.Count(m => m.GatesBlocking > 0);
                Row(wrong.Count == 0, $"the library: {red} of {maps.Count} maps red («играть нельзя»), every other not red",
                    $"the library's chips disagree with the checks that stop play: {string.Join(", ", wrong.Take(6))}");
                // 3.57 (the PO 07.11: «в русском описании … есть анг формулировки в студии»): on this library, a map's Russian
                // description, its checks' names and what a failed one measured hold no English word - the names of maps,
                // of the game and of the Studio aside.
                // 3.58 (brief 31; the PO on the guide, 07.11: «карты людей» is our own word): nor «людей» - the maps the
                // generator is measured against are «известные карты». RED: a copy of his library before
                // tools/mapgen_redescribe.py (his descriptions said «отделка как у карты людей», «как у людей 50..100%»)
                var peopleWord = new System.Text.RegularExpressions.Regex(@"[^\n]{0,24}(?:людей|люди\b|people's)[^\n]{0,12}",
                                                                          System.Text.RegularExpressions.RegexOptions.IgnoreCase);
                IEnumerable<string> People(string text) => peopleWord.Matches(text).Select(t => t.Value.Trim()).Distinct();
                {
                    var keepLangE = Loc.Language;
                    Loc.Language = "ru";
                    var english = new List<string>();
                    var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
                    {
                        "Quake", "II", "BFG", "MAPGEN", "Studio", "kaktus", "omf", "ptrip", "Windows", "Python", "GitHub", "zip", "bsp",
                        "map", "pak", "baseq2", "cor", "corl", "ly", "PNG", "JPG",
                    };
                    var token = new System.Text.RegularExpressions.Regex(@"[A-Za-z0-9_'./\-]+");
                    IEnumerable<string> Latin(string text) => token.Matches(text).Select(t => t.Value.Trim('.', '\'', '-'))
                        .Where(t => t.Count(char.IsLetter) >= 3 && !t.Any(char.IsDigit) && !t.Contains('_') && !t.Contains('.') && !t.Contains('/')
                                    && t.All(c => c < 128) && !names.Contains(t));
                    var people = 0;
                    foreach (var m in Library.Scan(s))
                    {
                        if (m.Description != null)
                        {
                            foreach (var t in Latin(m.Description).Distinct().Take(3))
                                english.Add($"{m.Name} description: «{t}»");
                            foreach (var t in People(m.Description).Take(3))
                            {
                                english.Add($"{m.Name} description: «{t}»");
                                people++;
                            }
                        }
                        for (var i = 0; i < m.Gates.Count; i++)
                        {
                            if (m.Gates[i].pass)
                                continue;
                            var measure = i < m.Said.Count ? SaidWords(m.Gates[i].what, m.Said[i]) : "";
                            var row = Loc.Gate(m.Gates[i].what) + " " + measure;
                            foreach (var t in Latin(row).Distinct().Take(2))
                                english.Add($"{m.Name} {Loc.GateKey(m.Gates[i].what)}: «{t}»");
                            foreach (var t in People(row).Take(2))
                            {
                                english.Add($"{m.Name} {Loc.GateKey(m.Gates[i].what)}: «{t}»");
                                people++;
                            }
                        }
                    }
                    Loc.Language = keepLangE;
                    Row(english.Count == 0, "the library in Russian: no English and no «карты людей» in a map's description, its failed checks or their measures",
                        $"the library in Russian, English or «людей» left ({english.Count}, «людей» {people}): {string.Join("; ", english.Take(8))}");
                    File.WriteAllLines(Path.Combine(Settings.ProgramDir, "selftest_english.txt"), english);
                }
                // 3.58: the English side of the same - the English descriptions carried the Russian «как у людей 50..100%» and
                // «dressed as people's map» (RED on the same copy); the failed checks' words in English say «well-known maps».
                // 3.58 addendum (the coordinator, 07.11): and no Russian word at all - the powerups' row («смешанно → мега — в
                // нише»), the round shapes, the edges, «план 67%» were written into both languages; the names of maps, of the
                // game and of the Studio are Latin, so any Cyrillic letter is a find. RED: a copy of his library before
                // tools/mapgen_redescribe.py's English pass
                {
                    var keepLangP = Loc.Language;
                    Loc.Language = "en";
                    var left = new List<string>();
                    var scanned = 0;
                    var cyrillic = new System.Text.RegularExpressions.Regex(@"[^\n]{0,16}[Ѐ-ӿ][^\n]{0,24}");
                    IEnumerable<string> Russian(string text) => cyrillic.Matches(text).Select(t => t.Value.Trim()).Distinct();
                    var russian = 0;
                    foreach (var m in Library.Scan(s))
                    {
                        scanned++;
                        if (m.Description != null)
                        {
                            left.AddRange(People(m.Description).Take(3).Select(t => $"{m.Name} description: «{t}»"));
                            var ru = Russian(m.Description).Where(t => !People(t).Any()).Take(4).ToList();
                            russian += ru.Count;
                            left.AddRange(ru.Select(t => $"{m.Name} description: «{t}»"));
                        }
                        for (var i = 0; i < m.Gates.Count; i++)
                            if (!m.Gates[i].pass)
                            {
                                var row = Loc.Gate(m.Gates[i].what) + " " + (i < m.Said.Count ? SaidWords(m.Gates[i].what, m.Said[i]) : "");
                                var finds = People(row).Concat(Russian(row).Where(t => !People(t).Any())).Take(2).ToList();
                                russian += finds.Count(t => cyrillic.IsMatch(t));
                                left.AddRange(finds.Select(t => $"{m.Name} {Loc.GateKey(m.Gates[i].what)}: «{t}»"));
                            }
                    }
                    Loc.Language = keepLangP;
                    Row(left.Count == 0, $"the library in English: no Russian word and no «people's maps» in a map's description, its failed checks or their measures ({scanned} maps)",
                        $"the library in English, Russian or «people's» left ({left.Count}, Russian {russian}): {string.Join("; ", left.Take(8))}");
                    File.AppendAllLines(Path.Combine(Settings.ProgramDir, "selftest_english.txt"), left.Select(x => "en " + x));
                }
                // 3.58: the Studio's own words - no «карты людей» in its Russian table, no «people's maps» in its English one
                {
                    var ru = Loc.Table("ru").Where(x => People(x.text).Any()).Select(x => x.key).ToList();
                    var en = Loc.Table("en").Where(x => People(x.text).Any() || x.text.Contains("people make")
                                                        || System.Text.RegularExpressions.Regex.IsMatch(x.text, @"[Ѐ-ӿ]"))
                                            .Select(x => x.key).ToList();
                    Row(ru.Count + en.Count == 0,
                        $"the Studio's own words say «известные карты» / «well-known maps»: {Loc.Table("ru").Count()} Russian and {Loc.Table("en").Count()} English texts, none says «людей» or «people's», no English one holds a Russian letter",
                        $"the Studio's own words still say «людей» ({ru.Count}: {string.Join(", ", ru.Take(6))}) or «people's» / Russian in English ({en.Count}: {string.Join(", ", en.Take(6))})");
                }
            }
        }
        finally
        {
            Loc.Language = keepLang;
            s.Scratch = keepScratch;
            s.ScratchMode = keepMode;
            Generation.Current = keepCurrent;
            OldFormLayout = false;
        }
    }
}
