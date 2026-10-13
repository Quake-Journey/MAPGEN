using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Documents;
using Avalonia.Input;
using Avalonia.Controls.Primitives;
using Avalonia.Input.Platform;
using Avalonia.Interactivity;
using Avalonia.Media;
using Avalonia.Threading;
using Avalonia.VisualTree;

namespace MapgenStudio;

/// <summary>
/// Brief 15, the PO 08.10: «любой текст в любой окне программы студии должна быть возможность скопировать в буфер
/// обмена, а то сейчас даже название карты не скопировать». One rule for every window: the right mouse button over any
/// text - a label, a map's name on its card, a line of the run's page, a dialog's words, the scheme's feed - opens
/// «Копировать» with that text, the text around it, and the whole window's. A text box keeps its own menu.
/// And (the PO, 08.10: «текст в любом окне программы можно было выделить мышкой и скопировать») any text is SELECTED
/// with the mouse - a drag across it, a double click for the whole of it - painted over, and Ctrl+C copies it: the
/// texts the library's own templates draw (a setting's description, a notice's message) included, since it is done
/// on the window, not on the text's control.
/// </summary>
public static class CopyText
{
    /// <summary>What a control draws itself (the scheme's feed and labels): its words, for the copy menu.</summary>
    public interface IDrawnText
    {
        string DrawnText { get; }
    }

    private static bool s_installed;

    /// <summary>Once, before the first window: every window's right button goes through <see cref="Released"/>.</summary>
    public static void Install()
    {
        if (s_installed)
            return;
        s_installed = true;
        InputElement.PointerReleasedEvent.AddClassHandler<Window>(Released, RoutingStrategies.Tunnel, true);
        InputElement.PointerPressedEvent.AddClassHandler<Window>(Pressed, RoutingStrategies.Tunnel, true);
        InputElement.PointerMovedEvent.AddClassHandler<Window>(Moved, RoutingStrategies.Tunnel, true);
        InputElement.KeyDownEvent.AddClassHandler<Window>(KeyDown, RoutingStrategies.Tunnel);
        Control.ContextRequestedEvent.AddClassHandler<Window>(Requested, RoutingStrategies.Bubble, true);
    }

    // ---- the mouse's selection: one text at a time, in one window ------------------------------------------------

    private static TextBlock? s_sel;            /* the text selected (or being pressed on) */
    private static Window? s_selWindow;
    private static int s_anchor, s_caret;
    private static bool s_dragging;
    private static Point s_downAt;
    private static SelectionPaint? s_paint;

    /// <summary>The text the mouse selected, "" when none.</summary>
    public static string Selected =>
        s_sel is { } tb && s_caret != s_anchor
            ? Slice(TextOf(tb), Math.Min(s_anchor, s_caret), Math.Abs(s_caret - s_anchor)) : "";

    private static string Slice(string s, int start, int length)
    {
        start = Math.Clamp(start, 0, s.Length);
        return s.Substring(start, Math.Clamp(length, 0, s.Length - start));
    }

    private static int IndexAt(TextBlock tb, Point inWindow, Window w)
    {
        if (w.TranslatePoint(inWindow, tb) is not { } p)
            return 0;
        var hit = tb.TextLayout.HitTestPoint(new Point(p.X - tb.Padding.Left, p.Y - tb.Padding.Top));
        return Math.Clamp(hit.TextPosition + (hit.IsTrailing ? 1 : 0), 0, TextOf(tb).Length);
    }

    private static void ClearSelection()
    {
        if (s_sel != null && s_paint != null)
            AdornerLayer.SetAdorner(s_sel, null);
        s_sel = null;
        s_selWindow = null;
        s_paint = null;
        s_anchor = s_caret = 0;
        s_dragging = false;
    }

    private static void Paint()
    {
        if (s_sel == null)
            return;
        if (s_paint == null)
        {
            s_paint = new SelectionPaint { IsHitTestVisible = false };
            AdornerLayer.SetAdorner(s_sel, s_paint);
        }
        s_paint.Show(s_sel, Math.Min(s_anchor, s_caret), Math.Abs(s_caret - s_anchor));
    }

