package app.calmhome;

import java.util.Arrays;

/**
 * Pure maths for the wallpaper's dark gradient (no Android classes; unit-tested on a plain JVM).
 *
 * The launcher measures how bright each horizontal band of the wallpaper is, then darkens each
 * band just enough that the dimmest text colour keeps a readable contrast. The user's "dim"
 * setting adds a soft top-to-bottom gradient on top of that.
 */
final class Scrim {
    static final int BASE = 0xFF0D1117;       // the overlay colour (same as the plain background)
    static final int TEXT = 0xFFE6EDF3;
    static final int DIM_TEXT = 0xFFA8B1BC;   // the weakest text colour in the UI
    static final int BANDS = 8;
    static final int DEFAULT_DIM = 40;
    static final double TARGET_CONTRAST = 4.7;  // WCAG AA is 4.5; small safety margin
    static final double PERCENTILE = 0.95;      // ignore the brightest 5% specks in a band
    static final float MAX_ALPHA = 0.95f;       // the picture never disappears completely

    private static final double[] CHANNEL = new double[256];
    static {
        for (int i = 0; i < 256; i++) {
            double c = i / 255.0;
            CHANNEL[i] = c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
        }
    }

    private Scrim() { }

    // ------------------------------------------------------------------ colour maths

    static double luminance(int rgb) {
        return 0.2126 * CHANNEL[(rgb >> 16) & 255] + 0.7152 * CHANNEL[(rgb >> 8) & 255]
                + 0.0722 * CHANNEL[rgb & 255];
    }

    static double contrast(double lumA, double lumB) {
        double hi = Math.max(lumA, lumB), lo = Math.min(lumA, lumB);
        return (hi + 0.05) / (lo + 0.05);
    }

    private static int clamp8(double v) {
        return (int) Math.max(0, Math.min(255, Math.round(v)));
    }

    /** sRGB grey level (0..255) whose relative luminance is y. */
    static int greyFromLuminance(double y) {
        double yy = Math.max(0, Math.min(1, y));
        double c = yy <= 0.0031308 ? yy * 12.92 : 1.055 * Math.pow(yy, 1 / 2.4) - 0.055;
        return clamp8(c * 255);
    }

    /** Blend a colour over another with the given overlay alpha, per channel, as the screen does. */
    static int blend(int overlayRgb, double alpha, int underRgb) {
        int r = clamp8(alpha * ((overlayRgb >> 16) & 255) + (1 - alpha) * ((underRgb >> 16) & 255));
        int g = clamp8(alpha * ((overlayRgb >> 8) & 255) + (1 - alpha) * ((underRgb >> 8) & 255));
        int b = clamp8(alpha * (overlayRgb & 255) + (1 - alpha) * (underRgb & 255));
        return (r << 16) | (g << 8) | b;
    }

    /** Smallest overlay alpha so DIM_TEXT stays readable over a wallpaper pixel of luminance y. */
    static double requiredAlpha(double y) {
        double text = luminance(DIM_TEXT);
        int grey = greyFromLuminance(y);
        int pixel = (grey << 16) | (grey << 8) | grey;
        if (contrast(text, luminance(pixel)) >= TARGET_CONTRAST) return 0;
        double lo = 0, hi = 1;
        for (int i = 0; i < 24; i++) {
            double mid = (lo + hi) / 2;
            if (contrast(text, luminance(blend(BASE, mid, pixel))) >= TARGET_CONTRAST) hi = mid;
            else lo = mid;
        }
        return hi;
    }

    // ------------------------------------------------------------------ wallpaper analysis

