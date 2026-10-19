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
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.graphics.drawable.Drawable;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.StateListDrawable;
import android.media.tv.TvContract;
import android.media.tv.TvInputInfo;
import android.media.tv.TvInputManager;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.ViewOutlineProvider;
import android.widget.FrameLayout;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextClock;
import android.widget.TextView;
import android.widget.Toast;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
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

    private static final int BG = 0xFF0D1117;
    private static final int CARD = 0xFF1A2029;
    private static final int TEXT = 0xFFE6EDF3;
    private static final int DIM = 0xFF8B949E;
    private static final int ACCENT = 0xFF58A6FF;

    private static final int TILE_W = 200;   // dp, outer width of a tile
    private static final int IMG_W = 188;    // dp, artwork width
    private static final int IMG_H = 106;    // dp, artwork height (about 16:9)

    private static class Item {
        String key;
        String label;
        String badge;      // text shown instead of artwork (HDMI, Settings...)
        Drawable art;      // banner or icon
        boolean banner;    // true: art fills the card; false: art is a centred icon
        boolean input;
        Intent intent;
    }

    private final Handler ui = new Handler(Looper.getMainLooper());
    private SharedPreferences prefs;
    private LinearLayout content;
    private ScrollView scroll;
    private float dp;
    private int generation;

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

        LinearLayout column = new LinearLayout(this);
        column.setOrientation(LinearLayout.VERTICAL);
        // TV overscan-safe margins.
        column.setPadding(px(56), px(28), px(56), 0);
        column.addView(buildHeader());

        scroll = new ScrollView(this);
        scroll.setVerticalScrollBarEnabled(false);
        scroll.setClipChildren(false);
        scroll.setClipToPadding(false);
        scroll.setPadding(0, px(12), 0, px(40));

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
        time.setFormat12Hour("h:mm a");
        time.setFormat24Hour("HH:mm");
        time.setTextSize(44);
        time.setTextColor(TEXT);
        time.setTypeface(Typeface.create("sans-serif-light", Typeface.NORMAL));
        header.addView(time);

        TextClock date = new TextClock(this);
        date.setFormat12Hour("EEEE, d MMMM");
        date.setFormat24Hour("EEEE, d MMMM");
        date.setTextSize(18);
        date.setTextColor(DIM);
        date.setPadding(px(20), 0, 0, px(10));
        header.addView(date);
        return header;
    }

    // ---------------------------------------------------------------- loading

    /** Query packages on a worker thread; build views on the UI thread. */
    private void reload() {
        final int mine = ++generation;
        new Thread(new Runnable() {
            @Override public void run() {
                final List<Item> all = loadAll();
                ui.post(new Runnable() {
                    @Override public void run() {
                        if (mine == generation && !isFinishing()) render(all);
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
                    CharSequence label = info.loadCustomLabel(this);
                    if (label == null || label.length() == 0) label = info.loadLabel(this);
                    Item it = new Item();
                    it.key = "in:" + info.getId();
                    it.label = String.valueOf(label);
                    it.badge = "HDMI";
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

    // --------------------------------------------------------------- rendering

    private void render(List<Item> all) {
        View focused = getCurrentFocus();
        String refocusKey = null;
        if (focused != null && focused.getTag() instanceof Item) {
            refocusKey = ((Item) focused.getTag()).key;
        }

        Set<String> hidden = new HashSet<String>(
                prefs.getStringSet("hidden", new HashSet<String>()));
        final List<String> pins = new ArrayList<String>(
                Arrays.asList(prefs.getString("pins", "").split(",")));
        pins.remove("");

        List<Item> inputs = new ArrayList<Item>();
        List<Item> apps = new ArrayList<Item>();
        hiddenItems = new ArrayList<Item>();
        for (Item it : all) {
            if (it.input) inputs.add(it);
            else if (hidden.contains(it.key)) hiddenItems.add(it);
            else apps.add(it);
        }

        Collections.sort(apps, new Comparator<Item>() {
            @Override public int compare(Item a, Item b) {
                int pa = pins.indexOf(a.key), pb = pins.indexOf(b.key);
                if (pa < 0) pa = Integer.MAX_VALUE;
                if (pb < 0) pb = Integer.MAX_VALUE;
                if (pa != pb) return pa < pb ? -1 : 1;
                int na = prefs.getInt("n:" + a.key, 0), nb = prefs.getInt("n:" + b.key, 0);
                if (na != nb) return na > nb ? -1 : 1;
                return a.label.compareToIgnoreCase(b.label);
            }
        });
        Collections.sort(inputs, new Comparator<Item>() {
            @Override public int compare(Item a, Item b) {
                return a.label.compareToIgnoreCase(b.label);
            }
        });

        // Always-available system tiles go last.
        Item settings = new Item();
        settings.key = KEY_SETTINGS;
        settings.label = "Settings";
        settings.badge = "SETTINGS";
        settings.intent = new Intent(Settings.ACTION_SETTINGS)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        apps.add(settings);
        if (!hiddenItems.isEmpty()) {
            Item h = new Item();
            h.key = KEY_HIDDEN;
            h.label = "Hidden (" + hiddenItems.size() + ")";
            h.badge = "HIDDEN";
            apps.add(h);
        }

        int usable = getResources().getDisplayMetrics().widthPixels - px(112);
        int cols = Math.max(3, usable / px(TILE_W + 20));

        content.removeAllViews();
        tileByKey.clear();
        firstTile = null;
        if (!inputs.isEmpty()) {
            addSection("Inputs");
            addGrid(inputs, cols);
        }
        addSection("Apps");
        addGrid(apps, cols);

        View target = refocusKey != null ? tileByKey.get(refocusKey) : null;
        if (target == null) target = firstTile;
        if (target != null) target.requestFocus();
    }

    private void addSection(String title) {
        TextView t = new TextView(this);
        t.setText(title.toUpperCase());
        t.setTextColor(DIM);
        t.setTextSize(13);
        t.setLetterSpacing(0.12f);
        t.setPadding(px(10), px(18), 0, px(6));
        content.addView(t);
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
        tile.setPadding(px(6), px(6), px(6), px(6));
        tile.setBackground(focusBackground());

        FrameLayout art = new FrameLayout(this);
        art.setBackground(rounded(CARD, 8, 0, 0));
        art.setClipToOutline(true);
        art.setOutlineProvider(ViewOutlineProvider.BACKGROUND);
        if (it.art != null) {
            ImageView iv = new ImageView(this);
            iv.setImageDrawable(it.art);
            if (it.banner) {
                iv.setScaleType(ImageView.ScaleType.CENTER_CROP);
            } else {
                iv.setScaleType(ImageView.ScaleType.FIT_CENTER);
                iv.setPadding(px(30), px(18), px(30), px(18));
            }
            art.addView(iv, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        } else {
            TextView badge = new TextView(this);
            badge.setText(it.badge == null ? "" : it.badge);
            badge.setTextColor(DIM);
            badge.setTextSize(16);
            badge.setTypeface(Typeface.DEFAULT_BOLD);
            badge.setLetterSpacing(0.15f);
            badge.setGravity(Gravity.CENTER);
            art.addView(badge, new FrameLayout.LayoutParams(
                    ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        }
        tile.addView(art, new LinearLayout.LayoutParams(px(IMG_W), px(IMG_H)));

        TextView label = new TextView(this);
        label.setText(it.label);
        label.setTextColor(TEXT);
        label.setTextSize(14);
        label.setSingleLine(true);
        label.setEllipsize(TextUtils.TruncateAt.END);
        label.setPadding(px(2), px(8), px(2), px(2));
        tile.addView(label, new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT));

        // The only animation: a small lift on focus.
        tile.setOnFocusChangeListener(new View.OnFocusChangeListener() {
            @Override public void onFocusChange(View v, boolean focused) {
                float s = focused ? 1.07f : 1f;
                v.animate().scaleX(s).scaleY(s).setDuration(100).start();
                v.setTranslationZ(focused ? px(8) : 0);
            }
        });
        tile.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) { launch(it); }
        });
        tile.setOnLongClickListener(new View.OnLongClickListener() {
            @Override public boolean onLongClick(View v) { showOptions(it); return true; }
        });

        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                px(TILE_W), ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(px(5), px(5), px(5), px(5));
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
        new AlertDialog.Builder(this)
                .setTitle(it.label)
                .setItems(options, new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) {
                        if (which == 0) pin(it.key);
                        else if (which == 1) hide(it.key);
                        else openAppInfo(it.key);
                    }
                })
                .show();
    }

    private void showHidden() {
        if (hiddenItems.isEmpty()) return;
        final List<Item> list = new ArrayList<Item>(hiddenItems);
        String[] names = new String[list.size()];
        for (int i = 0; i < names.length; i++) names[i] = list.get(i).label;
        new AlertDialog.Builder(this)
                .setTitle("Tap an app to show it again")
                .setItems(names, new DialogInterface.OnClickListener() {
                    @Override public void onClick(DialogInterface d, int which) {
                        unhide(list.get(which).key);
                    }
                })
                .show();
    }

    private void pin(String key) {
        List<String> pins = new ArrayList<String>(
                Arrays.asList(prefs.getString("pins", "").split(",")));
        pins.remove("");
        pins.remove(key);
        pins.add(0, key);
        prefs.edit().putString("pins", TextUtils.join(",", pins)).apply();
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

    private Drawable focusBackground() {
        StateListDrawable s = new StateListDrawable();
        s.addState(new int[] { android.R.attr.state_focused },
                rounded(0xFF2A3342, 12, ACCENT, 2));
        s.addState(new int[] {}, new ColorDrawable(Color.TRANSPARENT));
        return s;
    }
}
