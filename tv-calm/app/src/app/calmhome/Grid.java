package app.calmhome;

/**
 * Pure layout maths for the tile grid (no Android classes, so it is unit-tested on a plain JVM).
 *
 * Tiles stretch to fill the row exactly, so there is never an empty strip on the right
 * and never a tile cut off by a pixel of rounding.
 */
final class Grid {
    static final int MIN_TILE_DP = 150;  // smallest comfortable tile
    static final int MIN_COLS = 3;
    static final int MAX_COLS = 6;       // keeps tiles large on very wide (dp) screens
    static final int MARGIN_DP = 5;      // around each tile, per side
    static final int PAD_DP = 6;         // inside each tile, per side

    final int cols;
    final int cellW;   // tile + its margins
    final int tileW;   // the focusable tile
    final int artW;    // artwork inside the tile
    final int artH;    // 16:9

    private Grid(int cols, int cellW, int tileW, int artW, int artH) {
        this.cols = cols;
        this.cellW = cellW;
        this.tileW = tileW;
        this.artW = artW;
        this.artH = artH;
    }

    static int px(float dp, float density) {
        return Math.round(dp * density);
    }

    /** @param contentWidthPx exact width available to the rows (window minus screen margins) */
    static Grid compute(int contentWidthPx, float density) {
        int content = Math.max(1, contentWidthPx);
        float d = density > 0f ? density : 1f;
        int minCell = Math.max(1, px(MIN_TILE_DP + 2 * MARGIN_DP, d));
        int cols = Math.min(MAX_COLS, Math.max(MIN_COLS, content / minCell));
        int cell = Math.max(1, content / cols);
        int tileW = Math.max(1, cell - 2 * px(MARGIN_DP, d));
        int artW = Math.max(1, tileW - 2 * px(PAD_DP, d));
        int artH = Math.max(1, artW * 9 / 16);
        return new Grid(cols, cell, tileW, artW, artH);
    }
}
