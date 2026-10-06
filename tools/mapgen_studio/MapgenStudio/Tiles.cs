using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Interactivity;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// Tiles that fill the page's whole width (the PO, 05.10: the library's maps and a map's shots - Ctrl+wheel and a
/// slider make the tiles bigger, the pictures stretched to the tile, the captions in proportion, and the tiles take
/// the whole width there is). Each child is a card designed at <see cref="BaseWidth"/>: the row's tiles are as wide
/// as fits the target width (<see cref="Target"/>) evenly across the width, and each card is scaled - picture and
/// words together - to its tile.
/// </summary>
public sealed class TileWall : Panel
{
    public double BaseWidth { get; init; } = 240;
    public double Gap { get; init; } = 14;
    private double _target = 240;

    public double Target
    {
        get => _target;
        set
        {
            if (Math.Abs(_target - value) < 0.5)
                return;
            _target = value;
            InvalidateMeasure();
        }
    }

    private (int cols, double width) Columns(double available)
    {
        if (double.IsInfinity(available) || available <= 0)
            return (1, _target);
        var cols = Math.Max(1, (int)Math.Floor((available + Gap) / (_target + Gap)));
        return (cols, (available - Gap * (cols - 1)) / cols);
    }

    protected override Size MeasureOverride(Size available)
    {
        var (cols, w) = Columns(available.Width);
        double height = 0, row = 0;
        for (var i = 0; i < Children.Count; i++)
        {
            var c = Children[i];
            if (c is LayoutTransformControl lt && lt.LayoutTransform is ScaleTransform st)
                st.ScaleX = st.ScaleY = w / BaseWidth;
            c.Measure(new Size(w, double.PositiveInfinity));
            row = Math.Max(row, c.DesiredSize.Height);
            if (i % cols == cols - 1 || i == Children.Count - 1)
            {
                height += row + (i == Children.Count - 1 ? 0 : Gap);
                row = 0;
            }
        }
        return new Size(double.IsInfinity(available.Width) ? cols * (w + Gap) : available.Width, height);
    }

    protected override Size ArrangeOverride(Size final)
    {
        var (cols, w) = Columns(final.Width);
        double y = 0;
        for (var start = 0; start < Children.Count; start += cols)
        {
            var row = 0.0;
            for (var i = start; i < Math.Min(Children.Count, start + cols); i++)
                row = Math.Max(row, Children[i].DesiredSize.Height);
            for (var i = start; i < Math.Min(Children.Count, start + cols); i++)
                Children[i].Arrange(new Rect((i - start) * (w + Gap), y, w, row));
            y += row + Gap;
        }
        return final;
    }

    /// <summary>A card at <see cref="BaseWidth"/>, to be scaled to its tile.</summary>
    public static LayoutTransformControl Card(Control content) =>
        new() { LayoutTransform = new ScaleTransform(1, 1), Child = content };
}

/// <summary>
/// The page frame for tiles: the top (title, buttons, the size slider) stays put, only the tiles scroll; Ctrl+wheel
/// anywhere on it resizes the tiles as the slider does, and the size is kept in the settings.
/// </summary>
public static class TilePage
{
    public static Control Build(Control top, Control body, TileWall wall, double min, Func<double> get, Action<double> set)
    {
        var slider = new Slider
        {
            Minimum = min, Maximum = Math.Max(min * 8, 2400), Value = get(), Width = 220,
            VerticalAlignment = VerticalAlignment.Center, Margin = new Thickness(8, 0, 0, 0),
        };
        ToolTip.SetTip(slider, Loc.T("tiles.size.tip"));
        wall.Target = get();
        slider.PropertyChanged += (_, e) =>
        {
            if (e.Property != Avalonia.Controls.Primitives.RangeBase.ValueProperty)
                return;
            wall.Target = slider.Value;
            set(slider.Value);
        };
        var size = new StackPanel
        {
            Orientation = Orientation.Horizontal, Margin = new Thickness(0, 4, 0, 0),
            Children =
            {
                new FASymbolIcon { Symbol = FASymbol.ZoomIn, FontSize = 16, VerticalAlignment = VerticalAlignment.Center },
                new TextBlock { Text = Loc.T("tiles.size"), VerticalAlignment = VerticalAlignment.Center,
                                Margin = new Thickness(8, 0, 0, 0), Opacity = 0.8 },
                slider,
            },
        };
        var head = new StackPanel { Spacing = 8, Margin = new Thickness(36, 28, 36, 8), Children = { top, size } };
        var scroll = new ScrollViewer
        {
            Content = new Border { Padding = new Thickness(36, 8, 36, 36), Child = body },
            HorizontalScrollBarVisibility = Avalonia.Controls.Primitives.ScrollBarVisibility.Disabled,
        };
        var page = new DockPanel { LastChildFill = true };
        DockPanel.SetDock(head, Dock.Top);
        page.Children.Add(head);
        page.Children.Add(scroll);
        // Ctrl+wheel: bigger or smaller tiles, not a scroll (taken before the scroll viewer sees it)
        page.AddHandler(InputElement.PointerWheelChangedEvent, (_, e) =>
        {
            if ((e.KeyModifiers & KeyModifiers.Control) == 0)
                return;
            slider.Value = Math.Clamp(slider.Value * Math.Pow(1.12, e.Delta.Y), slider.Minimum, slider.Maximum);
            e.Handled = true;
        }, RoutingStrategies.Tunnel);
        return page;
    }

    private static readonly Dictionary<string, (DateTime when, Bitmap bmp)> Cache = new(StringComparer.OrdinalIgnoreCase);

    /// <summary>A picture decoded once at a width that stays sharp on a big tile, kept while the file is the same.</summary>
    public static Bitmap? Picture(string path, int width = 1600)
    {
        try
        {
            var when = File.GetLastWriteTimeUtc(path);
            if (Cache.TryGetValue(path, out var hit) && hit.when == when)
                return hit.bmp;
            using var file = File.OpenRead(path);
            var bmp = Bitmap.DecodeToWidth(file, width);
            Cache[path] = (when, bmp);
            return bmp;
        }
        catch (Exception)
        {
            return null;
        }
    }
}
