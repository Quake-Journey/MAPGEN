using System.Globalization;
using System.Text;

namespace MapgenStudio;

/// <summary>
/// `--generate NAME FIDELITY SEED [--donor MAP] [--graft MAP ...] [--resume-job DIR]` (ledger rows 394-397, 399):
/// one full generation driven exactly as the window drives it - the final build with light, the map's checks, the
/// map with its source and descriptions into the library - without a window, its account into <c>generate.txt</c>
/// beside the program. MAP is a donor's name in the engine's donors folder or the path of any Quake II .bsp, which
/// is then added there (q2dm1 when no --donor is given); each --graft map is offered as a source of rooms.
/// </summary>
public static class GenerateCli
{
    public static string Run(Settings s, string[] args)
    {
        var b = new StringBuilder();
        var at = Array.IndexOf(args, "--generate");
        if (at < 0 || at + 3 >= args.Length)
            return "FAIL usage: --generate NAME FIDELITY SEED [--donor MAP] [--graft MAP ...] [--resume-job DIR]\n";
        var name = args[at + 1];
        var fidelity = int.Parse(args[at + 2], CultureInfo.InvariantCulture);
        var seed = long.Parse(args[at + 3], CultureInfo.InvariantCulture);
        string? Opt(string flag) => Array.IndexOf(args, flag) is var k and >= 0 && k + 1 < args.Length ? args[k + 1] : null;
        static string Donor(string map) => File.Exists(map) ? Engine.AddDonor(map) : map;
        var resume = Opt("--resume-job");
        var donor = Donor(Opt("--donor") ?? "q2dm1");
        var grafts = args.Select((a, k) => (a, k)).Where(x => x.a == "--graft" && x.k + 1 < args.Length)
                         .Select(x => Donor(args[x.k + 1])).Where(d => d != donor).Distinct().ToList();
        var missing = Generation.Missing(s, donor, grafts);
        if (missing != null)
            return $"FAIL {missing}\n";
        var g = resume == null
            ? Generation.Start(new GenerationRequest(name, donor, fidelity, seed, Array.Empty<string>(), s.SaveMapSource,
                                                     Grafts: grafts), s)
            : Generation.Resume(s, resume);
        while (g.Running)
        {
            g.Poll();
            Thread.Sleep(500);
        }
        b.AppendLine($"{(g.Error.Length == 0 ? "PASS" : "FAIL")} the generation ended {(g.Error.Length == 0 ? "with a map" : "without one: " + g.Error)}");
        b.AppendLine($"donor {g.Request.Donor}{(grafts.Count > 0 ? ", rooms offered from " + string.Join(", ", grafts) : "")}");
        b.AppendLine($"result {g.Result}, accepted {g.Accepted}, divergence {g.Divergence} of {g.Target}, ended by {g.EndedBy}");
        b.AppendLine($"took {(g.Ended!.Value - g.Began):hh\\:mm\\:ss}");
        foreach (var (pass, what) in g.Gates)
            b.AppendLine($"  {(pass ? "PASS" : "FAIL")}  gate: {what}");
        if (g.LibraryName.Length > 0)
            b.AppendLine($"library {Path.Combine(s.BspPath, g.LibraryName + ".bsp")}");
        b.AppendLine("LOG");
        foreach (var line in g.Log)
            b.AppendLine("  " + line);
        return b.ToString();
    }
}
