using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;

namespace MapgenStudio;

/// <summary>
/// Row 411 (Fable's brief 8): the generator's working files in memory - named sections the engine makes
/// (<c>Local\q2mem_&lt;root&gt;/try_0003/q2mg.bsp</c>: a 32-byte header «Q2MEM1», room, size, present, then the
/// bytes). The Studio only reads them, for the plan of the map being built, and asks Windows how much memory is free
/// for the engine's share.
/// </summary>
public static class MemFiles
{
    [StructLayout(LayoutKind.Sequential)]
    private struct MemoryStatusEx
    {
        public uint Length, MemoryLoad;
        public ulong TotalPhys, AvailPhys, TotalPageFile, AvailPageFile, TotalVirtual, AvailVirtual, AvailExtendedVirtual;
    }

    [DllImport("kernel32.dll", SetLastError = true)]
    private static extern bool GlobalMemoryStatusEx(ref MemoryStatusEx status);

    /// <summary>The physical memory free right now, in bytes (0 when Windows will not say).</summary>
    public static ulong FreeBytes()
    {
        var s = new MemoryStatusEx { Length = (uint)Marshal.SizeOf<MemoryStatusEx>() };
        return GlobalMemoryStatusEx(ref s) ? s.AvailPhys : 0;
    }

    /// <summary>The engine's ceiling for a run: <paramref name="percent"/> of what is free, in MB; 0 - files.</summary>
    public static ulong AllowedMb(int percent) => percent <= 0 ? 0 : FreeBytes() / 100 * (ulong)percent >> 20;

    /// <summary>A section's bytes while the engine holds it and something is in it; null otherwise.</summary>
    public static byte[]? Read(string root, string relative)
    {
        if (!OperatingSystem.IsWindows() || root.Length == 0)
            return null;
        try
        {
            var name = $@"Local\q2mem_{root}/{relative.Replace('\\', '/')}";
            using var map = MemoryMappedFile.OpenExisting(name, MemoryMappedFileRights.Read);
            using var view = map.CreateViewAccessor(0, 0, MemoryMappedFileAccess.Read);
            var magic = new byte[8];
            view.ReadArray(0, magic, 0, 8);
            if (System.Text.Encoding.ASCII.GetString(magic, 0, 6) != "Q2MEM1")
                return null;
            var room = view.ReadUInt64(8);
            var size = view.ReadUInt64(16);
            var present = view.ReadUInt64(24);
            if (present == 0 || size == 0 || size > room || size > int.MaxValue)
                return null;
            var bytes = new byte[size];
            view.ReadArray(32, bytes, 0, (int)size);
            // written while read? the size and the flag again: a section being rewritten is skipped this time
            return view.ReadUInt64(24) == 1 && view.ReadUInt64(16) == size ? bytes : null;
        }
        catch (Exception e) when (e is FileNotFoundException or IOException or UnauthorizedAccessException
                                      or ArgumentException)
        {
            return null;
        }
    }
}
