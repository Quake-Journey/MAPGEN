using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.Media;
using Avalonia.Platform.Storage;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// Brief 23 D1, the PO 06.11 (his picture of «По выбранным картам»: thirty check boxes in rows and «Добавить карты…»):
/// «Зачем ты в таком виде то сделал? Добавить можно, удалить нельзя… нужно поле типа select box, в котором галочками
/// можно выбрать карты с диска, пометив, с каких брать текстуры». One button whose drop-down lists the game's maps - its
/// maps folder, the people's maps the generator measured (in the game's paks), the bases - a tick each and a search;
/// «Добавить карты…» takes a .bsp from another folder BY ITS PATH: nothing is copied (3.45-3.47 copied it into the
/// engine's donors, where it stayed for ever and became a base of the other form too), and unticked it is gone.
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>One map of the list: what goes into `StyleMaps` (a name, or an added file's full path), its words, its tip.</summary>
    internal sealed record StyleMapEntry(string Key, string Shown, string Tip, bool Added);

    /// <summary>A style map given by its path (added from another folder), not by its name.</summary>
    internal static bool IsPathEntry(string m) => Path.IsPathRooted(m);

    /// <summary>The game's maps folder of a client folder (where the game's own and downloaded maps lie).</summary>
    internal static string? ClientMapsDir(string? clientDir) =>
        string.IsNullOrWhiteSpace(clientDir) ? null : Path.Combine(clientDir, "baseq2", "maps");

    /// <summary>
    /// The list's maps: the files added by path first (as ticked), then by name, each once, sorted - the game's maps folder,
    /// the people's maps the generator measured, the bases, and any name ticked that is found nowhere now (so it can be
    /// unticked).
    /// </summary>
    internal static List<StyleMapEntry> StyleMapEntries(ScratchParams p, string? clientDir)
    {
        var list = new List<StyleMapEntry>();
        foreach (var f in p.StyleMaps.Where(IsPathEntry).Distinct(StringComparer.OrdinalIgnoreCase))
            list.Add(new StyleMapEntry(f, Path.GetFileNameWithoutExtension(f), Loc.F("scr.tex.maps.added", f), true));
        var game = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        var dir = ClientMapsDir(clientDir);
        try
        {
            if (dir != null && Directory.Exists(dir))
                foreach (var f in Directory.EnumerateFiles(dir, "*.bsp"))
                    game.Add(Path.GetFileNameWithoutExtension(f));
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException)
        {
        }
        var people = new HashSet<string>(ScratchParams.ReferenceMaps(), StringComparer.OrdinalIgnoreCase);
        var studio = new HashSet<string>(Engine.Donors(), StringComparer.OrdinalIgnoreCase);
        var names = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);
        names.UnionWith(game);
        names.UnionWith(people);
        names.UnionWith(studio);
        names.UnionWith(p.StyleMaps.Where(m => !IsPathEntry(m) && m.Length > 0));
        foreach (var n in names)
        {
            var tip = game.Contains(n) ? Loc.F("scr.tex.maps.game", Path.Combine(dir!, n + ".bsp"))
                    : people.Contains(n) ? Loc.T("scr.tex.maps.pak")
                    : studio.Contains(n) ? Loc.T("scr.tex.maps.studio")
                    : Loc.T("scr.tex.maps.gone");
            list.Add(new StyleMapEntry(n, n, tip, false));
        }
        return list;
    }

    /// <summary>The button's face: the ticked maps by name, or «не выбрано».</summary>
    internal static string StyleMapsSaid(ScratchParams p) =>
        p.StyleMaps.Count == 0 ? Loc.T("scr.tex.maps.none")
                               : string.Join(", ", p.StyleMaps.Select(m => IsPathEntry(m) ? Path.GetFileNameWithoutExtension(m) : m));

    /// <summary>
    /// A file added by its path into the ticked maps: one that lies in the game's maps folder or among the bases goes in
    /// by its name (it is in the list already). Throws with the user's words when it is not a Quake II map.
    /// </summary>
    internal static string AddStyleMap(ScratchParams p, string path, string? clientDir)
    {
        Engine.CheckBsp(path);
        var full = Path.GetFullPath(path);
        var folder = (Path.GetDirectoryName(full) ?? "").TrimEnd('\\', '/');
        var key = full;
        foreach (var known in new[] { ClientMapsDir(clientDir), Engine.DonorsDir })
            if (known != null && string.Equals(Path.GetFullPath(known).TrimEnd('\\', '/'), folder, StringComparison.OrdinalIgnoreCase))
                key = Path.GetFileNameWithoutExtension(full);
        if (!p.StyleMaps.Contains(key, StringComparer.OrdinalIgnoreCase))
            p.StyleMaps.Add(key);
        return key;
    }

    /// <summary>The row's control: a button with the ticked maps on its face; its drop-down the list (none on a run's page).</summary>
    private Control StyleMapsButton(ScratchParams p, bool viewOnly, Action keep)
    {
        var face = new TextBlock { TextTrimming = TextTrimming.CharacterEllipsis, MaxWidth = 260, VerticalAlignment = VerticalAlignment.Center };
        var button = new DropDownButton { Content = face, MinWidth = 240, HorizontalContentAlignment = HorizontalAlignment.Left };
        void Say()
        {
            face.Text = StyleMapsSaid(p);
            ToolTip.SetTip(button, p.StyleMaps.Count == 0
                ? Loc.T("scr.tex.maps.button.tip")
                : Loc.T("scr.tex.maps.button.tip") + "\n\n" + string.Join("\n", p.StyleMaps));
        }
        Say();
        if (viewOnly)
            return button;
        var flyout = new Flyout { Placement = PlacementMode.BottomEdgeAlignedLeft };
        // built at each opening: a file added and then unticked is not in it the next time
        flyout.Opening += (_, _) => flyout.Content = StyleMapList(p, () =>
        {
            keep();
            Say();
        });
        button.Flyout = flyout;
        return button;
    }

    /// <summary>
    /// The list itself: a search, the maps with a tick each (scrolling past ~12), how many are ticked, «Снять все» and
    /// «Добавить карты…». Built by itself so the self-test can lay it out without a drop-down (one needs a shown window).
    /// </summary>
    internal Control StyleMapList(ScratchParams p, Action changed)
    {
        var rows = new StackPanel { Spacing = 2, Margin = new Thickness(0, 0, 14, 0) };
        var count = new TextBlock { FontSize = 12.5, Opacity = 0.7, VerticalAlignment = VerticalAlignment.Center, TextWrapping = TextWrapping.Wrap };
        var search = new TextBox { PlaceholderText = Loc.T("scr.tex.maps.search") }.Tip("scr.tex.maps.search.tip");
        void Count() => count.Text = Loc.F("scr.tex.maps.count", p.StyleMaps.Count, rows.Children.Count);
        void Filter()
        {
            var q = (search.Text ?? "").Trim();
            foreach (var c in rows.Children.OfType<CheckBox>())
                c.IsVisible = q.Length == 0 || ((c.Tag as StyleMapEntry)?.Shown ?? "").Contains(q, StringComparison.OrdinalIgnoreCase);
        }
        void Fill()
        {
            rows.Children.Clear();
            foreach (var e in StyleMapEntries(p, S.ClientDir))
            {
                var entry = e;
                var box = new CheckBox
                {
                    Content = entry.Added ? $"{entry.Shown}  ({Loc.T("scr.tex.maps.added.word")})" : entry.Shown,
                    IsChecked = p.StyleMaps.Contains(entry.Key, StringComparer.OrdinalIgnoreCase),
                    Tag = entry,
                };
                ToolTip.SetTip(box, entry.Tip);
                box.IsCheckedChanged += (_, _) =>
                {
                    p.StyleMaps.RemoveAll(m => string.Equals(m, entry.Key, StringComparison.OrdinalIgnoreCase));
                    if (box.IsChecked == true)
                        p.StyleMaps.Add(entry.Key);
                    else if (entry.Added)
                        rows.Children.Remove(box);      // a file from another folder unticked is gone (the PO: «удалить нельзя»)
                    changed();
                    Count();
                };
                rows.Children.Add(box);
            }
            Filter();
            Count();
        }
        search.TextChanged += (_, _) => Filter();
        var clear = Ui.Button("scr.tex.maps.clear", "scr.tex.maps.clear.tip", FASymbol.Cancel);
        clear.Click += (_, _) =>
        {
            p.StyleMaps.Clear();
            changed();
            Fill();
        };
        var add = Ui.Button("scr.tex.pick", "scr.tex.pick.tip", FASymbol.OpenFile);
        add.Click += async (_, _) =>
        {
            var files = await StorageProvider.OpenFilePickerAsync(new FilePickerOpenOptions
            {
                Title = Loc.T("scr.tex.pick"),
                AllowMultiple = true,
                FileTypeFilter = new[] { new FilePickerFileType("Quake II BSP") { Patterns = new[] { "*.bsp" } } },
            });
            var any = false;
            foreach (var f in files)
            {
                var path = f.TryGetLocalPath();
                if (path == null)
                    continue;
                try
                {
                    AddStyleMap(p, path, S.ClientDir);
                    any = true;
                }
                catch (Exception ex) when (ex is InvalidOperationException or IOException or UnauthorizedAccessException)
                {
                    Notice(ex.Message, FAInfoBarSeverity.Warning);
                }
            }
            if (!any)
                return;
            changed();
            Fill();
        };
        Fill();
        var scroller = new ScrollViewer
        {
            Content = rows, MaxHeight = 420, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
            Tag = "style-maps-list",
        };
        var foot = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto,Auto"), ColumnSpacing = 8 };
        foot.Children.Add(count);
        Grid.SetColumn(clear, 1);
        foot.Children.Add(clear);
        Grid.SetColumn(add, 2);
        foot.Children.Add(add);
        // 420 wide: the drop-down's frame is at most 456 wide with its margins (FluentAvalonia's FlyoutPresenter, measured by
        // the self-test 06.11) - 3.48's 480 had its right edge cut, the scroll bar and «Добавить карты…» with it
        return new StackPanel
        {
            Spacing = 8, Width = 420, VerticalAlignment = VerticalAlignment.Top, Children = { search, scroller, foot }, Tag = "style-maps-drop",
        };
    }
}
