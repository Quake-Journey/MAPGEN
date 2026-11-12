using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;
using System.Text;
using Avalonia;
using Avalonia.Media.Imaging;

namespace MapgenStudio;

/// <summary>
/// The PO 11.11: «было бы неплохо визуализировать построение каркаса … как он строится в реальном времени» and
/// «было бы круто чтобы карта хотьбы и визуализировалась как хотьба, ножками и тд» - the skeleton's steps and the
/// map's walk, handed to the Studio in memory (no file: «SSD не очень любит много записей») and drawn on the scheme.
/// The self-test makes the sections as the tools do and reads them through the run's own door.
/// </summary>
public sealed partial class MainWindow
{
    /// <summary>A section as the tools make it (mapgen_map_survey.mem_publish): the header «Q2MEM1», then the bytes.</summary>
    private static MemoryMappedFile? Publish(string root, string relative, string text)
    {
        if (!OperatingSystem.IsWindows())
            return null;
        var data = Encoding.UTF8.GetBytes(text);
        var map = MemoryMappedFile.CreateNew($@"Local\q2mem_{root}/{relative}", 32 + data.Length);
        using var view = map.CreateViewAccessor();
        view.WriteArray(0, Encoding.ASCII.GetBytes("Q2MEM1\0\0"), 0, 8);
        view.Write(8, (ulong)data.Length);
        view.Write(16, (ulong)data.Length);
        view.WriteArray(32, data, 0, data.Length);
        view.Write(24, 1UL);
        return map;
    }

    /// <summary>A section rewritten in place as the planner rewrites its tries (mapgen_map_survey.mem_update).</summary>
    private static void Rewrite(MemoryMappedFile map, string text)
    {
        var data = Encoding.UTF8.GetBytes(text);
        using var view = map.CreateViewAccessor();
        view.Write(24, 0UL);
        view.Write(16, (ulong)data.Length);
        view.WriteArray(32, data, 0, data.Length);
        view.Write(24, 1UL);
    }

    /// <summary>The pixels an overlay draws over nothing: how many are not see-through.</summary>
    private static int Drawn(Avalonia.Controls.Control c, int w, int h)
    {
        c.Measure(new Size(w, h));
        c.Arrange(new Rect(0, 0, w, h));
        using var bmp = new RenderTargetBitmap(new PixelSize(w, h));
        bmp.Render(c);
        var px = new byte[w * h * 4];
        var handle = GCHandle.Alloc(px, GCHandleType.Pinned);
        try
        {
            bmp.CopyPixels(new PixelRect(0, 0, w, h), handle.AddrOfPinnedObject(), px.Length, w * 4);
        }
        finally
        {
            handle.Free();
        }
        var n = 0;
        for (var i = 3; i < px.Length; i += 4)
            if (px[i] > 40)
                n++;
        return n;
    }

