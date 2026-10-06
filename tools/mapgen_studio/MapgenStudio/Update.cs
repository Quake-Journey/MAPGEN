using System.Diagnostics;
using System.IO.Compression;
using System.Net.Http;
using System.Security.Cryptography;
using System.Text.RegularExpressions;

namespace MapgenStudio;

/// <summary>
/// The Studio's updates (Fable's brief 10, D3; the PO, 06.10). The ONE change log of every version, newest first, kept
/// in the MAPGEN repository (`CHANGELOG.ru.md` / `CHANGELOG.en.md`, the Studio's language), its first `## X.Y` the
/// newest version. «Да»: the release's zip and `SHA256SUMS` are downloaded, the zip checked, unpacked into
/// `temp/update/new`; the NEW Studio is started from there with `--apply-update`, this one exits; the new one waits for
/// it, puts its files in place (the program, engine/, tools/, doc/, the change logs, the license - never data/, the
/// settings or temp/), leaves a note for the first start («Что нового») and starts the installed Studio.
/// </summary>
public static class Update
{
    public const string DefaultBase = "https://github.com/Quake-Journey/MAPGEN";
    public const string DefaultRaw = "https://raw.githubusercontent.com/Quake-Journey/MAPGEN/main";

    /// <summary>The hidden `update_url` setting (a test's local server) or the repository.</summary>
    private static string Raw => App.Settings.UpdateUrl.Length > 0 ? App.Settings.UpdateUrl.TrimEnd('/') : DefaultRaw;
    private static string Downloads(string v) => App.Settings.UpdateUrl.Length > 0
        ? App.Settings.UpdateUrl.TrimEnd('/') + $"/releases/download/v{v}"
        : DefaultBase + $"/releases/download/v{v}";

    public sealed record Found(string Version, string Log);

    private static readonly HttpClient Http = new() { Timeout = TimeSpan.FromSeconds(30) };

    static Update() => Http.DefaultRequestHeaders.UserAgent.ParseAdd("MapgenStudio/" + Versions.Current);

