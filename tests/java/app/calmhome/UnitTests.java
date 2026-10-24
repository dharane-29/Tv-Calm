package app.calmhome;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Random;

/** Plain-JVM tests (no Android needed). Exit code 0 = all passed. */
public class UnitTests {
    static int checks = 0;

    static void check(boolean ok, String msg) {
        checks++;
        if (!ok) throw new AssertionError(msg);
    }

    static final class E implements Order.Entry {
        final String k, l;
        E(String k, String l) { this.k = k; this.l = l; }
        public String key() { return k; }
        public String label() { return l; }
        public String toString() { return k; }
    }

    static List<String> keys(List<E> l) {
        List<String> o = new ArrayList<String>();
        for (E e : l) o.add(e.k);
        return o;
    }

    static Order.Counter counts(final Map<String, Integer> m) {
        return new Order.Counter() {
            public int launches(String key) { return m.containsKey(key) ? m.get(key) : 0; }
        };
    }

    // ------------------------------------------------------------------ Grid
    static void gridSweep() {
        int[] widths = { 640, 960, 1280, 1366, 1920, 2560, 3840, 4096 };
        float[] densities = { 0.75f, 1.0f, 1.33f, 1.5f, 2.0f, 2.5f, 3.0f, 4.0f };
        for (int w : widths) {
            for (float d : densities) {
                int content = w - 2 * Math.round(56 * d);
                if (content <= 0) continue;
                Grid g = Grid.compute(content, d);
                String ctx = w + "px @" + d + "x";
                check(g.cols >= Grid.MIN_COLS && g.cols <= Grid.MAX_COLS, "cols range " + ctx);
                check(g.tileW > 0 && g.artW > 0 && g.artH > 0, "positive sizes " + ctx);
                int rowWidth = g.cols * (g.tileW + 2 * Math.round(Grid.MARGIN_DP * d));
                check(rowWidth <= content, "row fits (" + rowWidth + " <= " + content + ") " + ctx);
                check(content - rowWidth < g.cols + 2 * g.cols,
                        "no wasted strip (" + (content - rowWidth) + "px left) " + ctx);
                int expectedH = g.artW * 9 / 16;
                check(Math.abs(g.artH - expectedH) <= 1, "16:9 " + ctx);
                int tileInner = g.tileW - 2 * Math.round(Grid.PAD_DP * d);
                if (tileInner >= 1) check(g.artW == tileInner, "art fills tile interior " + ctx);
                else check(g.artW == 1, "art clamps to 1px on absurdly small screens " + ctx);
                // On real TV widths (about 640..1920 dp) tiles must stay comfortably large.
                float widthDp = w / d;
                if (widthDp >= 640 && widthDp <= 1920) {
                    check(g.tileW / d >= 100f, "tile >= 100dp (" + (g.tileW / d) + ") " + ctx);
                }
            }
        }
        // Reference case used in the README mockup: 1080p at density 2.0 => 5 columns.
        check(Grid.compute(1920 - 2 * 112, 2.0f).cols == 5, "1080p@2.0 gives 5 columns");
        // Degenerate input must not throw or divide by zero.
        check(Grid.compute(0, 0f).cols == Grid.MIN_COLS, "zero width");
        check(Grid.compute(-50, -1f).tileW >= 1, "negative inputs");
    }

    // ----------------------------------------------------------------- Order
    static void pins() {
        check(Order.parsePins(null).isEmpty(), "null pins");
        check(Order.parsePins("").isEmpty(), "empty pins");
        check(Order.parsePins(",,").isEmpty(), "only commas");
        check(Order.parsePins("a, b ,a,,c").equals(Arrays.asList("a", "b", "c")), "trim and dedupe");
        List<String> p = Arrays.asList("a", "b", "c");
        check(Order.joinPins(p).equals("a,b,c"), "join");
        check(Order.parsePins(Order.joinPins(p)).equals(p), "round trip");
        check(Order.joinPins(new ArrayList<String>()).equals(""), "join empty");
        check(Order.moveToFront(p, "c").equals(Arrays.asList("c", "a", "b")), "move existing");
        check(Order.moveToFront(p, "z").equals(Arrays.asList("z", "a", "b", "c")), "move new");
        check(Order.moveToFront(Arrays.asList("a"), "a").equals(Arrays.asList("a")), "idempotent");
        check(p.equals(Arrays.asList("a", "b", "c")), "input list not mutated");
    }

