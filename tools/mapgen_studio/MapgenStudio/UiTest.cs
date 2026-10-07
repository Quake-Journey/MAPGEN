using System.Text;
using System.Text.RegularExpressions;
using Avalonia;
using Avalonia.Controls;
using Avalonia.VisualTree;

namespace MapgenStudio;

/// <summary>
/// `--ui-test` (ledger row 410; the PO, 05.10: «проверить студию и генератор на предмет подобных дурных косяков»): the
/// real window, off the screen's edge, driven through what broke on his screen that day - every page; a run (the
/// engine is tools/mapgen_studio/fixtures/fake_pipeline.c, a few seconds, its progress the real one's) left and come
/// back to; paused, its clocks standing; the plan full screen and back; stopped, listed, resumed and finished; no key
/// in brackets anywhere on the window or in the map's description; the bases ticked kept for the next start. One
/// PASS / FAIL line each into ui_test.txt, then END; a throw anywhere ends the process before END.
/// </summary>
public sealed partial class MainWindow
{
    public static Window UiTest()
    {
        var w = new MainWindow
        {
            ShowActivated = false, ShowInTaskbar = false,
            WindowStartupLocation = WindowStartupLocation.Manual, Position = new PixelPoint(-4000, -4000),
        };
        UiTesting = true;      // its own questions («Удалить?», «Отменить?») answered yes
        // once: the window is hidden behind the full-screen map and shown again (Studio 1.8), and Opened fires again -
        // a second walk ran beside the first and failed it from «resumed» on
        var started = false;
        w.Opened += async (_, _) =>
        {
            if (started)
                return;
            started = true;
            var b = new StringBuilder();
            void Check(string what, bool ok, string detail) =>
                b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));
            try
            {
                await Run(w, Check);
            }
            catch (Exception ex)
            {
                Check("the test ran to its end", false, ex.ToString());
            }
            b.AppendLine("END");
            File.WriteAllText(Path.Combine(Settings.ProgramDir, "ui_test.txt"), b.ToString());
            Environment.Exit(b.ToString().Contains("FAIL") ? 1 : 0);
        };
        return w;
    }

    private static readonly Regex KeyInBrackets = new(@"\[[a-z]+(\.[a-zA-Z0-9_{}\-]+)+\]");

    private static string Brackets(Window w) => string.Join(" | ", w.GetVisualDescendants().OfType<TextBlock>()
        .Select(t => t.Text ?? "").Where(t => KeyInBrackets.IsMatch(t)).Distinct().Take(5));

    private static async Task<bool> Until(Func<bool> done, int seconds)
    {
        var end = DateTime.Now.AddSeconds(seconds);
        while (!done() && DateTime.Now < end)
            await Task.Delay(100);
        return done();
    }

    private static async Task Run(MainWindow w, Action<string, bool, string> check)
    {
        void Check(string what, bool ok, string detail = "") => check(what, ok, detail);
        var s = App.Settings;
        await Task.Delay(300);
        foreach (var page in new[] { "home", "generate", "library", "settings", "about", "generate" })
        {
            w.Go(page);
            await Task.Delay(150);
        }
        Check("every page shows", true);
        Check("no key in brackets on the pages", Brackets(w).Length == 0, Brackets(w));
        // the PO, 05.10: the program's version is the newest of its history, and «О программе» lists them all
        var built = Versions.Said(typeof(MainWindow).Assembly.GetName().Version);
        w.Go("about");
        await Task.Delay(200);
        var about = w.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text ?? "").ToList();
        Check("the program's version is the newest in its history, and «О программе» shows every version",
              built == Versions.Current && about.Contains(Loc.F("about.version", Versions.Current))
              && Versions.All.All(v => about.Contains(Loc.F("about.history.version", v.Number, v.Date))),
              $"built {built}, history {Versions.Current}");

        // the form keeps what was set when the page is redrawn (ticking a base redraws it): it was 20 / 42 again
        s.Fidelity = 37;
        s.Seed = 5;
        w.Go("generate");
        w._chosen.Clear();
        w._chosen.Add("q2dm1");
        w.ShowPage();
        await Task.Delay(200);
        w._chosen.Add("koldduel1");
        w.ShowPage();
        await Task.Delay(200);
        var numbers = w.GetVisualDescendants().OfType<FluentAvalonia.UI.Controls.FANumberBox>().Select(n => n.Value).ToList();
        Check("redrawn after a base is ticked, the likeness and the seed are kept", numbers.Contains(37) && numbers.Contains(5),
              string.Join(",", numbers));
        // a run, through the window's own timer, with the creative options
        var opts = new GenerationOptions(Digs: 3, AnnexSize: 2, Spans: 1);
        var req = new GenerationRequest("ui_test_map", "q2dm1", 50, 1, Array.Empty<string>(), false, RunGates: false,
                                        Grafts: new[] { "koldduel1" }, Cover: false, Options: opts);
        var g = Generation.Start(req, s);
        w.Go("generate");
        Check("the run starts", await Until(() => g.Stage == "attempt", 20), g.Stage);
        var launched = g.Log.FirstOrDefault(l => l.StartsWith("pipeline.exe")) ?? "";
        Check("the creative options reach the generator", launched.Contains("--digs 3") && launched.Contains("--annexes 0 384 384 256")
              && launched.Contains("--spans 1"), launched.Length > 200 ? launched[^200..] : launched);
        Check("the base rebuilt with faithful skins leaves the stage named", g.Stage != "baseline-faithful", g.Stage);
        // left and come back to while it runs (the Studio died here on 05.10)
        foreach (var page in new[] { "home", "generate", "library", "generate" })
        {
            w.Go(page);
            await Task.Delay(250);
        }
        Check("left and come back to while it runs, the window lives", true);
        Check("the run page says what the plan holds", g.PlanMade.Length > 0
              && w.GetVisualDescendants().OfType<TextBlock>().Any(t => (t.Text ?? "") == g.PlanMade), g.PlanMade);
        Check("the run page names its base and the rooms' source",
              w.GetVisualDescendants().OfType<TextBlock>().Any(t => (t.Text ?? "").Contains("q2dm1") && (t.Text ?? "").Contains("koldduel1")));
        Check("the plan has a map to draw", await Until(() => w._runView?.Scheme.Model.Current != null, 10));
        // paused: the clocks stand
        g.Pause(true);
        var before = GenerationView.RunLine(g);
        await Task.Delay(2200);
        var after = GenerationView.RunLine(g);
        Check("paused, the run's clock stands", before == after, $"{before} / {after}");
        g.Pause(false);
        // brief 10 (D1): the guide's picture of a run under way, both languages, when MAPGEN_SHOTS names the shots folder
        if (Environment.GetEnvironmentVariable("MAPGEN_SHOTS") is { Length: > 0 } shotsRun)
        {
            var keepLang = Loc.Language;
            foreach (var lang in new[] { "ru", "en" })
            {
                Loc.Language = lang;
                Directory.CreateDirectory(Path.Combine(shotsRun, lang));
                w.Rebuild();
                await Task.Delay(400);
                w._runView?.Update(g);
                await Task.Delay(400);
                Shot(w, Path.Combine(shotsRun, lang, "run.png"));
            }
            Loc.Language = keepLang;
            w.Rebuild();
            await Task.Delay(300);
        }
        // the plan full screen and back
        w._runView?.Scheme.FullScreen();
        await Task.Delay(1200);
        var full = w._runView?.Scheme.Full;
        Check("the plan opens full screen", full != null);
        // (the guide's picture of the map on the whole screen is `--shots-full`'s: a real map, not this stand-in's)
        // the PO, 06.10: one window at a time - the Studio hidden behind the full-screen map, back when it closes
        Check("the Studio's window is hidden while the map is full screen", !w.IsVisible);
        full?.Close();
        await Task.Delay(400);
        Check("and closes back to the run", w._runView?.Scheme.Full == null);
        Check("the Studio's window is back on the screen", w.IsVisible && w.WindowState != WindowState.Minimized);
        // the PO, 07.10: maximised before, maximised after «Назад в студию»
        w.WindowState = WindowState.Maximized;
        await Task.Delay(400);
        w._runView?.Scheme.FullScreen();
        await Task.Delay(1000);
        w._runView?.Scheme.Full?.Close();
        await Task.Delay(500);
        // by its size on the screen, not the state's name: the PO saw it come back at its normal size
        var area = w.Screens.ScreenFromWindow(w)?.WorkingArea;
        var wide = area is { } wa ? w.ClientSize.Width * w.RenderScaling / wa.Width : 0;
        Check("a maximised Studio comes back maximised", w.WindowState == WindowState.Maximized && wide > 0.95,
              $"{w.WindowState}, {wide:0.00} of the screen's width");
        w.WindowState = WindowState.Normal;
        await Task.Delay(300);
        Check("no key in brackets while it runs", Brackets(w).Length == 0, Brackets(w));
        // stopped, listed, resumed, finished
        await Until(() => g.Accepted >= 2, 20);
        var wasRunning = g.Running;
        g.Stop();
        await Task.Delay(300);
        var listed = Generation.Interrupted(s).Any(x => string.Equals(x.runDir, g.RunDir, StringComparison.OrdinalIgnoreCase));
        Check("stopped, the run is listed as interrupted", listed,
              $"running when stopped: {wasRunning}, stage {g.Stage}, result {g.Result}");
        w.Go("generate");
        await Task.Delay(300);
        var r = Generation.Resume(s, g.RunDir);
        w.Go("generate");
        var relaunched = r.Log.FirstOrDefault(l => l.StartsWith("pipeline.exe")) ?? "";
        Check("resumed, the same options go to the generator (the replay must deal the same plan)",
              relaunched.Contains("--digs 3") && relaunched.Contains("--annexes 0 384 384 256") && relaunched.Contains("--resume"));
        Check("resumed, it replays and goes on", await Until(() => r.Accepted > 0 || !r.Running, 20), r.Stage);
        // row 411 (the PO, 05.10): what of each planned kind is done, the plan's edits on the plan, the light's steps
        Check("the run page says how much of each kind in the plan is done",
              await Until(() => r.PlanDone().Length > 0
                                && w.GetVisualDescendants().OfType<TextBlock>().Any(t => (t.Text ?? "") == r.PlanDone()), 20),
              r.PlanDone());
        Check("the plan view holds the plan's edits, still to come drawn faint",
              w._runView?.Scheme.Model.Plan.Count == 10, $"{w._runView?.Scheme.Model.Plan.Count}");
        Check("the light compile's step and share show on its stage",
              await Until(() => r.Stage == "light" && r.LightNow().Length > 0
                                && w.GetVisualDescendants().OfType<TextBlock>().Any(t => (t.Text ?? "").Contains(r.LightNow())), 60),
              $"{r.Stage}: {r.LightNow()}");
        Check("and ends", await Until(() => !r.Running, 60), r.Stage);
        // brief 9 D4: what the second map gave - its rooms built and the rooms in its skin - said at the end, and counted
        // in «Сделано по плану»
        Check("the end says what the second map gave: its rooms built, the rooms in its skin",
              r.SecondSaid() == Loc.F("second.gave", "koldduel1", 1, 1)
              && await Until(() => w.GetVisualDescendants().OfType<FluentAvalonia.UI.Controls.FAInfoBar>()
                                    .Any(x => (x.Message ?? "").Contains(r.SecondSaid())), 10)
              && r.PlanDone().Contains(Loc.F("plan.cat.rooms_from", 1, 1, "koldduel1")),
              $"{r.SecondSaid()} | {r.PlanDone()}");
        // the PO, 05.10: the plan's feed went still after the edits - the run's stages and the light's steps go in it
        var events = r.Events().Select(x => x.what).ToList();
        Check("the plan's feed has the run's stages and the light's steps, not only the edits",
              events.Contains(Loc.T("stage.judge.now")) && events.Contains(Loc.T("stage.light.now"))
              && events.Contains(Loc.F("scheme.light", Loc.T("light.step.vis1")))
              && events.Contains(Loc.F("scheme.light", Loc.T("light.step.rad0"))), string.Join(" | ", events));
        Check("without an error", r.Error.Length == 0, r.Error);
        Check("into the library", File.Exists(Path.Combine(s.BspPath, "ui_test_map.bsp")));
        var desc = Path.Combine(s.DescriptionsPath, "ui_test_map.ru.txt");
        var text = File.Exists(desc) ? File.ReadAllText(desc) : "";
        Check("its description holds no key in brackets", text.Length > 0 && !KeyInBrackets.IsMatch(text),
              text.Length == 0 ? "no description" : KeyInBrackets.Match(text).Value);
        await Task.Delay(600);
        Check("no key in brackets when it is over", Brackets(w).Length == 0, Brackets(w));
        // row 411 (Fable's brief 8 C): the working files in memory, the steps on the disk as the settings say
        Check("the generator is given its share of memory and keeps its steps on the disk by default",
              launched.Contains("--memory ") && launched.Contains("--checkpoints 1") && s.KeepCheckpoints
              && s.MemoryPercent == 50, launched.Length > 200 ? launched[^200..] : launched);
        Check("the run page says the working files are in memory", g.MemoryNote == Loc.T("run.memory.on"), g.MemoryNote);
        // the PO 05.10: the load card shows the graphics card too - its load and its memory, from Windows' counters
        Check("the load card shows the graphics card's load and its memory",
              GpuStats.Percent >= 0 && GpuStats.VramTotal > 0 && GpuStats.VramUsed > 0
              && w.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == Loc.T("load.gpu"))
              && w.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == Loc.T("load.vram")),
              $"{GpuStats.Name}: {GpuStats.Percent:0.0}%, {GpuStats.VramUsed >> 20} of {GpuStats.VramTotal >> 20} MB");
        w.Go("settings");
        await Task.Delay(300);
        var said = w.GetVisualDescendants().OfType<TextBlock>().Select(t => t.Text ?? "").ToList();
        Check("the settings page has the memory share and the steps on the disk",
              said.Contains(Loc.T("set.memory_percent")) && said.Contains(Loc.T("set.keep_checkpoints")));
        // without the steps on the disk: the plan is read from memory, and a stopped run is not offered to resume
        s.KeepCheckpoints = false;
        var bare = Generation.Start(req with { Name = "ui_test_bare" }, s);
        w.Go("generate");
        Check("without the steps on the disk the generator is told so",
              (bare.Log.FirstOrDefault(l => l.StartsWith("pipeline.exe")) ?? "").Contains("--checkpoints 0"));
        Check("without the steps on the disk the plan draws the map being built from memory",
              await Until(() => bare.Accepted >= 1
                                && (w._runView?.Scheme.Model.Current?.Source ?? "").StartsWith("mem:"), 20),
              w._runView?.Scheme.Model.Current?.Source ?? "no map");
        Check("and nothing of a try is on the disk", !Directory.EnumerateDirectories(bare.JobDir, "try_*").Any());
        bare.Stop();
        await Task.Delay(300);
        var refused = "";
        try
        {
            Generation.Resume(s, bare.RunDir);
        }
        catch (InvalidOperationException e)
        {
            refused = e.Message;
        }
        Check("stopped without its steps on the disk, it cannot be resumed - and says so",
              refused == Loc.T("run.resume.nocheckpoints"), refused);
        // the form, not the stopped run's page: that is where the stopped runs are listed
        Generation.Current = null;
        w.Go("generate");
        w.ShowPage();
        await Task.Delay(300);
        var why = Loc.T("gen.interrupted.nocheckpoints");
        why = why[(why.IndexOf("{3}.", StringComparison.Ordinal) + 4)..].Trim();
        Check("the page lists it as stopped, with «Удалить» and no «Продолжить», saying why",
              w.GetVisualDescendants().OfType<FluentAvalonia.UI.Controls.FAInfoBar>()
               .Any(x => (x.Message ?? "").EndsWith(why) && !(x.ActionButton?.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == Loc.T("gen.interrupted.resume")) ?? false)
                         && (x.ActionButton?.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == Loc.T("gen.interrupted.delete")) ?? false)), why);
        s.KeepCheckpoints = true;
        // too small a share: in files, said on the run page
        Environment.SetEnvironmentVariable("FAKE_MEMORY_NEED_MB", "999999999");
        var small = Generation.Start(req with { Name = "ui_test_small" }, s);
        w.Go("generate");
        var head = Loc.T("run.memory.files");
        head = head[..head.IndexOf(':')];
        Check("too small a share of memory: the run page says the files are on the disk and why",
              await Until(() => small.MemoryNote.StartsWith(head)
                                && w.GetVisualDescendants().OfType<TextBlock>().Any(t => t.IsEffectivelyVisible
                                                                                        && (t.Text ?? "") == small.MemoryNote), 20),
              small.MemoryNote);
        Environment.SetEnvironmentVariable("FAKE_MEMORY_NEED_MB", null);
        small.Stop();
        await Task.Delay(300);
        // the PO, 05.10: what is not wanted is deleted from the Studio, with all its files
        Button? ButtonSaying(string key) => w.GetVisualDescendants().OfType<Button>()
            .FirstOrDefault(x => x.IsEffectivelyVisible && x.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == Loc.T(key)));
        Check("a generation that ended well cleaned its working folder up, its map drawn from the library",
              await Until(() => !Directory.Exists(r.RunDir), 20)
              && r.Artifact == Path.Combine(s.BspPath, "ui_test_map.bsp"), $"{r.RunDir} / {r.Artifact}");
        // brief 9 D5: its ledger, progress, plan and request kept beside the map before the folder went
        var kept = Path.Combine(s.RunsPath, "ui_test_map");
        Check("its small evidence is kept with the map (ledger, progress, plan, request)",
              new[] { "ledger.txt", "progress.txt", "plan.txt", "request.txt" }.All(f => File.Exists(Path.Combine(kept, f))),
              string.Join(", ", Directory.Exists(kept) ? Directory.GetFiles(kept).Select(Path.GetFileName) : Array.Empty<string>()));
        Generation.Current = null;
        w.Go("generate");
        w.ShowPage();
        await Task.Delay(300);
        var bar = w.GetVisualDescendants().OfType<FluentAvalonia.UI.Controls.FAInfoBar>()
            .FirstOrDefault(x => (x.Title ?? "") == Loc.F("gen.interrupted.title", "ui_test_small"));
        var drop = bar?.GetVisualDescendants().OfType<Button>()
            .FirstOrDefault(x => x.GetVisualDescendants().OfType<TextBlock>().Any(t => t.Text == Loc.T("gen.interrupted.delete")));
        drop?.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        Check("«Удалить» on a stopped generation deletes its folder, and the page no longer lists it",
              drop != null && await Until(() => !Directory.Exists(small.RunDir), 10)
              && !Generation.Interrupted(s).Any(x => x.request.Name == "ui_test_small"),
              drop == null ? "no «Удалить» on its card" : small.RunDir);
        var gone = Generation.Start(req with { Name = "ui_test_cancel" }, s);
        w.Go("generate");
        await Until(() => gone.Stage == "attempt", 20);
        ButtonSaying("run.cancel")?.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        Check("«Отменить» stops a running generation and deletes its folder",
              await Until(() => !gone.Running && !Directory.Exists(gone.RunDir), 20), $"{gone.Stage}, {gone.RunDir}");
        var outside = Generation.Delete(s, Path.GetDirectoryName(s.TempPath)!);
        Check("the Studio deletes nothing outside its temp folder", outside == Loc.T("delete.outside"), outside);
        // the PO, 05.10: the library's tiles and a map's shots sized by Ctrl+wheel or the slider, across the whole width
        Generation.Current = null;
        var shotDir = Path.Combine(s.CoversPath, "ui_test_map");
        Directory.CreateDirectory(shotDir);
        for (var k = 0; k < 3; k++)
        {
            using var pic = new Avalonia.Media.Imaging.WriteableBitmap(new PixelSize(320, 180), new Vector(96, 96),
                Avalonia.Platform.PixelFormat.Rgba8888, Avalonia.Platform.AlphaFormat.Opaque);
            using (var fb = pic.Lock())
            {
                var row = new byte[320 * 4];
                for (var x = 0; x < 320; x++)
                    (row[x * 4], row[x * 4 + 1], row[x * 4 + 2], row[x * 4 + 3]) = ((byte)(80 * k), 120, (byte)x, 255);
                for (var y = 0; y < 180; y++)
                    System.Runtime.InteropServices.Marshal.Copy(row, 0, fb.Address + y * fb.RowBytes, row.Length);
            }
            pic.Save(Path.Combine(shotDir, $"shot{k}.png"));
        }
        w._openMap = null;
        w.Go("library");
        await Task.Delay(400);
        var slider = w.GetVisualDescendants().OfType<Slider>().FirstOrDefault();
        var libWall = w.LibraryWall;
        if (slider != null && libWall != null)
        {
            slider.Value = 700;
            await Task.Delay(400);
            var card = libWall.Children.FirstOrDefault();
            var width = libWall.Bounds.Width;
            var cols = Math.Max(1, (int)Math.Floor((width + libWall.Gap) / (700 + libWall.Gap)));
            var tile = (width - libWall.Gap * (cols - 1)) / cols;
            var scale = (card as LayoutTransformControl)?.LayoutTransform is Avalonia.Media.ScaleTransform st ? st.ScaleX : 0;
            Check("the slider makes the library's tiles bigger: they fill the width, picture and words scaled together",
                  libWall.Target == 700 && card != null && Math.Abs(card.Bounds.Width - tile) < 2
                  && Math.Abs(scale - tile / 240) < 0.01 && tile >= 600,
                  $"width {width:0}, {cols} across, tile {card?.Bounds.Width:0} (want {tile:0}), scale {scale:0.00}");
            Check("the tile size is kept in the settings", s.LibraryTile == 700, s.LibraryTile.ToString());
            Check("the library's top stays put: the size slider is outside the scrolled part",
                  w.GetVisualDescendants().OfType<ScrollViewer>().All(sv => !sv.GetVisualDescendants().OfType<Slider>().Any()));
        }
        else
            Check("the library has its tiles and their size slider", false, $"slider {slider != null}, wall {libWall != null}");
        w._openMap = Library.Scan(s).FirstOrDefault(x => x.Name == "ui_test_map");
        w.ShowPage();
        await Task.Delay(400);
        Check("a map's shots are tiles like the library's", w.ShotsWall is { } sw && sw.Children.Count == 3,
              $"{w.ShotsWall?.Children.Count}");
        var firstShot = (w.ShotsWall?.Children.FirstOrDefault() as LayoutTransformControl)?.Child as Button;
        firstShot?.RaiseEvent(new Avalonia.Interactivity.RoutedEventArgs(Button.ClickEvent));
        await Until(() => w.Viewer != null, 5);
        var viewer = w.Viewer;
        Check("a click on a shot opens it as big as the window", viewer != null
              && Math.Abs(viewer.Width - w.Bounds.Width) < 2 && Math.Abs(viewer.Height - w.Bounds.Height) < 2,
              viewer == null ? "no viewer" : $"{viewer.Width:0}x{viewer.Height:0} / {w.Bounds.Width:0}x{w.Bounds.Height:0}");
        if (viewer != null)
        {
            Avalonia.Input.KeyEventArgs Key(Avalonia.Input.Key k) =>
                new() { RoutedEvent = Avalonia.Input.InputElement.KeyDownEvent, Key = k };
            var shotWas = viewer.At;
            viewer.RaiseEvent(Key(Avalonia.Input.Key.Right));
            var shotNow = viewer.At;
            viewer.RaiseEvent(Key(Avalonia.Input.Key.Left));
            Check("the viewer turns the shots forward and back", shotNow == (shotWas + 1) % 3 && viewer.At == shotWas,
                  $"{shotWas} -> {shotNow} -> {viewer.At}");
            viewer.RaiseEvent(Key(Avalonia.Input.Key.Escape));
            Check("and closes", await Until(() => w.Viewer == null, 5));
        }
        w._openMap = null;
        // the bases ticked are kept for the next start
        Generation.Current = null;
        w._chosen.Clear();
        w._chosen.AddRange(new[] { "koldduel1", "q2dm1" });
        w._graftMode = true;
        w.Go("generate");
        await Task.Delay(200);
        var again = new MainWindow();
        Check("the bases ticked are there after a restart, the first still the base",
              again._chosen.SequenceEqual(new[] { "koldduel1", "q2dm1" }) && again._graftMode,
              string.Join(",", again._chosen));
    }
}
