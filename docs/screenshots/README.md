# Screenshots

Generate the public app screenshot with deterministic demo data. This image is
used by the README and AppStream/Flathub, so it should be just the app window,
use the platform-default light appearance, fit Flathub's recommended size, and
include transparent window shadow padding.

`docs/screenshots/mini-eq-dark.png` is the optional second AppStream/Flathub
screenshot. Keep the light/default screenshot first; use the dark screenshot
only to show that Mini EQ follows dark style.

`docs/social-preview.png` is separate. It is for GitHub and social link previews,
not Flathub quality checks, so it may use a branded promotional layout.

```bash
PYTHONPATH=src python3 tools/render_demo_screenshot.py docs/screenshots/mini-eq.png
PYTHONPATH=src python3 tools/render_demo_screenshot.py docs/screenshots/mini-eq-dark.png --appearance dark
python3 tools/render_social_preview.py docs/screenshots/mini-eq.png docs/social-preview.png
```

See `../../AGENTS.md` for screenshot privacy rules.