    static void ordering() {
        List<E> items = new ArrayList<E>(Arrays.asList(
                new E("k.zed", "Zed"), new E("k.apple", "apple"), new E("k.Banana", "Banana"),
                new E("k.most", "Most used"), new E("k.pinned", "Pinned one")));
        Map<String, Integer> n = new HashMap<String, Integer>();
        n.put("k.most", 9); n.put("k.zed", 2);
        Order.sort(items, Arrays.asList("k.pinned"), counts(n));
        check(keys(items).equals(Arrays.asList("k.pinned", "k.most", "k.zed", "k.apple", "k.Banana")),
                "pinned, then most launched, then A-Z ignoring case: " + keys(items));

        // Pin order: most recently pinned first.
        items = new ArrayList<E>(Arrays.asList(new E("a", "A"), new E("b", "B"), new E("c", "C")));
        Order.sort(items, Arrays.asList("c", "a"), counts(new HashMap<String, Integer>()));
        check(keys(items).equals(Arrays.asList("c", "a", "b")), "pin order respected");

        // Deterministic for identical labels (tie-break on key).
        items = new ArrayList<E>(Arrays.asList(new E("p2", "Same"), new E("p1", "Same"), new E("p3", "same")));
        Order.sort(items, new ArrayList<String>(), counts(new HashMap<String, Integer>()));
        List<String> first = keys(items);
        Collections.reverse(items);
        Order.sort(items, new ArrayList<String>(), counts(new HashMap<String, Integer>()));
        check(first.equals(keys(items)), "stable regardless of input order");

        // Empty and single lists.
        Order.sort(new ArrayList<E>(), new ArrayList<String>(), counts(new HashMap<String, Integer>()));
        List<E> one = new ArrayList<E>(Arrays.asList(new E("x", "X")));
        Order.sort(one, new ArrayList<String>(), counts(new HashMap<String, Integer>()));
        check(one.size() == 1, "single element");
    }

    /** TimSort throws if the comparator is not a consistent total order. Hammer it. */
    static void comparatorContract() {
        Random r = new Random(42);
        for (int round = 0; round < 300; round++) {
            int size = 1 + r.nextInt(200);
            List<E> items = new ArrayList<E>();
            Map<String, Integer> n = new HashMap<String, Integer>();
            List<String> pins = new ArrayList<String>();
            for (int i = 0; i < size; i++) {
                String key = "pkg." + r.nextInt(80);          // duplicates in key space on purpose
                String label = "L" + (char) ('a' + r.nextInt(6)) + (r.nextBoolean() ? "X" : "x");
                items.add(new E(key, label));
                if (r.nextInt(4) == 0) n.put(key, r.nextInt(5));
                if (r.nextInt(10) == 0) pins.add(key);
            }
            List<String> dedup = Order.parsePins(Order.joinPins(pins));
            Order.sort(items, dedup, counts(n));               // must not throw
            for (int i = 1; i < items.size(); i++) {
                E a = items.get(i - 1), b = items.get(i);
                int pa = dedup.indexOf(a.k) < 0 ? Integer.MAX_VALUE : dedup.indexOf(a.k);
                int pb = dedup.indexOf(b.k) < 0 ? Integer.MAX_VALUE : dedup.indexOf(b.k);
                check(pa <= pb, "pin ranks non-decreasing");
            }
        }
    }


    // ----------------------------------------------------------------- Scrim
    static int grey(int g) { return (g << 16) | (g << 8) | g; }

