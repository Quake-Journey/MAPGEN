using Avalonia;
using Avalonia.Controls;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Layout;
using Avalonia.Media;
using FluentAvalonia.UI.Controls;

namespace MapgenStudio;

/// <summary>The updates' windows (Fable's brief 10, D3): the check at start and from its buttons, «Что нового».</summary>
public sealed partial class MainWindow
{
    private bool _firstOpened;

    /// <summary>At the first showing: a finished update's «what's new», a failed one said, and the check when it is on.</summary>
    private async void OnFirstOpened(object? sender, EventArgs e)
    {
        if (_firstOpened || SelfTesting || UiTesting)
            return;
        _firstOpened = true;
        if (Update.TakeFailure() is { } failed)
            Notice(Loc.F("update.failed", failed.Split('\n')[0]), FAInfoBarSeverity.Error);
        if (Update.TakeNote() is { } was)
            await WhatsNew(was);
        if (S.AutoUpdateCheck)
            await CheckUpdates(manual: false);
    }

    /// <summary>«Проверить обновления»: the log from the repository, and the question when it holds a newer version.</summary>
    internal async Task CheckUpdates(bool manual)
    {
        var found = await Update.Check();
        if (found == null)
        {
            if (manual)
                Notice(Loc.T("update.unreachable"), FAInfoBarSeverity.Warning);
            return;
        }
        if (!Update.Newer(found.Version))
        {
            if (manual)
                Notice(Loc.F("update.latest", Versions.Current));
            return;
        }
        var running = Generation.Current is { Running: true };
        var body = new StackPanel { Spacing = 8, MaxWidth = 640 };
        body.Children.Add(new TextBlock { Text = Loc.F("update.yours", Versions.Current), TextWrapping = TextWrapping.Wrap });
        if (running)
            body.Children.Add(new TextBlock { Text = Loc.T("update.waits"), TextWrapping = TextWrapping.Wrap, FontWeight = FontWeight.SemiBold });
        body.Children.Add(new ScrollViewer
        {
            MaxHeight = 380,
            Content = new TextBlock { Text = Update.Said(found.Log), TextWrapping = TextWrapping.Wrap, FontSize = 13 },
        });
        var dialog = new FAContentDialog
        {
            Title = Loc.F("update.title", found.Version),
            Content = body,
            PrimaryButtonText = Loc.T("update.yes"),
            IsPrimaryButtonEnabled = !running,
            CloseButtonText = Loc.T("update.no"),
            DefaultButton = running ? FAContentDialogButton.Close : FAContentDialogButton.Primary,
        };
        if (await dialog.ShowAsync(this) != FAContentDialogResult.Primary)
            return;                               // «Отмена»: nothing remembered - the next start asks again
        Notice(Loc.F("update.downloading", found.Version), FAInfoBarSeverity.Informational);
        var why = await Update.Fetch(found.Version,
            t => Avalonia.Threading.Dispatcher.UIThread.Post(() => Notice(t, FAInfoBarSeverity.Informational)));
        if (why != null)
        {
            Notice(why, FAInfoBarSeverity.Error);
            return;
        }
        // the new Studio waits for this one to end, then puts itself in place and starts
        _closeConfirmed = true;
        (Application.Current?.ApplicationLifetime as IClassicDesktopStyleApplicationLifetime)?.Shutdown();
    }

    /// <summary>«Что нового в X»: this version's lines, and under them every version's in a scroll.</summary>
    private async Task WhatsNew(string was)
    {
        var (now, all) = Update.History();
        var body = new StackPanel { Spacing = 10, MaxWidth = 640 };
        body.Children.Add(new TextBlock { Text = Loc.F("whatsnew.from", was), Opacity = 0.75, TextWrapping = TextWrapping.Wrap });
        body.Children.Add(new TextBlock { Text = now, TextWrapping = TextWrapping.Wrap });
        body.Children.Add(new TextBlock { Text = Loc.T("whatsnew.all"), FontWeight = FontWeight.SemiBold, Margin = new Thickness(0, 6, 0, 0) });
        body.Children.Add(new ScrollViewer
        {
            MaxHeight = 320,
            Content = new TextBlock { Text = all, TextWrapping = TextWrapping.Wrap, FontSize = 13 },
        });
        await new FAContentDialog
        {
            Title = Loc.F("whatsnew.title", Versions.Current),
            Content = body,
            CloseButtonText = Loc.T("whatsnew.close"),
        }.ShowAsync(this);
    }

    /// <summary>The settings' «Обновления» rows: the automatic check and the button.</summary>
    private void UpdateRows(StackPanel p)
    {
        p.Children.Add(Ui.Section(Loc.T("set.updates")));
        var auto = new ToggleSwitch { IsChecked = S.AutoUpdateCheck };
        auto.IsCheckedChanged += (_, _) =>
        {
            S.AutoUpdateCheck = auto.IsChecked == true;
            S.Save();
        };
        p.Children.Add(Ui.Setting("set.update_check", "set.update_check.desc", FASymbol.Sync, auto, "set.update_check.tip"));
        p.Children.Add(Ui.Setting("update.check", "update.check.desc", FASymbol.Download, UpdateButton(), "update.check.tip"));
    }

    private Control UpdateButton()
    {
        var check = Ui.Button("update.check", "update.check.tip", FASymbol.Sync);
        check.Click += async (_, _) =>
        {
            check.IsEnabled = false;
            try
            {
                await CheckUpdates(manual: true);
            }
            finally
            {
                check.IsEnabled = true;
            }
        };
        return check;
    }
}
