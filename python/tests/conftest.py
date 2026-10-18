"""Keep test-created application keys inside each test's temporary directory."""

import functools
import threading
from collections.abc import Iterator
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_application_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "application-data"))


@pytest.fixture
def article_site(tmp_path: Path) -> Iterator[str]:
    class FixtureHandler(SimpleHTTPRequestHandler):
        def do_POST(self) -> None:
            from urllib.parse import parse_qsl, urlencode

            length = int(self.headers.get("Content-Length", "0"))
            if self.path != "/submit" or not 0 < length <= 4096:
                self.send_error(400)
                return
            # Echo the actual submitted pairs through a real POST/303/GET flow.
            # Receipt checks, not this fixture, decide whether values are right.
            fields = parse_qsl(self.rfile.read(length).decode(), max_num_fields=20)
            self.send_response(303)
            self.send_header("Location", "/receipt.html?" + urlencode(fields))
            self.send_header("Content-Length", "0")
            self.end_headers()

    pages = {
        "index.html": "<title>Library</title><h1>Library</h1>"
        '<a href="astronomy.html">Astronomy</a> <a href="botany.html">Botany</a> '
        '<a href="geology.html">Geology</a>',
        "botany.html": '<title>Plants</title><h1>Botany</h1><a href="leaf.html">Leaf structure</a> '
        '<a href="roots.html">Roots</a> <a href="flowers.html">Flowers</a>',
        "leaf.html": "<title>Leaf structure</title><h1>Leaf structure</h1>"
        "<p>Leaves capture sunlight.</p>",
        "astronomy.html": "<h1>Astronomy</h1>",
        "geology.html": "<h1>Geology</h1>",
    }
    for filename, html in pages.items():
        (tmp_path / filename).write_text(html)
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), functools.partial(FixtureHandler, directory=str(tmp_path))
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
