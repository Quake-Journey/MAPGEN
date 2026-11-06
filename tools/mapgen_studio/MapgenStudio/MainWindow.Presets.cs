using System.ComponentModel;
using System.Reflection;
using System.Text;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.LogicalTree;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// Brief 23 D2, the PO 06.11: «на окошке с параметрами где-то сверху (his picture: the empty space right of «Новая карта»)
/// появляется новый интерфейс работы с пресетами, контекстно зависимый от того, форк или новая карта. Кнопочки Загрузить
/// пресет, Создать пресет, Изменить пресет, Удалить пресет. При создании запрашивается имя и категория (новая либо из
/// ранее созданных, включая заводские). Удалять заводские нельзя, при удалении пользовательских - подтверждение».
/// </summary>
public sealed partial class MainWindow
{
    private TextBlock? _presetLabel;
    private DropDownButton? _presetLoad;
    private Button? _presetCreate;
    private Button? _presetEdit;
    private Button? _presetDelete;
    private static bool s_presetFileSaid;

    private string PresetKind => S.ScratchMode ? Presets.Scratch : Presets.Base;

    private string LastPresetId
    {
        get => S.ScratchMode ? S.PresetScratch : S.PresetBase;
        set
        {
            if (S.ScratchMode)
                S.PresetScratch = value;
            else
                S.PresetBase = value;
        }
    }

    /// <summary>The preset the label names: the one the form's values are (the last loaded first), else the last loaded.</summary>
    internal Preset? CurrentPreset() => PresetNow().cur;

    /// <summary>«Вертикаль», «Вертикаль (изменён)» or «свой набор».</summary>
    internal string PresetSaid() => PresetNow().said;

    /// <summary>The preset in use and the label's words, the form's values compared once.</summary>
    private (Preset? cur, string said) PresetNow()
    {
        var kind = PresetKind;
        var match = Presets.Matching(kind, Presets.BodyOf(S, kind), LastPresetId);
        if (match != null)
            return (match, match.Name);
        var last = Presets.All(kind).FirstOrDefault(p => p.Id == LastPresetId);
        return (last, last != null ? Loc.F("preset.changed", last.Name) : Loc.T("preset.own"));
    }

    /* what «Загрузить»'s menu was made for: made again only when its rows would differ (160 presets - brief 24 D5) */
    private string _presetMenuFor = "";

    /// <summary>The label and the buttons said again (every change of the form passes here, through KeepForm).</summary>
    private void SayPreset()
    {
        if (_presetLabel == null || _presetLoad == null || _presetEdit == null || _presetDelete == null || _presetCreate == null)
            return;
        var (cur, said) = PresetNow();
        /*
         * «Загрузить»'s menu made anew here, full, before any press. The PO 06.11 (3.48): «при нажатии на Загрузить ничего
         * не происходит - появляется только вертикальная линия слева». 3.48 filled the menu in its Opening; Avalonia 12.1
         * gives the popup the menu's list BEFORE Opening (PopupFlyoutBase.ShowAtCore: CreatePresenter, then Opening), and
         * the rows put into the list then never reached it - an empty frame, the thin line (self-test: 0 rows of 5). A
         * menu made with its rows, as the copy menu is made (CopyText.ShowAt), shows them.
         */
        var menuFor = $"{PresetKind}|{Loc.Language}|{cur?.Id}|{Presets.ReadError != null}|"
                      + string.Join(";", Presets.User().Where(x => x.Kind == PresetKind).Select(x => $"{x.Id}:{x.Name}:{x.Category}"));
        if (menuFor != _presetMenuFor || _presetLoad.Flyout == null)
        {
            _presetMenuFor = menuFor;
            _presetLoad.Flyout = new MenuFlyout { Placement = PlacementMode.BottomEdgeAlignedLeft, ItemsSource = PresetMenu(cur) };
        }
        _presetLabel.Text = said;
        var tip = cur == null ? Loc.Ts("preset.bar.tip", S.ScratchMode)
                : cur.Factory ? $"{cur.Name} — {Loc.T($"preset.{cur.Kind}.{Presets.FactoryKey(cur)}.tip")}"
                : $"{cur.Name} — {Loc.T("preset.user.tip")} ({Presets.CategoryName(cur.Category)})";
        ToolTip.SetTip(_presetLabel, tip);
        var writable = Presets.ReadError == null;
        var mine = cur != null && !cur.Factory;
        _presetCreate.IsEnabled = writable;
        _presetEdit.IsEnabled = writable && mine;
        _presetDelete.IsEnabled = writable && mine;
        ToolTip.SetTip(_presetEdit, Loc.T(!writable ? "preset.file.bad.tip" : mine ? "preset.edit.tip" : cur != null ? "preset.edit.factory.tip" : "preset.edit.none.tip"));
        ToolTip.SetTip(_presetDelete, Loc.T(!writable ? "preset.file.bad.tip" : mine ? "preset.delete.tip" : cur != null ? "preset.delete.factory.tip" : "preset.edit.none.tip"));
        ToolTip.SetTip(_presetCreate, Loc.T(writable ? "preset.create.tip" : "preset.file.bad.tip"));
    }

