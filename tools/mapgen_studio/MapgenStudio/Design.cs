using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// The Studio's look, one for every page (the PO, 11.10, after the run's page: «раз ты сделал новый современный
/// красивый UI для самой генерации то и для карт сделай ... и для параметров програмы и для параметров генерации
/// самой»): a page's head (a title and a line under it), cards with a coloured sign and a title, settings as rows of
/// a card (the name and what it does on the left, the control on the right), parts folded under a card's head, two
/// columns on a wide window and one on a narrow one, and chips - small coloured words.
/// </summary>
public static class Look
{
    public static readonly Color GreenC = Color.FromRgb(0x22, 0xc5, 0x5e), RedC = Color.FromRgb(0xef, 0x44, 0x44),
                                 BlueC = Color.FromRgb(0x3b, 0x82, 0xf6), AmberC = Color.FromRgb(0xf5, 0x9e, 0x0b),
                                 VioletC = Color.FromRgb(0xa7, 0x8b, 0xfa), TealC = Color.FromRgb(0x2d, 0xd4, 0xbf),
                                 PinkC = Color.FromRgb(0xf4, 0x72, 0xb6), GreyC = Color.FromRgb(0x8b, 0x8b, 0x94);
    public static readonly IBrush Green = new SolidColorBrush(GreenC), Red = new SolidColorBrush(RedC),
                                  Blue = new SolidColorBrush(BlueC), Amber = new SolidColorBrush(AmberC),
                                  Violet = new SolidColorBrush(VioletC), Teal = new SolidColorBrush(TealC),
                                  Muted = new SolidColorBrush(GreyC);
    public static readonly IBrush CardBack = new SolidColorBrush(Color.FromArgb(0x1c, 0x80, 0x80, 0x80));
    public static readonly IBrush CardEdge = new SolidColorBrush(Color.FromArgb(0x40, 0x80, 0x80, 0x80));
    public static readonly IBrush Line = new SolidColorBrush(Color.FromArgb(0x30, 0x80, 0x80, 0x80));

    public static IBrush Soft(Color c, byte alpha = 0x30) => new SolidColorBrush(Color.FromArgb(alpha, c.R, c.G, c.B));

