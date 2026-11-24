// Script de compilación para Android (lo llama la CI de GitLab, .gitlab-ci.yml).
// AKANE_GENERIC=1: APK genérica (split binary, sin datos del juego; los genera la APK con la copia del usuario).
using System;
using System.IO;
using System.Linq;
using UnityEditor;
using UnityEditor.Build.Reporting;
using UnityEditor.Android;
using UnityEditor.SceneManagement;
using UnityEngine;

public static class BuildAndroid
{
    static void SetIcon()
    {
        Texture2D icon = AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/PortAndroid/icon.png");
        if (icon == null) { Debug.LogWarning("[AKANE] Sin icono propio (se usa el del juego)"); return; }
        Texture2D bg = AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/PortAndroid/icon_adaptive_bg.png") ?? icon;
        Texture2D fg = AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/PortAndroid/icon_transparent.png") ?? icon;
        Texture2D round = AssetDatabase.LoadAssetAtPath<Texture2D>("Assets/PortAndroid/icon_round.png") ?? icon;
        PlayerSettings.SetIconsForTargetGroup(BuildTargetGroup.Unknown, new[] { icon });
        foreach (PlatformIconKind kind in new PlatformIconKind[] { AndroidPlatformIconKind.Legacy, AndroidPlatformIconKind.Round, AndroidPlatformIconKind.Adaptive })
        {
            PlatformIcon[] icons = PlayerSettings.GetPlatformIcons(BuildTargetGroup.Android, kind);
            foreach (PlatformIcon pi in icons)
            {
                if (kind == AndroidPlatformIconKind.Adaptive) pi.SetTextures(bg, fg);
                else if (kind == AndroidPlatformIconKind.Round) pi.SetTexture(round);
                else pi.SetTexture(icon);
            }
            PlayerSettings.SetPlatformIcons(BuildTargetGroup.Android, kind, icons);
        }
        Debug.Log("[AKANE] Icono aplicado");
    }

    // ---- APK genérica ----
    const string BootScene = "Assets/PortAndroid/AkaneBoot.unity";

    // Escena vacía en el índice 0 que solo carga la primera escena real: es lo único que queda dentro de la APK.
    static void MakeBootScene()
    {
        var scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
        var cam = new GameObject("Camera").AddComponent<Camera>();
        cam.clearFlags = CameraClearFlags.SolidColor;
        cam.backgroundColor = Color.black;
        Type boot = AppDomain.CurrentDomain.GetAssemblies().Select(a => a.GetType("AkaneBoot")).FirstOrDefault(t => t != null);
        if (boot == null) throw new Exception("No se encuentra AkaneBoot");
        new GameObject("AkaneBoot").AddComponent(boot);
        Directory.CreateDirectory(Path.GetDirectoryName(BootScene));
        EditorSceneManager.SaveScene(scene, BootScene);
        AssetDatabase.Refresh();
        Debug.Log("[AKANE] Escena de arranque creada");
    }

    // Cada textura del juego en Android con el mismo formato que en PC (las DXT, sin comprimir),
    // para que la APK pueda rellenarla después con los datos de la copia del usuario.
    static void ApplyPcTextureFormats()
    {
        string tsv = Environment.GetEnvironmentVariable("AKANE_TEXFORMATS");
        if (string.IsNullOrEmpty(tsv) || !File.Exists(tsv)) throw new Exception("Falta la lista de formatos de textura (AKANE_TEXFORMATS)");
        int n = 0;
        AssetDatabase.StartAssetEditing();
        try
        {
            foreach (string line in File.ReadAllLines(tsv))
            {
                if (line.Length == 0 || line[0] == '#') continue;
                string[] p = line.Split('\t');
                var imp = AssetImporter.GetAtPath(p[0]) as TextureImporter;
                if (imp == null) { Debug.LogWarning("[AKANE] Textura no encontrada: " + p[0]); continue; }
                var fmt = (TextureImporterFormat)Enum.Parse(typeof(TextureImporterFormat), p[1]);
                var ps = imp.GetPlatformTextureSettings("Android");
                ps.overridden = true;
                ps.format = fmt;
                ps.maxTextureSize = 8192;
                ps.textureCompression = TextureImporterCompression.Uncompressed;
                imp.SetPlatformTextureSettings(ps);
                imp.mipmapEnabled = p[2] == "1";
                imp.npotScale = TextureImporterNPOTScale.None;
                imp.SaveAndReimport();
                n++;
            }
        }
        finally
        {
            AssetDatabase.StopAssetEditing();
        }
        AssetDatabase.Refresh();
        Debug.Log("[AKANE] Formatos de PC aplicados a " + n + " texturas");
    }

