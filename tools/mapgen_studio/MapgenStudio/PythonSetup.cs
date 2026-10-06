using System.Diagnostics;
using System.Net.Http;

namespace MapgenStudio;

/// <summary>
/// Python for the map's checks (the PO, 06.10: «если для работы нужен питон то программа должна сама предложить его
/// установить если его нет или предложить указать к нему путь»). The official installer from python.org, its
/// signature checked (Python Software Foundation, valid), installed for this user only - no administrator, «Add to
/// PATH» on - and found at once where it went; or a python.exe the user points at, proved by running it.
/// </summary>
public static class PythonSetup
{
    public const string Version = "3.12.10";
    public static string InstallerUrl => $"https://www.python.org/ftp/python/{Version}/python-{Version}-amd64.exe";

    /// <summary>`python --version` of a python.exe: its version said, or null when it is not a usable Python 3.10+.</summary>
    public static string? Probe(string exe)
    {
        try
        {
            using var p = Process.Start(new ProcessStartInfo(exe, "--version")
            {
                RedirectStandardOutput = true, RedirectStandardError = true, UseShellExecute = false, CreateNoWindow = true,
            });
            if (p == null)
                return null;
            var said = (p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd()).Trim();
            if (!p.WaitForExit(10000))
                return null;
            var m = System.Text.RegularExpressions.Regex.Match(said, @"Python (\d+)\.(\d+)");
            return m.Success && int.Parse(m.Groups[1].Value) == 3 && int.Parse(m.Groups[2].Value) >= 10 ? said : null;
        }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or InvalidOperationException or IOException)
        {
            return null;
        }
    }

    /// <summary>Is the file signed by the Python Software Foundation, the signature valid (Windows says).</summary>
    private static bool SignedByPsf(string file)
    {
        try
        {
            var script = $"$s = Get-AuthenticodeSignature -LiteralPath '{file.Replace("'", "''")}'; " +
                         "\"$($s.Status)|$($s.SignerCertificate.Subject)\"";
            using var p = Process.Start(new ProcessStartInfo("powershell.exe", $"-NoProfile -NonInteractive -Command \"{script}\"")
            {
                RedirectStandardOutput = true, UseShellExecute = false, CreateNoWindow = true,
            });
            if (p == null)
                return false;
            var said = p.StandardOutput.ReadToEnd().Trim();
            p.WaitForExit(30000);
            return said.StartsWith("Valid|", StringComparison.Ordinal)
                   && said.Contains("Python Software Foundation", StringComparison.Ordinal);
        }
        catch (Exception e) when (e is System.ComponentModel.Win32Exception or InvalidOperationException)
        {
            return false;
        }
    }

    /// <summary>
    /// Download, check and install; `say` gets the steps in the user's words. The python.exe it installed, or null with
    /// the reason said.
    /// </summary>
    public static async Task<string?> Install(Action<string> say)
    {
        var dir = Path.Combine(App.Settings.TempPath, "python_setup");
        Directory.CreateDirectory(dir);
        var file = Path.Combine(dir, $"python-{Version}-amd64.exe");
        try
        {
            say(Loc.F("python.downloading", Version));
            using (var http = new HttpClient { Timeout = TimeSpan.FromMinutes(10) })
            {
                http.DefaultRequestHeaders.UserAgent.ParseAdd("MapgenStudio/" + Versions.Current);
                await using var from = await http.GetStreamAsync(InstallerUrl);
                await using var to = File.Create(file);
                await from.CopyToAsync(to);
            }
            say(Loc.T("python.checking"));
            if (!await Task.Run(() => SignedByPsf(file)))
            {
                say(Loc.T("python.unsigned"));
                return null;
            }
            say(Loc.T("python.installing"));
            var code = await Task.Run(() =>
            {
                using var p = Process.Start(new ProcessStartInfo(file,
                    "/passive InstallAllUsers=0 PrependPath=1 Include_test=0 Include_launcher=0 Include_tcltk=0")
                    { UseShellExecute = false });
                p?.WaitForExit();
                return p?.ExitCode ?? -1;
            });
            var found = Engine.Python;
            if (code != 0 || found == null)
            {
                say(Loc.F("python.failed", code));
                return null;
            }
            say(Loc.F("python.done", found));
            return found;
        }
        catch (Exception e) when (e is HttpRequestException or TaskCanceledException or IOException
                                      or UnauthorizedAccessException or System.ComponentModel.Win32Exception)
        {
            say(Loc.F("python.error", e.Message));
            return null;
        }
        finally
        {
            try { File.Delete(file); } catch (Exception e) when (e is IOException or UnauthorizedAccessException) { }
        }
    }
}
