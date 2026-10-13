using System.Globalization;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;

namespace MapgenStudio;

/// <summary>
/// The base's frame as the generator laid it for a try (its «stage=warp-map» line): each axis's part edges in the
/// donor and where they land, the leans, the turn. <see cref="Apply"/> moves a point of the donor as the generator's
/// warp does (mapgen_warp.c: part_map, lean_of, affine_at; then the quarter turns and the mirror about the middle), so
/// the scheme can draw the donor stretching into its new frame (the PO, 11.10: «когда деформация тоже отображать как то
/// наглядно, карта то 3D»).
/// </summary>
public sealed class WarpMap
{
    public readonly float[][] At = new float[3][], To = new float[3][];
    public readonly float[][] Lean = new float[2][];
    public int Turns;
    public bool Mirror;
    public Vector2 Pivot;
    public string Key = "";

    public static WarpMap? Parse(Dictionary<string, string> f)
    {
        var w = new WarpMap();
        var any = false;
        for (var a = 0; a < 5; a++)
        {
            var key = a switch { 0 => "x", 1 => "y", 2 => "z", 3 => "lean_x", _ => "lean_y" };
            var pairs = f.GetValueOrDefault(key, "").Split(',', StringSplitOptions.RemoveEmptyEntries)
                         .Select(p => p.Split(':')).Where(p => p.Length == 2).ToList();
            var at = new List<float>();
            var to = new List<float>();
            foreach (var p in pairs)
                if (float.TryParse(p[0], NumberStyles.Float, CultureInfo.InvariantCulture, out var x)
                    && float.TryParse(p[1], NumberStyles.Float, CultureInfo.InvariantCulture, out var y))
                {
                    at.Add(x);
                    to.Add(y);
                }
            if (a < 3)
            {
                w.At[a] = at.ToArray();
                w.To[a] = to.ToArray();
                any |= at.Count >= 2;
            }
            else
                w.Lean[a - 3] = to.ToArray();
        }
        w.Turns = int.TryParse(f.GetValueOrDefault("turns", "0"), out var t) ? t & 3 : 0;
        w.Mirror = f.GetValueOrDefault("mirror", "0") == "1";
        w.Key = string.Join("|", new[] { "x", "y", "z", "lean_x", "lean_y", "turns", "mirror" }.Select(k => f.GetValueOrDefault(k, "")));
        return any || w.Turns != 0 || w.Mirror ? w : null;
    }

    /// <summary>The part an axis's value falls in: the generator's own search (the first and last parts run on).</summary>
    private int Part(int axis, float v)
    {
        var at = At[axis];
        var i = 0;
        while (i + 2 < at.Length && v >= at[i + 1])
            i++;
        return i;
    }

    private float Line(int axis, float v)
    {
        var at = At[axis];
        if (at.Length < 2)
            return v;
        var i = Part(axis, v);
        var span = at[i + 1] - at[i];
        if (span <= 0)
            return v;
        var k = (To[axis][i + 1] - To[axis][i]) / span;
        return To[axis][i] + k * (v - at[i]);
    }

    private float LeanOf(int axis, float v)
    {
        var at = At[axis];
        var lean = Lean[axis];
        if (at.Length < 2 || lean == null || lean.Length != at.Length)
            return 0;
        var i = Part(axis, v);
        var span = at[i + 1] - at[i];
        if (span <= 0)
            return lean[i];
        return lean[i] + (lean[i + 1] - lean[i]) / span * (v - at[i]);
    }

    /// <summary>The part's band of a point - for the colours that tell the parts apart.</summary>
    public (int x, int y) Band(Vector3 p) => (At[0].Length >= 2 ? Part(0, p.X) : 0, At[1].Length >= 2 ? Part(1, p.Y) : 0);

    /// <summary>A point of the donor, where the frame puts it (before the turn).</summary>
    public Vector3 Stretch(Vector3 p) =>
        new(Line(0, p.X) + LeanOf(1, p.Y), Line(1, p.Y) + LeanOf(0, p.X), Line(2, p.Z));

    /// <summary>The stretched point turned and mirrored about the stretched map's middle (<see cref="Pivot"/>).</summary>
    public Vector3 Turn(Vector3 q)
    {
        float x = q.X - Pivot.X, y = q.Y - Pivot.Y;
        for (var t = 0; t < Turns; t++)
            (x, y) = (-y, x);
        if (Mirror)
            x = -x;
        return new Vector3(x + Pivot.X, y + Pivot.Y, q.Z);
    }

    public Vector3 Apply(Vector3 p) => Turn(Stretch(p));
}

/// <summary>A light of the map: where it is, its colour, how strong, and where a spotlight points.</summary>
public sealed record Lamp(Vector3 At, Vector3 Colour, float Level, Vector3? Toward);

/// <summary>
/// What the scheme draws for the stage under way, the same for the card and the overlay at one moment (the PO, 11.10:
/// «каждый этап должен быть визуализирован так чтобы его смотреть было в удовольствие и с пользой»): how far the donor
/// has stretched into its frame, how far the light has spread from the lamps, how far the visibility has gone.
/// </summary>
public static class StageArt
{
    public readonly record struct State(float Morph, float Glow, float Vis, bool Lamps, bool Portals, string Caption);