    /// <summary>A page's head: its title large, a line under it, and on the right what the page offers first.</summary>
    public static Control PageHead(string title, string? subtitle = null, Control? right = null)
    {
        var words = new StackPanel { Spacing = 4 };
        words.Children.Add(new TextBlock { Text = title, FontSize = 30, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap });
        if (!string.IsNullOrEmpty(subtitle))
            words.Children.Add(new TextBlock { Text = subtitle, FontSize = 15, Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        var g = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Margin = new Thickness(0, 0, 0, 20) };
        g.Children.Add(words);
        if (right != null)
        {
            right.VerticalAlignment = VerticalAlignment.Center;
            right.Margin = new Thickness(16, 0, 0, 0);
            Grid.SetColumn(right, 1);
            g.Children.Add(right);
        }
        return g;
    }

    /// <summary>A card: the soft ground every part of a page stands on.</summary>
    public static Border Card(Control body, double pad = 18) => new()
    {
        Background = CardBack, BorderBrush = CardEdge, BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(12),
        Padding = new Thickness(pad, pad - 2, pad, pad), Child = body,
    };

    /// <summary>A coloured sign: the symbol in a rounded square of its colour.</summary>
    public static Border Sign(FASymbol symbol, Color colour, double size = 36) => new()
    {
        Width = size, Height = size, CornerRadius = new CornerRadius(size / 4), Background = Soft(colour, 0x38),
        VerticalAlignment = VerticalAlignment.Top,
        Child = new FASymbolIcon { Symbol = symbol, FontSize = size * 0.5, Foreground = new SolidColorBrush(colour),
                                   HorizontalAlignment = HorizontalAlignment.Center, VerticalAlignment = VerticalAlignment.Center },
    };

    /// <summary>A card's head: the sign, the title, a line under it, and a control on the right.</summary>
    public static Control CardHead(FASymbol symbol, Color colour, string title, string? sub = null, Control? right = null)
    {
        var words = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center };
        words.Children.Add(new TextBlock { Text = title, FontSize = 18, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap });
        if (!string.IsNullOrEmpty(sub))
            words.Children.Add(new TextBlock { Text = sub, FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*,Auto"), ColumnSpacing = 14 };
        g.Children.Add(Sign(symbol, colour));
        Grid.SetColumn(words, 1);
        g.Children.Add(words);
        if (right != null)
        {
            right.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(right, 2);
            g.Children.Add(right);
        }
        return g;
    }

    /// <summary>A card of rows under its head; a line between the rows.</summary>
    public static Border Group(FASymbol symbol, Color colour, string title, string? sub, params Control[] rows) =>
        Group(symbol, colour, title, sub, null, rows);

    public static Border Group(FASymbol symbol, Color colour, string title, string? sub, Control? right, IEnumerable<Control> rows)
    {
        var p = new StackPanel();
        p.Children.Add(CardHead(symbol, colour, title, sub, right));
        var body = new StackPanel { Margin = new Thickness(0, 10, 0, 0) };
        Fill(body, rows);
        p.Children.Add(body);
        var card = Card(p);
        card.Tag = body;
        return card;
    }

    /// <summary>Rows into a card's body, a thin line between each two.</summary>
    public static void Fill(StackPanel body, IEnumerable<Control> rows)
    {
        foreach (var r in rows)
        {
            if (body.Children.Count > 0)
                body.Children.Add(new Border { Height = 1, Background = Line, Margin = new Thickness(0, 2, 0, 2) });
            body.Children.Add(r);
        }
    }

    /// <summary>
    /// A setting as a row: its name and what it does on the left, its control on the right; the control goes under
    /// the words when the row is too narrow for both.
    /// </summary>
    public static Control Row(string title, string? desc, Control control, string? tip = null)
    {
        var words = new StackPanel { Spacing = 2, VerticalAlignment = VerticalAlignment.Center, MinWidth = 160 };
        words.Children.Add(new TextBlock { Text = title, FontSize = 14.5, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap });
        if (!string.IsNullOrEmpty(desc))
            words.Children.Add(new TextBlock { Text = desc, FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        control.VerticalAlignment = VerticalAlignment.Center;
        var row = new RowPanel(words, control) { Margin = new Thickness(0, 10, 0, 10) };
        if (tip != null)
            ToolTip.SetTip(row, tip);
        return row;
    }

    /// <summary>A chip: a few words in a rounded pill of their colour.</summary>
    public static Border Chip(string text, Color colour, FASymbol? symbol = null)
    {
        var words = new TextBlock { Text = text, FontSize = 12.5, FontWeight = FontWeight.SemiBold, Foreground = new SolidColorBrush(colour),
                                    VerticalAlignment = VerticalAlignment.Center };
        Control child = words;
        if (symbol is { } s)
            child = new StackPanel
            {
                Orientation = Orientation.Horizontal, Spacing = 5,
                Children = { new FASymbolIcon { Symbol = s, FontSize = 12, Foreground = new SolidColorBrush(colour) }, words },
            };
        return new Border
        {
            Background = Soft(colour, 0x2c), BorderBrush = Soft(colour, 0x70), BorderThickness = new Thickness(1),
            CornerRadius = new CornerRadius(10), Padding = new Thickness(9, 2, 9, 3), Child = child,
            VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Left,
        };
    }

    /// <summary>Two columns on a wide window, one under the other on a narrow one.</summary>
    public static Control Columns(Control left, Control right, double minColumn = 460) =>
        new ColumnsPanel { MinColumn = minColumn, Children = { left, right } };

    /// <summary>Two cards side by side, one height (the taller one's); one under the other on a narrow window.</summary>
    public static Control Pair(Control left, Control right, double minColumn = 460) =>
        new ColumnsPanel { MinColumn = minColumn, EqualHeights = true, Children = { left, right } };

    /// <summary>A column of cards.</summary>
    public static StackPanel Stack(params Control[] cards)
    {
        var s = new StackPanel { Spacing = 16 };
        foreach (var c in cards)
            s.Children.Add(c);
        return s;
    }

    /// <summary>A page wide enough for two columns, scrolled.</summary>
    public static ScrollViewer Page(Control content, double maxWidth = 1640) => new()
    {
        Content = new Border
        {
            Padding = new Thickness(40, 30, 40, 40), MaxWidth = maxWidth, HorizontalAlignment = HorizontalAlignment.Stretch,
            Child = content,
        },
        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
    };

    /// <summary>A card a click goes through: an action with its sign, its name and a line of what it does.</summary>
    public static Button ActionCard(FASymbol symbol, Color colour, string title, string desc, Action click)
    {
        var b = new Button
        {
            HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Stretch,
            Padding = new Thickness(18, 16, 18, 16), CornerRadius = new CornerRadius(12),
            Content = CardHead(symbol, colour, title, desc),
        };
        b.Click += (_, _) => click();
        return b;
    }
}

/// <summary>A row's words and its control: side by side when there is room, the control under the words when not.</summary>
public sealed class RowPanel : Panel
{
    private readonly Control _words, _control;
    private const double Gap = 16;

    public RowPanel(Control words, Control control)
    {
        _words = words;
        _control = control;
        Children.Add(words);
        Children.Add(control);
    }

    private bool Side(double width, Size control) => double.IsInfinity(width) || width - control.Width - Gap >= 220;

    protected override Size MeasureOverride(Size available)
    {
        _control.Measure(new Size(available.Width, double.PositiveInfinity));
        var c = _control.DesiredSize;
        if (Side(available.Width, c))
        {
            var w = double.IsInfinity(available.Width) ? double.PositiveInfinity : Math.Max(0, available.Width - c.Width - Gap);
            _words.Measure(new Size(w, double.PositiveInfinity));
            return new Size(double.IsInfinity(available.Width) ? _words.DesiredSize.Width + Gap + c.Width : available.Width,
                            Math.Max(_words.DesiredSize.Height, c.Height));
        }
        _words.Measure(new Size(available.Width, double.PositiveInfinity));
        return new Size(available.Width, _words.DesiredSize.Height + 8 + c.Height);
    }

    protected override Size ArrangeOverride(Size final)
    {
        var c = _control.DesiredSize;
        if (Side(final.Width, c))
        {
            var w = Math.Max(0, final.Width - c.Width - Gap);
            _words.Arrange(new Rect(0, (final.Height - _words.DesiredSize.Height) / 2, w, _words.DesiredSize.Height));
            _control.Arrange(new Rect(final.Width - c.Width, (final.Height - c.Height) / 2, c.Width, c.Height));
        }
        else
        {
            _words.Arrange(new Rect(0, 0, final.Width, _words.DesiredSize.Height));
            _control.Arrange(new Rect(0, _words.DesiredSize.Height + 8, Math.Min(final.Width, c.Width), c.Height));
        }
        return final;
    }
}

/// <summary>Two children side by side, each half the width, when both halves are wide enough; else one under the other.</summary>
public sealed class ColumnsPanel : Panel
{
    public double MinColumn { get; set; } = 460;
    public double Gap { get; set; } = 18;
    /// <summary>The PO, 12.10: two cards side by side are one height - the taller one's.</summary>
    public bool EqualHeights { get; set; }
    /// <summary>The PO, 12.10: the left card takes the right column's height and scrolls what does not fit in it.</summary>
    public bool LeftFollowsRight { get; set; }

    private bool Two(double width) => !double.IsInfinity(width) && width >= 2 * MinColumn + Gap && Children.Count == 2;

    protected override Size MeasureOverride(Size available)
    {
        if (Two(available.Width))
        {
            var w = (available.Width - Gap) / 2;
            if (LeftFollowsRight)
            {
                Children[1].Measure(new Size(w, double.PositiveInfinity));
                Children[0].Measure(new Size(w, Children[1].DesiredSize.Height));
                return new Size(available.Width, Children[1].DesiredSize.Height);
            }
            foreach (var c in Children)
                c.Measure(new Size(w, double.PositiveInfinity));
            return new Size(available.Width, Children.Max(c => c.DesiredSize.Height));
        }
        double h = 0;
        foreach (var c in Children)
        {
            c.Measure(new Size(available.Width, double.PositiveInfinity));
            h += c.DesiredSize.Height + (h > 0 ? Gap : 0);
        }
        return new Size(double.IsInfinity(available.Width) ? Children.Max(c => c.DesiredSize.Width) : available.Width, h);
    }

    protected override Size ArrangeOverride(Size final)
    {
        if (Two(final.Width))
        {
            var w = (final.Width - Gap) / 2;
            var tall = Math.Max(Children[0].DesiredSize.Height, Children[1].DesiredSize.Height);
            var h0 = LeftFollowsRight ? Children[1].DesiredSize.Height : EqualHeights ? tall : Children[0].DesiredSize.Height;
            var h1 = EqualHeights ? tall : Children[1].DesiredSize.Height;
            Children[0].Arrange(new Rect(0, 0, w, h0));
            Children[1].Arrange(new Rect(w + Gap, 0, w, h1));
            return final;
        }
        double y = 0;
        foreach (var c in Children)
        {
            c.Arrange(new Rect(0, y, final.Width, c.DesiredSize.Height));
            y += c.DesiredSize.Height + Gap;
        }
        return final;
    }
}

/// <summary>
/// A card of settings under a head, its rows added one by one (the PO, 12.10: the generation's options «без подписей
/// групп просто в воздухе висят» - each group a card with its sign, its name and a line of what it is for). `Key` is
/// the title's key - the guide's pictures find a group by it.
/// </summary>
public sealed class OptionGroup
{
    private readonly StackPanel _rows = new() { Margin = new Thickness(0, 10, 0, 0) };
    public Border Card { get; }
    public string Key { get; }

    public OptionGroup(string titleKey, string descKey, FASymbol symbol, Color colour, string? tipKey = null)
    {
        Key = titleKey;
        var p = new StackPanel();
        p.Children.Add(Look.CardHead(symbol, colour, Loc.T(titleKey), Loc.T(descKey)));
        p.Children.Add(_rows);
        Card = Look.Card(p);
        Card.Tag = this;
        if (tipKey != null)
            ToolTip.SetTip(Card, Loc.T(tipKey));
    }

    /// <summary>A row: its name, what it does, its control; the tip on the whole row.</summary>
    public void Add(string title, string? desc, Control control, string? tipKey = null) =>
        Look.Fill(_rows, new[] { Look.Row(title, desc, control, tipKey != null ? Loc.T(tipKey) : null) });

    /// <summary>
    /// A row whose words are long (the PO, 12.10, the ruin: «текст слева узким блоком, а бегунок справа»): the name
    /// and what it does across the card, the control under them.
    /// </summary>
    public void AddUnder(string title, string? desc, Control control, string? tipKey = null)
    {
        var row = new StackPanel { Spacing = 2, Margin = new Thickness(0, 10, 0, 10) };
        row.Children.Add(new TextBlock { Text = title, FontSize = 14.5, FontWeight = FontWeight.SemiBold, TextWrapping = TextWrapping.Wrap });
        if (!string.IsNullOrEmpty(desc))
            row.Children.Add(new TextBlock { Text = desc, FontSize = 13, Opacity = 0.7, TextWrapping = TextWrapping.Wrap });
        control.Margin = new Thickness(0, 10, 0, 0);
        control.HorizontalAlignment = HorizontalAlignment.Stretch;
        row.Children.Add(control);
        if (tipKey != null)
            ToolTip.SetTip(row, Loc.T(tipKey));
        Look.Fill(_rows, new Control[] { row });
    }
}

/// <summary>
/// A card whose rows fold under its head (the PO, 11.10: «что менее важно в свернутых секциях»): the sign, the title, a
/// line under it, and the rows. `Key` is the title's key - the guide's pictures open a fold by it.
/// </summary>
public sealed class Fold : Expander
{
    private readonly StackPanel _rows = new();
    public string Key { get; }

    public Fold(string titleKey, string descKey, FASymbol symbol, Color colour, bool open, string? tipKey = null)
    {
        Key = titleKey;
        Header = Look.CardHead(symbol, colour, Loc.T(titleKey), Loc.T(descKey));
        Content = _rows;
        IsExpanded = open;
        HorizontalAlignment = HorizontalAlignment.Stretch;
        HorizontalContentAlignment = HorizontalAlignment.Stretch;
        Padding = new Thickness(18, 4, 18, 8);
        CornerRadius = new CornerRadius(12);
        if (tipKey != null)
            ToolTip.SetTip(this, Loc.T(tipKey));
    }

    /// <summary>A row: its name, what it does, its control; the tip on the whole row.</summary>
    public void Add(string title, string? desc, Control control, string? tipKey = null) =>
        Look.Fill(_rows, new[] { Look.Row(title, desc, control, tipKey != null ? Loc.T(tipKey) : null) });
}

/// <summary>
/// The window's menu on the left (the PO, 11.10: «крупные иконочки и крупные тексты меню - чтоб современно было и
/// красиво ... подсвечивать выделенное при наведении мышкой»): each page a coloured sign and its name in large type;
/// under the mouse the row lights up softly, the page open stands out in its colour with a bar on the left. The
/// button at the top folds the menu to its signs and opens it again.
/// </summary>
public sealed class SideNav : DockPanel
{
    private readonly StackPanel _top = new() { Spacing = 4 }, _foot = new() { Spacing = 4 };
    private readonly TextBlock _title = new() { FontSize = 18, FontWeight = FontWeight.SemiBold, VerticalAlignment = VerticalAlignment.Center };
    private readonly Border _pane;
    private readonly List<Item> _items = new();
    private bool _narrow;
    public event Action<string>? Chosen;

    private sealed class Item : Border
    {
        public readonly string Tag2;
        public readonly Color Colour;
        public readonly TextBlock Words;
        private readonly Border _bar, _sign;
        private bool _on, _over;

        public Item(string tag, string text, string tip, FASymbol symbol, Color colour)
        {
            Tag2 = tag;
            Colour = colour;
            Words = new TextBlock { Text = text, FontSize = 16.5, VerticalAlignment = VerticalAlignment.Center };
            _sign = Look.Sign(symbol, colour, 38);
            _sign.VerticalAlignment = VerticalAlignment.Center;
            _bar = new Border { Width = 4, CornerRadius = new CornerRadius(2), Margin = new Thickness(0, 10, 10, 10),
                                Background = Brushes.Transparent };
            var g = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,Auto,*"), ColumnSpacing = 0 };
            g.Children.Add(_bar);
            Grid.SetColumn(_sign, 1);
            g.Children.Add(_sign);
            Words.Margin = new Thickness(14, 0, 8, 0);
            Grid.SetColumn(Words, 2);
            g.Children.Add(Words);
            Child = g;
            CornerRadius = new CornerRadius(10);
            Padding = new Thickness(0, 4, 8, 4);
            Cursor = new Cursor(StandardCursorType.Hand);
            Background = Brushes.Transparent;
            Transitions = new Avalonia.Animation.Transitions
            {
                new Avalonia.Animation.BrushTransition { Property = BackgroundProperty, Duration = TimeSpan.FromMilliseconds(160) },
            };
            _sign.Transitions = new Avalonia.Animation.Transitions
            {
                new Avalonia.Animation.BrushTransition { Property = BackgroundProperty, Duration = TimeSpan.FromMilliseconds(160) },
            };
            ToolTip.SetTip(this, tip);
            PointerEntered += (_, _) => { _over = true; Paint(); };
            PointerExited += (_, _) => { _over = false; Paint(); };
        }

        public bool On
        {
            set { _on = value; Paint(); }
        }

        private void Paint()
        {
            Background = _on ? Look.Soft(Colour, 0x2a) : _over ? Look.Soft(Colour, 0x16) : Brushes.Transparent;
            _bar.Background = _on ? new SolidColorBrush(Colour) : Brushes.Transparent;
            _sign.Background = Look.Soft(Colour, _on ? (byte)0x55 : _over ? (byte)0x48 : (byte)0x30);
            Words.FontWeight = _on ? FontWeight.SemiBold : FontWeight.Normal;
        }
    }

    public SideNav(Control content)
    {
        var fold = new Button
        {
            Content = new FASymbolIcon { Symbol = FASymbol.GlobalNavigationButton, FontSize = 18 },
            Background = Brushes.Transparent, BorderThickness = new Thickness(0), Padding = new Thickness(10, 8, 10, 8),
            VerticalAlignment = VerticalAlignment.Center,
        };
        fold.Click += (_, _) => Narrow(!_narrow);
        var head = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, Margin = new Thickness(4, 4, 0, 18),
                                    Children = { fold, _title } };
        var body = new DockPanel();
        DockPanel.SetDock(head, Dock.Top);
        body.Children.Add(head);
        DockPanel.SetDock(_foot, Dock.Bottom);
        _foot.Margin = new Thickness(0, 12, 0, 8);
        body.Children.Add(_foot);
        body.Children.Add(_top);
        _pane = new Border { Width = 252, Padding = new Thickness(8, 8, 8, 8), Child = body };
        DockPanel.SetDock(_pane, Dock.Left);
        Children.Add(_pane);
        Children.Add(new Border
        {
            Background = Look.Soft(Color.FromRgb(0x80, 0x80, 0x80), 0x12), CornerRadius = new CornerRadius(14, 0, 0, 0),
            BorderBrush = Look.Line, BorderThickness = new Thickness(1, 1, 0, 0), Child = content, ClipToBounds = true,
        });
    }

    private void Narrow(bool narrow)
    {
        _narrow = narrow;
        _pane.Width = narrow ? 76 : 252;
        _title.IsVisible = !narrow;
        foreach (var i in _items)
            i.Words.IsVisible = !narrow;
    }

    /// <summary>The menu anew (a language changed): the title, the pages, the one open.</summary>
    public void Set(string title, IEnumerable<(string tag, string text, string tip, FASymbol symbol, Color colour, bool foot)> pages,
                    string open)
    {
        _title.Text = title;
        _top.Children.Clear();
        _foot.Children.Clear();
        _items.Clear();
        foreach (var (tag, text, tip, symbol, colour, foot) in pages)
        {
            var item = new Item(tag, text, tip, symbol, colour);
            item.PointerReleased += (_, e) =>
            {
                if (e.InitialPressMouseButton == MouseButton.Left)
                    Chosen?.Invoke(tag);
            };
            _items.Add(item);
            (foot ? _foot : _top).Children.Add(item);
        }
        Narrow(_narrow);
        Select(open);
    }

    public void Select(string tag)
    {
        foreach (var i in _items)
            i.On = i.Tag2 == tag;
    }
}