    private static void Pressed(Window w, PointerPressedEventArgs e)
    {
        var point = e.GetCurrentPoint(w);
        if (!point.Properties.IsLeftButtonPressed)
            return;
        var at = point.Position;
        var under = Under(w, at);
        var tb = under.Any(v => v is TextBox) ? null : under.OfType<TextBlock>().FirstOrDefault(x => x is not SelectableTextBlock);
        ClearSelection();
        if (tb == null || string.IsNullOrEmpty(TextOf(tb)))
            return;
        s_sel = tb;
        s_selWindow = w;
        s_downAt = at;
        s_anchor = s_caret = IndexAt(tb, at, w);
        if (e.ClickCount >= 2)
        {
            /* a double click: the whole text - a map's name, a line of the log */
            s_anchor = 0;
            s_caret = TextOf(tb).Length;
            Paint();
        }
    }

    private static void Moved(Window w, PointerEventArgs e)
    {
        if (s_sel == null || s_selWindow != w || !e.GetCurrentPoint(w).Properties.IsLeftButtonPressed)
            return;
        var at = e.GetPosition(w);
        if (!s_dragging)
        {
            if (Math.Abs(at.X - s_downAt.X) + Math.Abs(at.Y - s_downAt.Y) < 5)
                return;
            s_dragging = true;
        }
        s_caret = IndexAt(s_sel, at, w);
        Paint();
    }

    private static void KeyDown(Window w, KeyEventArgs e)
    {
        if (e.Key != Key.C || (e.KeyModifiers & KeyModifiers.Control) == 0 || s_selWindow != w)
            return;
        /* a text box with its own selection copies its own */
        if (TopLevel.GetTopLevel(w)?.FocusManager?.GetFocusedElement() is TextBox { SelectedText.Length: > 0 })
            return;
        var text = Selected;
        if (text.Length == 0)
            return;
        if (TopLevel.GetTopLevel(w)?.Clipboard is { } clip)
            _ = clip.SetTextAsync(text);
        e.Handled = true;
    }

    /// <summary>The selection painted over its text, the theme's selection colour half seen through.</summary>
    private sealed class SelectionPaint : Control
    {
        private readonly List<Rect> _rects = new();

        public void Show(TextBlock tb, int start, int length)
        {
            _rects.Clear();
            if (length > 0)
                foreach (var r in tb.TextLayout.HitTestTextRange(start, length))
                    _rects.Add(r.Translate(new Vector(tb.Padding.Left, tb.Padding.Top)));
            InvalidateVisual();
        }

        public override void Render(DrawingContext context)
        {
            var brush = new SolidColorBrush(Color.FromArgb(0x70, 0x3b, 0x82, 0xf6));
            foreach (var r in _rects)
                context.FillRectangle(brush, r);
        }
    }

    private static void Released(Window w, PointerReleasedEventArgs e)
    {
        if (e.InitialPressMouseButton == MouseButton.Left)
        {
            /* a drag across a text selected it: the release is the selection's, not the button's under it */
            if (s_dragging && s_selWindow == w)
            {
                s_dragging = false;
                e.Handled = true;
                e.Pointer.Capture(null);    /* a button pressed under the text lets go and does not stay pressed */
            }
            else if (s_sel != null && s_anchor == s_caret)
            {
                s_sel = null;               /* a plain click: nothing selected */
                s_selWindow = null;
            }
            return;
        }
        if (e.InitialPressMouseButton != MouseButton.Right)
            return;
        if (ShowAt(w, e.GetPosition(w)))
            e.Handled = true;
    }

    /*
     * The PO, 08.10 (Studio 2.9): «нет меню по правой кнопке ... выбрать Копировать». The menu was opened inside the
     * button's own release, while that release still went on through the window - and it was not seen. Now it is
     * opened after the release is done (posted to the window's queue), and the window's own «context requested»
     * (the right button, Shift+F10, the menu key) opens it too when the release did not.
     */
    private static MenuFlyout? s_menu;
    private static DateTime s_menuAt;

