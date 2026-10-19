package app.calmhome;

import java.util.ArrayList;
import java.util.Collections;
import java.util.Comparator;
import java.util.List;

/** Pure ordering and "pinned" helpers (no Android classes, unit-tested on a plain JVM). */
final class Order {

    interface Entry {
        String key();
        String label();
    }

    interface Counter {
        int launches(String key);
    }

    private Order() { }

    /** Pinned first (most recently pinned first), then most launched, then A to Z. Total order. */
    static <T extends Entry> void sort(List<T> items, final List<String> pins, final Counter counts) {
        Collections.sort(items, new Comparator<T>() {
            @Override public int compare(T a, T b) {
                int pa = rank(pins, a.key()), pb = rank(pins, b.key());
                if (pa != pb) return pa < pb ? -1 : 1;
                int na = counts.launches(a.key()), nb = counts.launches(b.key());
                if (na != nb) return na > nb ? -1 : 1;
                int byLabel = a.label().compareToIgnoreCase(b.label());
                if (byLabel != 0) return byLabel;
                int byLabelExact = a.label().compareTo(b.label());
                if (byLabelExact != 0) return byLabelExact;
                return a.key().compareTo(b.key());
            }
        });
    }

    private static int rank(List<String> pins, String key) {
        int i = pins.indexOf(key);
        return i < 0 ? Integer.MAX_VALUE : i;
    }

    static List<String> parsePins(String raw) {
        List<String> out = new ArrayList<String>();
        if (raw == null) return out;
        for (String part : raw.split(",")) {
            String p = part.trim();
            if (!p.isEmpty() && !out.contains(p)) out.add(p);
        }
        return out;
    }

    static String joinPins(List<String> pins) {
        StringBuilder sb = new StringBuilder();
        for (String p : pins) {
            if (sb.length() > 0) sb.append(',');
            sb.append(p);
        }
        return sb.toString();
    }

    /** Returns a new list with key first and no duplicates. */
    static List<String> moveToFront(List<String> pins, String key) {
        List<String> out = new ArrayList<String>(pins);
        out.remove(key);
        out.add(0, key);
        return out;
    }
}
