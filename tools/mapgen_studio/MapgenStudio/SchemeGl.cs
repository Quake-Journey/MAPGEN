using System.Globalization;
using System.Numerics;
using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Input;
using Avalonia.Media;
using Avalonia.OpenGL;
using Avalonia.OpenGL.Controls;
using Avalonia.Threading;

namespace MapgenStudio;

/// <summary>
/// The plan's camera (ledger row 410): an orbit about a target - yaw, pitch, distance - shared by the GPU's drawing
/// of the map and the overlay that draws the marks over it, so a mark sits where its pickup is.
/// </summary>
public sealed class SchemeCamera
{
    public float Yaw = -90, Pitch = 89, Dist = 3000;
    public Vector3 Target;
    public double? Cut;
    public const float Fov = 50;

    public (Vector3 eye, Vector3 right, Vector3 up, Vector3 fwd) Frame()
    {
        double y = Yaw * Math.PI / 180, p = Pitch * Math.PI / 180;
        var dir = new Vector3((float)(Math.Cos(p) * Math.Cos(y)), (float)(Math.Cos(p) * Math.Sin(y)), (float)Math.Sin(p));
        var fwd = -dir;
        var right = new Vector3((float)-Math.Sin(y), (float)Math.Cos(y), 0);
        var up = Vector3.Cross(right, fwd);
        return (Target + dir * Dist, right, up, fwd);
    }

    public float Focal(double height) => (float)(Math.Max(1, height) / 2 / Math.Tan(Fov / 2 * Math.PI / 180));

    /// <summary>This camera as it is now, apart from the one that keeps moving.</summary>
    public SchemeCamera Copy() => new() { Yaw = Yaw, Pitch = Pitch, Dist = Dist, Target = Target, Cut = Cut };

    /// <summary>A world point on the screen of this size; null behind the camera.</summary>
    public Point? Project(Vector3 p, Size size)
    {
        var (eye, right, up, fwd) = Frame();
        var q = p - eye;
        var depth = Vector3.Dot(q, fwd);
        if (depth < 8)
            return null;
        var f = Focal(size.Height);
        return new Point(size.Width / 2 + f * Vector3.Dot(q, right) / depth, size.Height / 2 - f * Vector3.Dot(q, up) / depth);
    }

    /// <summary>World to clip space, for the GPU - the same view as <see cref="Project"/>.</summary>
    public Matrix4x4 ViewProjection(double width, double height, SchemeModel.Snapshot s)
    {
        var (eye, _, up, _) = Frame();
        var view = Matrix4x4.CreateLookAt(eye, Target, up);
        var span = (s.Max - s.Min).Length();
        var near = Math.Max(4f, Dist - span * 1.5f);
        var proj = Matrix4x4.CreatePerspectiveFieldOfView(Fov * MathF.PI / 180, (float)(width / Math.Max(1, height)),
                                                          Math.Min(near, Dist * 0.05f), Dist + span * 2);
        return view * proj;
    }

    public void Fit(SchemeModel.Snapshot s)
    {
        var top = (float)(Cut ?? s.Max.Z);
        Target = new Vector3((s.Min.X + s.Max.X) / 2, (s.Min.Y + s.Max.Y) / 2, Math.Min(top, (s.Min.Z + s.Max.Z) / 2));
        Dist = Math.Max(s.Max.X - s.Min.X, s.Max.Y - s.Min.Y) * 1.2f;
    }
}

/// <summary>
/// The plan drawn by the graphics card (the PO, 05.10: «чтобы схема не тормозила при отрисовке, особенно когда
/// разворачиваю её на весь экран - юзай аппаратное ускорение видеокартой»). The CPU drawing sorted ~7500 faces and
/// stroked each as an antialiased path ten times a second; here the map goes to the card once per map (a vertex buffer
/// of its faces as triangles and its edges as lines), and each frame is a few draw calls with a depth buffer. A face
/// is seen only from the side it faces, the roofs over play left out above the cut - in the fragment shader, as the
/// CPU drawing did per face. The edits' boxes are a small buffer written each frame, drawn over the map.
/// </summary>
public sealed class SchemeGlView : OpenGlControlBase
{
    private readonly SchemeModel _model;
    private readonly Func<Generation?> _run;
    public readonly SchemeCamera Camera;
    private SchemeModel.Snapshot? _loaded;
    private int _program, _vao, _vbo, _boxVbo;
    private int _faceCount, _liquidFirst, _liquidCount, _edgeFirst, _edgeCount;
    private int _uMvp, _uEye, _uCut, _uBias;
    private bool _es;
    private BlendFunc? _blend;
    private ReadPixels? _read;

    /// <summary>Set when the card could not be used: the host then draws with the CPU's <see cref="SchemeView"/>.</summary>
    public bool Failed { get; private set; }
    public bool Ready { get; private set; }
    public string Info { get; private set; } = "";

    /// <summary>The plan test: the next frame's pixels, read back (RGBA, bottom row first).</summary>
    public Action<int, int, byte[]>? Captured;

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void BlendFunc(int s, int d);

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void ReadPixels(int x, int y, int w, int h, int format, int type, IntPtr data);