    internal static void ShowsSelfTest(StringBuilder b)
    {
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        // (s1) the skeleton: three steps, the first on two levels (64 cells low, 12 high), then its doors, then its items
        var cells = new StringBuilder();
        for (var x = 0; x < 8; x++)
            for (var y = 0; y < 8; y++)
                cells.Append($"[{x},{y},0,0,0],");
        for (var x = 0; x < 4; x++)
            for (var y = 0; y < 3; y++)
                cells.Append($"[{x + 10},{y},256,1,1],");
        var cellText = cells.ToString().TrimEnd(',');
        string Step(string name, string doors, string items, string spawns) =>
            $"{{\"step\":\"{name}\",\"kinds\":[\"hall\",\"room\"],\"cells\":[{cellText}],\"doors\":[{doors}],\"liquids\":[],\"pits\":[],"
            + $"\"lifts\":[],\"pads\":[],\"teleports\":[],\"items\":[{items}],\"spawns\":[{spawns}]}}";
        var skeleton = "{\"version\":1,\"steps\":[" + Step("rooms", "", "", "") + "," + Step("doors", "[8,1,0,0]", "", "") + ","
                       + Step("items", "[8,1,0,0]", "[\"weapon_railgun\",3,3,0]", "[1,1,0]") + "]}";
        var scratch = FreshRun("scratch");
        var root = scratch.ShowRoot;
        // (s0) the PO 12.11 («когда 27 сек который шел Каркас карты то было вот так» - empty): the skeletons the planner
        // tries, from the first, rewritten in one section; then the chosen one's steps take over
        string Tried(int done, bool best) =>
            $"{{\"version\":1,\"done\":{done},\"tries\":100,\"made\":{done - 3},\"best\":{(best ? "true" : "false")},\"plan\":"
            + Step("try", "", "[\"weapon_railgun\",3,3,0]", "[1,1,0]") + "}";
        using (var live = Publish(root, "skeleton_live.json", Tried(10, true) + new string(' ', 4096)))
        {
            var model = new SchemeModel();
            if (live != null)
                Rewrite(live, Tried(10, true));
            model.Shows(scratch);
            var first = model.Current;
            var art1 = first != null ? StageArt.Now(scratch, first) : default;
            if (live != null)
                Rewrite(live, Tried(40, false));
            model.Shows(scratch);
            var second = model.Current;
            var art2 = second != null ? StageArt.Now(scratch, second) : default;
            string? stepsOn;
            using (Publish(root, "skeleton_show.json", skeleton))
            {
                model.Shows(scratch);
                stepsOn = model.Frames is { Count: > 0 } ? model.Current?.Source : null;
            }
            SchemeModel.OldTries = true;
            var old = new SchemeModel();
            old.Shows(scratch);
            SchemeModel.OldTries = false;
            Row(live != null && first?.Source == "skeleton:try" && first.Faces.Count > 0
                && art1.Caption == Loc.F("art.skel.try.best", 10, 100, 7) && !ReferenceEquals(first, second)
                && art2.Caption == Loc.F("art.skel.try", 40, 100, 37) && stepsOn == "skeleton:rooms" && old.Current == null,
                $"the skeletons tried, on the scheme as they come: «{art1.Caption}» → «{art2.Caption}», then the chosen one's steps (3.64: nothing)",
                $"the tries: section {live != null}, first «{first?.Source}» «{art1.Caption}», second «{art2.Caption}», "
                + $"then «{stepsOn}»; 3.64's way {old.Current?.Source}");
        }
        using (var held = Publish(root, "skeleton_show.json", skeleton))
        {
            var model = new SchemeModel();
            model.Shows(scratch);
            var frames = model.Frames;
            var first = model.Current;
            var art = first != null ? StageArt.Now(scratch, first) : default;
            var since = DateTime.Now;
            var seen = new List<string>();
            foreach (var k in new[] { 0, 1, 2, 3 })
            {
                model.ShowFrame(since.AddSeconds(0.1 + k * SkeletonShow.FrameSeconds));
                seen.Add(model.Current?.ShowCaption ?? "-");
            }
            SchemeModel.OldShows = true;
            var old = new SchemeModel();
            old.Shows(scratch);
            SchemeModel.OldShows = false;
            var part = frames is { Count: > 0 } ? SkeletonShow.Caption(frames[0]) : "";
            Row(held != null && frames is { Count: 4 } && frames.All(f => f.Snap.Faces.Count > 0) && first?.Source == "skeleton:rooms"
                && art.Caption == part && part == Loc.F("art.skel.part", Loc.T("skel.rooms"), 1, 3, 1, 2)
                && seen.Distinct().Count() == 4 && seen[^1] == Loc.F("art.skel", Loc.T("skel.items"), 3, 3)
                && old.Frames == null && old.Current == null,
                $"the skeleton handed over in memory: {frames?.Count} frames in turn - {string.Join(" | ", seen)} (3.63: none)",
                $"the skeleton in memory: section {held != null}, frames {frames?.Count}, first «{first?.Source}» «{art.Caption}», "
                + $"seen {string.Join(" | ", seen)}; 3.63's way frames {old.Frames?.Count}, current {old.Current?.Source}");
        }
        // (s2) the walk of the map's check: a spawn point, a footprint way with a teleporter on it to a railgun, a
        // megahealth no walk reaches
        const string walkText = "{\"version\":1,\"tmax\":2.5,\"reached\":3,\"points\":4,\"spawns\":[[0,0,24]],"
                                + "\"floor\":[[0,0,0,0],[32,0,0,0.2],[64,0,0,0.4]],\"unreached\":[[300,300,0]],"
                                + "\"trails\":[{\"cls\":\"weapon_railgun\",\"at\":[200,0,16],\"t\":2.5,"
                                + "\"steps\":[[22,7,0,0,0.07,1],[66,-7,0,0,0.22,-1],[110,7,0,0,0.37,1]],"
                                + "\"moves\":[{\"kind\":\"teleport\",\"from\":[120,0,0],\"to\":[190,0,0],\"t\":0.4}]}],"
                                + "\"lost\":[{\"cls\":\"item_health_mega\",\"at\":[300,300,16]}]}";
        var gates = FreshRun("gates");
        using (var held = Publish(gates.ShowRoot, "walk_show.json", walkText))
        {
            SchemeModel.Snapshot Map() => new() { Source = "selftest", Min = new(-300, -300, -50), Max = new(400, 400, 200), PlayTop = 200 };
            var model = new SchemeModel();
            model.ShowsForSelfTest(null, null, Map());
            model.Shows(gates);
            var s = model.Current!;
            var walk = s.Walk;
            var steps = new List<string>();
            var cam = new SchemeCamera { Yaw = -125, Pitch = 40 };
            cam.Fit(s);
            var pixels = new List<int>();
            foreach (var at in new[] { 0.1, 1.0, 3.0 })
            {
                if (walk != null)
                    walk.Since = DateTime.Now.AddSeconds(-at);
                var a = StageArt.Now(gates, s);
                steps.Add($"{a.WalkT:0.0} s vis {a.Vis:0.00} «{a.Caption}»");
                pixels.Add(Drawn(new SchemeOverlay(model, () => gates, cam), 800, 500));
            }
            var over = walk != null ? StageArt.Now(gates, s) : default;
            var moving = StageArt.Moving(gates, s);
            SchemeModel.OldShows = true;
            var old = new SchemeModel();
            old.ShowsForSelfTest(null, null, Map());
            old.Shows(gates);
            var oldArt = StageArt.Now(gates, old.Current!);
            var oldPixels = Drawn(new SchemeOverlay(old, () => gates, cam), 800, 500);
            SchemeModel.OldShows = false;
            Row(held != null && walk is { Trails.Count: 1, Lost.Count: 1 } && over.Walk && moving && over.Vis > 1.5f
                && over.Caption == Loc.F("art.walk", 1, StageArt.Seconds(2.5f), 1, 2) && pixels.All(p => p > oldPixels + 200) && pixels[^1] > pixels[0]
                && old.Current?.Walk == null && !oldArt.Walk,
                $"the map's checks walked: {string.Join("; ", steps)}; the overlay draws {string.Join("/", pixels)} pixels (3.63: {oldPixels}, no walk)",
                $"the walk in memory: section {held != null}, trails {walk?.Trails.Count}, lost {walk?.Lost.Count}, moving {moving}, "
                + $"{string.Join("; ", steps)}; pixels {string.Join("/", pixels)}; 3.63's way walk {old.Current?.Walk != null}, {oldPixels} px");
        }
    }
}
