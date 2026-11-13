using System.Globalization;
using System.Numerics;

namespace MapgenStudio;

/// <summary>
/// The PO 13.11 («сделай чтобы движущиеся конструкции были также видны в превью карты генерации на всех этапах где они
/// уже построены», «пусть они там движутся тоже так как на карте»): a brush entity of the map - or of the skeleton's
/// pieces - moved on the scheme as the game moves it (g_func.c):
/// <list type="bullet">
/// <item>a func_train rides its path_corner chain at its speed, waiting at each corner its wait;</item>
/// <item>a func_door and a func_water slide their way (angle -1 up, -2 down, else the yaw) by their size less their lip,
/// a func_door_rotating turns its distance about its axis (X_AXIS 64 the roll, Y_AXIS 128 the pitch, else the yaw) -
/// each opened when fired, held its wait, closed; a TOGGLE (32) one flips at each fire;</item>
/// <item>a func_rotating spins at its speed about its axis (4 the roll, 8 the pitch, else the yaw);</item>
/// <item>a func_plat rests lowered and rides up.</item>
/// </list>
/// What fires one: a func_timer (its wait, its first fire at 1 + delay + wait), through a trigger_relay's delay; what a
/// player fires in the game (a button, a plate in the floor, an item taken, a lift ridden) is shown as fired every
/// <see cref="DemoPeriod"/> seconds. The turn is the game's own: the model drawn on AngleVectors' forward, left and up.
/// </summary>
public sealed class Mover
{
    public enum Way { Slide, Turn, Spin, Ride }

    public Way How;
    public string Cls = "";
    public Vector3 Origin;
    public Vector3 Dir;
    /// <summary>A slide's units, a turn's degrees (signed).</summary>
    public float Distance;
    /// <summary>The angles' index turned: 0 pitch, 1 yaw, 2 roll.</summary>
    public int Axis = 1;
    public float Speed = 100;
    public float Wait = 3;
    public bool Toggle, StartOpen;
    /// <summary>The PO 13.11: a door that starts and stops gently (its accel and decel under its speed's four times).</summary>
    public bool Eased;
    /// <summary>A ride's box offsets at its corners, each corner's wait.</summary>
    public List<(Vector3 at, float wait)>? Path;
    /// <summary>A ride's corners the train jumps to (a path_corner's teleport, spawnflags 1): no leg into them.</summary>
    public HashSet<int>? Jumps;
    /// <summary>Fired at Phase + k × Period; a Period of 0: never fired, at rest.</summary>
    public double Phase, Period;
    public bool Demo;

    public const double DemoPeriod = 12, DemoLead = 3;

    /// <summary>The scheme's clock: every mover of every map on one time.</summary>
    public static readonly System.Diagnostics.Stopwatch Clock = System.Diagnostics.Stopwatch.StartNew();
    public static double Now => Clock.Elapsed.TotalSeconds + At;

    /// <summary>The scheme's test (`--scheme-test JOB OUT --at SECONDS`): the movers drawn as at that second.</summary>
    public static double At;

    /// <summary>How far it has moved (0 at rest as built, 1 moved) at time t.</summary>
    public double Frac(double t)
    {
        if (Period <= 0 || t < Phase)
            return StartOpen ? 1 : 0;
        var move = Math.Max(0.05, Math.Abs(Distance) / Math.Max(1, Speed));
        var k = Math.Floor((t - Phase) / Period);
        var since = t - Phase - k * Period;
        double f;
        double E(double p) => Eased ? p * p * (3 - 2 * p) : p;
        if (Toggle)
        {
            // each fire flips it: after the first, third … it has moved
            var moving = (long)k % 2 == 0;
            var p = E(Math.Min(1, since / move));
            f = moving ? p : 1 - p;
        }
        else
        {
            // a wait of -1 stays open in the game: shown closing again before the next showing
            var wait = Wait < 0 ? Math.Max(0, Period - 2 * move - 0.5) : Wait;
            f = since < move ? E(since / move) : since < move + wait ? 1 : since < 2 * move + wait ? 1 - E((since - move - wait) / move) : 0;
        }
        return StartOpen ? 1 - f : f;
    }

    /// <summary>Its faces' transform at time t (rest = identity).</summary>
    public Matrix4x4 Pose(double t)
    {
        switch (How)
        {
            case Way.Slide:
                return Matrix4x4.CreateTranslation(Dir * (float)(Distance * Frac(t)));
            case Way.Turn:
                return Turned(Origin, Axis, Distance * Frac(t));
            case Way.Spin:
                return Turned(Origin, Axis, Speed * t % 360);
            case Way.Ride when Path is { Count: > 0 } path:
                return Matrix4x4.CreateTranslation(RideAt(path, t));
            default:
                return Matrix4x4.Identity;
        }
    }