    static void scrimMaths() {
        check(Scrim.luminance(0x000000) == 0.0, "black luminance");
        check(Math.abs(Scrim.luminance(0xFFFFFF) - 1.0) < 1e-9, "white luminance");
        check(Math.abs(Scrim.contrast(1.0, 0.0) - 21.0) < 1e-9, "max contrast is 21");
        for (double y = 0; y <= 1.0001; y += 0.01) {
            double back = Scrim.luminance(grey(Scrim.greyFromLuminance(y)));
            check(Math.abs(back - y) < 0.01, "grey round trip at " + y);
        }
        double prev = -1;
        for (double y = 0; y <= 1.0001; y += 0.01) {
            double a = Scrim.requiredAlpha(y);
            check(a >= prev - 1e-9, "required alpha is non-decreasing at " + y);
            check(a >= 0 && a < Scrim.MAX_ALPHA, "required alpha stays below the cap at " + y);
            prev = a;
            int g = Scrim.greyFromLuminance(y);
            int shown = Scrim.blend(Scrim.BASE, a, grey(g));
            double c = Scrim.contrast(Scrim.luminance(Scrim.DIM_TEXT), Scrim.luminance(shown));
            check(c >= Scrim.TARGET_CONTRAST - 0.02, "contrast met at luminance " + y + " (got " + c + ")");
        }
        check(Scrim.requiredAlpha(0.0) == 0.0, "a dark wallpaper needs no extra darkening");
        // The worst possible wallpaper (pure white) still gives readable text after darkening.
        int worst = Scrim.blend(Scrim.BASE, Scrim.requiredAlpha(1.0), 0xFFFFFF);
        check(Scrim.contrast(Scrim.luminance(Scrim.DIM_TEXT), Scrim.luminance(worst)) >= 4.5, "white wallpaper readable");
        check(Scrim.contrast(Scrim.luminance(Scrim.TEXT), Scrim.luminance(worst)) >= 7.0, "main text on white wallpaper");
    }

    static void scrimAnalysis() {
        int w = 40, h = 40;
        int[] white = new int[w * h], black = new int[w * h], split = new int[w * h], clear = new int[w * h];
        for (int i = 0; i < w * h; i++) {
            white[i] = 0xFFFFFFFF; black[i] = 0xFF000000; clear[i] = 0x00FFFFFF;
            split[i] = (i / w < h / 2) ? 0xFFFFFFFF : 0xFF000000;
        }
        for (double v : Scrim.bandLuminance(white, w, h, 8, 0.95)) check(v > 0.99, "white image is bright");
        for (double v : Scrim.bandLuminance(black, w, h, 8, 0.95)) check(v < 0.001, "black image is dark");
        for (double v : Scrim.bandLuminance(clear, w, h, 8, 0.95)) check(v < 0.001, "transparent pixels show the dark base");
        double[] sp = Scrim.bandLuminance(split, w, h, 8, 0.95);
        for (int k = 0; k < 8; k++) check(k < 4 ? sp[k] > 0.99 : sp[k] < 0.001, "split image band " + k);
        // A few bright specks must not darken the whole band; a large bright area must.
        int[] specks = new int[w * h], patch = new int[w * h];
        java.util.Arrays.fill(specks, 0xFF000000); java.util.Arrays.fill(patch, 0xFF000000);
        for (int i = 0; i < 30; i++) specks[i * 7] = 0xFFFFFFFF;            // 30 of 1600 pixels (< 5%)
        for (int i = 0; i < 400; i++) patch[i] = 0xFFFFFFFF;                // a quarter of the picture
        check(Scrim.bandLuminance(specks, w, h, 1, 0.95)[0] < 0.01, "specks ignored");
                check(Scrim.bandLuminance(patch, w, h, 4, 0.95)[0] > 0.99, "bright band detected");
        // Bad input never throws and assumes the worst.
        for (double v : Scrim.bandLuminance(null, 10, 10, 8, 0.95)) check(v == 1.0, "null pixels");
        for (double v : Scrim.bandLuminance(new int[5], 10, 10, 8, 0.95)) check(v == 1.0, "short pixels");
        for (double v : Scrim.bandLuminance(white, 0, 0, 8, 0.95)) check(v == 1.0, "zero size");
        check(Scrim.bandLuminance(new int[3], 3, 1, 8, 0.95).length == 8, "tiny picture, many bands");
    }