    /** Brightness (relative luminance, 0..1) of each horizontal band, at the given percentile. */
    static double[] bandLuminance(int[] argb, int w, int h, int bands, double percentile) {
        double[] out = new double[bands];
        if (argb == null || w <= 0 || h <= 0 || argb.length < (long) w * h) {
            Arrays.fill(out, 1.0);   // unknown picture: assume the worst
            return out;
        }
        for (int k = 0; k < bands; k++) {
            int y0 = (int) ((long) k * h / bands);
            int y1 = (int) ((long) (k + 1) * h / bands);
            if (y1 <= y0) y1 = Math.min(h, y0 + 1);
            if (y0 >= h) y0 = h - 1;
            int count = (y1 - y0) * w;
            double[] v = new double[count];
            int n = 0;
            for (int y = y0; y < y1; y++) {
                for (int x = 0; x < w; x++) {
                    int p = argb[y * w + x];
                    double a = ((p >>> 24) & 255) / 255.0;      // transparent pixels show the dark base
                    int r = clamp8(((p >> 16) & 255) * a);
                    int g = clamp8(((p >> 8) & 255) * a);
                    int b = clamp8((p & 255) * a);
                    v[n++] = luminance((r << 16) | (g << 8) | b);
                }
            }
            Arrays.sort(v, 0, n);
            int idx = (int) Math.min(n - 1, Math.floor(percentile * n));
            out[k] = v[Math.max(0, idx)];
        }
        return out;
    }

    /**
     * Overlay alpha at BANDS+1 evenly spaced stops from top (0) to bottom (BANDS).
     *
     * Each stop starts from a floor that guarantees readable text (never less than a faint soft
     * gradient), then the user's dim setting darkens it further, so the setting always has a
     * visible effect without ever going below the readable minimum.
     */
    static float[] stops(double[] bandLum, int dim) {
        int n = BANDS;
        double t = clampDim(dim) / 100.0;
        float[] out = new float[n + 1];
        for (int j = 0; j <= n; j++) {
            double base = 0.25 * (0.75 + 0.25 * j / (double) n);   // soft gradient: lighter top, darker bottom
            if (j > 0) base = Math.max(base, need(bandLum, j - 1));
            if (j < n) base = Math.max(base, need(bandLum, j));
            double a = base + (MAX_ALPHA - base) * 0.7 * t;
            out[j] = (float) Math.min(MAX_ALPHA, a);
        }
        return out;
    }

    private static double need(double[] bandLum, int k) {
        double y = (bandLum != null && k < bandLum.length) ? bandLum[k] : 1.0;
        return requiredAlpha(y);
    }

    /** Linear interpolation of stop alphas at vertical position y01 (0 = top, 1 = bottom). */
    static double alphaAt(float[] stops, double y01) {
        double pos = Math.max(0, Math.min(1, y01)) * (stops.length - 1);
        int i = (int) Math.min(stops.length - 2, Math.floor(pos));
        double t = pos - i;
        return stops[i] * (1 - t) + stops[i + 1] * t;
    }

    // ------------------------------------------------------------------ small helpers

    static int clampDim(int dim) {
        return Math.max(0, Math.min(100, dim));
    }

    /** Parses the contents of wallpaper.cfg; anything unreadable gives the default. */
    static int parseDim(String raw) {
        if (raw == null) return DEFAULT_DIM;
        try {
            return clampDim(Integer.parseInt(raw.trim()));
        } catch (NumberFormatException e) {
            return DEFAULT_DIM;
        }
    }

    /** Power-of-two decode scale so the decoded picture is still at least maxW x maxH. */
    static int sampleSize(int srcW, int srcH, int maxW, int maxH) {
        int s = 1;
        if (srcW <= 0 || srcH <= 0 || maxW <= 0 || maxH <= 0) return s;
        while (srcW / (s * 2) >= maxW && srcH / (s * 2) >= maxH) s *= 2;
        return s;
    }

    /** The part of the source picture that "center crop" shows: {x, y, w, h}. */
    static int[] centerCrop(int srcW, int srcH, int dstW, int dstH) {
        if (srcW <= 0 || srcH <= 0 || dstW <= 0 || dstH <= 0) return new int[] { 0, 0, Math.max(1, srcW), Math.max(1, srcH) };
        if ((long) srcW * dstH > (long) dstW * srcH) {        // source is wider than the screen
            int cw = (int) Math.max(1, (long) srcH * dstW / dstH);
            return new int[] { (srcW - cw) / 2, 0, cw, srcH };
        }
        int ch = (int) Math.max(1, (long) srcW * dstH / dstW);
        return new int[] { 0, (srcH - ch) / 2, srcW, ch };
    }
}