    private Vector3 RideAt(List<(Vector3 at, float wait)> path, double t)
    {
        if (path.Count == 1)
            return path[0].at;
        var legs = new double[path.Count];
        double cycle = 0;
        for (var i = 0; i < path.Count; i++)
        {
            var next = path[(i + 1) % path.Count].at;
            var jump = Jumps != null && Jumps.Contains((i + 1) % path.Count);
            legs[i] = Math.Max(0, path[i].wait) + (jump ? 0 : Vector3.Distance(path[i].at, next) / Math.Max(1, Speed));
            cycle += legs[i];
        }
        if (cycle <= 0)
            return path[0].at;
        var u = t % cycle;
        for (var i = 0; i < path.Count; i++)
        {
            if (u >= legs[i])
            {
                u -= legs[i];
                continue;
            }
            var wait = Math.Max(0, path[i].wait);
            if (u < wait)
                return path[i].at;
            var span = legs[i] - wait;
            var p = span <= 0 ? 1 : (u - wait) / span;
            return Vector3.Lerp(path[i].at, path[(i + 1) % path.Count].at, (float)p);
        }
        return path[0].at;
    }

    /// <summary>
    /// A turn of `deg` about angles' index `axis` round `origin`, as the game draws a model: a point p (about the
    /// origin) goes to p.x·forward + p.y·left + p.z·up of AngleVectors (q_shared.c; the refresh's AnglesToAxis).
    /// </summary>
    public static Matrix4x4 Turned(Vector3 origin, int axis, double deg)
    {
        double rad = Math.PI / 180;
        double pitch = axis == 0 ? deg : 0, yaw = axis == 1 ? deg : 0, roll = axis == 2 ? deg : 0;
        double sy = Math.Sin(yaw * rad), cy = Math.Cos(yaw * rad);
        double sp = Math.Sin(pitch * rad), cp = Math.Cos(pitch * rad);
        double sr = Math.Sin(roll * rad), cr = Math.Cos(roll * rad);
        var fwd = new Vector3((float)(cp * cy), (float)(cp * sy), (float)-sp);
        var right = new Vector3((float)(-sr * sp * cy + cr * sy), (float)(-sr * sp * sy - cr * cy), (float)(-sr * cp));
        var up = new Vector3((float)(cr * sp * cy + sr * sy), (float)(cr * sp * sy - sr * cy), (float)(cr * cp));
        var left = -right;
        var m = new Matrix4x4(fwd.X, fwd.Y, fwd.Z, 0, left.X, left.Y, left.Z, 0, up.X, up.Y, up.Z, 0, 0, 0, 0, 1);
        return Matrix4x4.CreateTranslation(-origin) * m * Matrix4x4.CreateTranslation(origin);
    }

    // ---- from the entities ------------------------------------------------------------------------------------------