    private static float Ease(float t) => t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t);

    public static State Now(Generation? run, SchemeModel.Snapshot s)
    {
        var morph = 1f;
        var caption = "";
        if (s.Warp != null && s.IsDonor)
        {
            // the frame being tried: the donor eases into it, holds, eases back - over and over while it is built
            // and walked; once the frame is kept it stays stretched
            var warping = run is { Running: true, Stage: "warp" };
            if (warping)
            {
                var t = (float)(DateTime.Now.TimeOfDay.TotalSeconds % 7.0);
                morph = t < 1.0f ? 0 : t < 3.5f ? Ease((t - 1.0f) / 2.5f) : t < 5.8f ? 1 : 1 - Ease((t - 5.8f) / 1.2f);
            }
            caption = Loc.F(warping ? "art.warp" : "art.warp.kept", run?.Request.Options?.WarpSize ?? 100,
                            run?.Request.Options?.WarpShape ?? 0);
        }
        float glow = 0, vis = 0;
        bool lamps = false, portals = false;
        if (run is { Running: true, Stage: "light" } lr)
        {
            var tenths = Math.Clamp(lr.LightTenths, 0, 10) / 10f;
            var pulse = 0.5f + 0.5f * (float)Math.Sin(DateTime.Now.TimeOfDay.TotalSeconds * 2.2);
            if (lr.LightStep == "vis")
            {
                portals = s.Portals is { Count: > 0 };
                // the base pass the first third, the full pass the rest
                vis = lr.LightPass == 0 ? tenths / 3f : lr.LightPass == 1 ? 1f / 3f + tenths * 2f / 3f : 1f;
                lamps = true;
                glow = 0.15f + 0.05f * pulse;
                caption = portals ? Loc.F("art.vis", (int)(vis * s.Portals!.Count), s.Portals.Count, (int)(vis * 100))
                                  : Loc.F("art.vis.noportals", (int)(vis * 100));
            }
            else if (lr.LightStep == "rad")
            {
                lamps = true;
                glow = lr.LightPass == 0 ? 0.2f + 0.8f * Ease(tenths) : 0.85f + 0.15f * pulse;
                caption = lr.LightPass == 0 ? Loc.F("art.light", s.Lamps.Count, (int)(tenths * 100))
                                            : Loc.F("art.bounce", lr.LightPass, (int)(tenths * 100));
            }
            else
            {
                lamps = true;
                glow = 0.1f;
                caption = Loc.F("art.light.ready", s.Lamps.Count);
            }
        }
        return new State(morph, glow, vis, lamps && s.Lamps.Count > 0, portals, caption);
    }

    /// <summary>Whether the picture moves now - the scheme then draws thirty frames a second instead of ten.</summary>
    public static bool Moving(Generation? run, SchemeModel.Snapshot? s) =>
        s != null && run is { Running: true } r && ((r.Stage == "warp" && s.Warp != null) || r.Stage == "light");

    /// <summary>A light entity's colour: «_color» as given (0..1 or 0..255), white when none.</summary>
    public static Vector3 Colour(string? v)
    {
        var parts = (v ?? "").Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (parts.Length != 3)
            return Vector3.One;
        var c = new float[3];
        for (var i = 0; i < 3; i++)
            if (!float.TryParse(parts[i], NumberStyles.Float, CultureInfo.InvariantCulture, out c[i]))
                return Vector3.One;
        var max = Math.Max(c[0], Math.Max(c[1], c[2]));
        if (max <= 0)
            return Vector3.One;
        return new Vector3(c[0], c[1], c[2]) / max;
    }

    /// <summary>
    /// The light compile's portal file (PRT1): each portal between two clusters as its polygon. The order is the
    /// visibility's wave: by distance from <paramref name="from"/> (a start), nearest first.
    /// </summary>
    public static List<Vector3[]> Portals(byte[] data, Vector3 from)
    {
        var list = new List<Vector3[]>();
        var text = Encoding.ASCII.GetString(data);
        var lines = text.Split('\n');
        if (lines.Length < 4 || !lines[0].StartsWith("PRT1"))
            return list;
        var point = new Regex(@"\(\s*([-\d.eE+]+)\s+([-\d.eE+]+)\s+([-\d.eE+]+)\s*\)");
        for (var i = 3; i < lines.Length; i++)
        {
            var ms = point.Matches(lines[i]);
            if (ms.Count < 3)
                continue;
            var poly = new Vector3[ms.Count];
            for (var k = 0; k < ms.Count; k++)
                poly[k] = new Vector3(float.Parse(ms[k].Groups[1].Value, CultureInfo.InvariantCulture),
                                      float.Parse(ms[k].Groups[2].Value, CultureInfo.InvariantCulture),
                                      float.Parse(ms[k].Groups[3].Value, CultureInfo.InvariantCulture));
            list.Add(poly);
        }
        return list.OrderBy(p => Vector3.Distance(Mid(p), from)).ToList();
    }

    public static Vector3 Mid(Vector3[] poly)
    {
        var sum = Vector3.Zero;
        foreach (var v in poly)
            sum += v;
        return sum / Math.Max(1, poly.Length);
    }
}
