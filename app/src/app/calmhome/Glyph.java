package app.calmhome;

import java.util.ArrayList;
import java.util.List;

/**
 * The small icons on the system tiles (HDMI port, gear, hidden-eye), described as plain
 * geometry in a 0..1 square. Pure Java: the launcher draws these with a Canvas, and the tests and
 * the preview renderer read the same numbers.
 */
final class Glyph {
    enum Kind { HDMI, SETTINGS, HIDDEN }

    static final int POLY = 0, CIRCLE = 1, LINE = 2;

    /** One stroked (or filled) shape. POLY: x,y pairs. CIRCLE: cx,cy,r. LINE: x1,y1,x2,y2. */
    static final class Prim {
        final int type;
        final double[] p;
        final boolean closed;     // POLY only
        final boolean fill;
        final double width;       // stroke width as a fraction of the box (0 for fills)

        Prim(int type, double[] p, boolean closed, boolean fill, double width) {
            this.type = type;
            this.p = p;
            this.closed = closed;
            this.fill = fill;
            this.width = width;
        }
    }

    private Glyph() { }

    static List<Prim> shapes(Kind kind) {
        List<Prim> out = new ArrayList<Prim>();
        switch (kind) {
            case HDMI: hdmi(out); break;
            case SETTINGS: gear(out); break;
            default: eyeOff(out); break;
        }
        return out;
    }

    private static void hdmi(List<Prim> out) {
        // a wide, flat connector: flat top, angled lower corners
        out.add(new Prim(POLY, new double[] {
                0.10, 0.34, 0.90, 0.34, 0.90, 0.56, 0.78, 0.68, 0.22, 0.68, 0.10, 0.56 }, true, false, 0.06));
        // a comb of nine contact pins
        for (int i = 0; i < 9; i++) {
            double x = 0.24 + i * 0.065;
            out.add(new Prim(LINE, new double[] { x, 0.43, x, 0.54 }, false, false, 0.035));
        }
    }

    private static void gear(List<Prim> out) {
        int teeth = 8;
        double outer = 0.40, root = 0.31, cx = 0.5, cy = 0.5;
        double[] pts = new double[teeth * 4 * 2];
        int n = 0;
        double[] offsets = { -18, -9, 9, 18 };           // degrees around each tooth centre
        double[] radii = { root, outer, outer, root };
        for (int t = 0; t < teeth; t++) {
            for (int k = 0; k < 4; k++) {
                double a = Math.toRadians(t * 360.0 / teeth + offsets[k] - 90);
                pts[n++] = cx + radii[k] * Math.cos(a);
                pts[n++] = cy + radii[k] * Math.sin(a);
            }
        }
        out.add(new Prim(POLY, pts, true, false, 0.06));
        out.add(new Prim(CIRCLE, new double[] { cx, cy, 0.13 }, false, false, 0.06));
    }

    private static void eyeOff(List<Prim> out) {
        int steps = 24;
        double[] pts = new double[(steps + 1) * 2 * 2 - 4];
        int n = 0;
        // upper lid left to right, then lower lid right to left
        for (int i = 0; i <= steps; i++) {
            double u = i / (double) steps;
            double x = 0.10 + 0.80 * u;
            double t = (x - 0.5) / 0.40;
            pts[n++] = x;
            pts[n++] = 0.50 - 0.24 * (1 - t * t);
        }
        for (int i = steps - 1; i >= 1; i--) {
            double u = i / (double) steps;
            double x = 0.10 + 0.80 * u;
            double t = (x - 0.5) / 0.40;
            pts[n++] = x;
            pts[n++] = 0.50 + 0.24 * (1 - t * t);
        }
        double[] trimmed = new double[n];
        System.arraycopy(pts, 0, trimmed, 0, n);
        out.add(new Prim(POLY, trimmed, true, false, 0.06));
        out.add(new Prim(CIRCLE, new double[] { 0.5, 0.5, 0.10 }, false, false, 0.06));
        out.add(new Prim(LINE, new double[] { 0.22, 0.82, 0.78, 0.18 }, false, false, 0.07));
    }
}