    public static void Build()
    {
        try
        {
            EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);
            PlayerSettings.companyName = "Ludic";
            PlayerSettings.productName = "Akane";
            PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Android, "com.juanmote.akane");
            string ver = Environment.GetEnvironmentVariable("APK_VERSION") ?? "1";
            int code; if (!int.TryParse(ver, out code)) code = 1;
            string verName = Environment.GetEnvironmentVariable("APK_VERSION_NAME");
            PlayerSettings.bundleVersion = string.IsNullOrEmpty(verName) ? "1.0." + code : verName;
            PlayerSettings.Android.bundleVersionCode = code;

            PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.SetApiCompatibilityLevel(BuildTargetGroup.Android, ApiCompatibilityLevel.NET_4_6);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel24;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevelAuto;
            PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, new[] { UnityEngine.Rendering.GraphicsDeviceType.OpenGLES3 });
            PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
            PlayerSettings.defaultInterfaceOrientation = UIOrientation.LandscapeLeft;
            PlayerSettings.allowedAutorotateToPortrait = false;
            PlayerSettings.allowedAutorotateToPortraitUpsideDown = false;
            PlayerSettings.Android.androidIsGame = true;
            PlayerSettings.Android.androidTVCompatibility = true;
            PlayerSettings.Android.startInFullscreen = true;
            PlayerSettings.Android.renderOutsideSafeArea = true;
            PlayerSettings.SplashScreen.show = false;

            // Optimización: ritmo de fotogramas estable, sin pila en cada Debug.Log
            // (es lo más caro de los logs en Android) y datos comprimidos con LZ4HC
            // (APK más pequeña y carga rápida).
            PlayerSettings.Android.optimizedFramePacing = true;
            PlayerSettings.SetStackTraceLogType(LogType.Log, StackTraceLogType.None);
            PlayerSettings.SetStackTraceLogType(LogType.Warning, StackTraceLogType.None);
            PlayerSettings.SetStackTraceLogType(LogType.Error, StackTraceLogType.ScriptOnly);
            PlayerSettings.SetStackTraceLogType(LogType.Assert, StackTraceLogType.ScriptOnly);
            PlayerSettings.SetStackTraceLogType(LogType.Exception, StackTraceLogType.ScriptOnly);

            EditorUserBuildSettings.buildAppBundle = false;

            // Firma con la clave que prepara la CI (alias detectado allí).
            string ks = Environment.GetEnvironmentVariable("ANDROID_KEYSTORE_PATH");
            string kp = Environment.GetEnvironmentVariable("ANDROID_KEYSTORE_PASS");
            string ka = Environment.GetEnvironmentVariable("ANDROID_KEY_ALIAS");
            string kap = Environment.GetEnvironmentVariable("ANDROID_KEY_PASS");
            if (string.IsNullOrEmpty(kap)) kap = kp;
            if (!string.IsNullOrEmpty(ks) && File.Exists(ks) && !string.IsNullOrEmpty(kp) && !string.IsNullOrEmpty(ka))
            {
                PlayerSettings.Android.useCustomKeystore = true;
                PlayerSettings.Android.keystoreName = ks;
                PlayerSettings.Android.keystorePass = kp;
                PlayerSettings.Android.keyaliasName = ka;
                PlayerSettings.Android.keyaliasPass = kap;
                Debug.Log("[AKANE] Firmando con keystore propio (alias " + ka + ")");
            }
            else Debug.LogWarning("[AKANE] Sin keystore: firma de depuración");

            SetIcon();

            string[] scenes = EditorBuildSettings.scenes.Where(s => s.enabled).Select(s => s.path).ToArray();
            bool generic = Environment.GetEnvironmentVariable("AKANE_GENERIC") == "1";
            PlayerSettings.Android.useAPKExpansionFiles = generic;
            BuildOptions opts = BuildOptions.CompressWithLz4HC;
            if (generic)
            {
                // Datos sin comprimir: la APK los reconstruye byte a byte con la copia del usuario
                opts = BuildOptions.None;
                ApplyPcTextureFormats();
                MakeBootScene();
                scenes = new[] { BootScene }.Concat(scenes).ToArray();
                Debug.Log("[AKANE] Modo APK genérica (split binary)");
            }
            Debug.Log("[AKANE] Escenas: " + scenes.Length + " → " + string.Join(", ", scenes));
            string outPath = Path.GetFullPath(Path.Combine(Application.dataPath, "../../build/Akane.apk"));
            Directory.CreateDirectory(Path.GetDirectoryName(outPath));
            BuildReport r = BuildPipeline.BuildPlayer(scenes, outPath, BuildTarget.Android, opts);
            Debug.Log("[AKANE] Resultado: " + r.summary.result + " errores=" + r.summary.totalErrors + " tamaño=" + r.summary.totalSize);
            EditorApplication.Exit(r.summary.result == BuildResult.Succeeded ? 0 : 1);
        }
        catch (Exception e)
        {
            Debug.LogError("[AKANE] Excepción: " + e);
            EditorApplication.Exit(1);
        }
    }
}
