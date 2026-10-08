# Local application demo

The local fixture exercises a two-step form, an owned supporting tab, visible
text extraction, explicit working memory and a return to the original form.
It uses synthetic values and never submits data to a server.

## Try the product flow

After [installation](install.md) and [extension setup](extension.md), serve
the fixture from the repository root:

```sh
python3 -m http.server 8080 --bind 127.0.0.1 --directory examples/demo_site
```

Start `browski serve` in another terminal. Open
`http://127.0.0.1:8080/` in Chrome, connect the BROWSKI panel and explicitly
attach that tab. Configure your OpenAI key in Settings before a live task.

Use this task:

```text
set "Full name" to "Alex Demo";
fill "Email address" with "alex@example.invalid";
type "Bengaluru" into "Preferred city";
open "http://127.0.0.1:8080/guide.html" in a new tab;
transfer "Reference code" from supporting page into "Supporting reference code".
Return to the application and stop before final submission.
```

The explicit grammar authorizes finite values and destinations. The reference
code must come from the currently observed, named semantic text; the runtime
does not accept a model-invented value or unprovenanced memory as evidence.
The fixture displays “Application ready for review” once all fields are filled.
Do not approve submission if the task is to stop before it.

Live execution uses OpenAI and can incur charges. Live Luna success on this
task has not been validated. The fixture is useful for product review, not a
promise that the model will complete every run.

## Reproduce software acceptance without an API key

The real-browser test substitutes a deterministic reasoning provider. Chrome,
the packaged extension, Native Messaging, authentication, Rust observation and
actions, verification, LangGraph and encrypted checkpointing remain real.
No OpenAI or Jev request is made; Laya is disabled in the harness.

```sh
cd python
uv run playwright install chromium
cd ..
make build
make test-extension-e2e
```

The suite covers the full demo, pause/resume, safe stop, approval/denial,
tab and host loss, owned-tab refusal, viewport capture, settings and
synthetic-key isolation. The full demo's provider reads the reference value
from runtime working memory; it does not cache that answer privately.

See the [validation record](../development/productization-validation.md) for
the tested environment and the distinction between software acceptance and
agent reliability.
