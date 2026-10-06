using Avalonia;

namespace MapgenStudio;

/// <summary>MAPGEN Studio - the portable desktop front end of MAPGEN-1 (phase P1: the shell).</summary>
internal static class Program
{
    [STAThread]
    public static void Main(string[] args) =>
        BuildAvaloniaApp().StartWithClassicDesktopLifetime(args);

    public static AppBuilder BuildAvaloniaApp() =>
        AppBuilder.Configure<App>()
            .UsePlatformDetect()
            .WithInterFont()
            .LogToTrace();
}
