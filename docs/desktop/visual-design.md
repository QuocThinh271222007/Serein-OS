# Visual Design

## Aesthetic principles

Serein's name comes from the atmosphere of quiet night rain — the visual
target is:

```
quiet · dark · minimal · clean · technical · slightly nocturnal ·
premium · low-distraction
```

Not:

```
cyberpunk hacker desktop (Matrix rain, neon green, skulls, RGB accents,
excessive transparency/blur, fake terminal aesthetics)
```

## Strategy: 90% upstream, 10% deliberate integration

Per the S1 governing principle, S1 does not build a theme engine. It
configures upstream Breeze via the mechanisms Breeze/Plasma already
support:

- A KDE color scheme (`Colors:*` sections — the standard `.colors`
  format), not a fork of Breeze's rendering code.
- Upstream Breeze icons, cursor, and window decoration, unmodified.
- One Look-and-Feel package that *references* the above plus a panel
  layout template — it does not reimplement Plasma's shell.

## Color scheme: "Serein Dark"

`desktop/color-schemes/SereinDark.colors` — structurally a Breeze Dark
derivative (same section layout: `Colors:Window`, `Colors:Button`,
`Colors:View`, `Colors:Selection`, `Colors:Tooltip`, `WM`, `General`,
`ColorEffects:*`), with two deliberate changes:

1. **Background depth**: shifted slightly darker/more neutral-blue than
   stock Breeze Dark (`Window` background `RGB(27,30,34)` vs. Breeze
   Dark's `RGB(49,54,59)`) for the "very dark neutral/blue-black" target,
   while keeping `View`/`Selection`/text contrast ratios at least as high
   as Breeze Dark's — never sacrificing readability for mood.
2. **Accent**: a cool, desaturated blue-violet (`RGB(117,138,224)`)
   replacing Breeze's saturated sky-blue accent, used for
   `DecorationFocus`, `ForegroundActive`, and the active window-title
   accent in `[WM]`.

**Left untouched:** Breeze Dark's positive/negative/neutral semantic
colors (success/warning/error). These are accessibility-tuned upstream
values; there is no reason to relitigate them for a mood change, and
doing so would risk color-contrast regressions in dialogs that predate
Serein.

## Icons, cursor, window decoration

Unmodified upstream Breeze (light theme intentionally not overridden;
"Serein Dark" implies `breeze-dark` icons). No custom icon set ships in
S1 — a Serein-branded icon/logo pass is explicitly deferred until branding
assets exist, per the instruction not to block S1 on artwork.

## Fonts

**S1 does not override any font setting.** Ubuntu/KDE's own default UI
and monospace fonts are left exactly as packaged. Overriding a font
requires verifying its exact package availability and license on Ubuntu
26.04, which this environment cannot do reliably; per the explicit
instruction ("retain upstream Ubuntu/KDE defaults" when licensing is
uncertain), the conservative choice is to not touch font configuration at
all rather than guess.

## Konsole

`desktop/konsole/SereinDark.colorscheme` (Konsole's own `.colorscheme`
format, distinct from the global KDE `.colors` format) shifts only the
ANSI blue slot toward the same blue-violet accent, for visual continuity
with the desktop scheme; every other ANSI color slot matches the standard
Breeze terminal palette (again: accessibility-tested values, not
reinvented). `desktop/konsole/Serein.profile` sets no `Font=` key at all,
for the same reason fonts are untouched elsewhere: it inherits whatever
Konsole's own packaged default monospace font is.

## One theme, not five

Per the explicit instruction, S1 ships exactly one color scheme and one
Look-and-Feel package. No theme picker, no seasonal variants, no
alternate accent colors.
