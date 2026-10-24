package app.calmhome;

/**
 * Design tokens for the launcher (pure Java, so tests and the preview renderer share them).
 * Colours are ARGB ints; sizes are dp (or sp for text).
 */
final class Theme {
    private Theme() { }

    // surfaces
    static final int BG = Scrim.BASE;               // plain background / wallpaper gradient colour
    static final int CARD_TOP = 0xFF222A36;         // artwork card, top of its soft gradient
    static final int CARD = 0xFF1A2029;             // artwork card, bottom
    static final int CARD_FOCUSED = 0xFF2A3342;     // the focused tile's plate
    static final int DIALOG_BG = 0xFF1A2029;

    // lines
    static final int STROKE = 0x29FFFFFF;           // hairline around artwork (16% white)
    static final int HAIRLINE = 0x26FFFFFF;         // dividers (15% white)
    static final int ACCENT = 0xFF58A6FF;           // focus ring

    // text
    static final int TEXT = Scrim.TEXT;             // clock, dialog titles
    static final int TEXT_SOFT = 0xFFC9D1D9;        // unfocused tile labels
    static final int TEXT_FOCUS = 0xFFFFFFFF;       // focused tile label
    static final int DIM = Scrim.DIM_TEXT;          // section titles, date: the weakest text colour
    static final int GLYPH = 0xFF9AA4B2;            // drawn icons on cards

    // shape
    static final int CARD_RADIUS = 10;
    static final int TILE_RADIUS = 14;
    static final int DIALOG_RADIUS = 16;
    static final int RING = 2;
    static final int STROKE_W = 1;
    static final float FOCUS_SCALE = 1.06f;
    static final int FOCUS_LIFT = 10;               // dp of shadow lift when focused
    static final int GLYPH_SIZE = 46;               // dp
    static final int FADE = 28;                     // dp of soft fade where rows scroll away

    // type (sp)
    static final int CLOCK_SP = 48;
    static final int AMPM_SP = 18;
    static final int DATE_SP = 18;
    static final int LABEL_SP = 14;
    static final int SECTION_SP = 14;
}
