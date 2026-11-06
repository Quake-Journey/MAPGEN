using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.Primitives;
using Avalonia.Layout;
using Avalonia.LogicalTree;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>
/// The PO, 05.11: «когда генерация запущена, я уже не могу вернуться и посмотреть на параметры, которые были установлены
/// мной до запуска генерации - это странно, нужно сделать на экране генерации раздел для просмотра выбранных параметров».
/// The run page's tab «Параметры»: what the run was started with, from its own request (request.txt - a run resumed
/// after a restart, or one started before this version, shows its own too), in the same cards as the generate page,
/// to look at only: their controls are off, and nothing of them goes into the settings.
/// </summary>
public sealed partial class MainWindow
{
    private Control RunParams(Generation g)
    {
        var r = g.Request;
        var page = new StackPanel { Spacing = 16 };
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("Auto,*"), RowSpacing = 6, ColumnSpacing = 18 };
        var row = 0;
        void Line(string key, string value)
        {
            head.RowDefinitions.Add(new RowDefinition(GridLength.Auto));
            var k = new TextBlock { Text = Loc.T(key), Opacity = 0.7 };
            var v = new TextBlock { Text = value, TextWrapping = TextWrapping.Wrap, FontWeight = FontWeight.SemiBold };
            Grid.SetRow(k, row);
            Grid.SetRow(v, row);
            Grid.SetColumn(v, 1);
            head.Children.Add(k);
            head.Children.Add(v);
            row++;
        }
        Line("run.params.name", r.Name);
        Line("run.params.from", r.FromScratch ? Loc.T("run.params.from.scratch")
                                : r.Grafts is { Count: > 0 } grafts ? $"{r.Donor} + {string.Join(", ", grafts)}" : r.Donor);
        Line("run.params.seed", r.Seed.ToString());
        Line("run.params.time", r.TimeMinutes > 0 ? Loc.F("run.params.time.value", r.TimeMinutes) : Loc.T("run.params.time.none"));
        if (!r.FromScratch)
        {
            Line("run.params.likeness", $"{r.Fidelity} %");
            // a family is off when every kind of it is skipped
            var off = Families.Where(kv => kv.Value.All(r.SkipFamilies.Contains)).Select(kv => Loc.T($"fam.{kv.Key}")).ToList();
            Line("run.params.skip", off.Count > 0 ? string.Join(", ", off) : Loc.T("run.params.skip.none"));
        }
        page.Children.Add(Look.Group(FASymbol.Document, Look.BlueC, Loc.T("run.params.head"), Loc.T("run.params.desc"), head));
        var creative = CreativePicker(r.Options ?? new GenerationOptions());
        if (r.FromScratch)
        {
            var sc = ScratchCards(ScratchParams.FromPython(r.Scratch, r.Fidelity));
            page.Children.Add(Look.Balanced(FormColumn, sc.people, sc.shape, sc.own, sc.liquids, sc.moves, sc.items, sc.mechanics,
                                            sc.style, creative.ruin));
        }
        else
            page.Children.Add(Look.Balanced(FormColumn, FramePicker(r.Options ?? new GenerationOptions()), creative.rooms,
                                            creative.basis, creative.liquids, creative.ruin));
        ViewOnly(page);
        return new ScrollViewer
        {
            Content = new Border { Padding = new Thickness(4, 12, 16, 16), Child = page },
            HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled,
        };
    }

    /// <summary>Every input of a view to look at turned off; its words, values and tips stay.</summary>
    private static void ViewOnly(Control root)
    {
        foreach (var c in root.GetLogicalDescendants().OfType<Control>().ToList())
            // every kind named (brief 22 D2): a check box, a switch or a radio button is off because it is one, not
            // because it happens to derive from a button
            if (c is ComboBox or Button or CheckBox or ToggleSwitch or RadioButton or ToggleButton or Slider or TextBox
                  or NumericUpDown or FANumberBox)
                c.IsEnabled = false;
    }
}
