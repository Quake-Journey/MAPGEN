using System.Runtime.CompilerServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.LogicalTree;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// Brief 35 (the PO 11.11: «хочу чтобы в параметрах генерации сверху появилось окошко поиска параметров (работать должно и
/// на английском и на русском вводе) … оставались на экране только те, что соответствуют … в реальном времени ввода …
/// когда все стерто то возвращаются все параметры, а если ни одного не найдено то все скрываются»; «секции в которых
/// найдены параметры сохранять»; «остальные параметры в секции которые не соответствуют поиску не показываем»; «это
/// живой поиск»).
///
/// Every parameter row carries its words - its name, the line under it and its tip, in Russian AND English whatever the
/// Studio's language (each text is looked up in the string table and its other language's text added). A query of two
/// characters or more shows only the rows holding every word of it, each inside its own section; a section with none is
/// not shown. The search only ever hides what it hid itself: a row the form hides stays hidden, and clearing the box
/// shows back exactly what the search took away.
/// </summary>
public static class Search
{
    /// <summary>The query's least length: under it every row shows (the PO: «от трёх букв … или от двух как удобней»).</summary>
    public const int MinChars = 2;

    private static readonly ConditionalWeakTable<Control, string> s_words = new();
    private static readonly ConditionalWeakTable<Control, object> s_sections = new();
    private static readonly ConditionalWeakTable<Control, object> s_always = new();
    /* brief 36 item 10: a card's separator line and the row under it (Look.Fill) */
    private static readonly ConditionalWeakTable<Control, Control> s_lines = new();
    /* brief 36 item 9: what the search hides now, and what the form asked of such a control meanwhile */
    private static readonly ConditionalWeakTable<Control, object> s_hiddenNow = new();
    private static readonly ConditionalWeakTable<Control, StrongBox<bool>> s_formWish = new();
    private static Dictionary<string, string>? s_ruToEn, s_enToRu;

    /// <summary>3.61's search (a row the form hid under a query came back when the box was cleared; a card's first row
    /// shown under a line), for the self-test's RED.</summary>
    internal static bool Old;

    /// <summary>A separator line of a card and the row it stands over (Look.Fill).</summary>
    public static void Line(Control line, Control row) => s_lines.AddOrUpdate(line, row);

    /// <summary>Is this a card's separator line.</summary>
    public static bool IsLine(Control c) => s_lines.TryGetValue(c, out _);

    /// <summary>
    /// Brief 36 item 9 (Fable's review of 3.61): the form shows or hides one of its rows - while the search hides that
    /// row, the form's wish is kept and given back when the search lets the row go (clearing the box never shows a row
    /// the form hid meanwhile).
    /// </summary>
    public static void FormShows(Control c, bool shown)
    {
        if (!Old && s_hiddenNow.TryGetValue(c, out _))
        {
            s_formWish.AddOrUpdate(c, new StrongBox<bool>(shown));
            return;
        }
        c.IsVisible = shown;
    }