    static void scrimStops() {
        double[] dark = new double[Scrim.BANDS], bright = new double[Scrim.BANDS];
        java.util.Arrays.fill(bright, 1.0);
        float[] d0 = Scrim.stops(dark, 0), d100 = Scrim.stops(dark, 100), b0 = Scrim.stops(bright, 0);
        check(d0.length == Scrim.BANDS + 1, "stop count");
        for (int j = 0; j < d0.length; j++) {
            check(d0[j] >= 0f && d0[j] <= Scrim.MAX_ALPHA, "alpha in range");
            check(d100[j] >= d0[j], "more dim is never lighter");
            check(b0[j] >= Scrim.requiredAlpha(1.0) - 1e-6, "bright wallpaper is darkened enough");
            if (j > 0) check(d0[j] >= d0[j - 1] - 1e-6, "soft gradient gets darker downwards");
        }
        check(d0[0] >= 0.16f, "even a dark wallpaper gets a visible soft gradient");
        float[] b100 = Scrim.stops(bright, 100), b40 = Scrim.stops(bright, 40);
        for (int j = 0; j < b0.length; j++) {
            check(b40[j] > b0[j] + 0.01f && b100[j] > b40[j] + 0.01f, "dim setting always has an effect, even on bright pictures");
            check(b100[j] <= Scrim.MAX_ALPHA, "never above the cap");
        }
        check(d100[0] - d0[0] > 0.3f, "dim setting has a large effect on dark pictures");
        check(Scrim.stops(null, 40).length == Scrim.BANDS + 1, "null band data handled");
        check(Scrim.alphaAt(d0, 0.0) == d0[0] && Scrim.alphaAt(d0, 1.0) == d0[Scrim.BANDS], "alphaAt ends");
        check(Scrim.alphaAt(d0, -5) == d0[0] && Scrim.alphaAt(d0, 5) == d0[Scrim.BANDS], "alphaAt clamps");

        // Property: at EVERY point inside a band, the alpha is at least what that band needs.
        Random r = new Random(7);
        for (int round = 0; round < 2000; round++) {
            double[] lum = new double[Scrim.BANDS];
            for (int k = 0; k < lum.length; k++) lum[k] = r.nextDouble();
            float[] st = Scrim.stops(lum, r.nextInt(101));
            for (int k = 0; k < lum.length; k++) {
                for (int step = 0; step <= 10; step++) {
                    double y01 = (k + step / 10.0) / lum.length;
                    check(Scrim.alphaAt(st, y01) >= Scrim.requiredAlpha(lum[k]) - 1e-6,
                            "interpolated alpha covers band " + k);
                }
            }
        }
    }

    /** Whole pipeline on synthetic wallpapers: measure -> darken -> check text contrast per pixel. */
    static void scrimEndToEnd() {
        final int w = 96, h = 54;
        Random r = new Random(11);
        String[] names = { "white", "black", "mid grey", "noise", "h-gradient", "v-gradient",
                "bright top / dark bottom", "dark top / bright bottom", "checker", "saturated colours", "sunset" };
        for (int n = 0; n < names.length; n++) {
            int[] px = new int[w * h];
            for (int y = 0; y < h; y++) {
                for (int x = 0; x < w; x++) {
                    int v;
                    switch (n) {
                        case 0: v = grey(255); break;
                        case 1: v = grey(0); break;
                        case 2: v = grey(128); break;
                        case 3: v = (r.nextInt(256) << 16) | (r.nextInt(256) << 8) | r.nextInt(256); break;
                        case 4: v = grey(x * 255 / (w - 1)); break;
                        case 5: v = grey(y * 255 / (h - 1)); break;
                        case 6: v = grey(255 - y * 255 / (h - 1)); break;
                        case 7: v = grey(y * 255 / (h - 1)); break;
                        case 8: v = ((x / 6 + y / 6) % 2 == 0) ? grey(255) : grey(20); break;
                        case 9: v = new int[] { 0xFF0000, 0x00FF00, 0xFFFF00, 0x00FFFF, 0xFF00FF }[(x / 10) % 5]; break;
                        default: v = ((255 - y * 3 / 2) << 16) | ((140 - y) << 8) | (80 + x); break;
                    }
                    px[y * w + x] = 0xFF000000 | (v & 0xFFFFFF);
                }
            }
            double[] bands = Scrim.bandLuminance(px, w, h, Scrim.BANDS, Scrim.PERCENTILE);
            for (int dim : new int[] { 0, 40, 100 }) {
                float[] st = Scrim.stops(bands, dim);
                int ok45 = 0, ok30 = 0, okMain = 0;
                for (int y = 0; y < h; y++) {
                    double a = Scrim.alphaAt(st, (y + 0.5) / h);
                    for (int x = 0; x < w; x++) {
                        int shown = Scrim.blend(Scrim.BASE, a, px[y * w + x] & 0xFFFFFF);
                        double lum = Scrim.luminance(shown);
                        double c = Scrim.contrast(Scrim.luminance(Scrim.DIM_TEXT), lum);
                        if (c >= 4.5) ok45++;
                        if (c >= 3.0) ok30++;
                        if (Scrim.contrast(Scrim.luminance(Scrim.TEXT), lum) >= 4.5) okMain++;
                    }
                }
                double total = w * h;
                check(ok45 / total >= 0.94, names[n] + " dim " + dim + ": " + (100 * ok45 / total) + "% of pixels meet 4.5:1");
                check(ok30 / total >= 0.985, names[n] + " dim " + dim + ": " + (100 * ok30 / total) + "% meet 3:1");
                check(okMain / total >= 0.99, names[n] + " dim " + dim + ": main text readable");
            }
        }
    }

