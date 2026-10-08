# Local BROWSKI demo site

This site is a deterministic, offline fixture for extension and browser-runtime
checks. It uses synthetic values, opens a second page for a reference code, and
prevents the final form submission. It sends no data to an external service.

Serve it locally with:

```sh
python3 -m http.server 8765 --bind 127.0.0.1 --directory examples/demo_site
```

Open `http://127.0.0.1:8765/` in the tab you explicitly attach from the
BROWSKI side panel. Use `Alex Demo` and `alex@example.invalid` for contact
details, read `BROWSKI-DEMO-42` from the supporting page, then stop before
**Submit application**.