    /// <summary>Lower case, «ё» as «е», runs of spaces as one.</summary>
    public static string Norm(string? s) =>
        string.Join(' ', (s ?? "").ToLowerInvariant().Replace('ё', 'е').Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries));

    /// <summary>A text's other language: the string table's text of the same key ("" when the text is no key's).</summary>
    public static string Other(string? text)
    {
        if (string.IsNullOrWhiteSpace(text))
            return "";
        if (s_ruToEn == null || s_enToRu == null)
        {
            var en = Loc.Table("en").ToDictionary(t => t.key, t => t.text);
            s_ruToEn = new Dictionary<string, string>();
            s_enToRu = new Dictionary<string, string>();
            foreach (var (key, ru) in Loc.Table("ru"))
                if (en.TryGetValue(key, out var e))
                {
                    s_ruToEn.TryAdd(ru, e);
                    s_enToRu.TryAdd(e, ru);
                }
        }
        return s_ruToEn.TryGetValue(text, out var other) ? other : s_enToRu.TryGetValue(text, out var back) ? back : "";
    }

    /// <summary>A parameter row: its words in both languages (the builders of rows call it).</summary>
    public static void Mark(Control row, params string?[] texts)
    {
        var all = texts.Where(t => !string.IsNullOrWhiteSpace(t)).SelectMany(t => new[] { t!, Other(t) });
        s_words.AddOrUpdate(row, Norm(string.Join(' ', all)));
    }

    /// <summary>The words a row carries ("" when it is no parameter row).</summary>
    public static string WordsOf(Control row) => s_words.TryGetValue(row, out var w) ? w : "";

    /// <summary>A section the search shows or hides as a whole by its rows (a card, a fold).</summary>
    public static void Section(Control card) => s_sections.AddOrUpdate(card, card);

    /// <summary>A part of the page the search never hides (the «Откуда карта» switch).</summary>
    public static void Always(Control c) => s_always.AddOrUpdate(c, c);

    /// <summary>Does a row's words hold every word of the query.</summary>
    public static bool Matches(string words, string query)
    {
        var q = Norm(query);
        return q.Length < MinChars || q.Split(' ').All(words.Contains);
    }

    /// <summary>What one application of a query did: the rows it found, and what it hid (for the self-test).</summary>
    public sealed record Result(int Rows, int Found, int Sections, int SectionsShown);

    /// <summary>The state of one page under the search: what it hid, the folds it opened.</summary>
    public sealed class PageState
    {
        public readonly HashSet<Control> Hidden = new();
        public readonly Dictionary<Expander, bool> Folds = new();
        public TextBlock? Nothing;
    }

    private static readonly ConditionalWeakTable<Control, PageState> s_states = new();

    /// <summary>
    /// Apply a query to a page: under <see cref="MinChars"/> everything the search hid comes back; else only the matching
    /// rows and their sections stay, the containers that hold nothing visible close up, and «Ничего не найдено» shows
    /// when no row matches.
    /// </summary>
    public static Result Apply(Control page, string query, TextBlock? nothing = null)
    {
        var st = s_states.GetOrCreateValue(page);
        if (nothing != null)
            st.Nothing = nothing;
        // what the search hid before comes back first - as the form wants it now (brief 36 item 9); the lines last, each as
        // its row stands
        foreach (var c in st.Hidden.Where(c => !s_lines.TryGetValue(c, out _)))
        {
            c.IsVisible = !Old && s_formWish.TryGetValue(c, out var wish) ? wish.Value : true;
            s_formWish.Remove(c);
            s_hiddenNow.Remove(c);
        }
        foreach (var c in st.Hidden.Where(c => s_lines.TryGetValue(c, out _)))
        {
            c.IsVisible = s_lines.TryGetValue(c, out var under) ? under.IsVisible : true;
            s_hiddenNow.Remove(c);
        }
        st.Hidden.Clear();
        foreach (var (fold, open) in st.Folds)
            fold.IsExpanded = open;
        st.Folds.Clear();
        var q = Norm(query);
        var rows = page.GetLogicalDescendants().OfType<Control>().Where(c => s_words.TryGetValue(c, out _)).ToList();
        var sections = page.GetLogicalDescendants().OfType<Control>().Where(c => s_sections.TryGetValue(c, out _)).ToList();
        if (q.Length < MinChars)
        {
            if (st.Nothing != null)
                st.Nothing.IsVisible = false;
            return new Result(rows.Count, rows.Count, sections.Count, sections.Count(s => s.IsVisible));
        }
        void Hide(Control c)
        {
            if (!c.IsVisible || s_always.TryGetValue(c, out _))
                return;
            c.IsVisible = false;
            st.Hidden.Add(c);
            s_hiddenNow.AddOrUpdate(c, c);
        }
        var found = 0;
        var keep = new HashSet<Control>();
        foreach (var r in rows)
        {
            if (Matches(WordsOf(r), q))
            {
                if (r.IsVisible)
                {
                    found++;
                    keep.Add(r);
                }
            }
            else
                Hide(r);
        }
        // a section stays when it holds a row found; a fold holding one opens (and closes again when the box is cleared)
        foreach (var s in sections)
        {
            var holds = s.GetLogicalDescendants().OfType<Control>().Any(keep.Contains);
            if (!holds)
                Hide(s);
            else if (s is Expander ex && !ex.IsExpanded)
            {
                st.Folds[ex] = false;
                ex.IsExpanded = true;
            }
        }
        // brief 36 item 10: a card's first row shown has no line over it - a line with no row shown above it goes
        if (!Old)
            foreach (var body in page.GetLogicalDescendants().OfType<StackPanel>()
                                     .Where(b => b.Children.Any(ch => s_lines.TryGetValue(ch, out _))).ToList())
            {
                var rowAbove = false;
                foreach (var ch in body.Children.ToList())
                {
                    if (s_lines.TryGetValue(ch, out _))
                    {
                        if (!rowAbove)
                            Hide(ch);
                    }
                    else if (ch.IsVisible)
                        rowAbove = true;
                }
            }
        // the containers left empty close up
        var content = page.GetLogicalDescendants().OfType<Control>().ToList();
        foreach (var panel in content.OfType<Panel>().Reverse())
        {
            if (panel == page || panel.Children.Count == 0 || s_always.TryGetValue(panel, out _))
                continue;
            if (!panel.Children.Any(ch => ch.IsVisible) && panel.GetLogicalAncestors().Contains(page))
                Hide(panel);
        }
        if (st.Nothing != null)
        {
            st.Nothing.Text = Loc.F("gen.search.none", query.Trim());
            st.Nothing.IsVisible = found == 0;
        }
        return new Result(rows.Count, found, sections.Count, sections.Count(s => s.IsVisible));
    }

    /// <summary>
    /// The box at the top of the Generate page: the magnifier, the watermark, a clear button; Esc clears; every change
    /// of the text filters at once.
    /// </summary>
    public static Control Box(Func<Control?> page, Func<string> get, Action<string> set, TextBlock nothing)
    {
        var box = new TextBox
        {
            Text = get(), Watermark = Loc.T("gen.search.watermark"), Width = 360, HorizontalAlignment = HorizontalAlignment.Left,
            InnerLeftContent = new FASymbolIcon { Symbol = FASymbol.Find, FontSize = 14, Margin = new Thickness(8, 0, 2, 0), Opacity = 0.7 },
            Classes = { "clearButton" },
        };
        ToolTip.SetTip(box, Loc.T("gen.search.tip"));
        // every change of the text, typed or set (a TextBox not yet shown raises no TextChanged)
        box.PropertyChanged += (_, e) =>
        {
            if (e.Property != TextBox.TextProperty)
                return;
            set(box.Text ?? "");
            if (page() is { } p)
                Apply(p, box.Text ?? "", nothing);
        };
        box.KeyDown += (_, e) =>
        {
            if (e.Key == Key.Escape && !string.IsNullOrEmpty(box.Text))
            {
                box.Text = "";
                e.Handled = true;
            }
        };
        nothing.FontSize = 15;
        nothing.Opacity = 0.75;
        nothing.IsVisible = false;
        nothing.TextWrapping = Avalonia.Media.TextWrapping.Wrap;
        var line = new StackPanel { Spacing = 8, Margin = new Thickness(0, 0, 0, 4), Children = { box, nothing } };
        Always(line);
        return line;
    }
}
