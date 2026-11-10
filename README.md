# kilix-pane

Kilix-native terminal interfaces in Python: one widget tree, two looks.

In a Kilix or Kitty pane the shapes (rounded panels, check marks, progress
bars, row highlights) are drawn as pixels *beneath* the terminal's own text.
Anywhere else (an SSH session, tmux, a plain VT100) the same widgets draw
with characters and colours. Text is always the terminal's: the raster sits at
a negative z-index, so every character, including accented, CJK and emoji,
is drawn by the terminal font rather than an embedded bitmap face.

```sh
make demo      # every widget on one screen
make doctor    # which backend this terminal gets, and why
make test
```

Python 3.11 or newer, standard library only. It uses three stack modules,
found at run time by `kilix_pane.deps`:

| module | role | without it |
|---|---|---|
| [`kitty-input`](https://github.com/itsmygithubacct/kitty-input) (`python/`) | keyboard, mouse, focus and paste decoding | required |
| [`soft-raster`](https://github.com/itsmygithubacct/soft-raster) | draws the pixel layer | cells backend |
| [`kitty-frame-presenter`](https://github.com/itsmygithubacct/kitty-frame-presenter) | places frames in the pane with damage tracking | one inline image per frame |

They are found by an ordinary import first, then in an application's
`third_party/`, then in sibling checkouts under `$GPU_TERMINAL_HOME`,
`~/gpu_terminal` or `~/.local/gpu_terminal/sources`, then in Kilix's pinned
copies under `$KILIX_HOME/third_party`.

## Writing an application

```python
from kilix_pane import ListView, Rect, chord, run

class Hello:
    def __init__(self):
        self.items = ["one", "two", "three"]
        self.list = ListView()

    def render(self, p):                      # draw the whole frame
        p.text(1, 0, "Hello", "ink", bold=True)
        self.list.set_count(len(self.items))
        self.list.render(p, Rect(0, 2, p.width, p.height - 2),
                         lambda p, i, row, sel, hov: p.text(2, row.y, self.items[i]))

    def handle(self, event, ctx):             # keys, mouse, paste, resize
        if chord(event) == "q":
            ctx.quit()
        else:
            self.list.handle(event)

run(Hello(), title="Hello")
```

`render` draws into a `Painter` in cell coordinates. `handle` receives
`kitty_input` key and mouse events, `Paste` (a whole bracketed paste) and
`Resize`. An optional `tick(now, ctx)` returns the seconds until it wants to
run again. `ctx.run_external(argv)` lends the real terminal to a child such as
`$EDITOR` and repaints when it returns; `ctx.copy(text)` uses OSC 52.

`run` restores the terminal on every exit path: raw mode, the alternate
screen, mouse reporting, bracketed paste, focus events, the Kitty keyboard
protocol level, autowrap and the cursor, including after an exception or
SIGTERM. The PTY tests check that on a real pseudo-terminal.

### Painter

| call | pixels | cells |
|---|---|---|
| `fill(rect, role)` | flat rectangle | background colour |
| `panel(rect)` | rounded card with outline | background colour |
| `highlight(rect)` | rounded pill | background band |
| `text(x, y, s, role, …)` | terminal text | terminal text |
| `check(x, y, done)` | filled circle with a tick, or a ring | `[✓]` / `[ ]` |
| `stripe`, `dot`, `bar`, `chip`, `rule` | anti-aliased shapes | block and line characters |
| `show_cursor(x, y)` | the terminal's own cursor | the same |

Colours are roles (`ink`, `accent`, `danger`, `selection`, …) resolved by a
`Theme`; `DARK` and `LIGHT` are built in, chosen by `$KILIX_PANE_THEME` or the
`theme=` line of the shared Kilix `settings.conf`.

In pixel mode a shape drawn later blanks the text cells under it, because a
terminal always draws text above an image: without that a dialog would show
the list behind it through its panel.

### Widgets

`ListView` (keyboard, wheel, click, double-click, scrollbar), `LineEdit`
(a one-line editor with readline keys and the terminal cursor), `ButtonRow`,
`FormDialog` (text and choice fields, validation), `ConfirmDialog` and
`HelpOverlay`. Each records what it drew, so a click is hit-tested against
what is on screen.

### Testing an application

`render_text(app, columns, rows)` returns the cells-mode frame as text lines,
from the application's real `render`. `snapshot_png(app, path)` writes a
layout preview of either backend; its text uses an embedded ASCII face, so it
is for documentation. Prove the real thing with a screenshot of a real pane.

## Backend selection

`pixels` needs a terminal that speaks the Kitty graphics protocol (judged from
`KITTY_WINDOW_ID`, `TERM`, `KILIX_STREAM` or `TERM_PROGRAM`), a loadable
soft-raster, and a terminal that reports its cell size in pixels. Inside tmux
or screen it is `cells`. `KILIX_PANE_MODE=cells` or `pixels` overrides;
`python3 -m kilix_pane doctor` says which you get and why.

## License

MIT. See [LICENSE](LICENSE).
