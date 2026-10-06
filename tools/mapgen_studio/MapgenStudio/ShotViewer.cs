using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Media.Imaging;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// A map's shots one at a time, as big as the window (the PO, 05.10: «при клике на фото ... модальное окошко в
/// увеличенном размере по размеру окна с кнопками вперед-назад ... а также с крестиком закрытия»). Over the Studio's
/// window and the size of it; ← / → and the buttons turn the shots, Esc and ✕ close; «Сделать обложкой» makes the
/// shot shown the map's cover.
/// </summary>
public sealed class ShotViewer : Window
{
    private readonly IReadOnlyList<string> _shots;
    private int _at;
    private readonly Image _image = new() { Stretch = Stretch.Uniform };
    private readonly TextBlock _count = new() { Foreground = Brushes.White, FontSize = 15, Opacity = 0.85,
                                                VerticalAlignment = VerticalAlignment.Center };
    private readonly Button _cover;
    private Bitmap? _shown;
    private string? _coverNow;

    /// <summary>The shot made the cover, when one was.</summary>
    public string? Chosen { get; private set; }

    public ShotViewer(IReadOnlyList<string> shots, int at, string? cover, Window owner)
    {
        _shots = shots;
        _at = Math.Clamp(at, 0, Math.Max(0, shots.Count - 1));
        _coverNow = cover;
        Title = "MAPGEN Studio";
        WindowDecorations = Avalonia.Controls.WindowDecorations.None;
        ShowInTaskbar = false;
        CanResize = false;
        Background = new SolidColorBrush(Color.FromArgb(0xf2, 0x10, 0x11, 0x14));
        // the owner's own place and size - the whole window, not a box in it
        WindowStartupLocation = WindowStartupLocation.Manual;
        Position = owner.Position;
        Width = owner.Bounds.Width;
        Height = owner.Bounds.Height;
        if (owner.WindowState == WindowState.Maximized)
            WindowState = WindowState.Maximized;

        Button Round(FASymbol symbol, string tip)
        {
            var b = new Button
            {
                Content = new FASymbolIcon { Symbol = symbol, FontSize = 28 }, Width = 64, Height = 64,
                CornerRadius = new CornerRadius(32), Opacity = 0.85,
                Background = new SolidColorBrush(Color.FromArgb(0x90, 0x30, 0x33, 0x3a)),
            };
            ToolTip.SetTip(b, Loc.T(tip));
            return b;
        }
        var prev = Round(FASymbol.Back, "shots.prev");
        var next = Round(FASymbol.Forward, "shots.next");
        var close = Round(FASymbol.Cancel, "shots.close");
        prev.Click += (_, _) => Turn(-1);
        next.Click += (_, _) => Turn(+1);
        close.Click += (_, _) => Close();
        _cover = Ui.Button("shots.cover", "shots.cover.tip", FASymbol.Pictures, accent: true);
        _cover.Click += (_, _) =>
        {
            Chosen = _coverNow = _shots[_at];
            Show(_at, _coverNow);
        };
        prev.HorizontalAlignment = HorizontalAlignment.Left;
        prev.VerticalAlignment = VerticalAlignment.Center;
        prev.Margin = new Thickness(24, 0, 0, 0);
        next.HorizontalAlignment = HorizontalAlignment.Right;
        next.VerticalAlignment = VerticalAlignment.Center;
        next.Margin = new Thickness(0, 0, 24, 0);
        close.HorizontalAlignment = HorizontalAlignment.Right;
        close.VerticalAlignment = VerticalAlignment.Top;
        close.Margin = new Thickness(0, 20, 24, 0);
        var bottom = new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 16, HorizontalAlignment = HorizontalAlignment.Center,
            VerticalAlignment = VerticalAlignment.Bottom, Margin = new Thickness(0, 0, 0, 20),
            Children = { _count, _cover },
        };
        _image.Margin = new Thickness(104, 24, 104, 84);
        Content = new Grid { Children = { _image, prev, next, close, bottom } };
        prev.IsVisible = next.IsVisible = shots.Count > 1;
        // taken before any button: a focused button would take the arrows for moving the focus
        AddHandler(KeyDownEvent, (_, e) =>
        {
            if (e.Key == Key.Escape)
                Close();
            else if (e.Key == Key.Left)
                Turn(-1);
            else if (e.Key == Key.Right)
                Turn(+1);
            else
                return;
            e.Handled = true;
        }, Avalonia.Interactivity.RoutingStrategies.Tunnel);
        PointerWheelChanged += (_, e) => Turn(e.Delta.Y > 0 ? -1 : +1);
        Closed += (_, _) => _shown?.Dispose();
        Show(_at, cover);
    }

    /// <summary>The shot shown now (the window test reads it).</summary>
    public int At => _at;

    private void Turn(int by)
    {
        if (_shots.Count == 0)
            return;
        Show((_at + by + _shots.Count) % _shots.Count, _coverNow);
    }

    private void Show(int at, string? cover)
    {
        _at = at;
        if (_shots.Count == 0)
            return;
        var old = _shown;
        try
        {
            using var file = File.OpenRead(_shots[at]);
            _shown = new Bitmap(file);
        }
        catch (Exception)
        {
            _shown = null;
        }
        _image.Source = _shown;
        old?.Dispose();
        var isCover = cover != null && string.Equals(_shots[at], cover, StringComparison.OrdinalIgnoreCase);
        _count.Text = Loc.F("shots.count", at + 1, _shots.Count) + (isCover ? " · " + Loc.T("shots.is_cover") : "");
        _cover.IsVisible = !isCover;
    }
}