    static void scrimHelpers() {
        String[] in = { "40", " 75\n", "150", "-5", "abc", "", null, "50.5", "0", "100", "  " };
        int[] want = { 40, 75, 100, 0, 40, 40, 40, 40, 0, 100, 40 };
        for (int i = 0; i < in.length; i++) check(Scrim.parseDim(in[i]) == want[i], "parseDim(" + in[i] + ")");
        check(Scrim.sampleSize(4000, 3000, 1920, 1080) == 2, "sample 4000x3000");
        check(Scrim.sampleSize(3840, 2160, 1920, 1080) == 2, "sample 4K");
        check(Scrim.sampleSize(1920, 1080, 1920, 1080) == 1, "sample 1080p");
        check(Scrim.sampleSize(1000, 500, 1920, 1080) == 1, "small picture not upscaled");
        check(Scrim.sampleSize(8000, 6000, 1920, 1080) == 4, "sample 8000x6000");
        check(Scrim.sampleSize(0, 0, 1920, 1080) == 1, "sample zero");
        Random r = new Random(5);
        for (int i = 0; i < 3000; i++) {
            int sw = 100 + r.nextInt(9000), sh = 100 + r.nextInt(9000), dw = 640 + r.nextInt(3200);
            int dh = Math.max(1, (int) (dw / (1.3 + r.nextDouble() * 1.1)));
            int s = Scrim.sampleSize(sw, sh, dw, dh);
            check(s >= 1 && (s & (s - 1)) == 0, "power of two");
            if (sw >= dw && sh >= dh) check(sw / s >= dw && sh / s >= dh, "decoded picture still covers the screen");
            int[] c = Scrim.centerCrop(sw, sh, dw, dh);
            check(c[0] >= 0 && c[1] >= 0 && c[2] > 0 && c[3] > 0 && c[0] + c[2] <= sw && c[1] + c[3] <= sh, "crop inside picture");
            double asp = (double) dw / dh;       // integer truncation can only shift the shape by this much
            check(Math.abs((double) c[2] / c[3] - asp) <= (asp + 1.0) / c[3] + 1e-9, "crop matches screen shape");
            check(Math.abs(c[0] - (sw - c[0] - c[2])) <= 1 && Math.abs(c[1] - (sh - c[1] - c[3])) <= 1, "crop is centred");
        }
        int[] c = Scrim.centerCrop(4000, 3000, 1920, 1080);
        check(c[0] == 0 && c[1] == 375 && c[2] == 4000 && c[3] == 2250, "known crop");
        check(Scrim.centerCrop(0, 0, 10, 10)[2] >= 1, "degenerate crop");
    }

    // ----------------------------------------------------------------- Theme and Glyph
    static double lum(int argb) { return Scrim.luminance(argb & 0xFFFFFF); }
    static double ratio(int a, int b) { return Scrim.contrast(lum(a), lum(b)); }
    static int over(int argb, int under) { return Scrim.blend(argb & 0xFFFFFF, ((argb >>> 24) & 255) / 255.0, under & 0xFFFFFF); }

