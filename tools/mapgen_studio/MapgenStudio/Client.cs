using System.Diagnostics;
using System.Security.Cryptography;

namespace MapgenStudio;

/// <summary>
/// Every launch of the game client by the Studio (S5): <c>+set q2prox_config_readonly 1 +set net_clientport -1</c>
/// first on its command line - the user's configs are never written, the client takes no fixed port - and the
/// user's configs hashed before the launch and compared after it, so a changed config is said, not assumed away.
/// </summary>
public static class Client
{
    public sealed class Run
    {
        public required Process Process { get; init; }
        public required DateTime Began { get; init; }
        public required Dictionary<string, string> ConfigsBefore { get; init; }
    }

    public static readonly string[] Guard = { "+set", "q2prox_config_readonly", "1", "+set", "net_clientport", "-1" };

    private static readonly List<Process> Live = new();

    /// <summary>
    /// Is a cover's game, started by the Studio, still open (the PO, 08.10: «программа отказывается запускать мне
    /// карту если у меня запущен q2pro-x.exe ... запускать несколько экземпляров не проблема» - the user's own game
    /// no longer holds anything back: a map is played and a cover is shot beside it; mg_4_6686's cover waited ten
    /// minutes for his game to close and was skipped). Every launch takes no fixed port (<c>net_clientport -1</c>).
    /// </summary>
    public static bool Busy(Settings s)
    {
        Live.RemoveAll(p => p.HasExited);
        return Live.Count > 0;
    }

    public static Run Launch(Settings s, params string[] args)
    {
        var (ok, exe) = Settings.CheckClient(s.ClientDir);
        if (!ok)
            throw new InvalidOperationException(Loc.T("lib.to_client.noclient"));
        var before = HashConfigs(s.ClientDir);
        var psi = new ProcessStartInfo(exe) { WorkingDirectory = s.ClientDir, UseShellExecute = false };
        foreach (var a in Guard.Concat(args))
            psi.ArgumentList.Add(a);
        var p = Process.Start(psi) ?? throw new InvalidOperationException(Loc.T("client.nostart"));
        Live.Add(p);
        return new Run { Process = p, Began = DateTime.Now, ConfigsBefore = before };
    }

    /// <summary>Play the map: copied into the client, then the client started on it, a deathmatch.</summary>
    public static Run Play(Settings s, MapEntry map)
    {
        Library.CopyToClient(s, map);
        var run = Launch(s, "+set", "deathmatch", "1", "+map", map.Name);
        Live.Remove(run.Process);           /* a map played holds no cover back */
        return run;
    }

    /// <summary>Every .cfg of baseq2 by its sha256 (the Studio's own temporary cover config left out).</summary>
    public static Dictionary<string, string> HashConfigs(string clientDir)
    {
        var d = new Dictionary<string, string>();
        var baseq2 = Path.Combine(clientDir, "baseq2");
        if (!Directory.Exists(baseq2))
            return d;
        foreach (var f in Directory.GetFiles(baseq2, "*.cfg"))
            if (!Path.GetFileName(f).StartsWith("mgs_cover", StringComparison.OrdinalIgnoreCase))
                d[Path.GetFileName(f)] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(f)));
        return d;
    }

    public static bool ConfigsKept(Run r, Settings s)
    {
        var after = HashConfigs(s.ClientDir);
        return r.ConfigsBefore.Count == after.Count
               && r.ConfigsBefore.All(kv => after.GetValueOrDefault(kv.Key) == kv.Value);
    }
}
