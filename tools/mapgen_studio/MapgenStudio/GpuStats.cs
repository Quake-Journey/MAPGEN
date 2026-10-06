using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace MapgenStudio;

/// <summary>
/// The graphics card's load for the load card (the PO, 05.10: «загрузку видеокарты GPU добавь - сколько процентов и
/// сколько vram ... и ватты видеокарты ... работать должно и на Nvidia и на AMD и на Intel»).
///
/// The share and the memory come from Windows itself - the «GPU Engine» and «GPU Adapter Memory» counters every
/// WDDM driver feeds, NVIDIA's, AMD's and Intel's alike - read the way the Task Manager reads them: per card and
/// kind of engine the processes' shares summed, the busiest kind the card's load; its dedicated memory in use against
/// the card's own (the display driver's registry entry). No watts: Windows does not say them, and the makers' own
/// libraries differ per maker (the PO: «если по ваттам сложно то не нужно»).
///
/// Sampled once a second on a thread of its own - never on the window's.
/// </summary>
public static class GpuStats
{
    public static double Percent { get; private set; } = -1;
    public static ulong VramUsed { get; private set; }
    public static ulong VramTotal { get; private set; }
    public static string Name { get; private set; } = "";

    private static Thread? _thread;
    private static readonly object Gate = new();

    /// <summary>Starts the sampler once; later calls do nothing.</summary>
    public static void Start()
    {
        lock (Gate)
        {
            if (_thread != null || !OperatingSystem.IsWindows())
                return;
            _thread = new Thread(Loop) { IsBackground = true, Name = "gpu-stats", Priority = ThreadPriority.BelowNormal };
            _thread.Start();
        }
    }

    private static void Loop()
    {
        try
        {
            (VramTotal, Name) = CardMemory();
        }
        catch (Exception)
        {
        }
        IntPtr query = IntPtr.Zero, engines = IntPtr.Zero, memory = IntPtr.Zero;
        try
        {
            if (PdhOpenQueryW(null, IntPtr.Zero, out query) != 0)
                return;
            PdhAddEnglishCounterW(query, @"\GPU Engine(*)\Utilization Percentage", IntPtr.Zero, out engines);
            PdhAddEnglishCounterW(query, @"\GPU Adapter Memory(*)\Dedicated Usage", IntPtr.Zero, out memory);
            PdhCollectQueryData(query);
            while (true)
            {
                Thread.Sleep(1000);
                if (PdhCollectQueryData(query) != 0)
                    continue;
                // per card and kind of engine, the processes summed; the busiest kind is the card's load
                var kinds = new Dictionary<string, double>();
                foreach (var (instance, value) in Read(engines))
                {
                    var luid = Part(instance, "luid_", "_phys");
                    var kind = instance[(instance.LastIndexOf("engtype_", StringComparison.Ordinal) + 8)..];
                    var key = luid + "|" + kind;
                    kinds[key] = kinds.GetValueOrDefault(key) + value;
                }
                Percent = kinds.Count > 0 ? Math.Min(100, kinds.Values.Max()) : -1;
                var used = Read(memory).Select(x => x.value).DefaultIfEmpty(0).Max();
                VramUsed = (ulong)Math.Max(0, used);
            }
        }
        catch (Exception)
        {
            Percent = -1;
        }
        finally
        {
            if (query != IntPtr.Zero)
                PdhCloseQuery(query);
        }
    }

    private static string Part(string s, string from, string to)
    {
        var a = s.IndexOf(from, StringComparison.Ordinal);
        if (a < 0)
            return "";
        a += from.Length;
        var b = s.IndexOf(to, a, StringComparison.Ordinal);
        return b > a ? s[a..b] : s[a..];
    }

    /// <summary>The largest display adapter's own memory and name, from the display drivers' registry entries.</summary>
    private static (ulong, string) CardMemory()
    {
        ulong best = 0;
        var name = "";
        using var cls = Registry.LocalMachine.OpenSubKey(
            @"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}");
        if (cls == null)
            return (0, "");
        foreach (var sub in cls.GetSubKeyNames().Where(n => n.All(char.IsDigit)))
        {
            using var k = cls.OpenSubKey(sub);
            var v = k?.GetValue("HardwareInformation.qwMemorySize");
            var size = v switch
            {
                long l => (ulong)l,
                byte[] b when b.Length >= 8 => BitConverter.ToUInt64(b, 0),
                byte[] b when b.Length >= 4 => BitConverter.ToUInt32(b, 0),
                int i => (uint)i,
                _ => 0UL,
            };
            if (size > best)
            {
                best = size;
                name = k?.GetValue("DriverDesc") as string ?? "";
            }
        }
        return (best, name);
    }

    private static List<(string instance, double value)> Read(IntPtr counter)
    {
        var list = new List<(string, double)>();
        if (counter == IntPtr.Zero)
            return list;
        uint size = 0, count = 0;
        const uint PDH_FMT_DOUBLE = 0x200, PDH_MORE_DATA = 0x800007D2;
        if (PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ref size, out count, IntPtr.Zero) != PDH_MORE_DATA)
            return list;
        var buffer = Marshal.AllocHGlobal((int)size);
        try
        {
            if (PdhGetFormattedCounterArrayW(counter, PDH_FMT_DOUBLE, ref size, out count, buffer) != 0)
                return list;
            var item = Marshal.SizeOf<PDH_FMT_COUNTERVALUE_ITEM_W>();
            for (var i = 0; i < count; i++)
            {
                var it = Marshal.PtrToStructure<PDH_FMT_COUNTERVALUE_ITEM_W>(buffer + i * item);
                if (it.CStatus == 0 || it.CStatus == 1)
                    list.Add((Marshal.PtrToStringUni(it.szName) ?? "", it.doubleValue));
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
        return list;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PDH_FMT_COUNTERVALUE_ITEM_W
    {
        public IntPtr szName;
        public uint CStatus;
        private uint _pad;
        public double doubleValue;
    }

    [DllImport("pdh.dll", CharSet = CharSet.Unicode)]
    private static extern uint PdhOpenQueryW(string? source, IntPtr user, out IntPtr query);

    [DllImport("pdh.dll", CharSet = CharSet.Unicode)]
    private static extern uint PdhAddEnglishCounterW(IntPtr query, string path, IntPtr user, out IntPtr counter);

    [DllImport("pdh.dll")]
    private static extern uint PdhCollectQueryData(IntPtr query);

    [DllImport("pdh.dll", CharSet = CharSet.Unicode)]
    private static extern uint PdhGetFormattedCounterArrayW(IntPtr counter, uint format, ref uint size, out uint count,
                                                           IntPtr items);

    [DllImport("pdh.dll")]
    private static extern uint PdhCloseQuery(IntPtr query);
}
