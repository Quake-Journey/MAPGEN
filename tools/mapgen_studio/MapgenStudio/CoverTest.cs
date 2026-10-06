using System.Globalization;
using System.Text;

namespace MapgenStudio;

/// <summary>
/// `--cover-test NAME` (phase P4's proof): the cover of library map NAME made exactly as the card's button makes it -
/// ONE watched launch of the client - then: a shot per viewpoint in data\covers\NAME, every map copy and the
/// temporary config gone from the client, the client's configs byte-equal before and after, the launch carrying
/// the S5 guard. One PASS / FAIL line per question.
/// </summary>
public static class CoverTest
{
    public static string Run(Settings s, string[] args)
    {
        var b = new StringBuilder();
        void Check(string what, bool ok, string detail = "") =>
            b.AppendLine($"{(ok ? "PASS" : "FAIL")} {what}" + (detail.Length > 0 ? $" -- {detail}" : ""));

        var at = Array.IndexOf(args, "--cover-test");
        var name = at + 1 < args.Length ? args[at + 1] : "";
        var map = Library.Scan(s).FirstOrDefault(m => m.Name == name);
        Check($"map {name} is in the library", map != null);
        if (map == null)
            return b.ToString();
        var views = Covers.Viewpoints(map, s);
        b.AppendLine("VIEWS " + string.Join("; ", views.Select(v => $"{v.What} {v.X:0} {v.Y:0} {v.Z:0} yaw {v.Yaw:0}")));
        // the copy the client loads: every entity but the spawns kept, one deathmatch spawn and one start, both at
        // the viewpoint
        var bsp = File.ReadAllBytes(map.BspPath);
        if (views.Count > 0)
        {
            var was = Covers.Entities(bsp);
            var now = Covers.Entities(Covers.WithStart(bsp, views[0]));
            var at0 = string.Create(CultureInfo.InvariantCulture, $"{views[0].X:0} {views[0].Y:0} {views[0].Z:0}");
            var dm = now.Where(e => e.GetValueOrDefault("classname") == "info_player_deathmatch").ToList();
            var sp = now.Where(e => e.GetValueOrDefault("classname") == "info_player_start").ToList();
            Check("a map copy keeps every other entity and has one deathmatch spawn and one start, at the first viewpoint",
                  dm.Count == 1 && sp.Count == 1 && dm[0]["origin"] == at0 && sp[0]["origin"] == at0
                  && now.Count(e => !Covers.IsSpawn(e)) == was.Count(e => !Covers.IsSpawn(e)),
                  $"{was.Count} -> {now.Count} entities");
        }
        var dir = Path.Combine(s.CoversPath, map.Name);
        if (Directory.Exists(dir))
            foreach (var f in Directory.GetFiles(dir, "cover_*.png"))
                File.Delete(f);
        var r = Covers.Start(map, s);
        Check("the launch carries the guard first: configs read-only, no fixed client port",
              r.Game.Process.StartInfo.ArgumentList.Take(Client.Guard.Length).SequenceEqual(Client.Guard),
              string.Join(" ", r.Game.Process.StartInfo.ArgumentList));
        var temp = r.TempFiles.ToList();
        var exited = r.Game.Process.WaitForExit(TimeSpan.FromMinutes(3));
        var (n, kept, note) = Covers.Finish(r, s, timeout: !exited);
        Check("the client closed itself within three minutes", exited, note);
        Check("a shot per viewpoint is in the cover folder", n == r.Views, $"{n} of {r.Views}");
        Check("the map copies and the cover config are gone from the client", temp.All(t => !File.Exists(t)),
              string.Join(" ", temp.Where(File.Exists)));
        Check("the client's configs are byte-equal before and after", kept, $"{r.Game.ConfigsBefore.Count} configs");
        return b.ToString();
    }
}
