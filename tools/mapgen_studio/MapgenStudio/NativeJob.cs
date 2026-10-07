using System.Runtime.InteropServices;
using System.Text;

namespace MapgenStudio;

/// <summary>
/// The generator runs as its own process inside a Windows job object (R5, R6, R7): the job holds it and every
/// compiler it spawns, so the CPU share and the priority apply to all of them, pause suspends all of them, stop ends
/// all of them, and closing the Studio ends them too (kill-on-close). The process is created suspended and put in the
/// job before its first instruction, so no child can start outside it.
/// </summary>
public sealed class NativeJob : IDisposable
{
    private IntPtr _job;
    public int ProcessId { get; private set; }
    private IntPtr _process;

    public NativeJob()
    {
        _job = CreateJobObjectW(IntPtr.Zero, null);
        if (_job == IntPtr.Zero)
            throw new InvalidOperationException("CreateJobObject failed: " + Marshal.GetLastWin32Error());
    }

    /// <summary>
    /// Limits for every process in the job: <paramref name="cpus"/> logical CPUs - performance cores only - and the
    /// priority.
    /// </summary>
    public void Limit(int cpus, string priority)
    {
        cpus = Math.Clamp(cpus, 1, Math.Min(Environment.ProcessorCount, 64));
        var info = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_AFFINITY | JOB_OBJECT_LIMIT_PRIORITY_CLASS
                                                | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        info.BasicLimitInformation.Affinity = (UIntPtr)Mask(cpus);
        info.BasicLimitInformation.PriorityClass = priority switch
        {
            "idle" => IDLE_PRIORITY_CLASS,
            "normal" => NORMAL_PRIORITY_CLASS,
            _ => BELOW_NORMAL_PRIORITY_CLASS,
        };
        if (!SetInformationJobObject(_job, JobObjectExtendedLimitInformation, ref info,
                                     (uint)Marshal.SizeOf<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>()))
            throw new InvalidOperationException("SetInformationJobObject failed: " + Marshal.GetLastWin32Error());
    }