    static void themeTokens() {
        // text is readable on every surface it appears on (WCAG AA is 4.5; large text 3)
        check(ratio(Theme.TEXT_SOFT, Theme.BG) >= 7.0, "unfocused label on background");
        check(ratio(Theme.TEXT_SOFT, Theme.CARD_FOCUSED) >= 7.0, "unfocused label on focus plate");
        check(ratio(Theme.TEXT_FOCUS, Theme.CARD_FOCUSED) >= 10.0, "focused label on focus plate");
        check(ratio(Theme.TEXT, Theme.BG) >= 12.0, "clock on background");
        check(ratio(Theme.DIM, Theme.BG) >= 7.0, "section titles / date on background");
        check(ratio(Theme.DIM, Theme.CARD) >= 4.5 && ratio(Theme.DIM, Theme.CARD_TOP) >= 4.5, "dim text on cards");
        check(ratio(Theme.TEXT, Theme.DIALOG_BG) >= 10.0, "dialog text");
        // The wallpaper scrim guarantees DIM_TEXT is readable; every other label colour is brighter.
        check(lum(Theme.TEXT_SOFT) >= lum(Theme.DIM) && lum(Theme.TEXT_FOCUS) >= lum(Theme.TEXT_SOFT)
                && lum(Theme.TEXT) >= lum(Theme.DIM), "all label colours are at least as bright as the guaranteed one");
        // non-text parts need 3:1
        check(ratio(Theme.ACCENT, Theme.BG) >= 3.0, "focus ring on background");
        check(ratio(Theme.ACCENT, Theme.CARD_FOCUSED) >= 3.0, "focus ring on its own plate");
        check(ratio(Theme.GLYPH, Theme.CARD) >= 3.0 && ratio(Theme.GLYPH, Theme.CARD_TOP) >= 3.0, "icons on cards");
        // subtle lines: visible but never loud
        double hair = ratio(over(Theme.HAIRLINE, Theme.BG), Theme.BG);
        check(hair >= 1.1 && hair <= 2.0, "divider is visible but subtle (" + hair + ")");
        double edge = ratio(over(Theme.STROKE, Theme.CARD), Theme.CARD);
        check(edge >= 1.15 && edge <= 2.5, "card edge is visible but subtle (" + edge + ")");
        double sheen = ratio(Theme.CARD_TOP, Theme.CARD);
        check(sheen > 1.0 && sheen < 1.3, "card gradient is soft (" + sheen + ")");
        // sizes: legible from a sofa, hierarchy preserved
        check(Theme.LABEL_SP >= 14 && Theme.SECTION_SP >= 14 && Theme.DATE_SP >= 16 && Theme.AMPM_SP >= 16, "minimum text sizes");
        check(Theme.CLOCK_SP > Theme.DATE_SP && Theme.DATE_SP >= Theme.LABEL_SP, "type hierarchy");
        check(Theme.FOCUS_SCALE > 1.02f && Theme.FOCUS_SCALE < 1.12f, "focus lift is noticeable but contained");
        check(Theme.TILE_RADIUS > Theme.CARD_RADIUS, "plate is rounder than the card it frames");
        check(((Theme.STROKE >>> 24) & 255) > 0 && ((Theme.STROKE >>> 24) & 255) < 0x80, "stroke is translucent");
        check(((Theme.HAIRLINE >>> 24) & 255) > 0 && ((Theme.HAIRLINE >>> 24) & 255) < 0x80, "hairline is translucent");
    }

    static int polyCount(Glyph.Prim p) { return p.p.length / 2; }

    static boolean hasPoint(double[] pts, double x, double y) {
        for (int i = 0; i + 1 < pts.length; i += 2) {
            if (Math.abs(pts[i] - x) < 1e-6 && Math.abs(pts[i + 1] - y) < 1e-6) return true;
        }
        return false;
    }

