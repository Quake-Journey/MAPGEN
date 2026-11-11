using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.LogicalTree;
using Avalonia.VisualTree;

namespace MapgenStudio;

/// <summary>
/// Brief 35 (the PO 11.11: «окошко поиска параметров … и на английском и на русском вводе … живой поиск»; «секции в
/// которых найдены параметры сохранять»; «остальные параметры в секции которые не соответствуют поиску не показываем»):
/// the search on the Generate page, both ways to start, on windows laid out as the PO's.
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>A control and every one of its ancestors shown.</summary>
    private static bool Shown(Control c) =>
        c.IsVisible && c.GetLogicalAncestors().OfType<Control>().Where(a => a is not TopLevel).All(a => a.IsVisible);

    /// <summary>The page's parameter rows (each with its words) shown now.</summary>
    private static List<Control> RowsShown(Window w) =>
        w.GetLogicalDescendants().OfType<Control>().Where(c => Search.WordsOf(c).Length > 0 && Shown(c)).ToList();

    /// <summary>A row's name: its first line of words.</summary>
    private static string TitleOf(Control row) =>
        row.GetLogicalDescendants().OfType<TextBlock>().FirstOrDefault()?.Text ?? "";

    /// <summary>
    /// Brief 36 items 8-10 (Fable's review of 3.61): a row the form hides while the search hides it stays hidden when the
    /// box is cleared; a card's first row shown has no line over it; of the bases' page's two top cards, the one found
    /// stands in the left column. Each with its RED (3.61's search, 3.61's columns).
    /// </summary>
    private static void SearchFixesSelfTest(StringBuilder b, MainWindow w, TextBox box, Action<bool, string, string> Row,
                                            Func<string, List<Control>> query)
    {
        var s = App.Settings;
        // (9) the variant number: hidden by the search, then by «Случайный вариант», then the box cleared
        if (w._seedRandom is { } tog && w._seedRow is { } seedRow)
        {
            var togRow = w.GetLogicalDescendants().OfType<Control>().FirstOrDefault(c => Search.WordsOf(c).Length > 0
                                                                                         && TitleOf(c) == Loc.T("gen.seed.random"));
            var seedWords = Search.WordsOf(seedRow);
            var token = togRow == null ? null
                : Search.WordsOf(togRow).Split(' ').FirstOrDefault(t => t.Length >= 4 && !seedWords.Contains(t));
            if (token == null)
                Row(false, "", "the variant number's row: no word of «Случайный вариант» that the number's row lacks");
            else
            {
                var keepTog = tog.IsChecked;
                bool ShownAfter(bool old)
                {
                    Search.Old = old;
                    try
                    {
                        tog.IsChecked = false;
                        query("");
                        query(token);
                        var hiddenBySearch = !Shown(seedRow);
                        tog.IsChecked = true;
                        query("");
                        return hiddenBySearch && Shown(seedRow);
                    }
                    finally
                    {
                        Search.Old = false;
                        tog.IsChecked = keepTog;
                        query("");
                    }
                }
                var now = ShownAfter(false);
                var old = ShownAfter(true);
                Row(!now && old,
                    $"«{TitleOf(seedRow)}» hidden by the search «{token}», then «Случайный вариант» ticked: stays hidden when the box is cleared (3.61: shown)",
                    $"«{TitleOf(seedRow)}» after the box cleared: {(now ? "SHOWN" : "hidden")}; 3.61's way {(old ? "shown" : "hidden - the RED does not bite")}");
            }
        }
        else
            Row(false, "", "the variant number's row: not on the page");
        // (10) a card's first row shown has no line over it
        int LinesOnTop()
        {
            var n = 0;
            foreach (var body in w.GetLogicalDescendants().OfType<StackPanel>().Where(Shown))
            {
                var first = body.Children.FirstOrDefault(ch => ch.IsVisible);
                if (first != null && Search.IsLine(first))
                    n++;
            }
            return n;
        }
        var queries = new[] { "лифт", "телепорт", "окн", "lift" };
        var on = queries.Sum(q => { query(q); return LinesOnTop(); });
        Search.Old = true;
        var onOld = queries.Sum(q => { query(q); return LinesOnTop(); });
        Search.Old = false;
        query("");
        Row(on == 0 && onOld > 0, $"a card's first row shown has no line over it ({string.Join(", ", queries)}; 3.61: {onOld} cards with one)",
            $"cards whose first row shown has a line over it: {on}; 3.61's way {onOld}");
        // (8) the bases' page: under «похож» the card found stands in the left column
        var keepMode = s.ScratchMode;
        try
        {
            s.ScratchMode = false;
            double Offset(bool old)
            {
                ColumnsPanel.OldColumns = old;
                try
                {
                    var bw = new MainWindow { _page = "generate" };
                    bw.Rebuild();
                    LayOut(bw, ScreenSizes[1], unfold: false);
                    var bb = bw.GetLogicalDescendants().OfType<TextBox>().First(t => t.Watermark == Loc.T("gen.search.watermark"));
                    bb.Text = "похож";
                    // a window never shown runs no layout pass of its own: the panels a hidden card changed are measured
                    // again only when asked - the Studio's own pass does it when a card hides
                    foreach (var l in bw.GetVisualDescendants().OfType<Avalonia.Layout.Layoutable>().ToList())
                        l.InvalidateMeasure();
                    bw.InvalidateMeasure();
                    LayOut(bw, ScreenSizes[1], unfold: false);
                    // the bases' page's top pair: the bases' card left, the new map's and the run's cards right
                    var pair = bw.GetLogicalDescendants().OfType<ColumnsPanel>().FirstOrDefault(cp => cp.LeftFollowsRight);
                    if (pair == null || pair.Children.Count != 2 || pair.Children[0].IsVisible || !Shown(pair.Children[1]))
                        return double.NaN;
                    return pair.Children[1].TranslatePoint(new Point(0, 0), pair)?.X ?? double.NaN;
                }
                finally
                {
                    ColumnsPanel.OldColumns = false;
                }
            }
            var dNow = Offset(false);
            var dOld = Offset(true);
            Row(Math.Abs(dNow) < 1 && dOld > 100,
                $"the bases' page under «похож»: the bases' card hidden, «{Loc.T("gen.card.map")}» in the left column (3.61: {dOld:0} px to the right)",
                $"«{Loc.T("gen.card.map")}» {dNow:0} px from the left column (the bases' card hidden and the other shown: {!double.IsNaN(dNow)}); 3.61's way {dOld:0}");
        }
        finally
        {
            s.ScratchMode = keepMode;
        }
    }

    internal static void SearchSelfTest(StringBuilder b)
    {
        var s = App.Settings;
        var keepLang = Loc.Language;
        var keepMode = s.ScratchMode;
        var keepScratch = s.Scratch;
        var keepRandom = s.SeedRandom;
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        try
        {
            Loc.Language = "ru";
            Generation.Current = null;
            s.ScratchMode = true;
            s.SeedRandom = true;
            var tower = Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == "tower_skyscraper");
            var w = new MainWindow { _page = "generate" };
            w.Rebuild();
            w.LoadPreset(tower);
            LayOut(w, ScreenSizes[1], unfold: false);
            var box = w.GetLogicalDescendants().OfType<TextBox>().FirstOrDefault(t => t.Watermark == Loc.T("gen.search.watermark"));
            if (box == null)
            {
                Row(false, "", "the search box: not on the Generate page");
                return;
            }
            var before = RowsShown(w);
            var lifts = Loc.T("scr.tower.lifts");
            List<Control> Query(string q)
            {
                box.Text = q;
                LayOut(w, ScreenSizes[1], unfold: false);
                return RowsShown(w);
            }
            // «лифт»: «Лифты» and only rows holding the word, each in a section shown
            var lift = Query("лифт");
            var liftOk = lift.Any(r => TitleOf(r) == lifts) && lift.All(r => Search.WordsOf(r).Contains("лифт"));
            var sections = w.GetLogicalDescendants().OfType<Border>().Where(c => Shown(c) && c.CornerRadius.TopLeft >= 10
                                                                                   && c.BorderThickness.Left > 0).ToList();
            var empty = sections.Where(sct => !sct.GetLogicalDescendants().OfType<Control>().Any(c => lift.Contains(c))
                                              && !sct.GetLogicalDescendants().OfType<Control>().Any(c => c is Avalonia.Controls.Primitives.ToggleButton)).ToList();
            Row(liftOk && lift.Count < before.Count && empty.Count == 0,
                $"the search «лифт» on the tower page: {lift.Count} of {before.Count} rows shown, «{lifts}» among them, no section without a row found",
                $"the search «лифт»: {lift.Count} of {before.Count} rows, «{lifts}» {lift.Any(r => TitleOf(r) == lifts)}, every row holds it {lift.All(r => Search.WordsOf(r).Contains("лифт"))}, sections with nothing found {empty.Count}");
            // «lift» on the Russian page finds «Лифты» too
            var en = Query("lift");
            Row(en.Any(r => TitleOf(r) == lifts),
                $"the search «lift» on a Russian page finds «{lifts}» ({en.Count} rows)",
                $"the search «lift» on a Russian page: «{lifts}» not found ({en.Count} rows: {string.Join(", ", en.Take(5).Select(TitleOf))})");
            // one letter: every row
            var one = Query("л");
            Row(one.Count == before.Count, $"one letter: every row shown ({one.Count})", $"one letter: {one.Count} of {before.Count} rows shown");
            // nothing found: no section, the line says so
            var none = Query("qqqq");
            var noneLine = w.GetLogicalDescendants().OfType<TextBlock>().FirstOrDefault(t => t.Text == Loc.F("gen.search.none", "qqqq"));
            var cardsLeft = w.GetLogicalDescendants().OfType<Border>().Count(c => Shown(c) && c.CornerRadius.TopLeft >= 10 && c.BorderThickness.Left > 0
                                                                                    && Search.WordsOf(c).Length == 0
                                                                                    && !c.GetLogicalDescendants().OfType<Avalonia.Controls.Primitives.ToggleButton>().Any());
            Row(none.Count == 0 && noneLine != null && Shown(noneLine) && cardsLeft == 0,
                $"the search «qqqq»: no row, no section, «{Loc.F("gen.search.none", "qqqq")}»",
                $"the search «qqqq»: {none.Count} rows, the line {(noneLine == null ? "missing" : Shown(noneLine) ? "shown" : "hidden")}, {cardsLeft} sections left");
            // cleared: the very rows of before
            var back = Query("");
            Row(back.Count == before.Count && back.All(before.Contains),
                $"the box cleared: the same {back.Count} rows as before the first letter",
                $"the box cleared: {back.Count} rows, of them {back.Count(before.Contains)} of the {before.Count} before");
            // a row the form hides stays hidden under a query that matches it, and after it
            var seedTitle = Loc.T("gen.seed");
            var seedRow = w.GetLogicalDescendants().OfType<Control>().FirstOrDefault(c => Search.WordsOf(c).Length > 0 && TitleOf(c) == seedTitle);
            var q1 = Query(Search.Norm(seedTitle).Split(' ')[0]);
            var hiddenUnder = seedRow != null && !Shown(seedRow);
            Query("");
            var hiddenAfter = seedRow != null && !Shown(seedRow);
            Row(seedRow != null && hiddenUnder && hiddenAfter,
                $"«{seedTitle}» hidden by «Случайный вариант» stays hidden under «{Search.Norm(seedTitle).Split(' ')[0]}» ({q1.Count} rows) and after it",
                $"«{seedTitle}»: {(seedRow == null ? "no such row" : $"under the query {(hiddenUnder ? "hidden" : "SHOWN")}, after {(hiddenAfter ? "hidden" : "SHOWN")}")}");
            // a rebuild keeps the query (another shape chosen)
            box.Text = "лифт";
            w.Rebuild();
            var box2 = w.GetLogicalDescendants().OfType<TextBox>().FirstOrDefault(t => t.Watermark == Loc.T("gen.search.watermark"));
            LayOut(w, ScreenSizes[1], unfold: false);
            var kept = RowsShown(w);
            Row(box2?.Text == "лифт" && kept.Count < before.Count && kept.Any(r => TitleOf(r) == lifts),
                $"a rebuilt page keeps the query «лифт» ({kept.Count} rows)",
                $"a rebuilt page: the box «{box2?.Text}», {kept.Count} rows of {before.Count}");
            box2!.Text = "";
            SearchFixesSelfTest(b, w, box2, Row, Query2);
            List<Control> Query2(string q)
            {
                box2.Text = q;
                LayOut(w, ScreenSizes[1], unfold: false);
                return RowsShown(w);
            }
            // the box fits: nothing cut or overlapping at the narrowest and the widest, both languages, both ways to start
            var cut = new List<string>();
            foreach (var lang in new[] { "ru", "en" })
                foreach (var scratch in new[] { true, false })
                {
                    Loc.Language = lang;
                    s.ScratchMode = scratch;
                    var fw = new MainWindow { _page = "generate" };
                    fw.Rebuild();
                    foreach (var size in new[] { ScreenSizes[0], ScreenSizes[^1] })
                    {
                        LayOut(fw, size, unfold: false);
                        cut.AddRange(CutTexts(fw).Concat(TextOverlaps(fw)).Select(x => $"{lang} {(scratch ? "scratch" : "base")} {size.Width}: {x}"));
                    }
                }
            Row(cut.Count == 0, "the search box and the presets' bar fit at 1180 and 3440, RU and EN, both ways to start",
                $"cut or overlapping: {string.Join("; ", cut.Take(4))}");
            // every row of both pages carries both languages' name
            var missing = new List<string>();
            var donors = Engine.Donors().ToHashSet();
            foreach (var scratch in new[] { true, false })
                foreach (var lang in new[] { "ru", "en" })
                {
                    Loc.Language = lang;
                    s.ScratchMode = scratch;
                    var pw = new MainWindow { _page = "generate" };
                    pw.Rebuild();
                    if (scratch)
                        pw.LoadPreset(tower);
                    foreach (var r in pw.GetLogicalDescendants().OfType<Control>().Where(c => Search.WordsOf(c).Length > 0))
                    {
                        var title = TitleOf(r);
                        if (donors.Contains(title))
                            continue;                         // a base's own name is one word in every language
                        var other = Search.Other(title);
                        if (other.Length == 0 || !Search.WordsOf(r).Contains(Search.Norm(other)))
                            missing.Add($"{lang} «{title}»");
                    }
                }
            Row(missing.Count == 0, "every parameter row of both pages carries its name in Russian and English",
                $"rows without their other language's name: {string.Join(", ", missing.Distinct().Take(8))} ({missing.Distinct().Count()})");
        }
        catch (Exception ex)
        {
            Row(false, "", $"the parameters' search: {ex.GetType().Name}: {ex.Message}");
        }
        finally
        {
            Loc.Language = keepLang;
            s.ScratchMode = keepMode;
            s.Scratch = keepScratch;
            s.SeedRandom = keepRandom;
        }
    }
}