    /// <summary>The newest version of the log in the Studio's language (else the other), or null when it cannot be read.</summary>
    public static async Task<Found?> Check()
    {
        foreach (var lang in new[] { Loc.Language, Loc.Language == "ru" ? "en" : "ru" })
        {
            try
            {
                using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(8));
                var log = await Http.GetStringAsync($"{Raw}/CHANGELOG.{lang}.md", cts.Token);
                var m = Regex.Match(log, @"^##\s+(\d+\.\d+)", RegexOptions.Multiline);
                if (m.Success)
                    return new Found(m.Groups[1].Value, log);
            }
            catch (Exception e) when (e is HttpRequestException or TaskCanceledException or OperationCanceledException) { }
        }
        return null;
    }

    public static bool Newer(string version) =>
        Version.TryParse(version, out var a) && Version.TryParse(Versions.Current, out var b) && a > b;

    /// <summary>The log's parts newer than this Studio, then the rest - the newest on top as the log has them.</summary>
    public static string Said(string log) =>
        Regex.Replace(log, @"^# .*\r?\n", "", RegexOptions.Multiline).Trim();

    /// <summary>
    /// Download, check, unpack and hand over: the new Studio started with `--apply-update`. Null when it is under way
    /// (this Studio must exit now), else the reason it is not.
    /// </summary>
    public static async Task<string?> Fetch(string version, Action<string> say)
    {
        var dir = Path.Combine(App.Settings.TempPath, "update");
        try
        {
            if (Directory.Exists(dir))
                Directory.Delete(dir, true);
            Directory.CreateDirectory(dir);
            var name = $"MapgenStudio-{version}-win-x64.zip";
            var zip = Path.Combine(dir, name);
            say(Loc.F("update.downloading", version));
            using (var http = new HttpClient { Timeout = TimeSpan.FromMinutes(20) })
            {
                http.DefaultRequestHeaders.UserAgent.ParseAdd("MapgenStudio/" + Versions.Current);
                var sums = await http.GetStringAsync($"{Downloads(version)}/SHA256SUMS");
                var want = Regex.Match(sums, @"^([0-9a-fA-F]{64})\s+\*?" + Regex.Escape(name) + @"\s*$", RegexOptions.Multiline);
                if (!want.Success)
                    return Loc.T("update.nosum");
                await using (var from = await http.GetStreamAsync($"{Downloads(version)}/{name}"))
                await using (var to = File.Create(zip))
                    await from.CopyToAsync(to);
                say(Loc.T("update.checking"));
                string got;
                await using (var f = File.OpenRead(zip))
                    got = Convert.ToHexString(await SHA256.HashDataAsync(f));
                if (!got.Equals(want.Groups[1].Value, StringComparison.OrdinalIgnoreCase))
                    return Loc.T("update.badsum");
            }
            var unpacked = Path.Combine(dir, "new");
            ZipFile.ExtractToDirectory(zip, unpacked);
            var root = Directory.GetDirectories(unpacked).FirstOrDefault(d => File.Exists(Path.Combine(d, "MapgenStudio.exe")))
                       ?? unpacked;
            var exe = Path.Combine(root, "MapgenStudio.exe");
            if (!File.Exists(exe))
                return Loc.T("update.noexe");
            say(Loc.T("update.applying"));
            Process.Start(new ProcessStartInfo(exe)
            {
                UseShellExecute = false, WorkingDirectory = root,
                ArgumentList = { "--apply-update", root, Settings.ProgramDir.TrimEnd('\\', '/'), Environment.ProcessId.ToString(),
                                 Versions.Current },
            });
            return null;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException
                                      or UnauthorizedAccessException or InvalidDataException
                                      or System.ComponentModel.Win32Exception)
        {
            return Loc.F("update.error", e.Message);
        }
    }

    /// <summary>What a release replaces; the rest of the install folder (data/, the settings, temp/) is the user's.</summary>
    private static readonly string[] Replaced = { "MapgenStudio.exe", "engine", "tools", "doc", "CHANGELOG.ru.md",
                                                   "CHANGELOG.en.md", "LICENSE.txt", "THIRD_PARTY.md" };

    /// <summary>
    /// `--apply-update FROM TO PID OLDVERSION`, run by the NEW Studio from its unpacked folder: wait for the old one to
    /// end, copy, keep the old program as MapgenStudio.previous.exe, write the «what's new» note, start the installed one.
    /// </summary>
    public static int Apply(string from, string to, int pid, string oldVersion)
    {
        var note = Path.Combine(to, "update.txt");
        try
        {
            try
            {
                using var old = Process.GetProcessById(pid);
                old.WaitForExit(60000);
            }
            catch (ArgumentException) { }
            // the user's donors stay: only the program's own engine parts are replaced
            var donors = Path.Combine(to, "engine", "donors");
            var keep = Path.Combine(to, "engine.donors.keep");
            if (Directory.Exists(donors))
            {
                if (Directory.Exists(keep))
                    Directory.Delete(keep, true);
                Directory.Move(donors, keep);
            }
            var exe = Path.Combine(to, "MapgenStudio.exe");
            if (File.Exists(exe))
                File.Copy(exe, Path.Combine(to, "MapgenStudio.previous.exe"), true);
            foreach (var item in Replaced)
            {
                var src = Path.Combine(from, item);
                var dst = Path.Combine(to, item);
                if (File.Exists(src))
                    File.Copy(src, dst, true);
                else if (Directory.Exists(src))
                {
                    if (Directory.Exists(dst))
                        Directory.Delete(dst, true);
                    CopyDir(src, dst);
                }
            }
            if (Directory.Exists(keep))
            {
                var fresh = Path.Combine(to, "engine", "donors");
                if (Directory.Exists(fresh))
                    foreach (var f in Directory.GetFiles(fresh))
                        File.Copy(f, Path.Combine(keep, Path.GetFileName(f)), true);
                if (Directory.Exists(fresh))
                    Directory.Delete(fresh, true);
                Directory.Move(keep, fresh);
            }
            File.WriteAllText(note, oldVersion + "\n");
            // the update guard asks for no restart: a window on the PO's screen is not a test's to open
            if (Environment.GetEnvironmentVariable("MAPGEN_UPDATE_NO_RESTART") != "1")
                Process.Start(new ProcessStartInfo(exe) { UseShellExecute = false, WorkingDirectory = to });
            return 0;
        }
        catch (Exception e) when (e is IOException or UnauthorizedAccessException or System.ComponentModel.Win32Exception)
        {
            File.WriteAllText(Path.Combine(to, "update_failed.txt"), e.ToString());
            return 1;
        }
    }

    private static void CopyDir(string src, string dst)
    {
        Directory.CreateDirectory(dst);
        foreach (var f in Directory.GetFiles(src))
            File.Copy(f, Path.Combine(dst, Path.GetFileName(f)), true);
        foreach (var d in Directory.GetDirectories(src))
            CopyDir(d, Path.Combine(dst, Path.GetFileName(d)));
    }

    /// <summary>The note the updater left: the version updated from, once (the «what's new» window reads it).</summary>
    public static string? TakeNote()
    {
        var note = Path.Combine(Settings.ProgramDir, "update.txt");
        if (!File.Exists(note))
            return null;
        var was = File.ReadAllText(note).Trim();
        File.Delete(note);
        return was;
    }

    /// <summary>A failed update's record, once.</summary>
    public static string? TakeFailure()
    {
        var file = Path.Combine(Settings.ProgramDir, "update_failed.txt");
        if (!File.Exists(file))
            return null;
        var said = File.ReadAllText(file);
        File.Delete(file);
        return said;
    }

    /// <summary>The installed versions' history as the «what's new» window shows it: this version's lines, then all.</summary>
    public static (string now, string all) History()
    {
        string Lines(Versions.Entry v) => string.Join("\n", (Loc.Language == "ru" ? v.Ru : v.En).Select(l => "• " + l));
        var now = Versions.All[0];
        var all = string.Join("\n\n", Versions.All.Select(v => $"{v.Number} — {v.Date}\n{Lines(v)}"));
        return (Lines(now), all);
    }
}