    static void glyphGeometry() {
        for (Glyph.Kind k : Glyph.Kind.values()) {
            java.util.List<Glyph.Prim> shapes = Glyph.shapes(k);
            check(!shapes.isEmpty(), k + " has shapes");
            for (Glyph.Prim s : shapes) {
                check(s.fill || s.width > 0, k + " strokes have a width");
                check(s.width < 0.2, k + " strokes are not absurdly thick");
                double lo = 1, hi = 0;
                if (s.type == Glyph.POLY) {
                    check(s.p.length % 2 == 0 && s.p.length >= 6, k + " polygon has >= 3 points");
                    for (double v : s.p) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
                } else if (s.type == Glyph.CIRCLE) {
                    check(s.p.length == 3 && s.p[2] > 0, k + " circle");
                    lo = Math.min(s.p[0], s.p[1]) - s.p[2];
                    hi = Math.max(s.p[0], s.p[1]) + s.p[2];
                } else {
                    check(s.p.length == 4, k + " line");
                    for (double v : s.p) { lo = Math.min(lo, v); hi = Math.max(hi, v); }
                }
                check(lo >= 0.05 && hi <= 0.95, k + " shape stays inside the box (" + lo + ".." + hi + ")");
                check(lo - s.width / 2 >= 0 && hi + s.width / 2 <= 1, k + " strokes are not clipped");
            }
        }
        // Gear: 8 teeth => 32 vertices, with 8-fold rotational symmetry.
        Glyph.Prim gear = Glyph.shapes(Glyph.Kind.SETTINGS).get(0);
        check(gear.closed && polyCount(gear) == 32, "gear has 8 teeth");
        for (int i = 0; i + 1 < gear.p.length; i += 2) {
            double dx = gear.p[i] - 0.5, dy = gear.p[i + 1] - 0.5, a = Math.toRadians(45);
            check(hasPoint(gear.p, 0.5 + dx * Math.cos(a) - dy * Math.sin(a), 0.5 + dx * Math.sin(a) + dy * Math.cos(a)),
                    "gear is symmetric under a 45 degree turn");
        }
        // HDMI: connector + 9 evenly spaced pins; left/right mirror symmetric.
        java.util.List<Glyph.Prim> hdmi = Glyph.shapes(Glyph.Kind.HDMI);
        int pins = 0, lines = 0;
        for (Glyph.Prim s : hdmi) if (s.type == Glyph.LINE) { lines++; if (Math.abs(s.p[1] - 0.43) < 1e-9) pins++; }
        check(pins == 9 && lines == 9, "HDMI has nine pins and nothing else (no cable stub)");
        double prevX = -1;
        for (Glyph.Prim s : hdmi) {
            if (s.type != Glyph.LINE) continue;
            check(s.p[0] > prevX && (prevX < 0 || Math.abs(s.p[0] - prevX - 0.065) < 1e-9), "pins are evenly spaced");
            check(Math.abs(s.p[0] - 0.5) <= 0.26 + 1e-9, "pins sit inside the connector body");
            prevX = s.p[0];
        }
        Glyph.Prim body = hdmi.get(0);
        for (int i = 0; i + 1 < body.p.length; i += 2) check(hasPoint(body.p, 1 - body.p[i], body.p[i + 1]), "HDMI body is mirror symmetric");
        // Hidden: lens symmetric both ways, with a slash from lower-left to upper-right.
        java.util.List<Glyph.Prim> eye = Glyph.shapes(Glyph.Kind.HIDDEN);
        Glyph.Prim lens = eye.get(0);
        for (int i = 0; i + 1 < lens.p.length; i += 2) {
            check(hasPoint(lens.p, 1 - lens.p[i], lens.p[i + 1]), "eye is left/right symmetric");
            check(hasPoint(lens.p, lens.p[i], 1 - lens.p[i + 1]), "eye is top/bottom symmetric");
        }
        Glyph.Prim slash = eye.get(2);
        check(slash.type == Glyph.LINE && slash.p[0] < slash.p[2] && slash.p[1] > slash.p[3], "slash runs up and to the right");
    }

    public static void main(String[] args) {
        gridSweep();
        pins();
        ordering();
        comparatorContract();
        scrimMaths();
        scrimAnalysis();
        scrimStops();
        scrimEndToEnd();
        scrimHelpers();
        themeTokens();
        glyphGeometry();
        System.out.println("Java unit tests passed (" + checks + " checks)");
    }
}
