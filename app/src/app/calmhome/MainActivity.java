package app.calmhome;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.ComponentName;
import android.content.Context;
import android.content.DialogInterface;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorFilter;
import android.graphics.PixelFormat;
import android.graphics.Path;
import android.graphics.Rect;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.media.tv.TvContract;
import android.media.tv.TvInputInfo;
import android.media.tv.TvInputManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.text.format.DateFormat;
import android.content.res.Configuration;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.view.Window;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextClock;
import android.widget.TextView;
import android.widget.Toast;

import java.io.File;
import java.io.FileInputStream;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Calm Home: one screen, no network, no permissions.
 *
 * Shows HDMI inputs and installed TV apps. Apps you open most float to the top.
 * Long-press OK (or press Menu) on an app to move it to the front, hide it, or
 * open its App info. Hidden apps are always recoverable from the "Hidden" tile.
 * The Settings tile is always present so you can never lock yourself out.
 */
public class MainActivity extends Activity {

    private static final String KEY_SETTINGS = "__settings__";
    private static final String KEY_HIDDEN = "__hidden__";

    private static final int BG = Theme.BG;
    private static final int TEXT = Theme.TEXT;
    private static final int DIM = Theme.DIM;

    private static final int SCREEN_MARGIN_DP = 56;   // TV overscan-safe side margin

    /** A decoded wallpaper plus the darkening gradient computed for it. */
    private static final class Wall {
        Bitmap bitmap;
        float[] alphas;
        String stamp;
    }

    /** Draws a Glyph (pure geometry in a 0..1 box) with a Canvas. */
    private static final class GlyphDrawable extends Drawable {
        private final List<Glyph.Prim> shapes;
        private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
        private final Path path = new Path();

        GlyphDrawable(Glyph.Kind kind, int color) {
            shapes = Glyph.shapes(kind);
            paint.setColor(color);
            paint.setStrokeCap(Paint.Cap.ROUND);
            paint.setStrokeJoin(Paint.Join.ROUND);
        }

        @Override
        public void draw(Canvas c) {
            Rect b = getBounds();
            float size = Math.min(b.width(), b.height());
            float ox = b.left + (b.width() - size) / 2f;
            float oy = b.top + (b.height() - size) / 2f;
            for (Glyph.Prim sh : shapes) {
                paint.setStyle(sh.fill ? Paint.Style.FILL : Paint.Style.STROKE);
                paint.setStrokeWidth((float) (sh.width * size));
                if (sh.type == Glyph.POLY) {
                    path.reset();
                    for (int i = 0; i + 1 < sh.p.length; i += 2) {
                        float x = ox + (float) sh.p[i] * size, y = oy + (float) sh.p[i + 1] * size;
                        if (i == 0) path.moveTo(x, y); else path.lineTo(x, y);
                    }
                    if (sh.closed) path.close();
                    c.drawPath(path, paint);
                } else if (sh.type == Glyph.CIRCLE) {
                    c.drawCircle(ox + (float) sh.p[0] * size, oy + (float) sh.p[1] * size,
                            (float) sh.p[2] * size, paint);
                } else {
                    c.drawLine(ox + (float) sh.p[0] * size, oy + (float) sh.p[1] * size,
                            ox + (float) sh.p[2] * size, oy + (float) sh.p[3] * size, paint);
                }
            }
        }

        @Override public void setAlpha(int alpha) { paint.setAlpha(alpha); }
        @Override public void setColorFilter(ColorFilter cf) { paint.setColorFilter(cf); }
        @SuppressWarnings("deprecation")      // still abstract on the oldest supported Android (5.0)
        @Override public int getOpacity() { return PixelFormat.TRANSLUCENT; }
    }

    /** Draws the soft dark gradient over the wallpaper. */
    private static final class ScrimView extends View {
        private final Paint paint = new Paint();
        private float[] alphas;
        private int builtForHeight = -1;