    /*
     * Row 404, the PO (2026-10-03): «у меня в моем процессоре есть P-ядра, а есть E-ядра и нет никакого смысла
     * использовать 8 ядер в миксе, для моего проца нужны только P-ядра». The share was the LOW bits: 60 % of his 32
     * is 19, his P-core threads are 0-15, so three E-cores came with every daytime run. The mask is the performance
     * class's logical CPUs, lowest first, as many as the share allows and never more than there are: 16 by day,
     * 9 at night on his machine. A machine that is not hybrid has one class, and the mask is the low bits as before.
     */
    /*
     * Row 410, the PO (2026-10-04): «опять у меня vs code вешается когда ты генератор запускаешь». The share was of
     * ALL logical CPUs (19 of 32 by day) and then taken from the P-cores, of which there are 16: every P-core went to
     * the run and his editor was left the E-cores. The share is now of the performance class itself - 9 of 16 by day,
     * 4 at night - so the fast cores he works on are never all taken.
     */
    /*
     * Brief 12 (07.10): the PO's i9-14900KF - generator crashes (the CPU executing at its own branch target with bit 31
     * set) and, in the System log, 37 corrected machine checks of the processor core (internal parity and TLB errors)
     * at APIC 0, 1, 32, 33, 41 in 30 days. The cores WHEA-Logger names (events of the last 30 days) are left out of the
     * mask, both threads of each; read once a day into %LOCALAPPDATA%\mapgen_faulty_cpus.json - the same file the
     * map checks' load guard (tools/mapgen_load_guard.py, faulty_cpus) reads and writes. On Intel's hybrid parts a
     * P-core's APIC IDs are 8 apart and its threads the logical CPUs 2k and 2k+1; elsewhere the APIC ID is the index.
     */
    public static HashSet<int> FaultyCpus(List<int> fast)
    {
        var cache = Path.Combine(Environment.GetEnvironmentVariable("LOCALAPPDATA") ?? Path.GetTempPath(),
                                 "mapgen_faulty_cpus.json");
        try
        {
            if (File.Exists(cache) && (DateTime.Now - File.GetLastWriteTime(cache)).TotalHours < 24)
            {
                var m = System.Text.RegularExpressions.Regex.Match(File.ReadAllText(cache), "\"cpus\"\\s*:\\s*\\[([^\\]]*)\\]");
                if (m.Success)
                    return m.Groups[1].Value.Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries)
                        .Select(int.Parse).ToHashSet();
            }
        }
        catch (Exception)
        {
            // an unreadable cache is read again from the log below
        }
        var apics = new HashSet<int>();
        try
        {
            var ps = "Get-WinEvent -FilterHashtable @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; " +
                     "StartTime=(Get-Date).AddDays(-30)} -ErrorAction SilentlyContinue | ForEach-Object { $_.Message }";
            var si = new System.Diagnostics.ProcessStartInfo("powershell", new[] { "-NoProfile", "-NonInteractive", "-Command", ps })
            {
                RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true,
                StandardOutputEncoding = Encoding.UTF8,
            };
            using var proc = System.Diagnostics.Process.Start(si);
            if (proc == null)
                return new HashSet<int>();
            var read = proc.StandardOutput.ReadToEndAsync();
            if (!proc.WaitForExit(60000))
            {
                try { proc.Kill(); } catch (Exception) { }
                return new HashSet<int>();
            }
            foreach (System.Text.RegularExpressions.Match m in
                     System.Text.RegularExpressions.Regex.Matches(read.Result, "APIC[^:\\n]*:\\s*(\\d+)"))
                apics.Add(int.Parse(m.Groups[1].Value));
        }
        catch (Exception)
        {
            return new HashSet<int>();
        }
        var hybrid = fast.Count > 0 && fast.Count < Environment.ProcessorCount;
        var cpus = new HashSet<int>();
        foreach (var a in apics)
            if (hybrid && a < 64)
            {
                cpus.Add(2 * (a / 8));
                cpus.Add(2 * (a / 8) + 1);
            }
            else
                cpus.Add(a);
        try
        {
            File.WriteAllText(cache, "{\"cpus\": [" + string.Join(", ", cpus.OrderBy(x => x)) + "], \"apic\": ["
                                     + string.Join(", ", apics.OrderBy(x => x)) + "], \"days\": 30}");
        }
        catch (Exception)
        {
            // no cache: read again next time
        }
        return cpus;
    }

    public static ulong Mask(int cpus)
    {
        var fast = PerformanceCpus();
        if (fast.Count == 0)
            return cpus >= 64 ? ulong.MaxValue : (1UL << cpus) - 1UL;
        var take = Math.Max(1, (int)Math.Floor((double)cpus * fast.Count / Math.Max(1, Environment.ProcessorCount)));
        // brief 12: never a core the machine itself reported for hardware errors (the next ones instead)
        var bad = FaultyCpus(fast);
        var usable = fast.Where(i => !bad.Contains(i)).ToList();
        if (usable.Count == 0)
            usable = fast;
        ulong mask = 0;
        foreach (var i in usable.Take(take))
            mask |= 1UL << i;
        return mask;
    }

    /// <summary>The logical CPUs (group 0) of the highest efficiency class, ascending; empty when it cannot be read.</summary>
    public static List<int> PerformanceCpus()
    {
        var list = new List<(int index, int cls)>();
        try
        {
            GetSystemCpuSetInformation(IntPtr.Zero, 0, out var need, IntPtr.Zero, 0);
            if (need == 0)
                return new List<int>();
            var buf = Marshal.AllocHGlobal((int)need);
            try
            {
                if (!GetSystemCpuSetInformation(buf, need, out var got, IntPtr.Zero, 0))
                    return new List<int>();
                // SYSTEM_CPU_SET_INFORMATION: Size, Type, then Id, Group, LogicalProcessorIndex, CoreIndex,
                // LastLevelCacheIndex, NumaNodeIndex, EfficiencyClass at 8, 12, 14, 15, 16, 17, 18
                for (uint at = 0; at + 19 <= got;)
                {
                    var size = (uint)Marshal.ReadInt32(buf, (int)at);
                    if (size == 0)
                        break;
                    if (Marshal.ReadInt32(buf, (int)at + 4) == 0 && Marshal.ReadInt16(buf, (int)at + 12) == 0)
                        list.Add((Marshal.ReadByte(buf, (int)at + 14), Marshal.ReadByte(buf, (int)at + 18)));
                    at += size;
                }
            }
            finally
            {
                Marshal.FreeHGlobal(buf);
            }
        }
        catch (Exception e) when (e is EntryPointNotFoundException or DllNotFoundException)
        {
            return new List<int>();
        }
        if (list.Count == 0)
            return new List<int>();
        var top = list.Max(x => x.cls);
        return list.Where(x => x.cls == top && x.index < 64).Select(x => x.index).OrderBy(x => x).ToList();
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GetSystemCpuSetInformation(IntPtr information, uint bufferLength, out uint returnedLength,
                                                          IntPtr process, uint flags);

    /// <summary>Start <paramref name="exe"/> with <paramref name="args"/> suspended, in the job, then let it run.</summary>
    public void Start(string exe, IEnumerable<string> args, string workDir)
    {
        var cmd = new StringBuilder(Quote(exe));
        foreach (var a in args)
            cmd.Append(' ').Append(Quote(a));
        var si = new STARTUPINFOW { cb = Marshal.SizeOf<STARTUPINFOW>() };
        if (!CreateProcessW(null, cmd, IntPtr.Zero, IntPtr.Zero, false, CREATE_SUSPENDED | CREATE_NO_WINDOW,
                            IntPtr.Zero, workDir, ref si, out var pi))
            throw new InvalidOperationException("CreateProcess failed: " + Marshal.GetLastWin32Error());
        if (!AssignProcessToJobObject(_job, pi.hProcess))
        {
            TerminateProcess(pi.hProcess, 1);
            throw new InvalidOperationException("AssignProcessToJobObject failed: " + Marshal.GetLastWin32Error());
        }
        ResumeThread(pi.hThread);
        CloseHandle(pi.hThread);
        _process = pi.hProcess;
        ProcessId = pi.dwProcessId;
    }

    /// <summary>The main process has ended; its exit code (0x103 while it runs).</summary>
    public bool Exited(out uint code)
    {
        code = 0;
        if (_process == IntPtr.Zero || !GetExitCodeProcess(_process, out code))
            return true;
        return code != STILL_ACTIVE;
    }

    /// <summary>Every process in the job now.</summary>
    public List<int> Processes()
    {
        var ids = new List<int>();
        const int max = 256;
        var size = 8 + IntPtr.Size * max;
        var buf = Marshal.AllocHGlobal(size);
        try
        {
            if (QueryInformationJobObject(_job, JobObjectBasicProcessIdList, buf, (uint)size, IntPtr.Zero))
            {
                var n = Marshal.ReadInt32(buf, 4);
                for (var i = 0; i < n && i < max; i++)
                    ids.Add((int)Marshal.ReadIntPtr(buf, 8 + i * IntPtr.Size));
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buf);
        }
        return ids;
    }

    /// <summary>Suspend (pause) or resume every process in the job.</summary>
    public void Suspend(bool suspend)
    {
        foreach (var id in Processes())
        {
            var h = OpenProcess(PROCESS_SUSPEND_RESUME, false, id);
            if (h == IntPtr.Zero)
                continue;
            if (suspend)
                NtSuspendProcess(h);
            else
                NtResumeProcess(h);
            CloseHandle(h);
        }
    }

    /// <summary>CPU time of every process in the job, in 100 ns units - what a pause must hold still.</summary>
    /// <summary>Row 410: the memory the job's processes hold now (their working sets), in bytes.</summary>
    public long MemoryBytes()
    {
        long sum = 0;
        foreach (var id in Processes())
        {
            try
            {
                using var p = System.Diagnostics.Process.GetProcessById(id);
                sum += p.WorkingSet64;
            }
            catch (Exception)
            {
                // ended between the list and the look
            }
        }
        return sum;
    }

    public long CpuTime()
    {
        var info = new JOBOBJECT_BASIC_ACCOUNTING_INFORMATION();
        return QueryInformationJobObject(_job, JobObjectBasicAccountingInformation, ref info,
                                         (uint)Marshal.SizeOf<JOBOBJECT_BASIC_ACCOUNTING_INFORMATION>(), IntPtr.Zero)
            ? info.TotalUserTime + info.TotalKernelTime : -1;
    }

    /// <summary>
    /// Every process of the job ended - and waited for (5 s at most): a terminated process keeps its files open
    /// until it has really gone, and the window reads them right after (the Studio guard's crash, 2026-10-03:
    /// «progress.txt ... being used by another process»).
    /// </summary>
    public void Stop()
    {
        TerminateJobObject(_job, 1);
        if (_process != IntPtr.Zero)
            WaitForSingleObject(_process, 5000);
        var until = DateTime.Now.AddSeconds(5);
        while (Processes().Count > 0 && DateTime.Now < until)
            Thread.Sleep(50);
    }

    public void Dispose()
    {
        if (_process != IntPtr.Zero)
            CloseHandle(_process);
        if (_job != IntPtr.Zero)
            CloseHandle(_job);         // kill-on-close: whatever still runs in it ends here
        _process = _job = IntPtr.Zero;
    }

    private static string Quote(string a) =>
        a.Length > 0 && a.IndexOfAny(new[] { ' ', '\t', '"' }) < 0 ? a : "\"" + a.Replace("\"", "\\\"") + "\"";

    // ---- Win32 ----------------------------------------------------------------------------------------------

    private const uint JOB_OBJECT_LIMIT_AFFINITY = 0x10, JOB_OBJECT_LIMIT_PRIORITY_CLASS = 0x20,
                       JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000;
    private const uint IDLE_PRIORITY_CLASS = 0x40, BELOW_NORMAL_PRIORITY_CLASS = 0x4000, NORMAL_PRIORITY_CLASS = 0x20;
    private const int JobObjectBasicAccountingInformation = 1, JobObjectBasicProcessIdList = 3,
                      JobObjectExtendedLimitInformation = 9;
    private const uint CREATE_SUSPENDED = 0x4, CREATE_NO_WINDOW = 0x08000000, STILL_ACTIVE = 0x103;
    private const uint PROCESS_SUSPEND_RESUME = 0x0800;

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_LIMIT_INFORMATION
    {
        public long PerProcessUserTimeLimit, PerJobUserTimeLimit;
        public uint LimitFlags;
        public UIntPtr MinimumWorkingSetSize, MaximumWorkingSetSize;
        public uint ActiveProcessLimit;
        public UIntPtr Affinity;
        public uint PriorityClass, SchedulingClass;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct IO_COUNTERS
    {
        public ulong ReadOperationCount, WriteOperationCount, OtherOperationCount,
                     ReadTransferCount, WriteTransferCount, OtherTransferCount;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION
    {
        public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
        public IO_COUNTERS IoInfo;
        public UIntPtr ProcessMemoryLimit, JobMemoryLimit, PeakProcessMemoryUsed, PeakJobMemoryUsed;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
    {
        public long TotalUserTime, TotalKernelTime, ThisPeriodTotalUserTime, ThisPeriodTotalKernelTime;
        public uint TotalPageFaultCount, TotalProcesses, ActiveProcesses, TotalTerminatedProcesses;
    }

    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    private struct STARTUPINFOW
    {
        public int cb;
        public string? lpReserved, lpDesktop, lpTitle;
        public int dwX, dwY, dwXSize, dwYSize, dwXCountChars, dwYCountChars, dwFillAttribute, dwFlags;
        public short wShowWindow, cbReserved2;
        public IntPtr lpReserved2, hStdInput, hStdOutput, hStdError;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct PROCESS_INFORMATION
    {
        public IntPtr hProcess, hThread;
        public int dwProcessId, dwThreadId;
    }

    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern IntPtr CreateJobObjectW(IntPtr attributes, string? name);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool SetInformationJobObject(IntPtr job, int infoClass,
        ref JOBOBJECT_EXTENDED_LIMIT_INFORMATION info, uint length);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool QueryInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool QueryInformationJobObject(IntPtr job, int infoClass,
        ref JOBOBJECT_BASIC_ACCOUNTING_INFORMATION info, uint length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool TerminateJobObject(IntPtr job, uint exitCode);
    [DllImport("kernel32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    private static extern bool CreateProcessW(string? app, StringBuilder cmd, IntPtr pa, IntPtr ta, bool inherit,
        uint flags, IntPtr env, string? dir, ref STARTUPINFOW si, out PROCESS_INFORMATION pi);
    [DllImport("kernel32.dll")]
    private static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll")]
    private static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll")]
    private static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll")]
    private static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll")]
    private static extern IntPtr OpenProcess(uint access, bool inherit, int pid);
    [DllImport("kernel32.dll")]
    private static extern bool CloseHandle(IntPtr h);
    [DllImport("ntdll.dll")]
    private static extern int NtSuspendProcess(IntPtr process);
    [DllImport("ntdll.dll")]
    private static extern int NtResumeProcess(IntPtr process);
}
