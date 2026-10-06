using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>Small builders, so every element gets its tooltip (R3) the same way.</summary>
public static class Ui
{
    public static T Tip<T>(this T control, string key) where T : Control
    {
        ToolTip.SetTip(control, Loc.T(key));
        return control;
    }

    public static TextBlock Title(string text) => new()
    {
        Text = text,
        FontSize = 28,
        FontWeight = FontWeight.SemiBold,
        Margin = new Thickness(0, 0, 0, 12),
    };

    public static TextBlock Section(string text) => new()
    {
        Text = text,
        FontSize = 16,
        FontWeight = FontWeight.SemiBold,
        Margin = new Thickness(0, 20, 0, 8),
    };

    public static TextBlock Text(string text, double size = 14, double opacity = 1.0) => new()
    {
        Text = text,
        FontSize = size,
        Opacity = opacity,
        TextWrapping = TextWrapping.Wrap,
    };

    public static FAIconSource Icon(FASymbol symbol) => new FASymbolIconSource { Symbol = symbol };

    public static FASettingsExpander Setting(string headerKey, string descKey, FASymbol symbol, Control footer,
                                              string tipKey)
    {
        footer.Tip(tipKey);
        var e = new FASettingsExpander
        {
            Header = Loc.T(headerKey),
            Description = Loc.T(descKey),
            IconSource = Icon(symbol),
            Footer = footer,
            Margin = new Thickness(0, 0, 0, 4),
        };
        return e.Tip(tipKey);
    }

    public static Button Button(string textKey, string tipKey, FASymbol? symbol = null, bool accent = false)
    {
        object content = Loc.T(textKey);
        if (symbol is { } s)
        {
            content = new StackPanel
            {
                Orientation = Orientation.Horizontal,
                Spacing = 8,
                Children =
                {
                    new FASymbolIcon { Symbol = s, FontSize = 16 },
                    new TextBlock { Text = Loc.T(textKey), VerticalAlignment = VerticalAlignment.Center },
                },
            };
        }
        var b = new Button { Content = content };
        if (accent)
            b.Classes.Add("accent");
        return b.Tip(tipKey);
    }

    public static ScrollViewer Page(Control content) => new()
    {
        Content = new Border
        {
            Padding = new Thickness(36, 28, 36, 36),
            MaxWidth = 1100,
            HorizontalAlignment = HorizontalAlignment.Stretch,
            Child = content,
        },
        HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
    };

    /// <summary>
    /// A page whose content fills the window's height instead of scrolling (row 410: the run's page, its log down to
    /// the window's bottom and following its size).
    /// </summary>
    public static Border FillPage(Control content) => new()
    {
        Padding = new Thickness(36, 28, 36, 28),
        MaxWidth = 1100,
        HorizontalAlignment = HorizontalAlignment.Stretch,
        VerticalAlignment = VerticalAlignment.Stretch,
        Child = content,
    };

    public static string Size(long bytes) =>
        bytes >= 1 << 20 ? $"{bytes / 1048576.0:0.0} MB" : $"{bytes / 1024.0:0} KB";
}