        ScrimView(Context c) {
            super(c);
            setFocusable(false);
        }

        void setAlphas(float[] a) {
            alphas = a;
            builtForHeight = -1;
            invalidate();
        }

        @Override
        protected void onDraw(Canvas canvas) {
            if (alphas == null || getHeight() <= 0) return;
            if (builtForHeight != getHeight()) {
                int n = alphas.length;
                int[] colors = new int[n];
                float[] pos = new float[n];
                for (int i = 0; i < n; i++) {
                    colors[i] = Color.argb(Math.round(alphas[i] * 255f), 0x0D, 0x11, 0x17);
                    pos[i] = i / (float) (n - 1);
                }
                paint.setShader(new LinearGradient(0, 0, 0, getHeight(), colors, pos, Shader.TileMode.CLAMP));
                builtForHeight = getHeight();
            }
            canvas.drawRect(0, 0, getWidth(), getHeight(), paint);
        }
    }

    private static class Item implements Order.Entry {
        String key;
        String label;
        Glyph.Kind glyph;  // drawn icon shown instead of artwork (HDMI, Settings, Hidden)
        Drawable art;      // banner or icon
        boolean banner;    // true: art fills the card; false: art is a centred icon
        boolean input;
        Intent intent;

        @Override public String key() { return key; }
        @Override public String label() { return label; }
    }

    private final Handler ui = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private LinearLayout content;
    private ScrollView scroll;
    private float dp;
    private int generation;
    private Grid grid;
    private ImageView wallpaperView;
    private ScrimView scrimView;
    private TextView ampmClock;
    private String shownWallStamp;
    private volatile Wall wallCache;

    private View firstTile;
    private final Map<String, View> tileByKey = new HashMap<String, View>();
    private List<Item> hiddenItems = new ArrayList<Item>();

    // ---------------------------------------------------------------- lifecycle

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        prefs = getSharedPreferences("calm", MODE_PRIVATE);
        dp = getResources().getDisplayMetrics().density;

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(BG);
        root.setClipChildren(false);

        // Optional wallpaper (hidden until the user adds one) with a dark gradient over it.
        wallpaperView = new ImageView(this);
        wallpaperView.setScaleType(ImageView.ScaleType.CENTER_CROP);
        wallpaperView.setFocusable(false);
        wallpaperView.setVisibility(View.GONE);
        root.addView(wallpaperView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        scrimView = new ScrimView(this);
        scrimView.setVisibility(View.GONE);
        root.addView(scrimView, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));

        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        // TV overscan-safe margins.
        column.setClipChildren(false);
        column.setPadding(px(SCREEN_MARGIN_DP), px(28), px(SCREEN_MARGIN_DP), 0);
        column.addView(buildHeader());

        scroll = new ScrollView(this);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setClipChildren(false);
        scroll.setClipToPadding(false);
        scroll.setPadding(0, px(14), 0, px(40));
        scroll.setVerticalFadingEdgeEnabled(true);        // rows fade softly as they scroll away
        scroll.setFadingEdgeLength(px(Theme.FADE));

        content = new LinearLayout(this);
        content.setOrientation(LinearLayout.VERTICAL);
        content.setClipChildren(false);
        scroll.addView(content, new ViewGroup.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        column.addView(scroll, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));
        root.addView(column, new FrameLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
    }

    @Override
    protected void onResume() {
        super.onResume();
        reload();
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        // Home pressed while already on the home screen: jump back to the top.
        scroll.scrollTo(0, 0);
        if (firstTile != null) firstTile.requestFocus();
        reload();
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        dp = getResources().getDisplayMetrics().density;
        reload();
    }