    /// <summary>The bar at the page's head: the preset in use, and Загрузить ▾ / Создать / Изменить / Удалить.</summary>
    private Control PresetBar()
    {
        var kind = PresetKind;
        Presets.User();
        if (Presets.ReadError != null && !s_presetFileSaid && !SelfTesting)
        {
            s_presetFileSaid = true;
            Notice(Loc.F("preset.file.bad", Presets.ReadError), FAInfoBarSeverity.Warning);
        }
        _presetLabel = new TextBlock
        {
            FontWeight = FontWeight.SemiBold, FontSize = 14.5, TextTrimming = TextTrimming.CharacterEllipsis, MaxWidth = 340,
            VerticalAlignment = VerticalAlignment.Center,
        };
        var head = new StackPanel
        {
            Orientation = Orientation.Horizontal, Spacing = 6,
            Children = { new TextBlock { Text = Loc.T("preset.label"), FontSize = 14.5, Opacity = 0.75, VerticalAlignment = VerticalAlignment.Center }, _presetLabel },
        };
        ToolTip.SetTip(head, Loc.Ts("preset.bar.tip", S.ScratchMode));
        var load = new DropDownButton
        {
            Content = new StackPanel
            {
                Orientation = Orientation.Horizontal, Spacing = 8,
                Children = { new FASymbolIcon { Symbol = FASymbol.List, FontSize = 16 }, new TextBlock { Text = Loc.T("preset.load"), VerticalAlignment = VerticalAlignment.Center } },
            },
            Tag = "preset-load",
        }.Tip("preset.load.tip");
        _presetLoad = load;
        _presetCreate = Ui.Button("preset.create", "preset.create.tip", FASymbol.Add);
        _presetEdit = Ui.Button("preset.edit", "preset.edit.tip", FASymbol.Edit);
        _presetDelete = Ui.Button("preset.delete", "preset.delete.tip", FASymbol.Delete);
        _presetCreate.Click += async (_, _) => await PresetDialog(null);
        _presetEdit.Click += async (_, _) =>
        {
            if (CurrentPreset() is { Factory: false } mine)
                await PresetDialog(mine);
        };
        _presetDelete.Click += async (_, _) =>
        {
            if (CurrentPreset() is not { Factory: false } mine)
                return;
            await DeletePreset(mine, () => Confirm(Loc.F("preset.delete.title", mine.Name), Loc.T("preset.delete.text"),
                                                   "preset.delete.yes", "preset.delete.no"));
        };
        var buttons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 6, Children = { load, _presetCreate, _presetEdit, _presetDelete } };
        SayPreset();
        return new StackPanel { Spacing = 8, HorizontalAlignment = HorizontalAlignment.Right, Children = { head, buttons }, Tag = "preset-bar-" + kind };
    }

    /// <summary>The presets the menu offers: the form's own - the factory's, then the user's.</summary>
    internal List<Preset> PresetMenuList() => Presets.All(PresetKind);

    /// <summary>«Загрузить»: a sub-menu per category, the factory's first, the preset in use ticked.</summary>
    private List<MenuItem> PresetMenu(Preset? cur)
    {
        var kind = PresetKind;
        var all = PresetMenuList();
        var items = new List<MenuItem>();
        foreach (var cat in Presets.Categories(kind))
        {
            var inCat = all.Where(p => string.Equals(p.Category, cat, StringComparison.OrdinalIgnoreCase)).ToList();
            if (inCat.Count == 0)
                continue;
            var factoryCat = cat.StartsWith(Presets.FactoryPrefix, StringComparison.Ordinal);
            var head = new MenuItem
            {
                Header = Presets.CategoryName(cat),
                Icon = new FASymbolIcon { Symbol = factoryCat ? FASymbol.Library : FASymbol.People, FontSize = 16 },
            };
            ToolTip.SetTip(head, Loc.T(factoryCat ? "preset.cat.factory.tip" : "preset.cat.user.tip"));
            foreach (var p in inCat.Where(p => p.Factory).Concat(inCat.Where(p => !p.Factory).OrderBy(p => p.Name, StringComparer.CurrentCultureIgnoreCase)))
            {
                var preset = p;
                var item = new MenuItem
                {
                    Header = preset.Name,
                    Icon = cur?.Id == preset.Id ? new FASymbolIcon { Symbol = FASymbol.Accept, FontSize = 16 } : null,
                };
                ToolTip.SetTip(item, preset.Factory ? Loc.T($"preset.{kind}.{Presets.FactoryKey(preset)}.tip") : Loc.T("preset.user.tip"));
                item.Click += (_, _) => LoadPreset(preset);
                head.Items.Add(item);
            }
            items.Add(head);
        }
        // a user preset whose category was left empty (a hand-edited file) is still offered
        foreach (var p in all.Where(p => !p.Factory && p.Category.Length == 0))
        {
            var preset = p;
            var item = new MenuItem { Header = preset.Name };
            item.Click += (_, _) => LoadPreset(preset);
            items.Add(item);
        }
        return items;
    }

    /// <summary>A preset's values into the form; the bases, the number and the name stay as they are.</summary>
    internal void LoadPreset(Preset p)
    {
        Presets.Apply(S, p.Kind, p.Body);
        LastPresetId = p.Id;
        if (p.Kind == Presets.Base)
            _graftMode = S.GraftMode;
        if (!SelfTesting)
            S.Save();
        ShowPage();
    }

    /// <summary>What is wrong with a name and a category for a preset of a form; null when they will do.</summary>
    internal static string? PresetProblem(string kind, string name, string category, Preset? editing)
    {
        if (name.Trim().Length == 0)
            return Loc.T("preset.err.name");
        if (Presets.IsFactoryName(kind, name))
            return Loc.T("preset.err.factory");
        if (category.Trim().Length == 0)
            return Loc.T("preset.err.category");
        if (editing != null && Presets.UserNamed(kind, name) is { } other && other.Id != editing.Id)
            return Loc.T("preset.err.taken");
        return null;
    }

    /// <summary>«Создать» (editing null) and «Изменить»: the name, the category - one of the form's or a new one - and,
    /// when changing, whether the form's values go into it.</summary>
    private async Task PresetDialog(Preset? editing)
    {
        var kind = PresetKind;
        var cats = Presets.Categories(kind);
        var catNames = cats.Select(Presets.CategoryName).Append(Loc.T("preset.cat.new")).ToList();
        var name = new TextBox { Text = editing?.Name ?? "", PlaceholderText = Loc.T("preset.name.hint"), MinWidth = 380 };
        var catAt = editing != null ? cats.FindIndex(c => string.Equals(c, editing.Category, StringComparison.OrdinalIgnoreCase))
                  : cats.FindIndex(c => !c.StartsWith(Presets.FactoryPrefix, StringComparison.Ordinal));
        var catBox = new ComboBox { ItemsSource = catNames, MinWidth = 380, SelectedIndex = catAt >= 0 ? catAt : catNames.Count - 1 };
        var newCat = new TextBox { PlaceholderText = Loc.T("preset.cat.new.hint"), MinWidth = 380, IsVisible = catBox.SelectedIndex == catNames.Count - 1 };
        catBox.SelectionChanged += (_, _) => newCat.IsVisible = catBox.SelectedIndex == catNames.Count - 1;
        var write = new CheckBox { Content = Loc.T("preset.edit.write"), IsChecked = true, IsVisible = editing != null };
        var said = new TextBlock { TextWrapping = TextWrapping.Wrap, MaxWidth = 380, Foreground = Brushes.OrangeRed, IsVisible = false };
        var panel = new StackPanel
        {
            Spacing = 6,
            Children =
            {
                new TextBlock { Text = Loc.T("preset.name"), FontWeight = FontWeight.SemiBold }, name,
                new TextBlock { Text = Loc.T("preset.category"), FontWeight = FontWeight.SemiBold, Margin = new Thickness(0, 8, 0, 0) }, catBox, newCat,
                write, said,
            },
        };
        var dialog = new FAContentDialog
        {
            Title = editing == null ? Loc.T("preset.dialog.new") : Loc.F("preset.dialog.edit", editing.Name),
            Content = panel,
            PrimaryButtonText = Loc.T(editing == null ? "preset.create" : "preset.save"),
            CloseButtonText = Loc.T("preset.cancel"),
            DefaultButton = FAContentDialogButton.Primary,
        };
        Preset? overwrite = null;
        var overwriteAsked = false;
        string chosenName = "", chosenCat = "";
        name.TextChanged += (_, _) =>
        {
            if (!overwriteAsked)
                return;
            overwriteAsked = false;
            dialog.PrimaryButtonText = Loc.T(editing == null ? "preset.create" : "preset.save");
            said.IsVisible = false;
        };
        dialog.PrimaryButtonClick += (_, e) =>
        {
            var n = (name.Text ?? "").Trim();
            var cat = catBox.SelectedIndex >= 0 && catBox.SelectedIndex < cats.Count ? cats[catBox.SelectedIndex]
                                                                                       : Presets.CategoryOf(kind, newCat.Text ?? "");
            var why = PresetProblem(kind, n, cat, editing);
            if (why != null)
            {
                e.Cancel = true;
                said.Text = why;
                said.IsVisible = true;
                return;
            }
            overwrite = editing == null ? Presets.UserNamed(kind, n) : null;
            if (overwrite != null && !overwriteAsked)
            {
                // the PO: «сохранять, перезаписывать» - a name taken is written over only when asked twice
                e.Cancel = true;
                overwriteAsked = true;
                said.Text = Loc.F("preset.overwrite.ask", overwrite.Name);
                said.IsVisible = true;
                dialog.PrimaryButtonText = Loc.T("preset.overwrite");
                return;
            }
            chosenName = n;
            chosenCat = cat;
        };
        if (await dialog.ShowAsync(this) != FAContentDialogResult.Primary || chosenName.Length == 0)
            return;
        var body = editing == null || write.IsChecked == true ? Presets.BodyOf(S, kind) : null;
        var saved = Presets.Save(kind, chosenName, chosenCat, body, editing?.Id ?? overwrite?.Id);
        if (saved == null)
        {
            Notice(Loc.F("preset.write.failed", Presets.ReadError ?? Presets.FilePath), FAInfoBarSeverity.Error);
            return;
        }
        if (body != null || editing == null)
            LastPresetId = saved.Id;
        if (!SelfTesting)
            S.Save();
        Notice(Loc.F("preset.saved", saved.Name));
        SayPreset();
    }

    /// <summary>A user preset removed after `ask` says yes; a factory one never. True when it is gone.</summary>
    internal async Task<bool> DeletePreset(Preset p, Func<Task<bool>> ask)
    {
        if (p.Factory || !await ask())
            return false;
        if (!Presets.Delete(p.Id))
        {
            Notice(Loc.F("preset.write.failed", Presets.ReadError ?? Presets.FilePath), FAInfoBarSeverity.Error);
            return false;
        }
        if (LastPresetId == p.Id)
            LastPresetId = "";
        if (!SelfTesting)
            S.Save();
        Notice(Loc.F("preset.deleted", p.Name));
        SayPreset();
        return true;
    }

    // ---- the self-test's rows ----------------------------------------------------------------------------------

    /// <summary>
    /// A drop-down opened as the program opens it, without a shown window (the self-test shows none): Avalonia 12.1's
    /// PopupFlyoutBase.ShowAtCore makes the popup's content (CreatePresenter) and then raises Opening - read from its
    /// code 06.11. The content is then laid out in a window of its own. The PO 06.11: «при нажатии на Загрузить ничего не
    /// происходит - появляется только вертикальная линия слева»; the rows of 3.48 checked the list behind the menu and
    /// never the menu opened.
    /// </summary>
    internal static Control OpenedFlyout(FlyoutBase f, out int shown, out Size size)
    {
        const BindingFlags any = BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public;
        var popup = (Popup)typeof(PopupFlyoutBase).GetProperty("Popup", any)!.GetValue(f)!;
        var presenter = (Control)typeof(PopupFlyoutBase).GetMethod("CreatePresenter", any)!.Invoke(f, null)!;
        popup.Child = presenter;
        typeof(PopupFlyoutBase).GetMethod("OnOpening", any, new[] { typeof(CancelEventArgs) })!.Invoke(f, new object[] { new CancelEventArgs() });
        popup.Child = null;
        var w = new Window { Content = presenter };
        LayOut(w, new Size(900, 900), unfold: false);
        shown = presenter is ItemsControl ic ? ic.GetRealizedContainers().Count() : presenter.GetLogicalDescendants().OfType<CheckBox>().Count();
        size = presenter.Bounds.Size;
        return presenter;
    }

    /// <summary>A Quake II map's head and nothing else - enough for a list or for the style's check.</summary>
    private static void FakeBsp(string path)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        File.WriteAllBytes(path, new byte[] { (byte)'I', (byte)'B', (byte)'S', (byte)'P', 38, 0, 0, 0 });
    }

    /// <summary>Brief 23: the style maps' list, the six annex sizes, the presets - every row on the self-test's own files.</summary>
    internal static void PresetsSelfTest(StringBuilder b)
    {
        var s = App.Settings;
        var keepScratch = s.Scratch.Save();
        var keepMinutes = s.Minutes;
        var keepFidelity = s.Fidelity;
        var keepSkip = s.SkipFamilies.ToList();
        var keepGraft = s.GraftMode;
        var keepOptions = s.Options;
        var keepBases = s.Bases.ToList();
        var keepMode = s.ScratchMode;
        var keepIds = (s.PresetScratch, s.PresetBase);
        var keepClient = s.ClientDir;
        var keepLang = Loc.Language;
        var dir = Path.Combine(s.TempPath, $"selftest_presets_{Environment.ProcessId}");
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        try
        {
            Loc.Language = "ru";
            Directory.CreateDirectory(dir);
            // ---- D1: the style maps' list
            {
                var client = Path.Combine(dir, "client");
                for (var i = 0; i < 240; i++)
                    FakeBsp(Path.Combine(client, "baseq2", "maps", $"stm_{i:000}.bsp"));
                s.ClientDir = client;
                var p = new ScratchParams { Style = "maps" };
                var entries = StyleMapEntries(p, client);
                var w = new MainWindow();
                var list = w.StyleMapList(p, () => { });
                var lw = new Window { Content = list };
                LayOut(lw, ScreenSizes[1], unfold: false);
                var rows = list.GetLogicalDescendants().OfType<CheckBox>().Count();
                var game = entries.Count(e => e.Key.StartsWith("stm_", StringComparison.Ordinal));
                var scroll = list.GetLogicalDescendants().OfType<ScrollViewer>().FirstOrDefault(v => v.Tag as string == "style-maps-list");
                var high = list.Bounds.Height;
                Row(game == 240 && rows == entries.Count && high < 600 && scroll != null && scroll.Extent.Height > scroll.Viewport.Height,
                    $"the style maps' list: the game's 240 maps and {entries.Count - 240} more, a tick each, {high:0} px high (it scrolls: {scroll?.Extent.Height:0} in {scroll?.Viewport.Height:0})",
                    $"the style maps' list: {game} of the game's 240 maps, {rows} rows of {entries.Count}, {high:0} px high, scrolls {scroll?.Extent.Height:0} in {scroll?.Viewport.Height:0}");
                s.ScratchMode = true;
                s.Scratch = p;
                var pw = new MainWindow { _page = "generate" };
                pw.Rebuild();
                LayOut(pw, ScreenSizes[1], unfold: false);
                var card = pw.GetLogicalDescendants().OfType<Border>().FirstOrDefault(c => c.Tag is OptionGroup og && og.Key == "scr.style");
                var boxesOnPage = pw.GetLogicalDescendants().OfType<CheckBox>().Count(c => (c.Content as string ?? "").StartsWith("stm_", StringComparison.Ordinal));
                Row(card != null && card.Bounds.Height < 900 && boxesOnPage == 0,
                    $"the generate page with 240 maps in the game: the style card {card?.Bounds.Height:0} px, the maps in the drop-down, not on the page",
                    $"the generate page with 240 maps in the game: the style card {(card == null ? "missing" : $"{card.Bounds.Height:0} px")}, {boxesOnPage} map boxes on the page");
                // the drop-down opened as a press opens it: the list in it, not an empty frame
                var styleButton = pw.GetLogicalDescendants().OfType<DropDownButton>().FirstOrDefault(d => d.Flyout is Flyout);
                var styleShown = 0;
                var styleSize = default(Size);
                var styleDrop = styleButton?.Flyout is { } sf ? OpenedFlyout(sf, out styleShown, out styleSize) : null;
                // and the whole list inside the frame (3.48: a list 480 wide in a frame of 456 - its right edge cut)
                var styleList = styleDrop?.GetLogicalDescendants().OfType<StackPanel>().FirstOrDefault(c => c.Tag as string == "style-maps-drop");
                var styleRight = styleList == null ? double.NaN : styleList.TranslatePoint(new Point(styleList.Bounds.Width, 0), styleDrop!)?.X ?? double.NaN;
                Row(styleDrop != null && styleShown >= 240 && styleSize.Width > 300 && styleSize.Height > 200 && styleRight <= styleSize.Width,
                    $"«По выбранным картам» pressed: the drop-down shows the list, {styleShown} maps, {styleSize.Width:0} x {styleSize.Height:0} px, its right edge at {styleRight:0}",
                    $"«По выбранным картам» pressed: {(styleDrop == null ? "no drop-down" : $"{styleShown} maps shown, {styleSize.Width:0} x {styleSize.Height:0} px, the list's right edge at {styleRight:0}")}");
                // a map from another folder: read where it lies, never a base; unticked it is gone
                var other = Path.Combine(dir, "elsewhere", "my_map.bsp");
                FakeBsp(other);
                var donors = string.Join(",", Engine.Donors());
                var key = AddStyleMap(p, other, client);
                var py = p.ToPython(null, Engine.DonorsDir);
                var passed = py.Contains(other.Replace("\\", "\\\\"), StringComparison.OrdinalIgnoreCase);
                var list2 = w.StyleMapList(p, () => { });
                var added = list2.GetLogicalDescendants().OfType<CheckBox>().FirstOrDefault(c => (c.Tag as StyleMapEntry)?.Added == true);
                if (added != null)
                    added.IsChecked = false;
                var gone = !p.StyleMaps.Contains(other, StringComparer.OrdinalIgnoreCase)
                           && !list2.GetLogicalDescendants().OfType<CheckBox>().Any(c => (c.Tag as StyleMapEntry)?.Added == true);
                Row(key == Path.GetFullPath(other) && string.Join(",", Engine.Donors()) == donors && passed && added != null && gone,
                    "a style map from another folder: its path to the generator, the bases as they were, unticked it leaves the list",
                    $"a style map from another folder: key {key}, bases {(string.Join(",", Engine.Donors()) == donors ? "same" : "CHANGED")}, "
                    + $"path to the generator {passed}, in the list {added != null}, gone after unticking {gone}");
                var inGame = AddStyleMap(p, Path.Combine(client, "baseq2", "maps", "stm_007.bsp"), client);
                var bad = Path.Combine(dir, "elsewhere", "not_a_map.bsp");
                File.WriteAllText(bad, "not a map");
                var refused = false;
                try
                {
                    AddStyleMap(p, bad, client);
                }
                catch (InvalidOperationException)
                {
                    refused = true;
                }
                Row(inGame == "stm_007" && refused && !p.StyleMaps.Contains(bad, StringComparer.OrdinalIgnoreCase),
                    "a style map added from the game's own maps folder goes in by its name; a file that is not a Quake II map is refused",
                    $"a style map from the game's folder: {inGame}; a file not a map refused {refused}");
                s.ClientDir = keepClient;
            }
            // ---- D3: the six annex sizes kept by the settings
            {
                var ini = Path.Combine(dir, "settings.ini");
                var t = new Settings { PresetScratch = "factory:scratch:world_snow", PresetBase = "abc" };
                t.Options = t.Options with { AnnexSize = 5 };
                t.Save(ini);
                var r = Settings.Load(ini);
                Row(r.Options.AnnexSize == 5 && r.PresetScratch == t.PresetScratch && r.PresetBase == "abc",
                    "«Ниши» (annex size 5) and the presets in use come back from the settings file",
                    $"settings file: annex size {r.Options.AnnexSize} (5 asked), presets «{r.PresetScratch}» «{r.PresetBase}»");
            }
            // ---- D2: the presets
            Presets.PathOverride = Path.Combine(dir, "presets.json");
            Presets.Forget();
            // every factory value is one of its row's choices; names and tips in both languages
            foreach (var kind in new[] { Presets.Scratch, Presets.Base })
            {
                var misses = new List<string>();
                var words = new List<string>();
                foreach (var f in Presets.Factory(kind))
                {
                    var w = new MainWindow();
                    w._choiceMisses.Clear();
                    if (kind == Presets.Scratch)
                        w.ScratchCards(Presets.ScratchOf(f.Body));
                    else
                    {
                        var o = Presets.OptionsOf(f.Body);
                        w.FramePicker(o);
                        w.CreativePicker(o);
                    }
                    misses.AddRange(w._choiceMisses.Select(m => $"{Presets.FactoryKey(f)}: {m}"));
                    foreach (var k in new[] { $"preset.{kind}.{Presets.FactoryKey(f)}", $"preset.{kind}.{Presets.FactoryKey(f)}.tip" })
                        if (!Loc.HasIn("ru", k) || !Loc.HasIn("en", k))
                            words.Add(k);
                }
                foreach (var c in Presets.FactoryCategories(kind))
                    if (!Loc.HasIn("ru", "preset.cat." + c) || !Loc.HasIn("en", "preset.cat." + c))
                        words.Add("preset.cat." + c);
                var n = Presets.Factory(kind).Count;
                // brief 24 D5: 160 for a map from scratch (the PO: «ещё раз в 10 больше»), each key once
                var keysOnce = Presets.Factory(kind).Select(Presets.FactoryKey).Distinct().Count() == n;
                Row(misses.Count == 0 && words.Count == 0 && keysOnce && n >= (kind == Presets.Scratch ? 184 : 10),
                    $"{n} factory presets of «{kind}»: every value one of its row's choices, names and tips in both languages",
                    $"factory presets of «{kind}» ({n}): values the rows cannot show {string.Join("; ", misses.Take(6))}; words missing {string.Join(", ", words.Take(6))}");
            }
            // the store: written and read back the same
            var sp = new ScratchParams { Players = 4, Lifts = 6, Style = "generated", GenTheme = "snow" };
            sp.StyleMaps.Add("q2dm1");
            var body = Presets.ScratchBody(sp, 2);
            var mine = Presets.Save(Presets.Scratch, "Тест один", "Мои карты", body);
            Presets.Forget();
            var back = mine == null ? null : Presets.User().FirstOrDefault(x => x.Id == mine.Id);
            Row(back != null && back.Name == "Тест один" && back.Category == "Мои карты" && back.Kind == Presets.Scratch
                && Presets.Canon(Presets.Scratch, back.Body) == Presets.Canon(Presets.Scratch, body),
                "a user preset written to its file and read back: its name, category and values",
                $"a user preset round trip: {(back == null ? "not read back" : $"«{back.Name}» «{back.Category}»")}");
            // brief 24 D5: «Миры» (3.48-3.49) split into the duels' and the free-for-all's - a user preset put there stays offered
            {
                var keep = File.ReadAllText(Presets.FilePath);
                var node = System.Text.Json.Nodes.JsonNode.Parse(keep)!.AsObject();
                var old = new System.Text.Json.Nodes.JsonObject
                {
                    ["id"] = "user-old-worlds", ["kind"] = Presets.Scratch, ["name"] = "Старый мир", ["category"] = "factory:worlds",
                    ["body"] = Presets.ScratchBody(new ScratchParams(), 1),
                };
                node["presets"]!.AsArray().Add(old);
                File.WriteAllText(Presets.FilePath, node.ToJsonString());
                Presets.Forget();
                var moved = Presets.User().FirstOrDefault(x => x.Id == "user-old-worlds");
                var offered = moved != null && Presets.Categories(Presets.Scratch).Contains(moved.Category);
                File.WriteAllText(Presets.FilePath, keep);
                Presets.Forget();
                Row(moved?.Category == "factory:worlds_duel" && offered,
                    "a user preset of 3.48-3.49 in «Миры» is read into «Миры: дуэли» and offered there",
                    $"a user preset in the old «Миры»: read as «{moved?.Category}», offered {offered}");
            }
            // the label: loaded, changed, put back by hand
            s.ScratchMode = true;
            s.Scratch = new ScratchParams();
            var page = new MainWindow { _page = "generate" };
            page.Rebuild();
            var vertical = Presets.Factory(Presets.Scratch).First(x => Presets.FactoryKey(x) == "duel_vertical");
            page.LoadPreset(vertical);
            var l1 = page._presetLabel?.Text;
            var e1 = page._presetEdit?.IsEnabled;
            var d1 = page._presetDelete?.IsEnabled;
            s.Scratch.Lifts = 4;
            page.KeepForm();
            var l2 = page._presetLabel?.Text;
            s.Scratch.Lifts = 3;
            page.KeepForm();
            var l3 = page._presetLabel?.Text;
            Row(l1 == vertical.Name && l2 == Loc.F("preset.changed", vertical.Name) && l3 == vertical.Name,
                $"the preset bar: «{l1}» loaded, «{l2}» after a change, «{l3}» when put back by hand",
                $"the preset bar: «{l1}» / «{l2}» / «{l3}» (want «{vertical.Name}», changed, «{vertical.Name}»)");
            // «Загрузить» pressed: the menu shows the categories, each with its presets
            {
                var loadButton = page.GetLogicalDescendants().OfType<DropDownButton>().FirstOrDefault(d => d.Tag as string == "preset-load");
                var menuShown = 0;
                var menuSize = default(Size);
                var menuDrop = loadButton?.Flyout is { } lf ? OpenedFlyout(lf, out menuShown, out menuSize) : null;
                var heads = (menuDrop as ItemsControl)?.Items.OfType<MenuItem>().ToList() ?? new List<MenuItem>();
                var inside = heads.Sum(h => h.ItemCount);
                var want = Presets.Categories(Presets.Scratch).Count(c => page.PresetMenuList().Any(x => string.Equals(x.Category, c, StringComparison.OrdinalIgnoreCase)));
                Row(menuDrop != null && menuShown == want && heads.Count == want && inside == page.PresetMenuList().Count && menuSize.Width > 120,
                    $"«Загрузить» pressed: the menu shows {menuShown} categories with {inside} presets in them, {menuSize.Width:0} x {menuSize.Height:0} px",
                    $"«Загрузить» pressed: {(menuDrop == null ? "no menu" : $"{menuShown} rows shown of {want} categories, {inside} presets of {page.PresetMenuList().Count}, {menuSize.Width:0} x {menuSize.Height:0} px")}");
                // pressed again after a preset is created: the new one in it, the one in use ticked
                var extra = Presets.Save(Presets.Scratch, "Тест пять", "Мои карты", body);
                page.SayPreset();
                var again = loadButton?.Flyout is { } lf2 ? OpenedFlyout(lf2, out _, out _) as ItemsControl : null;
                var names = again?.Items.OfType<MenuItem>().SelectMany(h => h.Items.OfType<MenuItem>()).ToList() ?? new List<MenuItem>();
                var ticked = names.Where(m => m.Icon != null).Select(m => m.Header as string).ToList();
                Row(names.Any(m => m.Header as string == "Тест пять") && names.Count == inside + 1 && ticked.Count == 1 && ticked[0] == vertical.Name,
                    $"«Загрузить» pressed again after a preset is created: {names.Count} presets, the new one among them, «{ticked.FirstOrDefault()}» ticked",
                    $"«Загрузить» pressed again: {names.Count} presets (want {inside + 1}), the new one {names.Any(m => m.Header as string == "Тест пять")}, ticked [{string.Join(", ", ticked)}]");
                if (extra != null)
                    Presets.Delete(extra.Id);
                // brief 24 D5: 13 categories hold the 160; the longest sub-menu opened stands within a 1080 screen
                var fresh = page.PresetMenu(page.CurrentPreset());
                var longest = fresh.OrderByDescending(h => h.ItemCount).First();
                var rows = longest.Items.OfType<MenuItem>().ToList();
                longest.Items.Clear();
                var sub = OpenedFlyout(new MenuFlyout { ItemsSource = rows }, out var subShown, out _);
                sub.Measure(new Size(456, double.PositiveInfinity));
                var subHigh = sub.DesiredSize.Height;
                var factoryHeads = fresh.Count(h => Presets.FactoryCategories(Presets.Scratch).Any(c => Presets.CategoryName(Presets.FactoryPrefix + c) == h.Header as string));
                Row(factoryHeads == 15 && Presets.Factory(Presets.Scratch).Count == 184 && subShown == rows.Count && subHigh > 0 && subHigh < 900,
                    $"«Загрузить» of a new map: 15 factory categories, 184 presets (13 of open space, 11 of a tower); the longest, «{longest.Header}», {rows.Count} lines {subHigh:0} px high",
                    $"«Загрузить» of a new map: {factoryHeads} factory categories, {Presets.Factory(Presets.Scratch).Count} presets; «{longest.Header}» {subShown} of {rows.Count} lines shown, {subHigh:0} px high");
            }
            page.LoadPreset(back ?? vertical);
            var e2 = page._presetEdit?.IsEnabled;
            var d2 = page._presetDelete?.IsEnabled;
            Row(e1 == false && d1 == false && e2 == true && d2 == true && page._presetLabel?.Text == "Тест один",
                "a factory preset cannot be changed or deleted; a user preset can",
                $"buttons on a factory preset: change {e1}, delete {d1}; on a user one: change {e2}, delete {d2}; label «{page._presetLabel?.Text}»");
            // deleted only through the question; a factory one never
            var keptOnNo = back != null && !page.DeletePreset(back, () => Task.FromResult(false)).GetAwaiter().GetResult()
                           && Presets.User().Any(x => x.Id == back.Id);
            var goneOnYes = back != null && page.DeletePreset(back, () => Task.FromResult(true)).GetAwaiter().GetResult()
                            && Presets.User().All(x => x.Id != back.Id) && s.PresetScratch == "";
            var factoryKept = !page.DeletePreset(vertical, () => Task.FromResult(true)).GetAwaiter().GetResult()
                              && Presets.Factory(Presets.Scratch).Any(x => x.Id == vertical.Id);
            Row(keptOnNo && goneOnYes && factoryKept, "a user preset is deleted only when the question is answered yes; a factory one never",
                $"delete: kept on «no» {keptOnNo}, gone on «yes» {goneOnYes}, factory kept {factoryKept}");
            // the categories of a form: the factory's and the user's of that form only
            Presets.Save(Presets.Scratch, "Тест два", "Мои карты", body);
            Presets.Save(Presets.Base, "Тест три", "Для основ", Presets.BodyOf(s, Presets.Base));
            var cs = Presets.Categories(Presets.Scratch);
            var cb = Presets.Categories(Presets.Base);
            var asTyped = Presets.CategoryOf(Presets.Scratch, "Duels");
            Row(cs.Take(Presets.FactoryCategories(Presets.Scratch).Length).SequenceEqual(Presets.FactoryCategories(Presets.Scratch).Select(c => Presets.FactoryPrefix + c)) && cs.Contains("Мои карты")
                && !cs.Contains("Для основ") && cb.Contains("Для основ") && !cb.Contains("Мои карты") && asTyped == "factory:duels"
                && PresetProblem(Presets.Scratch, "Vertical", "x", null) != null && PresetProblem(Presets.Scratch, "", "x", null) != null
                && PresetProblem(Presets.Scratch, "Новый", "x", null) == null,
                "the categories of each form: the factory's first, then the user's; «Duels» typed is the factory's; a factory name or none refused",
                $"categories: new map [{string.Join(", ", cs)}], from a map [{string.Join(", ", cb)}], «Duels» -> {asTyped}");
            // the mode switch swaps the bar's set; a base preset leaves the bases ticked
            var scratchSet = page.PresetMenuList().All(x => x.Kind == Presets.Scratch);
            s.ScratchMode = false;
            var donorsNow = Engine.Donors();
            var bw = new MainWindow { _page = "generate" };
            if (donorsNow.Count > 0)
                bw._chosen.Add(donorsNow[0]);
            bw.Rebuild();
            var basesBefore = string.Join(",", s.Bases) + "|" + string.Join(",", bw._chosen);
            var niches = Presets.Factory(Presets.Base).First(x => Presets.FactoryKey(x) == "niches");
            bw.LoadPreset(niches);
            var baseSet = bw.PresetMenuList().All(x => x.Kind == Presets.Base) && bw.PresetMenuList().Any(x => x.Name == "Тест три");
            Row(scratchSet && baseSet && s.Options.AnnexSize == 5 && string.Join(",", s.Bases) + "|" + string.Join(",", bw._chosen) == basesBefore
                && bw._presetLabel?.Text == niches.Name,
                "each form its own presets; a preset of a map from a ready one leaves its bases ticked",
                $"presets by form: new map {scratchSet}, from a map {baseSet}; annex size {s.Options.AnnexSize}; bases kept "
                + $"{string.Join(",", s.Bases) + "|" + string.Join(",", bw._chosen) == basesBefore}; label «{bw._presetLabel?.Text}»");
            // a presets file of garbage: the factory's shown, the file untouched, nothing written over it
            File.WriteAllText(Presets.FilePath, "{ not json");
            var before = File.ReadAllBytes(Presets.FilePath);
            Presets.Forget();
            var none = Presets.User().Count == 0 && Presets.ReadError != null;
            var refusedWrite = Presets.Save(Presets.Scratch, "Тест четыре", "Мои карты", body) == null;
            var untouched = File.ReadAllBytes(Presets.FilePath).AsSpan().SequenceEqual(before);
            s.ScratchMode = true;
            var gw = new MainWindow { _page = "generate" };
            gw.Rebuild();
            Row(none && refusedWrite && untouched && gw.PresetMenuList().Count == Presets.Factory(Presets.Scratch).Count && gw._presetCreate?.IsEnabled == false,
                "a presets file that does not read: the factory presets shown, the file left as it is, creating off",
                $"a bad presets file: read as none {none}, write refused {refusedWrite}, untouched {untouched}, menu {gw.PresetMenuList().Count}, create {gw._presetCreate?.IsEnabled}");
        }
        catch (Exception ex)
        {
            b.AppendLine($"FAIL the presets' and style maps' check threw: {ex.GetType().Name}: {ex.Message}");
        }
        finally
        {
            Presets.PathOverride = null;
            Presets.Forget();
            s.Scratch = ScratchParams.Load(keepScratch);
            s.Minutes = keepMinutes;
            s.Fidelity = keepFidelity;
            s.SkipFamilies = keepSkip;
            s.GraftMode = keepGraft;
            s.Options = keepOptions;
            s.Bases = keepBases;
            s.ScratchMode = keepMode;
            (s.PresetScratch, s.PresetBase) = keepIds;
            s.ClientDir = keepClient;
            Loc.Language = keepLang;
            try
            {
                Directory.Delete(dir, true);
            }
            catch (Exception e) when (e is IOException or UnauthorizedAccessException)
            {
            }
        }
    }
}
