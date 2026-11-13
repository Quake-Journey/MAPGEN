using System.Numerics;
using System.Text;

namespace MapgenStudio;

/// <summary>
/// The PO 13.11 («сделай чтобы движущиеся конструкции были также видны в превью карты генерации на всех этапах где они
/// уже построены», «пусть они там движутся тоже так как на карте»): the scheme's movers - a ride along its corners, a
/// door a timer flips, a pendulum swung down through its bridge by the game's own turn (3.68's first map swung it up),
/// a drum spinning, a trap's doors shown fired by a player through the relay's delay - and the skeleton's step with
/// pieces drawn and moving, the scheme drawing at the moving pace.
/// </summary>
public sealed partial class MainWindow
{
    internal static void MoversSelfTest(StringBuilder b)
    {
        void Row(bool ok, string pass, string fail) => b.AppendLine(ok ? $"PASS {pass}" : $"FAIL {fail}");
        try
        {
            static Dictionary<string, string> E(params string[] kv)
            {
                var d = new Dictionary<string, string>();
                for (var i = 0; i + 1 < kv.Length; i += 2)
                    d[kv[i]] = kv[i + 1];
                return d;
            }
            // (m1) a ride: its box from corner to corner, waiting at each
            var train = E("classname", "func_train", "target", "t_0", "speed", "100", "spawnflags", "1");
            var c0 = E("classname", "path_corner", "targetname", "t_0", "target", "t_1", "origin", "0 0 0", "wait", "1");
            var c1 = E("classname", "path_corner", "targetname", "t_1", "target", "t_0", "origin", "400 0 0", "wait", "1");
            var all = new List<IReadOnlyDictionary<string, string>> { train, c0, c1 };
            var ride = Mover.Of(train, Vector3.Zero, new Vector3(64, 64, 16), all);
            var p0 = Vector3.Transform(Vector3.Zero, ride!.Pose(0.5));
            var p1 = Vector3.Transform(Vector3.Zero, ride.Pose(1 + 2));
            var p2 = Vector3.Transform(Vector3.Zero, ride.Pose(1 + 4 + 0.5));
            Row(p0.X == 0 && Math.Abs(p1.X - 200) < 1 && Math.Abs(p2.X - 400) < 1,
                "a ride: at its first corner 0 u, half way at 3 s (200 u), at the far corner at 5.5 s (400 u)",
                $"a ride: {p0.X:0} / {p1.X:0} / {p2.X:0} u (want 0, 200, 400)");
            // (m2) a door a timer flips (a piston's): 64 at speed 64 - closed before its first fire, open after
            var door = E("classname", "func_door", "targetname", "pst", "angle", "-2", "lip", "8", "speed", "64", "spawnflags", "36");
            var timer = E("classname", "func_timer", "target", "pst", "wait", "2", "spawnflags", "1");
            var d = Mover.Of(door, Vector3.Zero, new Vector3(64, 64, 72), new List<IReadOnlyDictionary<string, string>> { door, timer });
            Row(d is { Toggle: true, Demo: false } && d.Frac(2.9) == 0 && d.Frac(3 + 1.5) == 1 && d.Frac(5 + 1.5) == 0
                && Math.Abs(Vector3.Transform(Vector3.Zero, d.Pose(4.5)).Z + 64) < 1,
                "a door a timer flips: shut before the first fire (3 s), 64 u down after it, back after the next",
                $"a door a timer flips: {d?.Frac(2.9)}, {d?.Frac(4.5)}, {d?.Frac(6.5)}, down {(d == null ? 0 : Vector3.Transform(Vector3.Zero, d.Pose(4.5)).Z):0}");
            // (m2b) the game's own easing (the PO 13.11: «как реальная физика работает»): a door with an accel of its own
            // starts slow - a quarter of its way's time covers less than a quarter of the way; without one, even
            var eased = E("classname", "func_door", "targetname", "pst2", "angle", "-2", "lip", "8", "speed", "64", "accel", "90",
                          "decel", "90", "spawnflags", "36");
            var even = E("classname", "func_door", "targetname", "pst2", "angle", "-2", "lip", "8", "speed", "64", "spawnflags", "36");
            var t2 = E("classname", "func_timer", "target", "pst2", "wait", "2", "spawnflags", "1");
            var de = Mover.Of(eased, Vector3.Zero, new Vector3(64, 64, 72), new List<IReadOnlyDictionary<string, string>> { eased, t2 });
            var dv = Mover.Of(even, Vector3.Zero, new Vector3(64, 64, 72), new List<IReadOnlyDictionary<string, string>> { even, t2 });
            Row(de is { Eased: true } && dv is { Eased: false } && de.Frac(3 + 0.25) < 0.2 && Math.Abs(dv.Frac(3 + 0.25) - 0.25) < 0.01,
                $"a door with its own accel starts slow ({de?.Frac(3.25):0.00} of its way at a quarter of its time), one without moves evenly ({dv?.Frac(3.25):0.00})",
                $"easing: eased {de?.Eased} {de?.Frac(3.25):0.00}, even {dv?.Eased} {dv?.Frac(3.25):0.00}");
            // (m3) the pendulum of the PO's mg_new_368_ffa8: about Y, +90 takes the weight down through the bridge;
            // -90 (3.68's first map) up over the pivot
            Vector3 Swing(string distance)
            {
                var pend = E("classname", "func_door_rotating", "targetname", "pd", "origin", "0 0 500", "distance", distance,
                             "speed", "90", "spawnflags", "160");
                var tm = E("classname", "func_timer", "target", "pd", "wait", "10", "spawnflags", "1");
                var m = Mover.Of(pend, new Vector3(-10, -10, 100), new Vector3(300, 10, 500),
                                 new List<IReadOnlyDictionary<string, string>> { pend, tm })!;
                return Vector3.Transform(new Vector3(200, 0, 300), m.Pose(11 + 2));
            }
            var down = Swing("90");
            var up = Swing("-90");
            Row(down.X < -150 && down.Z < 400 && up.Z > 600,
                "a pendulum about Y swung +90: its weight from one side to the other under the pivot (-90 took it over, into the sky)",
                $"a pendulum: +90 ends at {down.X:0} {down.Z:0}, -90 at {up.X:0} {up.Z:0}");
            // (m4) a drum spins; a trap's doors fired by a player's button through a relay (delay 1): shown every 12 s
            var drum = Mover.Of(E("classname", "func_rotating", "origin", "0 0 0", "speed", "20", "spawnflags", "9"),
                                new Vector3(-48), new Vector3(48), new List<IReadOnlyDictionary<string, string>>());
            var trapDoor = E("classname", "func_door", "targetname", "doors", "angle", "-1", "speed", "300", "wait", "5", "lip", "8");
            var relay = E("classname", "trigger_relay", "targetname", "go", "target", "doors", "delay", "1");
            var button = E("classname", "func_button", "target", "go");
            var td = Mover.Of(trapDoor, Vector3.Zero, new Vector3(12, 64, 136), new List<IReadOnlyDictionary<string, string>> { trapDoor, relay, button });
            var spun = Vector3.Transform(new Vector3(48, 0, 0), drum!.Pose(4.5));
            Row(Math.Abs(spun.Z) > 1 && td is { Demo: true } && Math.Abs(td.Phase - (Mover.DemoLead + 1)) < 0.01 && td.Frac(td.Phase + 1) == 1,
                $"a drum turns (4.5 s: its edge {spun.Z:0} u off level); a trap's doors fired by its button through the relay's 1 s - shown every {Mover.DemoPeriod:0} s",
                $"a drum's edge {spun.Z:0}; a trap door: demo {td?.Demo}, first at {td?.Phase:0.0} s, open {td?.Frac((td?.Phase ?? 0) + 1)}");
            // (m5) the skeleton's step with a piece: drawn, moving, the scheme at the moving pace
            var json = """
                {"steps":[{"step":"items","kinds":["hall"],"cells":[[0,0,0,0,0],[1,0,0,0,0]],"doors":[],"liquids":[],"pits":[],
                "lifts":[],"pads":[],"teleports":[],"items":[],"spawns":[],"tubes":[],
                "pieces":{"brushes":[{"box":[0,0,0,8,8,64],"role":"trim"}],
                "ents":[{"keys":{"classname":"func_train","target":"t_0","speed":"100","spawnflags":"1"},
                         "brushes":[{"box":[0,0,-16,56,56,0],"role":"plate"}]},
                        {"keys":{"classname":"path_corner","targetname":"t_0","target":"t_1","origin":"0 0 -16","wait":"0"},"brushes":[]},
                        {"keys":{"classname":"path_corner","targetname":"t_1","target":"t_0","origin":"256 0 -16","wait":"0"},"brushes":[]}]}}]}
                """;
            var steps = SkeletonShow.Parse(Encoding.UTF8.GetBytes(json));
            var snap = steps is { Count: 1 } ? SkeletonShow.Snapshot(steps[0], steps[0].Cells) : null;
            var mf = snap?.Faces.FirstOrDefault(f => f.Move != null);
            var a = mf == null ? Vector3.Zero : Vector3.Transform(mf.V[0], mf.Move!.Pose(0.2));
            var z = mf == null ? Vector3.Zero : Vector3.Transform(mf.V[0], mf.Move!.Pose(1.5));
            var fixedFaces = snap?.Faces.Count(f => f.Move == null && f.Kind == 6) ?? 0;
            Row(snap != null && mf != null && Math.Abs(z.X - a.X) > 50 && fixedFaces >= 5 && snap.HasMovers
                && StageArt.Moving(null, snap),
                $"the skeleton's step with a ride: {fixedFaces} faces of its fixed brush, the ride {Math.Abs(z.X - a.X):0} u on in 1.3 s, the scheme at the moving pace",
                $"the skeleton's step: snapshot {snap != null}, moving face {mf != null}, moved {Math.Abs(z.X - a.X):0}, fixed {fixedFaces}, pace {snap != null && StageArt.Moving(null, snap)}");
            // (m6) a map of the library with pieces (a ride, a pendulum, a drum - the PO's mg_new_368_ffa8 when it is
            // there): read as the scheme reads it, its movers found and moving
            var withPieces = Library.Scan(App.Settings).Select(m => m.BspPath).FirstOrDefault(path =>
            {
                try
                {
                    var bytes = File.ReadAllBytes(path);
                    return System.Text.Encoding.Latin1.GetString(bytes).Contains("func_door_rotating");
                }
                catch (IOException)
                {
                    return false;
                }
            });
            if (withPieces != null)
            {
                var map = SchemeModel.Read(File.ReadAllBytes(withPieces));
                var movers = map.Faces.Where(f => f.Move != null).Select(f => f.Move!).Distinct().ToList();
                var shifted = movers.Count(m => m.Pose(0.3) != m.Pose(Mover.DemoLead + 7.3) || m.Pose(1.1) != m.Pose(9.7));
                Row(movers.Count > 0 && shifted > 0 && map.HasMovers,
                    $"{Path.GetFileNameWithoutExtension(withPieces)} as the scheme reads it: {movers.Count} movers ({string.Join(", ", movers.GroupBy(m => m.Cls).Select(g => $"{g.Key} {g.Count()}"))}), {shifted} seen moving",
                    $"{Path.GetFileNameWithoutExtension(withPieces)}: movers {movers.Count}, moving {shifted}");
            }
            else
                Row(true, "no map of the library has a turning piece: the movers read from the skeleton's step alone", "");
        }
        catch (Exception e)
        {
            Row(false, "", $"the scheme's movers: {e.GetType().Name}: {e.Message}");
        }
    }
}
