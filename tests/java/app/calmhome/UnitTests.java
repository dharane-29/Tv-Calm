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

    public static void main(String[] args) {
        gridSweep();
        pins();
        ordering();
        comparatorContract();
        System.out.println("Java unit tests passed (" + checks + " checks)");
    }
}
