# Screenshots

Generate the public release screenshot with deterministic demo data. The
screenshot tool renders the full desktop layout, then scales the saved PNG down
to Flathub's recommended width:

```bash
PYTHONPATH=src python3 tools/render_demo_screenshot.py docs/screenshots/mini-eq.png
python3 tools/render_social_preview.py docs/screenshots/mini-eq.png docs/social-preview.png
```

See `../../AGENTS.md` for screenshot privacy rules.
