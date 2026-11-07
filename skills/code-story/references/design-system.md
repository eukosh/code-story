# Black Liquid Glass, for creative extras

The page's components come from the engine. Read this when you add something of your own in raw HTML or SVG inside `story.md`: a diagram, a small table of states, a timeline. Extras use the page's tokens so they sit in the design instead of on top of it.

## Rules of the system

- Glass (blur, translucent gradient) is for floating navigation chrome only. Content surfaces, code above all, are opaque.
- The page is near-black. Text comes in three steps: `--text` for emphasis, `--text-2` for body, `--text-3` for quiet labels.
- Accents carry meaning: `--ice` is the link and focus colour; `--amber` a mismatch; `--lilac` a question; `--teal` a symlink; red and green belong to the diff and nothing else.
- Code-like text in an extra is a `::: sketch`, so nobody reads it as evidence from git.

## Tokens

| Token | Use |
|---|---|
| `--void`, `--ink`, `--ink-2`, `--ink-3` | Backgrounds, darkest to lightest |
| `--line`, `--line-2` | Hairlines and borders |
| `--text`, `--text-2`, `--text-3` | Text, strongest to quietest |
| `--ice`, `--ice-soft`, `--ice-glow` | Accent, its tint, its glow |
| `--amber`, `--lilac`, `--teal` | Mismatch, question, symlink |
| `--sans`, `--display`, `--mono` | System font stacks |
| `--measure` | Prose width (74ch) |
| `--r-md`, `--r-lg` | Radii (12px, 18px) |
| `--ease` | Motion curve |

## Classes you can reuse

| Class | What it gives |
|---|---|
| `prose` | Body paragraph width and indent in a chapter (Markdown blocks get it automatically) |
| `note` + kind | A side note; kinds as in directives.md |
| `chip` | A small rounded label |
| `stat` with `s-add` / `s-del` | `+12 −3` counts |

## A diagram that fits

```html
<figure class="prose" style="margin-top:8px">
  <svg viewBox="0 0 520 60" role="img" aria-label="Token to profile lookup" style="width:100%;height:auto;font:13px var(--sans)">
    <rect x="1" y="14" width="120" height="32" rx="8" style="fill:var(--ink-2);stroke:var(--line-2)"/>
    <text x="61" y="35" text-anchor="middle" style="fill:var(--text-2)">bearer token</text>
    <path d="M121 30h70" style="stroke:var(--ice);fill:none"/>
    <rect x="191" y="14" width="140" height="32" rx="8" style="fill:var(--ink-2);stroke:var(--ice)"/>
    <text x="261" y="35" text-anchor="middle" style="fill:var(--text)">claims.user_id</text>
  </svg>
</figure>
```

Set colours through `style` (`fill:var(--ice)`), not presentation attributes, so the tokens resolve everywhere.

Keep extras quiet: thin strokes, no glow, no gradients, labels in `--text-2`. One well-placed diagram helps; several compete with the code.
