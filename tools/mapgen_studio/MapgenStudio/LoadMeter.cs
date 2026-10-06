using System.Runtime.InteropServices;
using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;
using Avalonia.Media;

namespace MapgenStudio;

/// <summary>
/// The machine's load beside the run (ledger row 410; the PO, 05.10, after YuE2 Studio's card: «индикаторы загрузки
/// CPU/RAM»): the processor and the memory of the whole computer, and what the generation itself takes of each - its
/// job's processes. A card of rows, a label, a value and a bar each; sampled on the window's beat.
/// </summary>
public sealed class LoadMeter : Border
{
    private readonly (TextBlock value, ProgressBar bar) _cpu, _ram, _gpu, _vram, _genCpu, _genRam;
    private ulong _idle, _kernel, _user;
    private long _jobCpu = -1;
    private DateTime _jobAt;
    private Generation? _jobOf;

    public LoadMeter(bool overlay = false)
    {
        CornerRadius = new CornerRadius(10);
        Padding = new Thickness(16, 12, 16, 12);
        Background = new SolidColorBrush(Color.FromArgb(overlay ? (byte)150 : (byte)255, 0x20, 0x22, 0x27));
        BorderBrush = new SolidColorBrush(Color.FromArgb(60, 0xff, 0xff, 0xff));
        BorderThickness = new Thickness(1);
        Width = 280;
        var rows = new StackPanel { Spacing = 2 };
        rows.Children.Add(new TextBlock { Text = Loc.T("load.title"), FontWeight = FontWeight.SemiBold, FontSize = 14,
                                          Margin = new Thickness(0, 0, 0, 6) });
        _cpu = Row(rows, Loc.T("load.cpu"));
        _ram = Row(rows, Loc.T("load.ram"));
        // the PO 05.10: the graphics card too, its load and its memory (GpuStats: Windows' own counters, any maker)
        _gpu = Row(rows, Loc.T("load.gpu"));
        _vram = Row(rows, Loc.T("load.vram"));
        GpuStats.Start();
        _genCpu = Row(rows, Loc.T("load.gen.cpu"));
        _genRam = Row(rows, Loc.T("load.gen.ram"));
        Child = rows;
        SampleMachine();      // the first sample is the base of the next
    }

    private static (TextBlock, ProgressBar) Row(StackPanel rows, string label)
    {
        var name = new TextBlock { Text = label, FontSize = 13, Opacity = 0.8 };
        var value = new TextBlock { FontSize = 13, FontWeight = FontWeight.SemiBold, HorizontalAlignment = HorizontalAlignment.Right };
        var head = new Grid { ColumnDefinitions = new ColumnDefinitions("*,Auto"), Margin = new Thickness(0, 6, 0, 2) };
        head.Children.Add(name);
        Grid.SetColumn(value, 1);
        head.Children.Add(value);
        var bar = new ProgressBar { Minimum = 0, Maximum = 100, Height = 6, MinHeight = 6, CornerRadius = new CornerRadius(3),
                                    Foreground = new SolidColorBrush(Color.FromRgb(0x22, 0xc5, 0x5e)) };
        rows.Children.Add(head);
        rows.Children.Add(bar);
        return (value, bar);
    }

    /// <summary>One beat: the machine since the last one, the run's job since its last one.</summary>
    public void Update(Generation? g)
    {
        var cpu = SampleMachine();
        if (cpu >= 0)
            Set(_cpu, cpu, $"{cpu:0}%");
        var mem = new MEMORYSTATUSEX { dwLength = (uint)Marshal.SizeOf<MEMORYSTATUSEX>() };
        double total = 0;
        if (GlobalMemoryStatusEx(ref mem))
        {
            total = mem.ullTotalPhys;
            var used = mem.ullTotalPhys - mem.ullAvailPhys;
            Set(_ram, 100.0 * used / total, $"{Gb(used)} / {Gb(mem.ullTotalPhys)} GB");
        }
        if (GpuStats.Percent >= 0)
            Set(_gpu, GpuStats.Percent, $"{GpuStats.Percent:0}%");
        else
            Set(_gpu, 0, "—");
        if (GpuStats.VramTotal > 0)
            Set(_vram, 100.0 * GpuStats.VramUsed / GpuStats.VramTotal, $"{Gb(GpuStats.VramUsed)} / {Gb(GpuStats.VramTotal)} GB");
        else
            Set(_vram, 0, GpuStats.VramUsed > 0 ? $"{Gb(GpuStats.VramUsed)} GB" : "—");
        if (g is not { Running: true })
        {
            Set(_genCpu, 0, "—");
            Set(_genRam, 0, "—");
            _jobCpu = -1;
            return;
        }
        // the job's CPU time against the wall clock and every logical CPU: its share of the whole machine
        var now = DateTime.Now;
        var t = g.CpuTime();
        if (!ReferenceEquals(g, _jobOf) || t < _jobCpu)
            _jobCpu = -1;
        if (_jobCpu >= 0 && t >= 0)
        {
            var wall = (now - _jobAt).TotalSeconds;
            if (wall > 0.05)
            {
                var share = (t - _jobCpu) / 1e7 / wall / Environment.ProcessorCount * 100;
                Set(_genCpu, share, $"{share:0}%");
            }
        }
        _jobOf = g;
        _jobCpu = t;
        _jobAt = now;
        var bytes = g.MemoryBytes();
        Set(_genRam, total > 0 ? 100.0 * bytes / total : 0, $"{Gb((ulong)bytes)} GB");
    }

    private static string Gb(ulong bytes) => (bytes / 1073741824.0).ToString("0.0");

    private static void Set((TextBlock value, ProgressBar bar) row, double percent, string text)
    {
        row.value.Text = text;
        row.bar.Value = Math.Clamp(percent, 0, 100);
        row.bar.Foreground = new SolidColorBrush(percent > 85 ? Color.FromRgb(0xef, 0x44, 0x44)
                                               : percent > 60 ? Color.FromRgb(0xf5, 0x9e, 0x0b)
                                               : Color.FromRgb(0x22, 0xc5, 0x5e));
    }

    /// <summary>The whole machine's busy share since the last call, in percent; -1 the first time.</summary>
    private double SampleMachine()
    {
        if (!GetSystemTimes(out var idle, out var kernel, out var user))
            return -1;
        var (i, k, u) = (idle.Value, kernel.Value, user.Value);
        double result = -1;
        if (_kernel != 0)
        {
            var di = i - _idle;
            var total = (k - _kernel) + (u - _user);       // kernel time includes idle
            if (total > 0)
                result = 100.0 * (total - di) / total;
        }
        (_idle, _kernel, _user) = (i, k, u);
        return result;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct FILETIME64
    {
        public uint Low, High;
        public ulong Value => ((ulong)High << 32) | Low;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MEMORYSTATUSEX
    {
        public uint dwLength, dwMemoryLoad;
        public ulong ullTotalPhys, ullAvailPhys, ullTotalPageFile, ullAvailPageFile, ullTotalVirtual, ullAvailVirtual,
                     ullAvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetSystemTimes(out FILETIME64 idle, out FILETIME64 kernel, out FILETIME64 user);

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MEMORYSTATUSEX buffer);
}
