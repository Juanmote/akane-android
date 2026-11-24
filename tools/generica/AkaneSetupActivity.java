package com.juanmote.akane;

import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.res.AssetManager;
import android.database.Cursor;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.ParcelFileDescriptor;
import android.provider.DocumentsContract;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;

import java.io.BufferedReader;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.nio.channels.FileChannel;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;

// APK genérica: la primera vez pide la carpeta del juego (copia de Steam de Windows o Linux) y genera con ella
// la OBB (los datos del juego) en Android/obb/<paquete>/ y copia los bancos de sonido de FMOD a files/fmod/.
// Después abre el juego directamente. Adaptado del port de A Short Hike.
// Si la APK no lleva manifiesto (compilación completa con los datos dentro), abre el juego sin más.
public class AkaneSetupActivity extends Activity {
    static final String DIR = "akane/";
    static final String MOLDE = DIR + "molde/";
    static final int REQ_TREE = 4243;
    static final String PREFS = "akane_setup";
    static final String KEY_TREE = "tree";
    static final String MARKER = "akane-obb.ok";
    static final String DATA_DIR = "Akane_Data";

    boolean mEs;
    TextView mText;
    Button mButton;
    ProgressBar mBar;
    volatile boolean mBusy;

    // Variantes admitidas (una por versión del juego): nombre -> texto para el usuario
    final List<String[]> mVariants = new ArrayList<String[]>();

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        mEs = "es".equals(Locale.getDefault().getLanguage());
        if (!loadVariants()) { launchGame(); return; }
        mB = builder();
        if (!loadManifest(mB, mVariants.get(0)[0])) { launchGame(); return; }
        if (obbReady()) { launchGame(); return; }
        buildUi();
        Uri saved = savedTree();
        if (saved != null) startGeneration(saved);
        else showChoose(null);
    }

    String t(String es, String en) { return mEs ? es : en; }

    // ----- Arranque del juego -----
    void launchGame() {
        Intent i = new Intent();
        i.setClassName(this, "com.unity3d.player.UnityPlayerActivity");
        if (getIntent() != null && getIntent().getExtras() != null) i.putExtras(getIntent().getExtras());
        startActivity(i);
        overridePendingTransition(0, 0);
        finish();
    }

    int versionCode() {
        try {
            PackageInfo p = getPackageManager().getPackageInfo(getPackageName(), 0);
            return p.versionCode;
        } catch (Exception e) { return 0; }
    }

    File obbFile() {
        return new File(getObbDir(), "main." + versionCode() + "." + getPackageName() + ".obb");
    }

    String markerText() {
        return versionCode() + " " + mB.zipSize();
    }

    // Carpeta donde el juego busca los bancos de FMOD (Application.persistentDataPath + "/fmod")
    File bankDir() {
        File base = getExternalFilesDir(null);
        if (base == null) base = getFilesDir();
        return new File(base, "fmod");
    }

    static String baseName(String rel) {
        int k = rel.lastIndexOf('/');
        return k < 0 ? rel : rel.substring(k + 1);
    }

    boolean banksReady() {
        for (AkaneObbBuilder.Src s : mB.mBanks) {
            File f = new File(bankDir(), baseName(s.name));
            if (!f.isFile() || f.length() != s.size) return false;
        }
        return true;
    }

    boolean obbReady() {
        if (!banksReady()) return false;
        File obb = obbFile();
        File mk = new File(getObbDir(), MARKER);
        if (!obb.isFile() || !mk.isFile()) return false;
        if (obb.length() != mB.zipSize()) return false;
        try {
            byte[] d = readAll(new FileInputStream(mk));
            return new String(d, StandardCharsets.UTF_8).trim().equals(markerText());
        } catch (IOException e) { return false; }
    }

    // ----- Interfaz -----
    int dp(int v) { return (int) TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, getResources().getDisplayMetrics()); }

    void buildUi() {
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER);
        root.setBackgroundColor(Color.rgb(12, 12, 16));
        root.setPadding(dp(32), dp(24), dp(32), dp(24));

        TextView title = new TextView(this);
        title.setText("AKANE");
        title.setTextColor(Color.rgb(220, 30, 40));
        title.setTextSize(TypedValue.COMPLEX_UNIT_SP, 26);
        title.setGravity(Gravity.CENTER);
        root.addView(title);

        mText = new TextView(this);
        mText.setTextColor(Color.rgb(230, 230, 230));
        mText.setTextSize(TypedValue.COMPLEX_UNIT_SP, 16);
        mText.setGravity(Gravity.CENTER);
        mText.setPadding(0, dp(16), 0, dp(16));
        root.addView(mText, new LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT));

        mBar = new ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal);
        mBar.setMax(1000);
        root.addView(mBar, new LinearLayout.LayoutParams(dp(420), LinearLayout.LayoutParams.WRAP_CONTENT));

        mButton = new Button(this);
        mButton.setText(t("Seleccionar carpeta del juego", "Select game folder"));
        mButton.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { pickFolder(); }
        });
        LinearLayout.LayoutParams bl = new LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        bl.topMargin = dp(12);
        root.addView(mButton, bl);
        setContentView(root);
    }

    String versionsText() {
        StringBuilder sb = new StringBuilder();
        for (String[] v : mVariants) sb.append("\n• ").append(v.length > 1 ? v[1] : v[0]);
        return sb.toString();
    }

    void showChoose(String error) {
        String msg = t("Para jugar necesitas los archivos de tu copia de Akane (Steam). Versiones admitidas:",
                "To play you need the files from your copy of Akane (Steam). Supported versions:")
                + versionsText() + "\n\n"
                + t("Copia a la consola la carpeta del juego (la que contiene " + DATA_DIR + ") y selecciónala. Solo hay que hacerlo una vez.",
                "Copy the game folder (the one containing " + DATA_DIR + ") to your device and select it. You only need to do this once.");
        if (error != null) msg = error + "\n\n" + msg;
        mText.setText(msg);
        mBar.setVisibility(View.GONE);
        mButton.setVisibility(View.VISIBLE);
        mButton.requestFocus();
    }

    void showStatus(final String text, final int permille) {
        runOnUiThread(new Runnable() {
            @Override public void run() {
                mBar.setProgress(permille);
                mText.setText(text + "\n\n" + t("No cierres la aplicación.", "Don't close the app."));
            }
        });
    }

    void showProgress(long done, long total) {
        int p = total > 0 ? (int) (done * 1000 / total) : 0;
        showStatus(t("Preparando los datos del juego… ", "Preparing game data… ") + (p / 10) + " %", p);
    }

    void pickFolder() {
        if (mBusy) return;
        Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT_TREE);
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION);
        try {
            startActivityForResult(i, REQ_TREE);
        } catch (Exception e) {
            showChoose(t("Este sistema no tiene selector de carpetas.", "This system has no folder picker."));
        }
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        super.onActivityResult(req, res, data);
        if (req != REQ_TREE || res != RESULT_OK || data == null || data.getData() == null) return;
        Uri tree = data.getData();
        try {
            getContentResolver().takePersistableUriPermission(tree, Intent.FLAG_GRANT_READ_URI_PERMISSION);
        } catch (Exception ignored) { }
        startGeneration(tree);
    }

    Uri savedTree() {
        String s = getSharedPreferences(PREFS, MODE_PRIVATE).getString(KEY_TREE, null);
        return s == null ? null : Uri.parse(s);
    }

    void saveTree(Uri tree) {
        SharedPreferences.Editor e = getSharedPreferences(PREFS, MODE_PRIVATE).edit();
        e.putString(KEY_TREE, tree.toString());
        e.apply();
    }

    void startGeneration(final Uri tree) {
        if (mBusy) return;
        mBusy = true;
        mButton.setVisibility(View.GONE);
        mBar.setVisibility(View.VISIBLE);
        showProgress(0, 1);
        new Thread(new Runnable() {
            @Override public void run() {
                String err;
                try {
                    err = generate(tree);
                } catch (Throwable e) {
                    err = t("Error al preparar los datos: ", "Error while preparing data: ") + e;
                }
                final String fe = err;
                runOnUiThread(new Runnable() {
                    @Override public void run() {
                        mBusy = false;
                        if (fe == null) { saveTree(tree); launchGame(); }
                        else showChoose(fe);
                    }
                });
            }
        }, "akane-setup").start();
    }

    // ----- Manifiestos -----
    AkaneObbBuilder mB;

    boolean loadVariants() {
        try {
            BufferedReader r = new BufferedReader(new InputStreamReader(getAssets().open(DIR + "variants.txt"), StandardCharsets.UTF_8));
            String line;
            while ((line = r.readLine()) != null) {
                if (line.length() == 0 || line.charAt(0) == '#') continue;
                String[] p = line.split("\t");
                String desc = p.length > 2 ? (mEs ? p[1] : p[2]) : (p.length > 1 ? p[1] : p[0]);
                mVariants.add(new String[]{p[0], desc});
            }
            r.close();
        } catch (IOException e) {
            return false;
        }
        return !mVariants.isEmpty();
    }

    AkaneObbBuilder builder() {
        return new AkaneObbBuilder(mEs, new AkaneObbBuilder.Io() {
            @Override public InputStream molde(String name) throws IOException {
                return getAssets().open(MOLDE + name, AssetManager.ACCESS_STREAMING);
            }
            @Override public FileChannel source(String name) throws IOException { return channel(name); }
            @Override public long base(String name) { Long b = mBase.get(name); return b == null ? 0 : b; }
            @Override public void progress(long done, long total) { showProgress(done, total); }
        });
    }

    boolean loadManifest(AkaneObbBuilder b, String variant) {
        try {
            return b.parse(getAssets().open(DIR + "manifest-" + variant + ".txt"));
        } catch (IOException e) {
            return false;
        }
    }

    // ----- Generación de la OBB -----
    Uri mTree;
    HashMap<String, HashMap<String, String[]>> mListCache = new HashMap<String, HashMap<String, String[]>>();
    HashMap<String, Uri> mSrcUris = new HashMap<String, Uri>();        // fuente -> documento
    HashMap<String, File> mUnpacked = new HashMap<String, File>();     // bundle -> datos descomprimidos
    HashMap<String, Long> mBase = new HashMap<String, Long>();         // fuente -> posición base
    HashMap<String, FileChannel> mOpen = new HashMap<String, FileChannel>();
    List<ParcelFileDescriptor> mPfds = new ArrayList<ParcelFileDescriptor>();

    String generate(Uri tree) throws Exception {
        mTree = tree;
        String dataId = findDataDir(tree);
        if (dataId == null) {
            return t("En esa carpeta no está " + DATA_DIR + ". Elige la carpeta del juego (o la propia " + DATA_DIR + ").",
                    DATA_DIR + " was not found there. Choose the game folder (or " + DATA_DIR + " itself).");
        }
        // Busca la variante que encaja con los archivos del usuario
        String chosen = null, firstErr = null;
        for (String[] v : mVariants) {
            AkaneObbBuilder b = builder();
            if (!loadManifest(b, v[0])) continue;
            String err = findSources(b, dataId);
            if (err == null) { mB = b; chosen = v[1]; break; }
            if (firstErr == null) firstErr = err;
        }
        if (chosen == null) {
            return t("Tus archivos no coinciden con ninguna versión admitida.", "Your files don't match any supported version.")
                    + (firstErr != null ? "\n(" + firstErr + ")" : "");
        }

        File dir = getObbDir();
        dir.mkdirs();
        long need = mB.zipSize();
        long free = dir.getUsableSpace();
        File[] old = dir.listFiles();
        if (old != null) for (File f : old) if (f.getName().endsWith(".obb")) free += f.length();
        long extra = 300L << 20;  // data.unity3d descomprimido (unos 250 MB, se borra al terminar) y bancos de sonido
        for (AkaneObbBuilder.Src s : mB.mBanks) extra += s.size;
        if (free < need + extra) {
            return t("No hay espacio suficiente. Hacen falta ", "Not enough free space. Required: ") + ((need + extra) >> 20) + " MB.";
        }
        if (old != null) for (File f : old) if (f.getName().endsWith(".obb") || f.getName().equals(MARKER)) f.delete();

        File tmp = new File(dir, "akane-tmp.obb.part");
        String res;
        try {
            unpackBundles();
            res = mB.writeZip(tmp);
        } finally {
            for (FileChannel c : mOpen.values()) try { c.close(); } catch (IOException ignored) { }
            for (ParcelFileDescriptor p : mPfds) try { p.close(); } catch (IOException ignored) { }
            mOpen.clear(); mPfds.clear();
            for (File f : mUnpacked.values()) f.delete();
            mUnpacked.clear();
        }
        if (res != null) { tmp.delete(); return res; }
        String bankErr = copyBanks(dataId);
        if (bankErr != null) { tmp.delete(); return bankErr; }
        File obb = obbFile();
        if (!tmp.renameTo(obb)) { tmp.delete(); return t("No se pudo guardar la OBB.", "Could not save the OBB."); }
        FileOutputStream mk = new FileOutputStream(new File(dir, MARKER));
        mk.write(markerText().getBytes(StandardCharsets.UTF_8));
        mk.close();
        return null;
    }

    // Copia los bancos de sonido de FMOD (comprobando tamaño y CRC) a la carpeta donde los busca el juego
    String copyBanks(String dataId) throws IOException {
        File dir = bankDir();
        dir.mkdirs();
        byte[] buf = new byte[1 << 20];
        for (int i = 0; i < mB.mBanks.size(); i++) {
            AkaneObbBuilder.Src s = mB.mBanks.get(i);
            showStatus(t("Copiando el sonido… ", "Copying sound… ") + (i + 1) + "/" + mB.mBanks.size(), 1000);
            String[] f = resolve(dataId, s.name);
            if (f == null) return t("Falta el archivo ", "Missing file ") + DATA_DIR + "/" + s.name;
            File out = new File(dir, baseName(s.name));
            File part = new File(dir, baseName(s.name) + ".part");
            java.util.zip.CRC32 crc = new java.util.zip.CRC32();
            long n = 0;
            InputStream in = getContentResolver().openInputStream(DocumentsContract.buildDocumentUriUsingTree(mTree, f[0]));
            FileOutputStream os = new FileOutputStream(part);
            try {
                int r;
                while ((r = in.read(buf)) > 0) { os.write(buf, 0, r); crc.update(buf, 0, r); n += r; }
            } finally {
                in.close();
                os.close();
            }
            if (n != s.size || crc.getValue() != s.crc) {
                part.delete();
                return DATA_DIR + "/" + s.name + t(" es de otra versión", " is from another version");
            }
            out.delete();
            if (!part.renameTo(out)) return t("No se pudo guardar ", "Could not save ") + out.getName();
        }
        return null;
    }

    // Lista los hijos de un documento del árbol: nombre -> {docId, mime, size}
    HashMap<String, String[]> listChildren(String docId) {
        HashMap<String, String[]> out = mListCache.get(docId);
        if (out != null) return out;
        out = new HashMap<String, String[]>();
        Uri kids = DocumentsContract.buildChildDocumentsUriUsingTree(mTree, docId);
        Cursor c = null;
        try {
            c = getContentResolver().query(kids, new String[]{
                    DocumentsContract.Document.COLUMN_DOCUMENT_ID,
                    DocumentsContract.Document.COLUMN_DISPLAY_NAME,
                    DocumentsContract.Document.COLUMN_MIME_TYPE,
                    DocumentsContract.Document.COLUMN_SIZE}, null, null, null);
            while (c != null && c.moveToNext()) {
                out.put(c.getString(1), new String[]{c.getString(0), c.getString(2), c.isNull(3) ? "-1" : c.getString(3)});
            }
        } finally {
            if (c != null) c.close();
        }
        mListCache.put(docId, out);
        return out;
    }

    String findDataDir(Uri tree) {
        mTree = tree;
        try {
            String rootId = DocumentsContract.getTreeDocumentId(tree);
            HashMap<String, String[]> root = listChildren(rootId);
            if (root.containsKey("data.unity3d") || root.containsKey("globalgamemanagers")) return rootId;
            String[] d = root.get(DATA_DIR);
            if (d != null) return d[0];
            // Copia de Steam dentro de una subcarpeta (p. ej. "Akane" o "Linux64")
            for (String[] e : root.values()) {
                if (!DocumentsContract.Document.MIME_TYPE_DIR.equals(e[1])) continue;
                String[] dd = listChildren(e[0]).get(DATA_DIR);
                if (dd != null) return dd[0];
            }
        } catch (Exception ignored) { }
        return null;
    }

    // Busca un archivo por su ruta relativa a Akane_Data
    String[] resolve(String dataId, String rel) {
        String[] parts = rel.split("/");
        String id = dataId;
        String[] f = null;
        for (int i = 0; i < parts.length; i++) {
            f = listChildren(id).get(parts[i]);
            if (f == null) return null;
            id = f[0];
        }
        return f;
    }

    static String filePart(String src) {
        int k = src.indexOf('|');
        return k < 0 ? src : src.substring(0, k);
    }

    String findSources(AkaneObbBuilder b, String dataId) {
        HashMap<String, Uri> uris = new HashMap<String, Uri>();
        for (AkaneObbBuilder.Src s : b.mSrcs) {
            String file = filePart(s.name);
            String[] f = resolve(dataId, file);
            if (f == null) return t("Falta el archivo ", "Missing file ") + DATA_DIR + "/" + file;
            long size = Long.parseLong(f[2]);
            if (size >= 0 && size != s.size) return DATA_DIR + "/" + file + t(" es de otra versión", " is from another version");
            uris.put(file, DocumentsContract.buildDocumentUriUsingTree(mTree, f[0]));
        }
        mSrcUris = uris;
        return null;
    }

    FileChannel openFile(String file) throws IOException {
        ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(mSrcUris.get(file), "r");
        mPfds.add(pfd);
        return new FileInputStream(pfd.getFileDescriptor()).getChannel();
    }

    // Descomprime data.unity3d (texturas y fuentes) en la caché de la app
    void unpackBundles() throws IOException {
        List<String> bundles = new ArrayList<String>();
        for (AkaneObbBuilder.Src s : mB.mSrcs) {
            if (s.name.indexOf('|') >= 0 && !bundles.contains(filePart(s.name))) bundles.add(filePart(s.name));
        }
        File cache = new File(getCacheDir(), "akane-bundles");
        cache.mkdirs();
        for (int i = 0; i < bundles.size(); i++) {
            String file = bundles.get(i);
            showStatus(t("Leyendo los datos del juego… ", "Reading game data… ") + (i + 1) + "/" + bundles.size(),
                    i * 1000 / Math.max(1, bundles.size()));
            ParcelFileDescriptor pfd = getContentResolver().openFileDescriptor(mSrcUris.get(file), "r");
            AkaneBundle bundle = new AkaneBundle();
            File out = new File(cache, "b" + i + ".bin");
            FileChannel ch = new FileInputStream(pfd.getFileDescriptor()).getChannel();
            try {
                bundle.unpack(ch, out);
            } finally {
                ch.close();
                pfd.close();
            }
            mUnpacked.put(file, out);
            for (AkaneObbBuilder.Src s : mB.mSrcs) {
                if (!file.equals(filePart(s.name))) continue;
                long[] node = bundle.nodes.get(s.name.substring(s.name.indexOf('|') + 1));
                if (node == null) throw new IOException("Falta " + s.name);
                mBase.put(s.name, node[0]);
            }
        }
    }

    FileChannel channel(String name) throws IOException {
        FileChannel ch = mOpen.get(name);
        if (ch == null) {
            File unpacked = mUnpacked.get(filePart(name));
            if (unpacked != null && name.indexOf('|') >= 0) ch = new FileInputStream(unpacked).getChannel();
            else ch = openFile(name);
            mOpen.put(name, ch);
        }
        return ch;
    }

    static byte[] readAll(InputStream in) throws IOException {
        java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream();
        byte[] b = new byte[8192];
        int n;
        while ((n = in.read(b)) > 0) bo.write(b, 0, n);
        in.close();
        return bo.toByteArray();
    }
}