    /* the surface's own size (the PO 05.10: on the full screen the map was cut by a rectangle smaller than the
       screen, its markers off it - the frame was sized from the control, the surface the card drew on was not) */
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void GetIv3(int target, int attachment, int pname, out int value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void GetIv2(int target, int pname, out int value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void GetTexIv(int target, int level, int pname, out int value);
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void Bind2(int target, int name);
    private GetIv3? _attachIv;
    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void GetIv1(int pname, out int value);
    private GetIv2? _rbIv;
    private GetIv1? _getIv;
    private GetTexIv? _texIv;
    private Bind2? _bindRb, _bindTex;

    /// <summary>The size the last frame was drawn at, and the control's own size in pixels at that moment.</summary>
    public PixelSize DrawnSize { get; private set; }
    public PixelSize ControlSize { get; private set; }
    /// <summary>Frames whose surface was not the control's size (drawn at the surface's).</summary>
    public int Mismatched { get; private set; }

    /*
     * The camera the last frame on the screen was drawn with (the PO 05.10: under load the card's frame came late and
     * the marks, drawn over it from the camera as it already was, stood off the map). The marks are drawn from this
     * one, and asked for again when a frame lands.
     */
    public SchemeCamera? DrawnCamera { get; private set; }
    public event Action? FrameDrawn;

    private const int GL_ARRAY_BUFFER = 0x8892, GL_STATIC_DRAW = 0x88E4, GL_DYNAMIC_DRAW = 0x88E8, GL_FLOAT = 0x1406,
                      GL_TRIANGLES = 4, GL_LINES = 1, GL_DEPTH_TEST = 0x0B71, GL_BLEND = 0x0BE2, GL_SRC_ALPHA = 0x0302,
                      GL_ONE_MINUS_SRC_ALPHA = 0x0303, GL_COLOR_BUFFER_BIT = 0x4000, GL_DEPTH_BUFFER_BIT = 0x100,
                      GL_VERTEX_SHADER = 0x8B31, GL_FRAGMENT_SHADER = 0x8B30, GL_RGBA = 0x1908, GL_UNSIGNED_BYTE = 0x1401,
                      GL_LEQUAL = 0x0203;
    private const int Stride = 12;            // x y z, nx ny nz, r g b a, zlo, flags

    public SchemeGlView(SchemeModel model, Func<Generation?> run, SchemeCamera camera)
    {
        _model = model;
        _run = run;
        Camera = camera;
    }

    private string Header => _es ? "#version 300 es\nprecision highp float;\n" : "#version 330 core\n";

    private const string Vertex = @"
layout(location = 0) in vec3 aPos;
layout(location = 1) in vec3 aNormal;
layout(location = 2) in vec4 aColor;
layout(location = 3) in float aZlo;
layout(location = 4) in float aFlags;
uniform mat4 uMvp;
uniform float uBias;
out vec4 vColor;
out vec3 vNormal;
out vec3 vWorld;
out float vZlo;
out float vFlags;
void main() {
    vColor = aColor; vNormal = aNormal; vWorld = aPos; vZlo = aZlo; vFlags = aFlags;
    gl_Position = uMvp * vec4(aPos, 1.0);
    gl_Position.z -= uBias * gl_Position.w;
}";

    // flags: 1 a wall (kept when it rises past the cut), 2 seen from both sides (a liquid, an edit's box)
    private const string Fragment = @"
in vec4 vColor;
in vec3 vNormal;
in vec3 vWorld;
in float vZlo;
in float vFlags;
uniform vec3 uEye;
uniform float uCut;
out vec4 outColor;
void main() {
    bool wall = mod(vFlags, 2.0) >= 1.0;
    bool both = vFlags >= 2.0;
    if (!wall && vZlo > uCut + 1.0) discard;
    if (!both && dot(vNormal, uEye - vWorld) <= 0.0) discard;
    outColor = vColor;
}";

    protected override void OnOpenGlInit(GlInterface gl)
    {
        try
        {
            _es = GlVersion.Type == GlProfileType.OpenGLES;
            Info = $"{gl.Vendor} / {gl.Renderer} / {gl.Version}";
            var vs = gl.CreateShader(GL_VERTEX_SHADER);
            var fs = gl.CreateShader(GL_FRAGMENT_SHADER);
            var e1 = gl.CompileShaderAndGetError(vs, Header + Vertex);
            var e2 = gl.CompileShaderAndGetError(fs, Header + Fragment);
            if (e1 != null || e2 != null)
                throw new InvalidOperationException((e1 ?? "") + (e2 ?? ""));
            _program = gl.CreateProgram();
            gl.AttachShader(_program, vs);
            gl.AttachShader(_program, fs);
            var e3 = gl.LinkProgramAndGetError(_program);
            if (e3 != null)
                throw new InvalidOperationException(e3);
            _uMvp = gl.GetUniformLocationString(_program, "uMvp");
            _uEye = gl.GetUniformLocationString(_program, "uEye");
            _uCut = gl.GetUniformLocationString(_program, "uCut");
            _uBias = gl.GetUniformLocationString(_program, "uBias");
            _vao = gl.GenVertexArray();
            _vbo = gl.GenBuffer();
            _boxVbo = gl.GenBuffer();
            var blend = gl.GetProcAddress("glBlendFunc");
            _blend = blend != IntPtr.Zero ? Marshal.GetDelegateForFunctionPointer<BlendFunc>(blend) : null;
            var read = gl.GetProcAddress("glReadPixels");
            _read = read != IntPtr.Zero ? Marshal.GetDelegateForFunctionPointer<ReadPixels>(read) : null;
            T? Fn<T>(string name) where T : Delegate
            {
                var at = gl.GetProcAddress(name);
                return at != IntPtr.Zero ? Marshal.GetDelegateForFunctionPointer<T>(at) : null;
            }
            _attachIv = Fn<GetIv3>("glGetFramebufferAttachmentParameteriv");
            _rbIv = Fn<GetIv2>("glGetRenderbufferParameteriv");
            _getIv = Fn<GetIv1>("glGetIntegerv");
            _texIv = Fn<GetTexIv>("glGetTexLevelParameteriv");
            _bindRb = Fn<Bind2>("glBindRenderbuffer");
            _bindTex = Fn<Bind2>("glBindTexture");
            Ready = true;
        }
        catch (Exception ex)
        {
            Failed = true;
            Info = ex.Message;
        }
    }

    protected override void OnOpenGlDeinit(GlInterface gl)
    {
        if (_vbo != 0)
            gl.DeleteBuffer(_vbo);
        if (_boxVbo != 0)
            gl.DeleteBuffer(_boxVbo);
        if (_vao != 0)
            gl.DeleteVertexArray(_vao);
        if (_program != 0)
            gl.DeleteProgram(_program);
        _vbo = _boxVbo = _vao = _program = 0;
        _loaded = null;
    }

    protected override void OnOpenGlLost()
    {
        Failed = true;
        Ready = false;
    }

    private static void Put(List<float> v, Vector3 p, Vector3 n, (float r, float g, float b, float a) c, float zlo, float flags)
    {
        v.Add(p.X); v.Add(p.Y); v.Add(p.Z);
        v.Add(n.X); v.Add(n.Y); v.Add(n.Z);
        v.Add(c.r); v.Add(c.g); v.Add(c.b); v.Add(c.a);
        v.Add(zlo); v.Add(flags);
    }

    /// <summary>The map into the card: opaque faces, then the liquids, then every face's edges.</summary>
    private unsafe void Load(GlInterface gl, SchemeModel.Snapshot s)
    {
        var light = Vector3.Normalize(new Vector3(0.35f, 0.55f, 0.75f));
        var zspan = Math.Max(1, s.Max.Z - s.Min.Z);
        var opaque = new List<float>(s.Faces.Count * 6 * Stride);
        var liquid = new List<float>();
        var edges = new List<float>(s.Faces.Count * 8 * Stride);
        foreach (var f in s.Faces)
        {
            if (f.Kind == 2 || f.V.Length < 3)
                continue;                   // a ceiling hides what is under it from every view that matters here
            var lit = 0.55f + 0.45f * Math.Max(0, Vector3.Dot(f.N, light));
            (float, float, float, float) c = f.Light is { } own && f.Kind is 0 or 1 or 6
                // row 411: a lit map drawn with its own light - the face's lightmap colour, brightened to be read
                ? (Math.Min(1f, 0.08f + own.X * 1.6f), Math.Min(1f, 0.08f + own.Y * 1.6f), Math.Min(1f, 0.08f + own.Z * 1.6f), 1f)
                : f.Kind switch
            {
                0 => Shade((0x3a + (f.ZLo - s.Min.Z) / zspan * 0x90) / 255f, lit, 4 / 255f, 12 / 255f),
                1 => Shade(0x6e / 255f, lit, 6 / 255f, 14 / 255f),
                3 => (0x2f / 255f, 0x7d / 255f, 0xf0 / 255f, 0.70f),
                4 => (1f, 0x6a / 255f, 0f, 0.82f),
                5 => (0x6b / 255f, 0xd1 / 255f, 0x2f / 255f, 0.75f),
                _ => (0xa8 / 255f * lit, 0x7c / 255f * lit, 0xe8 / 255f * lit, 1f),
            };
            var isLiquid = f.Kind is 3 or 4 or 5;
            var flags = (f.Kind == 1 ? 1f : 0f) + (isLiquid ? 2f : 0f);
            var into = isLiquid ? liquid : opaque;
            for (var i = 1; i + 1 < f.V.Length; i++)
            {
                Put(into, f.V[0], f.N, c, f.ZLo, flags);
                Put(into, f.V[i], f.N, c, f.ZLo, flags);
                Put(into, f.V[i + 1], f.N, c, f.ZLo, flags);
            }
            var edge = (0f, 0f, 0f, f.Kind == 1 ? 0.30f : 0.18f);
            for (var i = 0; i < f.V.Length; i++)
            {
                Put(edges, f.V[i], f.N, edge, f.ZLo, flags);
                Put(edges, f.V[(i + 1) % f.V.Length], f.N, edge, f.ZLo, flags);
            }
        }
        _faceCount = opaque.Count / Stride;
        _liquidFirst = _faceCount;
        _liquidCount = liquid.Count / Stride;
        _edgeFirst = _liquidFirst + _liquidCount;
        _edgeCount = edges.Count / Stride;
        var all = new float[opaque.Count + liquid.Count + edges.Count];
        opaque.CopyTo(all, 0);
        liquid.CopyTo(all, opaque.Count);
        edges.CopyTo(all, opaque.Count + liquid.Count);
        gl.BindBuffer(GL_ARRAY_BUFFER, _vbo);
        fixed (float* p = all)
            gl.BufferData(GL_ARRAY_BUFFER, new IntPtr(all.Length * 4), new IntPtr(p), GL_STATIC_DRAW);
        _loaded = s;
    }

    private static (float, float, float, float) Shade(float g, float lit, float db, float dg) =>
        (Math.Min(1, g * lit), Math.Min(1, (g + db) * lit), Math.Min(1, (g + dg) * lit), 1f);

    private void Attribs(GlInterface gl)
    {
        for (var i = 0; i < 5; i++)
            gl.EnableVertexAttribArray(i);
        gl.VertexAttribPointer(0, 3, GL_FLOAT, 0, Stride * 4, IntPtr.Zero);
        gl.VertexAttribPointer(1, 3, GL_FLOAT, 0, Stride * 4, new IntPtr(3 * 4));
        gl.VertexAttribPointer(2, 4, GL_FLOAT, 0, Stride * 4, new IntPtr(6 * 4));
        gl.VertexAttribPointer(3, 1, GL_FLOAT, 0, Stride * 4, new IntPtr(10 * 4));
        gl.VertexAttribPointer(4, 1, GL_FLOAT, 0, Stride * 4, new IntPtr(11 * 4));
    }

    /// <summary>The edits as boxes this frame: the one tried blinking blue, refused red fading, accepted green to brown.</summary>
    private List<float> Boxes(double? cut)
    {
        var v = new List<float>();
        var now = DateTime.Now;
        List<SchemeModel.Edit> edits;
        lock (_model.Sync)
            edits = _model.Edits.ToList();
        void Box(float[] b, (float r, float g, float bl) c, double alpha)
        {
            var p = new[]
            {
                new Vector3(b[0], b[1], b[2]), new Vector3(b[3], b[1], b[2]), new Vector3(b[3], b[4], b[2]), new Vector3(b[0], b[4], b[2]),
                new Vector3(b[0], b[1], b[5]), new Vector3(b[3], b[1], b[5]), new Vector3(b[3], b[4], b[5]), new Vector3(b[0], b[4], b[5]),
            };
            int[][] sides = { new[] { 0, 1, 2, 3 }, new[] { 4, 5, 6, 7 }, new[] { 0, 1, 5, 4 }, new[] { 2, 3, 7, 6 },
                              new[] { 1, 2, 6, 5 }, new[] { 0, 3, 7, 4 } };
            var fill = (c.r, c.g, c.bl, (float)Math.Clamp(alpha * 0.6, 0, 1));
            foreach (var sd in sides)
            {
                Put(v, p[sd[0]], Vector3.UnitZ, fill, -1e9f, 2);
                Put(v, p[sd[1]], Vector3.UnitZ, fill, -1e9f, 2);
                Put(v, p[sd[2]], Vector3.UnitZ, fill, -1e9f, 2);
                Put(v, p[sd[0]], Vector3.UnitZ, fill, -1e9f, 2);
                Put(v, p[sd[2]], Vector3.UnitZ, fill, -1e9f, 2);
                Put(v, p[sd[3]], Vector3.UnitZ, fill, -1e9f, 2);
            }
        }
        // row 411: the plan's edits still to come, faint, coloured by what they make - where the options will act
        if (_run() is { Running: true, Stage: "attempt" or "plan" or "resume" } rg)
        {
            List<SchemeModel.Planned> plan;
            lock (_model.Sync)
                plan = _model.Plan;
            foreach (var pe in plan)
            {
                if (pe.Index <= rg.AtEdit || pe.Box is not { } pb || (cut is { } pc && pb[2] > pc + 1))
                    continue;
                var colour = Generation.Category(pe.Family, pe.Shape) switch
                {
                    "digs" or "annexes" or "storeys" => (0xf5 / 255f, 0x9e / 255f, 0x0b / 255f),
                    "spans" => (0xa7 / 255f, 0x8b / 255f, 0xfa / 255f),
                    "floods" or "reliquids" => (0x38 / 255f, 0xbd / 255f, 0xf8 / 255f),
                    "windows" => (0xe5 / 255f, 0xe7 / 255f, 0xeb / 255f),
                    _ => (0x9c / 255f, 0xa3 / 255f, 0xaf / 255f),
                };
                Box(pb, colour, 0.16);
            }
        }
        foreach (var e in edits)
        {
            if (e.Box is not { } b || (cut is { } c && b[2] > c + 1))
                continue;
            var age = (now - e.Seen).TotalSeconds;
            if (e.Verdict == "ACCEPTED")
            {
                var k = e.Old ? 1 : Math.Clamp((age - 20) / 10, 0, 1);
                var col = ((float)(0x22 + (0x9a - 0x22) * k) / 255f, (float)(0xc5 + (0x6a - 0xc5) * k) / 255f,
                           (float)(0x5e + (0x3c - 0x5e) * k) / 255f);
                Box(b, col, e.Old ? 0.12 : 0.55 - 0.40 * k);
            }
            else if (!e.Old && age < 10)
                Box(b, (0xef / 255f, 0x44 / 255f, 0x44 / 255f), 0.65 * (1 - age / 10));
        }
        if (_run() is { Running: true, TryEdit: >= 0, TryBox: { } tb } g && !g.Paused)
        {
            var box = SchemeModel.Box(tb);
            for (var a = 0; a < 3; a++)
                if (box[a + 3] - box[a] < 96)
                {
                    var mid = (box[a] + box[a + 3]) / 2;
                    (box[a], box[a + 3]) = (mid - 48, mid + 48);
                }
            var blink = 0.45 + 0.55 * (0.5 + 0.5 * Math.Sin((now - g.TryAt).TotalSeconds * Math.PI * 2));
            Box(box, (0x3b / 255f, 0x82 / 255f, 0xf6 / 255f), blink);
        }
        return v;
    }

    protected override void OnSizeChanged(SizeChangedEventArgs e)
    {
        base.OnSizeChanged(e);
        RequestNextFrameRendering();
    }

    /// <summary>The last frame's own time on the CPU side (what the window waits for), in ms; frames drawn.</summary>
    public double LastFrameMs { get; private set; }
    public int Frames { get; private set; }

    protected override void OnOpenGlRender(GlInterface gl, int fb)
    {
        var t0 = System.Diagnostics.Stopwatch.GetTimestamp();
        Draw(gl, fb);
        LastFrameMs = System.Diagnostics.Stopwatch.GetElapsedTime(t0).TotalMilliseconds;
        Frames++;
    }

    /// <summary>The colour buffer's own size of the framebuffer the frame goes to, or nothing when it cannot be asked.</summary>
    private PixelSize? Surface(int fb)
    {
        if (fb == 0 || _attachIv == null || _getIv == null)
            return null;
        const int GL_FRAMEBUFFER = 0x8D40, GL_COLOR_ATTACHMENT0 = 0x8CE0, GL_OBJECT_TYPE = 0x8CD0, GL_OBJECT_NAME = 0x8CD1,
                  GL_RENDERBUFFER = 0x8D41, GL_RB_WIDTH = 0x8D42, GL_RB_HEIGHT = 0x8D43, GL_RB_BINDING = 0x8CA7,
                  GL_TEXTURE = 0x1702, GL_TEXTURE_2D = 0x0DE1, GL_TEX_BINDING = 0x8069, GL_TEX_WIDTH = 0x1000,
                  GL_TEX_HEIGHT = 0x1001;
        _attachIv(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_OBJECT_TYPE, out var type);
        _attachIv(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_OBJECT_NAME, out var name);
        int w = 0, h = 0;
        if (type == GL_RENDERBUFFER && _rbIv != null && _bindRb != null)
        {
            _getIv(GL_RB_BINDING, out var was);
            _bindRb(GL_RENDERBUFFER, name);
            _rbIv(GL_RENDERBUFFER, GL_RB_WIDTH, out w);
            _rbIv(GL_RENDERBUFFER, GL_RB_HEIGHT, out h);
            _bindRb(GL_RENDERBUFFER, was);
        }
        else if (type == GL_TEXTURE && _texIv != null && _bindTex != null)
        {
            _getIv(GL_TEX_BINDING, out var was);
            _bindTex(GL_TEXTURE_2D, name);
            _texIv(GL_TEXTURE_2D, 0, GL_TEX_WIDTH, out w);
            _texIv(GL_TEXTURE_2D, 0, GL_TEX_HEIGHT, out h);
            _bindTex(GL_TEXTURE_2D, was);
        }
        return w > 0 && h > 0 ? new PixelSize(w, h) : null;
    }

    private unsafe void Draw(GlInterface gl, int fb)
    {
        if (!Ready)
            return;
        var scale = TopLevel.GetTopLevel(this)?.RenderScaling ?? 1.0;
        var control = new PixelSize(Math.Max(1, (int)Math.Round(Bounds.Width * scale)),
                                    Math.Max(1, (int)Math.Round(Bounds.Height * scale)));
        // the frame is drawn at the size of what it is drawn ON; a surface not yet the control's size (a window just
        // made full screen) is drawn whole, and the next frame asked for at once
        var size = Surface(fb) ?? control;
        ControlSize = control;
        DrawnSize = size;
        if (size != control)
        {
            Mismatched++;
            Dispatcher.UIThread.Post(RequestNextFrameRendering, DispatcherPriority.Background);
        }
        gl.Viewport(0, 0, size.Width, size.Height);
        DrawnCamera = Camera.Copy();
        if (FrameDrawn is { } landed)
            Dispatcher.UIThread.Post(() => landed(), DispatcherPriority.Background);
        gl.ClearColor(0x16 / 255f, 0x18 / 255f, 0x1c / 255f, 1f);
        gl.ClearDepth(1);
        gl.Clear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        var s = _model.Current;
        if (s == null || s.Faces.Count == 0)
            return;
        gl.BindVertexArray(_vao);
        if (!ReferenceEquals(s, _loaded))
            Load(gl, s);
        gl.UseProgram(_program);
        var mvp = Camera.ViewProjection(size.Width, size.Height, s);
        var m = new float[16];
        for (var r = 0; r < 4; r++)
            for (var c = 0; c < 4; c++)
                m[r * 4 + c] = mvp[r, c];
        fixed (float* p = m)
            gl.UniformMatrix4fv(_uMvp, 1, false, p);
        var (eye, _, _, _) = Camera.Frame();
        var uEye3 = gl.GetProcAddress("glUniform3f");
        if (uEye3 != IntPtr.Zero)
            Marshal.GetDelegateForFunctionPointer<Uniform3f>(uEye3)(_uEye, eye.X, eye.Y, eye.Z);
        gl.Uniform1f(_uCut, Camera.Cut is { } cut ? (float)cut : 1e9f);
        gl.Enable(GL_DEPTH_TEST);
        gl.DepthFunc(GL_LEQUAL);
        gl.DepthMask(1);
        gl.BindBuffer(GL_ARRAY_BUFFER, _vbo);
        Attribs(gl);
        gl.Uniform1f(_uBias, 0);
        gl.DrawArrays(GL_TRIANGLES, 0, new IntPtr(_faceCount));
        gl.Enable(GL_BLEND);
        _blend?.Invoke(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA);
        gl.Uniform1f(_uBias, 0.0004f);
        gl.DrawArrays(GL_LINES, _edgeFirst, new IntPtr(_edgeCount));
        gl.Uniform1f(_uBias, 0);
        gl.DepthMask(0);
        gl.DrawArrays(GL_TRIANGLES, _liquidFirst, new IntPtr(_liquidCount));
        // the edits over everything, as the CPU drawing had them
        var boxes = Boxes(Camera.Cut).ToArray();
        if (boxes.Length > 0)
        {
            gl.Disable(GL_DEPTH_TEST);
            gl.BindBuffer(GL_ARRAY_BUFFER, _boxVbo);
            fixed (float* p = boxes)
                gl.BufferData(GL_ARRAY_BUFFER, new IntPtr(boxes.Length * 4), new IntPtr(p), GL_DYNAMIC_DRAW);
            Attribs(gl);
            gl.DrawArrays(GL_TRIANGLES, 0, new IntPtr(boxes.Length / Stride));
        }
        gl.DepthMask(1);
        gl.Disable(GL_BLEND);
        gl.Disable(GL_DEPTH_TEST);
        if (Captured is { } done && _read != null)
        {
            Captured = null;
            var px = new byte[size.Width * size.Height * 4];
            fixed (byte* p = px)
                _read(0, 0, size.Width, size.Height, GL_RGBA, GL_UNSIGNED_BYTE, new IntPtr(p));
            done(size.Width, size.Height, px);
        }
    }

    [UnmanagedFunctionPointer(CallingConvention.StdCall)]
    private delegate void Uniform3f(int location, float x, float y, float z);
}

/// <summary>
/// What is drawn over the card's picture each beat - cheap, a hundred marks and a few lines of text: the pickups and
/// spawns at their places, the edit being tried pinned and named, the last events in the corner.
/// </summary>
public sealed class SchemeOverlay : Control
{
    private readonly SchemeModel _model;
    private readonly Func<Generation?> _run;
    private readonly SchemeCamera _live;
    /// <summary>The camera of the frame under the marks (the card's last drawn one); the live one when none.</summary>
    public Func<SchemeCamera?>? Under { get; set; }

    /// <summary>Where the events' list starts from the top: under the run's lines on the full screen.</summary>
    public double FeedTop { get; set; } = 10;

    public SchemeOverlay(SchemeModel model, Func<Generation?> run, SchemeCamera camera)
    {
        _model = model;
        _run = run;
        _live = camera;
        IsHitTestVisible = false;
    }

    private static string Kind(string family) => Loc.Has($"kind.{family}") ? Loc.T($"kind.{family}") : family;

    public override void Render(DrawingContext ctx)
    {
        var s = _model.Current;
        if (s == null)
        {
            ctx.DrawText(new FormattedText(Loc.T("scheme.wait"), CultureInfo.CurrentUICulture, FlowDirection.LeftToRight,
                                           Typeface.Default, 14, Brushes.Gray), new Point(16, 16));
            return;
        }
        var size = Bounds.Size;
        var _camera = Under?.Invoke() ?? _live;
        foreach (var (what, at) in s.Marks)
        {
            if (_camera.Cut is { } c && at.Z > c + 64)
                continue;
            if (_camera.Project(at, size) is { } p)
                Mark(ctx, what, p);
        }
        var now = DateTime.Now;
        var feed = new List<(IBrush dot, string text)>();
        var run = _run();
        if (run is { Running: true, Stage: "light" } lr && lr.LightNow() is { Length: > 0 } step)
            feed.Add((new SolidColorBrush(Color.FromRgb(0xfb, 0xbf, 0x24)), Loc.F("scheme.light", step)));
        else if (s.Lit && run is not { Stage: "attempt" or "plan" or "baseline" or "resume" })
            feed.Add((new SolidColorBrush(Color.FromRgb(0xfb, 0xbf, 0x24)), Loc.T("scheme.lit")));
        if (run is { Running: true, TryEdit: >= 0 } g && !g.Paused)
        {
            var since = now - g.TryAt;
            var label = $"{Kind(g.TryFamily)} — {Loc.T("scheme.trying")} {(int)since.TotalMinutes}:{since.Seconds:00}";
            if (g.TryBox is { } tb)
            {
                var b = SchemeModel.Box(tb);
                var top = new Vector3((b[0] + b[3]) / 2, (b[1] + b[4]) / 2, b[5]);
                if (_camera.Project(top, size) is { } foot && _camera.Project(top + new Vector3(0, 0, 420), size) is { } head)
                {
                    var blue = new SolidColorBrush(Color.FromRgb(0x60, 0xa5, 0xfa));
                    ctx.DrawLine(new Pen(blue, 2), foot, head);
                    ctx.DrawEllipse(null, new Pen(blue, 2), head, 4, 4);
                    var t = new FormattedText(label, CultureInfo.CurrentUICulture, FlowDirection.LeftToRight, Typeface.Default, 15, Brushes.White);
                    ctx.FillRectangle(new SolidColorBrush(Color.FromArgb(0xd0, 0x1e, 0x3a, 0x8a)),
                                      new Rect(head.X + 8, head.Y - 13, t.Width + 12, t.Height + 4), 4);
                    ctx.DrawText(t, new Point(head.X + 14, head.Y - 11));
                }
            }
            feed.Add((new SolidColorBrush(Color.FromRgb(0x60, 0xa5, 0xfa)), $"{Loc.T("scheme.trying")}: {Kind(g.TryFamily)}  {(int)since.TotalMinutes}:{since.Seconds:00}"));
        }
        List<SchemeModel.Edit> edits;
        lock (_model.Sync)
            edits = _model.Edits.Where(x => !x.Old && x.Verdict != "REJECTED_NOT_APPLIED").Reverse().Take(7).ToList();
        // row 411: the edits and the run's own events (each stage begun, each step of the light) by time, newest first
        var timeline = edits.Select(e =>
        {
            var ok = e.Verdict == "ACCEPTED";
            return (when: e.Seen, dot: (IBrush)new SolidColorBrush(ok ? Color.FromRgb(0x4a, 0xde, 0x80) : Color.FromRgb(0xf8, 0x71, 0x71)),
                    text: $"{Loc.T(ok ? "verdict.accepted" : "verdict.rejected")}: {Kind(e.Family)}  {e.Seen:HH:mm:ss}");
        }).Concat((run?.Events() ?? new()).Select(x => (when: x.when, dot: (IBrush)new SolidColorBrush(Color.FromRgb(0xc4, 0xb5, 0xfd)),
                                                        text: $"{x.what}  {x.when:HH:mm:ss}")))
          .OrderByDescending(x => x.when).Take(7);
        foreach (var x in timeline)
            feed.Add((x.dot, x.text));
        if (feed.Count > 0)
        {
            var texts = feed.Select(f => new FormattedText(f.text, CultureInfo.CurrentUICulture, FlowDirection.LeftToRight,
                                                           Typeface.Default, 14, Brushes.White)).ToList();
            var y0 = FeedTop;
            ctx.FillRectangle(new SolidColorBrush(Color.FromArgb(0x90, 0, 0, 0)),
                              new Rect(10, y0, 46 + texts.Max(t => t.Width), 14 + 22 * texts.Count), 6);
            for (var i = 0; i < texts.Count; i++)
            {
                ctx.DrawEllipse(feed[i].dot, null, new Point(26, y0 + 18 + 22 * i), 5, 5);
                ctx.DrawText(texts[i], new Point(40, y0 + 9 + 22 * i));
            }
        }
    }

    private static void Mark(DrawingContext ctx, string what, Point p)
    {
        switch (what)
        {
            case "weapon":
                Poly(ctx, Color.FromRgb(0xfa, 0xcc, 0x15), p, (0, -7), (7, 6), (-7, 6));
                break;
            case "armor":
                Poly(ctx, Color.FromRgb(0x22, 0xd3, 0xee), p, (0, -7), (7, 0), (0, 7), (-7, 0));
                break;
            case "health":
            case "mega":
                var w = what == "mega" ? 3.5 : 2.5;
                ctx.FillRectangle(Brushes.White, new Rect(p.X - w, p.Y - 7, 2 * w, 14));
                ctx.FillRectangle(Brushes.White, new Rect(p.X - 7, p.Y - w, 14, 2 * w));
                break;
            case "ammo":
                ctx.DrawEllipse(new SolidColorBrush(Color.FromRgb(0xa8, 0xa2, 0x9e)), null, p, 3, 3);
                break;
            case "power":
                ctx.DrawEllipse(new SolidColorBrush(Color.FromRgb(0xd9, 0x46, 0xef)), new Pen(Brushes.White, 1.2), p, 7, 7);
                break;
            case "spawn":
                ctx.DrawEllipse(null, new Pen(Brushes.White, 2), p, 7, 7);
                ctx.DrawEllipse(Brushes.White, null, p, 2.5, 2.5);
                break;
            case "teleport":
                ctx.DrawEllipse(null, new Pen(new SolidColorBrush(Color.FromRgb(0xf4, 0x72, 0xb6)), 2.5), p, 8, 8);
                break;
        }
    }

    private static void Poly(DrawingContext ctx, Color color, Point p, params (double x, double y)[] pts)
    {
        var g = new StreamGeometry();
        using (var c = g.Open())
        {
            c.BeginFigure(new Point(p.X + pts[0].x, p.Y + pts[0].y), true);
            foreach (var (x, y) in pts.Skip(1))
                c.LineTo(new Point(p.X + x, p.Y + y));
            c.EndFigure(true);
        }
        ctx.DrawGeometry(new SolidColorBrush(color), new Pen(Brushes.Black, 1), g);
    }
}

/// <summary>
/// The plan as shown: the card's picture with the overlay over it, or the CPU's drawing when the card cannot be used;
/// the mouse turns, moves and zooms the one camera both share. What the panel and the full screen hold.
/// </summary>
public sealed class SchemeHost : Panel
{
    public readonly SchemeCamera Camera = new();
    private readonly SchemeModel _model;
    private readonly Func<Generation?> _run;
    private readonly SchemeGlView _gl;
    private readonly SchemeOverlay _overlay;
    private SchemeView? _cpu;
    private readonly DispatcherTimer _timer;
    private SchemeModel.Snapshot? _fitted;
    private Point? _drag;
    private bool _panning;

    public SchemeGlView Gl => _gl;

    /// <summary>Where the events' list starts (the full screen puts it under its own lines).</summary>
    public double FeedTop
    {
        get => _overlay.FeedTop;
        set
        {
            if (Math.Abs(_overlay.FeedTop - value) > 0.5)
                _overlay.FeedTop = value;
        }
    }
    public bool OnCard => _cpu == null;

    public double? Cut
    {
        get => Camera.Cut;
        set
        {
            Camera.Cut = value;
            if (_cpu != null)
                _cpu.Cut = value;
        }
    }

    public SchemeHost(SchemeModel model, Func<Generation?> run)
    {
        _model = model;
        _run = run;
        ClipToBounds = true;
        Background = new SolidColorBrush(Color.FromRgb(0x16, 0x18, 0x1c));
        _gl = new SchemeGlView(model, run, Camera);
        _overlay = new SchemeOverlay(model, run, Camera);
        Children.Add(_gl);
        Children.Add(_overlay);
        _overlay.Under = () => OnCard ? _gl.DrawnCamera : null;
        _gl.FrameDrawn += () => _overlay.InvalidateVisual();
        _timer = new DispatcherTimer { Interval = TimeSpan.FromMilliseconds(100) };
        _timer.Tick += (_, _) => Beat();
        AttachedToVisualTree += (_, _) => _timer.Start();
        DetachedFromVisualTree += (_, _) => _timer.Stop();
        PointerWheelChanged += (_, e) =>
        {
            Camera.Dist = Math.Clamp(Camera.Dist * (e.Delta.Y > 0 ? 1 / 1.15f : 1.15f), 100, 100000);
            e.Handled = true;
            Beat();
        };
        PointerPressed += (_, e) =>
        {
            if (e.ClickCount == 2)
            {
                Top();
                return;
            }
            var pt = e.GetCurrentPoint(this);
            _panning = pt.Properties.IsRightButtonPressed || pt.Properties.IsMiddleButtonPressed;
            _drag = pt.Position;
            e.Pointer.Capture(this);
        };
        PointerMoved += (_, e) =>
        {
            if (_drag is not { } from)
                return;
            var p = e.GetPosition(this);
            var dx = (float)(p.X - from.X);
            var dy = (float)(p.Y - from.Y);
            _drag = p;
            if (_panning)
            {
                var (_, right, up, _) = Camera.Frame();
                var k = Camera.Dist / Camera.Focal(Bounds.Height);
                Camera.Target += (-right * dx + up * dy) * k;
            }
            else
            {
                Camera.Yaw -= dx * 0.4f;
                Camera.Pitch = Math.Clamp(Camera.Pitch + dy * 0.4f, 5, 89.5f);
            }
            Beat();
        };
        PointerReleased += (_, e) =>
        {
            _drag = null;
            e.Pointer.Capture(null);
        };
    }

    /// <summary>One frame: the card asked to draw again, the overlay redrawn; the CPU's drawing if the card failed.</summary>
    private void Beat()
    {
        if (_model.Current is { } s && _fitted == null)
        {
            _fitted = s;
            Camera.Fit(s);
        }
        if (_cpu == null && _gl.Failed)
        {
            // the card could not be used: the CPU's drawing in its place (slower, the same picture)
            _cpu = new SchemeView(_model, _run) { Cut = Camera.Cut };
            Children.Clear();
            Children.Add(_cpu);
        }
        if (_cpu != null)
        {
            _cpu.InvalidateVisual();
            return;
        }
        _gl.RequestNextFrameRendering();
        _overlay.InvalidateVisual();
    }

    public void Top()
    {
        Camera.Yaw = -90;
        Camera.Pitch = 89;
        if (_model.Current is { } s)
            Camera.Fit(s);
        _cpu?.Top();
        Beat();
    }

    public void Slant()
    {
        Camera.Yaw = -125;
        Camera.Pitch = 40;
        if (_model.Current is { } s)
            Camera.Fit(s);
        _cpu?.Slant();
        Beat();
    }
}
