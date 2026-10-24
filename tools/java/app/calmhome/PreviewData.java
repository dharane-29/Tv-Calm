package app.calmhome;

import java.io.File;
import java.util.List;
import java.util.Scanner;

/**
 * Prints the launcher's real design values as JSON for tools/render_preview.py, so the preview
 * image is drawn from the same numbers the app uses (colours, sizes, grid maths, icon geometry,
 * wallpaper gradient). Usage: PreviewData <widthPx> <density> [pixelsFile dim]
 */
public class PreviewData {
    static String hex(int argb) { return String.format("\"#%08X\"", argb); }

    public static void main(String[] a) throws Exception {
        int widthPx = Integer.parseInt(a[0]);
        float density = Float.parseFloat(a[1]);
        StringBuilder o = new StringBuilder("{\n");
        o.append("\"colors\": {");
        o.append("\"BG\":").append(hex(Theme.BG)).append(",\"CARD_TOP\":").append(hex(Theme.CARD_TOP))
         .append(",\"CARD\":").append(hex(Theme.CARD)).append(",\"CARD_FOCUSED\":").append(hex(Theme.CARD_FOCUSED))
         .append(",\"STROKE\":").append(hex(Theme.STROKE)).append(",\"HAIRLINE\":").append(hex(Theme.HAIRLINE))
         .append(",\"ACCENT\":").append(hex(Theme.ACCENT)).append(",\"TEXT\":").append(hex(Theme.TEXT))
         .append(",\"TEXT_SOFT\":").append(hex(Theme.TEXT_SOFT)).append(",\"TEXT_FOCUS\":").append(hex(Theme.TEXT_FOCUS))
         .append(",\"DIM\":").append(hex(Theme.DIM)).append(",\"GLYPH\":").append(hex(Theme.GLYPH)).append("},\n");
        o.append("\"sizes\": {\"CARD_RADIUS\":").append(Theme.CARD_RADIUS).append(",\"TILE_RADIUS\":").append(Theme.TILE_RADIUS)
         .append(",\"RING\":").append(Theme.RING).append(",\"STROKE_W\":").append(Theme.STROKE_W)
         .append(",\"FOCUS_SCALE\":").append(Theme.FOCUS_SCALE).append(",\"FOCUS_LIFT\":").append(Theme.FOCUS_LIFT)
         .append(",\"GLYPH_SIZE\":").append(Theme.GLYPH_SIZE).append(",\"FADE\":").append(Theme.FADE)
         .append(",\"CLOCK_SP\":").append(Theme.CLOCK_SP).append(",\"AMPM_SP\":").append(Theme.AMPM_SP)
         .append(",\"DATE_SP\":").append(Theme.DATE_SP).append(",\"LABEL_SP\":").append(Theme.LABEL_SP)
         .append(",\"SECTION_SP\":").append(Theme.SECTION_SP).append(",\"MARGIN\":").append(Grid.MARGIN_DP)
         .append(",\"PAD\":").append(Grid.PAD_DP).append("},\n");
        int content = widthPx - 2 * Math.round(56 * density);
        Grid g = Grid.compute(content, density);
        o.append("\"grid\": {\"cols\":").append(g.cols).append(",\"tileW\":").append(g.tileW)
         .append(",\"artW\":").append(g.artW).append(",\"artH\":").append(g.artH).append("},\n");
        o.append("\"glyphs\": {");
        boolean firstKind = true;
        for (Glyph.Kind k : Glyph.Kind.values()) {
            if (!firstKind) o.append(",");
            firstKind = false;
            o.append("\"").append(k).append("\": [");
            List<Glyph.Prim> shapes = Glyph.shapes(k);
            for (int i = 0; i < shapes.size(); i++) {
                Glyph.Prim s = shapes.get(i);
                if (i > 0) o.append(",");
                o.append("{\"type\":").append(s.type).append(",\"closed\":").append(s.closed)
                 .append(",\"fill\":").append(s.fill).append(",\"width\":").append(s.width).append(",\"p\":[");
                for (int j = 0; j < s.p.length; j++) o.append(j > 0 ? "," : "").append(s.p[j]);
                o.append("]}");
            }
            o.append("]");
        }
        o.append("}");
        if (a.length >= 4) {
            Scanner sc = new Scanner(new File(a[2]));
            int w = sc.nextInt(), h = sc.nextInt();
            int[] px = new int[w * h];
            for (int i = 0; i < px.length; i++) px[i] = (int) sc.nextLong();
            double[] bands = Scrim.bandLuminance(px, w, h, Scrim.BANDS, Scrim.PERCENTILE);
            float[] stops = Scrim.stops(bands, Integer.parseInt(a[3]));
            o.append(",\n\"stops\": [");
            for (int i = 0; i < stops.length; i++) o.append(i > 0 ? "," : "").append(stops[i]);
            o.append("]");
        }
        o.append("\n}");
        System.out.println(o);
    }
}