    private static float F(IReadOnlyDictionary<string, string> e, string key, float dflt) =>
        e.TryGetValue(key, out var v) && float.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out var f) ? f : dflt;

    private static int Flags(IReadOnlyDictionary<string, string> e) => (int)F(e, "spawnflags", 0);

    private static Vector3? V3(IReadOnlyDictionary<string, string> e, string key)
    {
        if (!e.TryGetValue(key, out var v))
            return null;
        var p = v.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (p.Length < 3)
            return null;
        return float.TryParse(p[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var x)
               && float.TryParse(p[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var y)
               && float.TryParse(p[2], NumberStyles.Float, CultureInfo.InvariantCulture, out var z)
            ? new Vector3(x, y, z) : null;
    }

    /// <summary>
    /// The mover of brush entity `e` (its box as drawn: `mins`, `maxs`), with what fires it among `all` the map's
    /// entities; null for one that does not move (a wall, a button, a trigger, a door nothing fires).
    /// </summary>
    public static Mover? Of(IReadOnlyDictionary<string, string> e, Vector3 mins, Vector3 maxs,
                            IReadOnlyList<IReadOnlyDictionary<string, string>> all)
    {
        var cls = e.TryGetValue("classname", out var c) ? c : "";
        var flags = Flags(e);
        var origin = V3(e, "origin") ?? Vector3.Zero;
        Mover? m = null;
        switch (cls)
        {
            case "func_rotating":
                if ((flags & 1) == 0)
                    return null;                 // not START_ON
                m = new Mover
                {
                    How = Way.Spin, Origin = origin, Axis = (flags & 4) != 0 ? 2 : (flags & 8) != 0 ? 0 : 1,
                    Speed = F(e, "speed", 100) * ((flags & 2) != 0 ? -1 : 1),
                };
                break;
            case "func_door_rotating":
                m = new Mover
                {
                    How = Way.Turn, Origin = origin, Axis = (flags & 64) != 0 ? 2 : (flags & 128) != 0 ? 0 : 1,
                    Distance = F(e, "distance", 90) * ((flags & 2) != 0 ? -1 : 1), Speed = F(e, "speed", 100),
                    Wait = F(e, "wait", 3), Toggle = (flags & 32) != 0, StartOpen = (flags & 1) != 0,
                };
                break;
            case "func_door":
            case "func_water":
            {
                var angle = F(e, "angle", 0);
                var dir = angle == -1 ? Vector3.UnitZ : angle == -2 ? -Vector3.UnitZ
                    : new Vector3((float)Math.Cos(angle * Math.PI / 180), (float)Math.Sin(angle * Math.PI / 180), 0);
                var size = maxs - mins;
                // the game: a door's lip 8 when none is given (g_func.c SP_func_door), a func_water's none
                var lip = F(e, "lip", 0);
                if (cls == "func_door" && lip == 0)
                    lip = 8;
                var dist = Math.Abs(dir.X) * size.X + Math.Abs(dir.Y) * size.Y + Math.Abs(dir.Z) * size.Z - lip;
                var spd = F(e, "speed", 100);
                var acc = F(e, "accel", spd);
                m = new Mover
                {
                    How = Way.Slide, Dir = dir, Distance = dist, Speed = spd,
                    Wait = F(e, "wait", cls == "func_water" ? -1 : 3), Toggle = (flags & 32) != 0, StartOpen = (flags & 1) != 0,
                    // the game's own easing: an accel of its own - its start and stop seen
                    // (the game moves a door at an even speed when its accel and decel equal its speed - as given or not)
                    Eased = e.ContainsKey("accel") && Math.Abs(acc - spd) > 0.5f,
                };
                break;
            }
            case "func_plat":
            {
                // rests lowered; ridden up by a player in the game - shown ridden
                var h = F(e, "height", 0);
                var dist = h > 0 ? h : maxs.Z - mins.Z - F(e, "lip", 8);
                return new Mover
                {
                    How = Way.Slide, Cls = cls, Dir = -Vector3.UnitZ, Distance = dist, Speed = 150,
                    Wait = 3, StartOpen = true, Demo = true, Period = DemoPeriod, Phase = DemoLead,
                };
            }
            case "func_train":
            {
                var path = new List<(Vector3, float)>();
                var jumps = new HashSet<int>();
                var name = e.TryGetValue("target", out var t0) ? t0 : "";
                var seen = new HashSet<string>();
                while (name.Length > 0 && seen.Add(name))
                {
                    var corner = all.FirstOrDefault(x => x.TryGetValue("targetname", out var tn) && tn == name
                                                         && x.TryGetValue("classname", out var cc) && cc == "path_corner");
                    if (corner == null || V3(corner, "origin") is not { } at)
                        break;
                    // the game puts the train's mins on each corner; a teleport corner is jumped to
                    if ((Flags(corner) & 1) != 0)
                        jumps.Add(path.Count);
                    path.Add((at - mins, F(corner, "wait", 0)));
                    name = corner.TryGetValue("target", out var nx) ? nx : "";
                }
                if (path.Count == 0)
                    return null;
                return new Mover { How = Way.Ride, Cls = cls, Path = path, Jumps = jumps, Speed = F(e, "speed", 100) };
            }
            default:
                return null;
        }
        m.Cls = cls;
        if (!e.TryGetValue("targetname", out var own) || own.Length == 0 || Fired(own, all, 0, 0) is not { } fire)
            return m.How == Way.Spin ? m : null;          // nothing fires it: it stays as built
        (m.Period, m.Phase, m.Demo) = fire;
        return m;
    }

    /// <summary>What fires the entities named `name`: a timer's (period, first fire), else a player's (shown every
    /// DemoPeriod) - through the relays' delays.</summary>
    private static (double period, double phase, bool demo)? Fired(string name, IReadOnlyList<IReadOnlyDictionary<string, string>> all,
                                                                 double delay, int depth)
    {
        if (depth > 6)
            return null;
        (double, double, bool)? demo = null;
        foreach (var x in all)
        {
            if (!x.TryGetValue("target", out var tg) || tg != name)
                continue;
            var cls = x.TryGetValue("classname", out var c) ? c : "";
            var d = delay + F(x, "delay", 0);
            if (cls == "func_timer")
            {
                var wait = Math.Max(0.1, F(x, "wait", 1));
                return (wait, 1 + d + wait, false);
            }
            if (cls == "trigger_relay" && x.TryGetValue("targetname", out var rn) && Fired(rn, all, d, depth + 1) is { } r)
            {
                if (!r.demo)
                    return r;
                demo ??= r;
                continue;
            }
            if (cls is "trigger_multiple" or "trigger_once" or "func_button" or "item" || cls.StartsWith("item_")
                || cls.StartsWith("weapon_") || cls.StartsWith("ammo_"))
                demo ??= (DemoPeriod, DemoLead + d, true);
        }
        return demo;
    }
}