    /// <summary>The copy menu at this point of the window, opened once the input in hand is done.</summary>
    public static bool ShowAt(Window w, Point at)
    {
        var offer = Offer(w, at, out var anchor);
        /* the evidence, if the menu is still not seen (the PO, 08.10): each right button, what it offered, when the
           menu opened and when it closed, in ui_clicks.txt beside the program */
        MainWindow.ClickLog($"copy menu: right button at {at.X:0} {at.Y:0}, {offer.Count} lines offered"
                            + (anchor != null ? $" over {anchor.GetType().Name}" : ""));
        if (offer.Count == 0)
            return false;
        var items = new List<MenuItem>();
        foreach (var (key, what) in offer)
        {
            var item = new MenuItem { Header = Loc.F(key, Short(what)) };
            item.Click += async (_, _) =>
            {
                if (TopLevel.GetTopLevel(w)?.Clipboard is { } clip)
                    await clip.SetTextAsync(what);
            };
            items.Add(item);
        }
        s_menuAt = DateTime.Now;
        /*
         * The PO, 09.10, his ui_clicks.txt: «open» then «closed» at his NEXT press each time - the menu was open and
         * not seen. A ContextMenu made in code and opened on a control it is not attached to has no logical parent:
         * no style reaches it, no template, nothing drawn. A MenuFlyout is made to be shown from code - it takes its
         * look from the control it is shown at (the text boxes' own cut / copy / paste is one).
         */
        Dispatcher.UIThread.Post(() =>
        {
            s_menu?.Hide();
            s_menu = new MenuFlyout { ItemsSource = items, Placement = PlacementMode.Pointer };
            var opened = DateTime.Now;
            s_menu.Opened += (_, _) => MainWindow.ClickLog("copy menu: open");
            s_menu.Closed += (_, _) => MainWindow.ClickLog($"copy menu: closed after {(DateTime.Now - opened).TotalMilliseconds:0} ms");
            try
            {
                s_menu.ShowAt(anchor ?? (Control)w, true);
            }
            catch (Exception ex)
            {
                MainWindow.ClickLog($"copy menu: did not open - {ex.GetType().Name}: {ex.Message}");
            }
        }, DispatcherPriority.Input);
        return true;
    }

    private static void Requested(Window w, ContextRequestedEventArgs e)
    {
        MainWindow.ClickLog("copy menu: the window asked for a context menu");
        if (DateTime.Now - s_menuAt < TimeSpan.FromMilliseconds(500))
        {
            e.Handled = true;           /* the release opened it already */
            return;
        }
        var at = e.TryGetPosition(w, out var p) ? p : new Point(w.Bounds.Width / 2, w.Bounds.Height / 2);
        if (ShowAt(w, at))
            e.Handled = true;
    }

    /// <summary>
    /// What the right button at this point of the window offers to copy, in the menu's order: (the Loc key of the
    /// line, the text it copies). Empty over a text box (it has its own menu). The self-test asks it of every page.
    /// </summary>
    public static List<(string key, string text)> Offer(Window w, Point at, out Control? anchor)
    {
        var offer = new List<(string key, string text)>();
        anchor = null;
        var under = Under(w, at);
        if (under.Any(v => v is TextBox))
            return offer;                               // a text box: its own cut / copy / paste
        var text = under.OfType<TextBlock>().FirstOrDefault();
        var drawn = under.OfType<IDrawnText>().FirstOrDefault();
        void Add(string key, string what)
        {
            if (!string.IsNullOrWhiteSpace(what))
                offer.Add((key, what));
        }
        if (text is SelectableTextBlock { SelectedText: { Length: > 0 } sel })
            Add("copy.selected", sel);
        else if (Selected is { Length: > 0 } mouse && s_selWindow == w)
            Add("copy.selected", mouse);
        if (text != null)
        {
            Add("copy.this", TextOf(text));
            if (Around(text) is { } around && around != TextOf(text))
                Add("copy.around", around);
        }
        if (drawn != null)
            Add("copy.drawn", drawn.DrawnText);
        Add("copy.window", All(w));
        anchor = text as Control ?? drawn as Control;
        return offer;
    }

    /// <summary>
    /// The self-test's question (brief 15, the PO: «даже название карты не скопировать»): every text the page shows, at
    /// its middle, offers itself first. Returns the texts asked and the ones that did not (with what came instead).
    /// </summary>
    public static (int asked, List<string> failed) CheckPage(Window w)
    {
        var failed = new List<string>();
        var asked = 0;
        int all = 0, hidden = 0, tiny = 0, empty = 0, outside = 0, cut = 0;
        foreach (var v in w.GetVisualDescendants())
        {
            if (v is not TextBlock tb)
                continue;
            all++;
            if (!Shown(tb, w))
            {
                hidden++;
                continue;
            }
            if (tb.Bounds.Width < 4 || tb.Bounds.Height < 4)
            {
                tiny++;
                continue;
            }
            var want = TextOf(tb);
            if (string.IsNullOrWhiteSpace(want) || tb.TranslatePoint(new Point(tb.Bounds.Width / 2, tb.Bounds.Height / 2), w) is not { } mid)
            {
                empty++;
                continue;
            }
            if (mid.X < 0 || mid.Y < 0 || mid.X > w.Bounds.Width || mid.Y > w.Bounds.Height)
            {
                outside++;
                continue;                               // scrolled out of the window
            }
            var clipped = false;
            for (var p = tb.GetVisualParent(); p != null && p != w && !clipped; p = p.GetVisualParent())
                clipped = p.ClipToBounds && p.TranslatePoint(new Point(0, 0), w) is { } po && !new Rect(po, p.Bounds.Size).Contains(mid);
            if (clipped)
            {
                cut++;
                continue;
            }
            asked++;
            var offer = Offer(w, mid, out _);
            if (Under(w, mid).Any(x => x is TextBox))
                continue;                               // inside a text box's own template: its menu copies
            var first = offer.FirstOrDefault(o => o.key == "copy.this").text;
            if (first == null)
                failed.Add($"«{Short(want)}»: nothing offered");
            else if (first != want && !Under(w, mid).OfType<TextBlock>().Any(x => TextOf(x) == first))
                failed.Add($"«{Short(want)}»: offered «{Short(first)}»");
        }
        LastNote = $"text blocks {all}: hidden {hidden}, empty {tiny}+{empty}, outside {outside}, scrolled away {cut}";
        return (asked, failed);
    }