    @Override
    public void onBackPressed() {
        // A home screen has nowhere to go back to.
    }

    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (keyCode == KeyEvent.KEYCODE_BACK) return true;
        if (keyCode == KeyEvent.KEYCODE_MENU) {
            View focused = getCurrentFocus();
            if (focused != null && focused.getTag() instanceof Item) {
                showOptions((Item) focused.getTag());
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    // ------------------------------------------------------------------ header

    private View buildHeader() {
        LinearLayout header = new LinearLayout(this);
        header.setOrientation(LinearLayout.HORIZONTAL);
        header.setGravity(Gravity.BOTTOM);

        TextClock time = new TextClock(this);
        time.setFormat12Hour("h:mm");
        time.setFormat24Hour("HH:mm");
        time.setTextSize(Theme.CLOCK_SP);
        time.setTextColor(TEXT);
        time.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        header.addView(time);

        TextClock ampm = new TextClock(this);            // hidden on 24-hour setups (see render)
        ampm.setFormat12Hour("a");
        ampm.setFormat24Hour("a");
        ampm.setTextSize(Theme.AMPM_SP);
        ampm.setTextColor(DIM);
        ampm.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        ampm.setPadding(px(8), 0, 0, px(8));      // shares the clock's baseline
        header.addView(ampm);
        ampmClock = ampm;

        View divider = new View(this);
        divider.setBackgroundColor(Theme.HAIRLINE);
        LinearLayout.LayoutParams dp = new LinearLayout.LayoutParams(px(1), px(28));
        dp.setMargins(px(20), 0, px(20), px(11));
        header.addView(divider, dp);

        TextClock date = new TextClock(this);
        date.setFormat12Hour("EEEE, d MMMM");
        date.setFormat24Hour("EEEE, d MMMM");
        date.setTextSize(Theme.DATE_SP);
        date.setTextColor(DIM);
        date.setPadding(0, 0, 0, px(8));
        header.addView(date);
        return header;
    }

    // ---------------------------------------------------------------- loading

    /** Query packages on a worker thread; build views on the UI thread. */
    private void reload() {
        final int mine = ++generation;
        new Thread(new Runnable() {
            @Override public void run() {
                final Wall wall = loadWall();
                final List<Item> all = loadAll();
                ui.post(new Runnable() {
                    @Override public void run() {
                        if (mine == generation && !isFinishing() && !isDestroyed()) render(all, wall);
                    }
                });
            }
        }, "calm-load").start();
    }

    private List<Item> loadAll() {
        List<Item> out = new ArrayList<Item>();

        try {
            TvInputManager tim = (TvInputManager) getSystemService(Context.TV_INPUT_SERVICE);
            if (tim != null) {
                for (TvInputInfo info : tim.getTvInputList()) {
                    // HDMI ports only; skip CEC child devices (they have a parent).
                    if (info.getType() != TvInputInfo.TYPE_HDMI) continue;
                    if (info.getParentId() != null) continue;
                    CharSequence label = customLabel(info);
                    if (label == null || label.length() == 0) label = info.loadLabel(this);
                    Item it = new Item();
                    it.key = "in:" + info.getId();
                    it.label = String.valueOf(label);
                    it.glyph = Glyph.Kind.HDMI;
                    it.input = true;
                    it.intent = new Intent(Intent.ACTION_VIEW,
                            TvContract.buildChannelUriForPassthroughInput(info.getId()))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                    out.add(it);
                }
            }
        } catch (Throwable ignored) {
            // No TV input framework (or it misbehaves): apps still work.
        }

        PackageManager pm = getPackageManager();
        Set<String> seen = new HashSet<String>();
        String[] categories = { Intent.CATEGORY_LEANBACK_LAUNCHER, Intent.CATEGORY_LAUNCHER };
        for (String category : categories) {
            Intent query = new Intent(Intent.ACTION_MAIN).addCategory(category);
            for (ResolveInfo r : pm.queryIntentActivities(query, 0)) {
                String pkg = r.activityInfo.packageName;
                if (pkg.equals(getPackageName()) || !seen.add(pkg)) continue;
                Item it = new Item();
                it.key = pkg;
                it.label = String.valueOf(r.loadLabel(pm));
                Drawable banner = null;
                try { banner = r.activityInfo.loadBanner(pm); } catch (Throwable ignored) { }
                if (banner != null) {
                    it.art = banner;
                    it.banner = true;
                } else {
                    it.art = r.loadIcon(pm);
                }
                it.intent = new Intent(Intent.ACTION_MAIN).addCategory(category)
                        .setComponent(new ComponentName(pkg, r.activityInfo.name))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                                | Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED);
                out.add(it);
            }
        }
        return out;
    }

    /**
     * Reads the user's wallpaper from the app's own folder on shared storage (no permission
     * needed): Android/data/app.calmhome/files/wallpaper.img, plus an optional wallpaper.cfg
     * holding the "dim" setting 0-100. Returns null when there is none or it can't be read.
     */
    private Wall loadWall() {
        try {
            File dir = getExternalFilesDir(null);
            if (dir == null) { wallCache = null; return null; }
            File img = new File(dir, "wallpaper.img");
            File cfg = new File(dir, "wallpaper.cfg");
            if (!img.isFile() || img.length() == 0) { wallCache = null; return null; }
            String stamp = img.lastModified() + ":" + img.length() + ":"
                    + (cfg.isFile() ? cfg.lastModified() + ":" + cfg.length() : "none");
            Wall cached = wallCache;
            if (cached != null && cached.stamp.equals(stamp)) return cached;

            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeFile(img.getPath(), bounds);
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null;

            int screenW = getResources().getDisplayMetrics().widthPixels;
            int screenH = getResources().getDisplayMetrics().heightPixels;
            BitmapFactory.Options opts = new BitmapFactory.Options();
            opts.inSampleSize = Scrim.sampleSize(bounds.outWidth, bounds.outHeight,
                    Math.min(screenW, 1920), Math.min(screenH, 1080));
            opts.inPreferredConfig = Bitmap.Config.ARGB_8888;
            Bitmap bmp = BitmapFactory.decodeFile(img.getPath(), opts);
            if (bmp == null) return null;

            // Measure the part of the picture that is actually visible (centre crop).
            int[] crop = Scrim.centerCrop(bmp.getWidth(), bmp.getHeight(), screenW, screenH);
            Bitmap visible = Bitmap.createBitmap(bmp, crop[0], crop[1], crop[2], crop[3]);
            int sw = 96;
            int sh = Math.max(8, Math.round(sw * (float) crop[3] / crop[2]));
            Bitmap small = Bitmap.createScaledBitmap(visible, sw, sh, true);
            int[] px = new int[sw * sh];
            small.getPixels(px, 0, sw, 0, 0, sw, sh);
            double[] bands = Scrim.bandLuminance(px, sw, sh, Scrim.BANDS, Scrim.PERCENTILE);

            Wall w = new Wall();
            w.bitmap = bmp;
            w.alphas = Scrim.stops(bands, Scrim.parseDim(readSmallFile(cfg)));
            w.stamp = stamp;
            wallCache = w;
            return w;
        } catch (Throwable t) {          // corrupt picture, out of memory, ...: plain background
            wallCache = null;
            return null;
        }
    }

    private static String readSmallFile(File f) {
        if (f == null || !f.isFile() || f.length() > 64) return null;
        FileInputStream in = null;
        try {
            in = new FileInputStream(f);
            byte[] buf = new byte[64];
            int n = in.read(buf);
            return n > 0 ? new String(buf, 0, n, "UTF-8") : null;
        } catch (Throwable t) {
            return null;
        } finally {
            if (in != null) {
                try { in.close(); } catch (Throwable ignored) { }
            }
        }
    }

    private void applyWall(Wall wall) {
        if (wall == null) {
            if (shownWallStamp != null) {
                wallpaperView.setImageDrawable(null);
                wallpaperView.setVisibility(View.GONE);
                scrimView.setVisibility(View.GONE);
                shownWallStamp = null;
            }
            return;
        }
        if (!wall.stamp.equals(shownWallStamp)) {
            wallpaperView.setImageBitmap(wall.bitmap);
            scrimView.setAlphas(wall.alphas);
            wallpaperView.setVisibility(View.VISIBLE);
            scrimView.setVisibility(View.VISIBLE);
            shownWallStamp = wall.stamp;
        }
    }

    /** The name the user gave an input (e.g. "Game console"); the API only exists on newer TVs. */
    private CharSequence customLabel(TvInputInfo info) {
        if (Build.VERSION.SDK_INT < 26) return null;
        try {
            return (CharSequence) TvInputInfo.class
                    .getMethod("loadCustomLabel", Context.class).invoke(info, this);
        } catch (Throwable ignored) {
            return null;
        }
    }

    // --------------------------------------------------------------- rendering

    private void render(List<Item> all, Wall wall) {
        applyWall(wall);
        ampmClock.setVisibility(DateFormat.is24HourFormat(this) ? View.GONE : View.VISIBLE);
        View focused = getCurrentFocus();
        String refocusKey = null;
        if (focused != null && focused.getTag() instanceof Item) {
            refocusKey = ((Item) focused.getTag()).key;
        }

        Set<String> hidden = new HashSet<String>(
                prefs.getStringSet("hidden", new HashSet<String>()));
        final List<String> pins = Order.parsePins(prefs.getString("pins", ""));

        List<Item> inputs = new ArrayList<Item>();
        List<Item> apps = new ArrayList<Item>();
        hiddenItems = new ArrayList<Item>();
        for (Item it : all) {
            if (it.input) inputs.add(it);
            else if (hidden.contains(it.key)) hiddenItems.add(it);
            else apps.add(it);
        }

        Order.Counter counts = new Order.Counter() {
            @Override public int launches(String key) { return prefs.getInt("n:" + key, 0); }
        };
        Order.sort(apps, pins, counts);
        Order.sort(inputs, Collections.<String>emptyList(), new Order.Counter() {
            @Override public int launches(String key) { return 0; }
        });

        final int appCount = apps.size();

        // Always-available system tiles go last.
        Item settings = new Item();
        settings.key = KEY_SETTINGS;
        settings.label = "Settings";
        settings.glyph = Glyph.Kind.SETTINGS;
        settings.intent = new Intent(Settings.ACTION_SETTINGS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        apps.add(settings);
        if (!hiddenItems.isEmpty()) {
            Item h = new Item();
            h.key = KEY_HIDDEN;
            h.label = "Hidden (" + hiddenItems.size() + ")";
            h.glyph = Glyph.Kind.HIDDEN;
            apps.add(h);
        }

        int contentWidth = getResources().getDisplayMetrics().widthPixels - 2 * px(SCREEN_MARGIN_DP);
        grid = Grid.compute(contentWidth, dp);
        int cols = grid.cols;

        content.removeAllViews();
        tileByKey.clear();
        firstTile = null;
        if (!inputs.isEmpty()) {
            addSection("Inputs", inputs.size());
            addGrid(inputs, cols);
        }
        addSection("Apps", appCount);
        addGrid(apps, cols);

        View target = refocusKey != null ? tileByKey.get(refocusKey) : null;
        if (target == null) target = firstTile;
        if (target != null) target.requestFocus();
    }

    private void addSection(String title, int count) {
        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER_VERTICAL);
        row.setPadding(px(10), px(20), px(10), px(8));

        TextView t = new TextView(this);
        t.setText(title.toUpperCase() + (count > 0 ? "  \u00b7  " + count : ""));
        t.setTextColor(DIM);
        t.setTextSize(Theme.SECTION_SP);
        t.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        t.setLetterSpacing(0.12f);
        row.addView(t);

        View line = new View(this);
        line.setBackgroundColor(Theme.HAIRLINE);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, px(1), 1f);
        lp.setMargins(px(16), 0, 0, 0);
        row.addView(line, lp);
        content.addView(row, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));
    }

    private void addGrid(List<Item> items, int cols) {
        LinearLayout row = null;
        for (int i = 0; i < items.size(); i++) {
            if (i % cols == 0) {
                row = new LinearLayout(this);
                row.setOrientation(LinearLayout.HORIZONTAL);
                row.setClipChildren(false);
                content.addView(row);
            }
            View tile = buildTile(items.get(i));
            row.addView(tile);
            if (firstTile == null) firstTile = tile;
        }
    }

    private View buildTile(final Item it) {
        LinearLayout tile = new LinearLayout(this);
        tile.setOrientation(LinearLayout.VERTICAL);
        tile.setFocusable(true);
        tile.setClickable(true);
        tile.setLongClickable(true);
        tile.setTag(it);
        tile.setClipChildren(false);
        tile.setPadding(px(Grid.PAD_DP), px(Grid.PAD_DP), px(Grid.PAD_DP), px(Grid.PAD_DP));
        tile.setBackground(focusBackground());

        FrameLayout art = new FrameLayout(this);
        art.setBackground(cardBackground());
        art.setForeground(rounded(Color.TRANSPARENT, Theme.CARD_RADIUS, Theme.STROKE, Theme.STROKE_W));
        art.setClipToOutline(true);
        art.setOutlineProvider(ViewOutlineProvider.BACKGROUND);
        if (it.art != null) {
            ImageView iv = new ImageView(this);
            iv.setImageDrawable(it.art);
            if (it.banner) {
                iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
            } else {
                iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
                iv.setPadding(px(22), px(12), px(22), px(12));
            }
            art.addView(iv, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        } else if (it.glyph != null) {
            ImageView iv = new ImageView(this);
            iv.setImageDrawable(new GlyphDrawable(it.glyph, Theme.GLYPH));
            iv.setContentDescription(it.label);
            int g = Math.min(px(Theme.GLYPH_SIZE), Math.min(grid.artW, grid.artH));
            FrameLayout.LayoutParams glp = new FrameLayout.LayoutParams(g, g);
            glp.gravity = Gravity.CENTER;
            art.addView(iv, glp);
        }
        tile.addView(art, new LinearLayout.LayoutParams(grid.artW, grid.artH));

        final TextView label = new TextView(this);
        label.setText(it.label);
        label.setTextColor(Theme.TEXT_SOFT);
        label.setTextSize(Theme.LABEL_SP);
        label.setTypeface(Typeface.create("sans-serif-medium", Typeface.NORMAL));
        label.setSingleLine(true);
        label.setEllipsize(TextUtils.TruncateAt.END);
        label.setPadding(px(2), px(9), px(2), px(3));
        tile.addView(label, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // The only animation: a small lift on focus, with the label brightening.
        tile.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override public void onFocusChange(View v, boolean focused) {
                float s = focused ? Theme.FOCUS_SCALE : 1f;
                v.animate().scaleX(s).scaleY(s).setDuration(110).start();
                v.setTranslationZ(focused ? px(Theme.FOCUS_LIFT) : 0);
                label.setTextColor(focused ? Theme.TEXT_FOCUS : Theme.TEXT_SOFT);
            }
        });
        tile.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { launch(it); }
        });
        tile.setOnLongClickListener(new View.OnLongClickListener() {
            @Override public boolean onLongClick(View v) { showOptions(it); return true; }
        });

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                grid.tileW, ViewGroup.LayoutParams.WRAP_CONTENT);
        int m = px(Grid.MARGIN_DP);
        lp.setMargins(m, m, m, m);
        tile.setLayoutParams(lp);
        tileByKey.put(it.key, tile);
        return tile;
    }

    // ----------------------------------------------------------------- actions

    private void launch(Item it) {
        if (KEY_HIDDEN.equals(it.key)) {
            showHidden();
            return;
        }
        try {
            if (!it.input && !KEY_SETTINGS.equals(it.key)) {
                prefs.edit().putInt("n:" + it.key, prefs.getInt("n:" + it.key, 0) + 1).apply();
            }
            startActivity(it.intent);
        } catch (Exception e) {
            Toast.makeText(this, "Can't open " + it.label, Toast.LENGTH_SHORT).show();
        }
    }

    private void showOptions(final Item it) {
        if (it.input || KEY_SETTINGS.equals(it.key) || KEY_HIDDEN.equals(it.key)) return;
        String[] options = { "Move to front", "Hide from home", "App info" };
        showStyled(new AlertDialog.Builder(this)
                .setTitle(it.label)
                .setItems(options, new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) {
                        if (which == 0) pin(it.key);
                        else if (which == 1) hide(it.key);
                        else openAppInfo(it.key);
                    }
                }));
    }

    private void showHidden() {
        if (hiddenItems.isEmpty()) return;
        final List<Item> list = new ArrayList<Item>(hiddenItems);
        String[] names = new String[list.size()];
        for (int i = 0; i < names.length; i++) names[i] = list.get(i).label;
        showStyled(new AlertDialog.Builder(this)
                .setTitle("Choose an app to show again")
                .setItems(names, new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) {
                        unhide(list.get(which).key);
                    }
                }));
    }

    private void pin(String key) {
        List<String> pins = Order.moveToFront(Order.parsePins(prefs.getString("pins", "")), key);
        prefs.edit().putString("pins", Order.joinPins(pins)).apply();
        reload();
    }

    private void hide(String key) {
        Set<String> hidden = new HashSet<String>(
                prefs.getStringSet("hidden", new HashSet<String>()));
        hidden.add(key);
        prefs.edit().putStringSet("hidden", hidden).apply();
        reload();
    }

    private void unhide(String key) {
        Set<String> hidden = new HashSet<String>(
                prefs.getStringSet("hidden", new HashSet<String>()));
        hidden.remove(key);
        prefs.edit().putStringSet("hidden", hidden).apply();
        reload();
    }

    private void openAppInfo(String pkg) {
        try {
            startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                    Uri.parse("package:" + pkg)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
        } catch (Exception e) {
            Toast.makeText(this, "App info isn't available on this TV", Toast.LENGTH_SHORT).show();
        }
    }

    // ----------------------------------------------------------------- helpers

    private int px(float v) {
        return Math.round(v * dp);
    }

    private GradientDrawable rounded(int fill, int radiusDp, int strokeColor, int strokeDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(px(radiusDp));
        if (strokeDp > 0) g.setStroke(px(strokeDp), strokeColor);
        return g;
    }

    /** Artwork card: a very soft top-to-bottom gradient so cards have depth on any background. */
    private Drawable cardBackground() {
        GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
                new int[] { Theme.CARD_TOP, Theme.CARD });
        g.setCornerRadius(px(Theme.CARD_RADIUS));
        return g;
    }

    /** Transparent normally; a plate with an accent ring when the tile has focus. */
    private Drawable focusBackground() {
        StateListDrawable s = new StateListDrawable();
        s.addState(new int[] { android.R.attr.state_focused },
                rounded(Theme.CARD_FOCUSED, Theme.TILE_RADIUS, Theme.ACCENT, Theme.RING));
        s.addState(new int[] {}, new ColorDrawable(Color.TRANSPARENT));
        return s;
    }

    /** Shows a dialog with the launcher's rounded dark look and a stronger dim behind it. */
    private void showStyled(AlertDialog.Builder builder) {
        AlertDialog dialog = builder.create();
        try {
            Window w = dialog.getWindow();
            if (w != null) {
                w.setBackgroundDrawable(rounded(Theme.DIALOG_BG, Theme.DIALOG_RADIUS, Theme.STROKE, Theme.STROKE_W));
                w.setDimAmount(0.65f);
            }
        } catch (Throwable ignored) {
            // keep the default look rather than fail to show the dialog
        }
        dialog.show();
    }
}