    /// <summary>What the last <see cref="CheckPage"/> left out and why, for the self-test's line.</summary>
    public static string LastNote { get; private set; } = "";

    /// <summary>The text a text block shows, its runs joined when it has no plain text.</summary>
    public static string TextOf(TextBlock t)
    {
        if (!string.IsNullOrEmpty(t.Text))
            return t.Text!;
        if (t.Inlines is not { Count: > 0 } inlines)
            return "";
        var b = new StringBuilder();
        foreach (var i in inlines)
            b.Append(i switch { Run r => r.Text, LineBreak => "\n", _ => "" });
        return b.ToString();
    }

    private static string Short(string s)
    {
        var one = s.ReplaceLineEndings(" ").Trim();
        return one.Length <= 48 ? one : one[..45] + "…";
    }

    /// <summary>
    /// The visuals under a point of the window, the top-most first: each one's box in the window's coordinates holds
    /// the point, it is shown, and no clipping parent cuts it off (a list's rows scrolled away are not under the mouse).
    /// </summary>
    private static List<Visual> Under(Window w, Point at)
    {
        var hits = new List<Visual>();
        foreach (var v in w.GetVisualDescendants())
        {
            if (v is not Control c || !Shown(c, w) || c.Bounds.Width <= 0 || c.Bounds.Height <= 0)
                continue;
            if (!(v is TextBlock || v is TextBox || v is IDrawnText))
                continue;
            if (!Holds(v, w, at))
                continue;
            hits.Add(v);
        }
        hits.Reverse();                                 // the later in the tree, the higher it is drawn
        return hits;
    }

    /// <summary>Shown up to `root`: neither it nor a parent below `root` hidden (a window the self-test lays out without
    /// showing is not itself visible, and everything in it would read hidden).</summary>
    private static bool Shown(Visual v, Visual root)
    {
        for (Visual? p = v; p != null && p != root; p = p.GetVisualParent())
            if (!p.IsVisible)
                return false;
        return true;
    }

    private static bool Holds(Visual v, Window w, Point at)
    {
        if (v.TranslatePoint(new Point(0, 0), w) is not { } o)
            return false;
        if (!new Rect(o, v.Bounds.Size).Contains(at))
            return false;
        for (var p = v.GetVisualParent(); p != null && p != w; p = p.GetVisualParent())
            if (p.ClipToBounds && p.TranslatePoint(new Point(0, 0), w) is { } po && !new Rect(po, p.Bounds.Size).Contains(at))
                return false;
        return true;
    }

    /// <summary>The words of the nearest block around this text that holds more than it: a card, a row, a panel.</summary>
    private static string? Around(TextBlock t)
    {
        for (var p = t.GetVisualParent(); p != null && p is not Window; p = p.GetVisualParent())
        {
            var texts = Texts(p).ToList();
            if (texts.Count >= 2)
                return string.Join(Environment.NewLine, texts);
        }
        return null;
    }

    private static string All(Window w) => string.Join(Environment.NewLine, Texts(w));

    private static IEnumerable<string> Texts(Visual root)
    {
        foreach (var v in root.GetVisualDescendants())
        {
            if (!Shown(v, root))
                continue;
            var s = v switch
            {
                TextBlock tb => TextOf(tb),
                TextBox tx => tx.Text ?? "",
                IDrawnText d => d.DrawnText,
                _ => "",
            };
            if (!string.IsNullOrWhiteSpace(s))
                yield return s.Trim();
        }
    }
}
