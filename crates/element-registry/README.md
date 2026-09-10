# element-registry

Stable semantic element references (`@name`), fingerprints, reacquisition,
and lifecycle/generation tracking.

## May

- Mint `ElementRef`s, compute fingerprints, track generations.
- Decide whether a ref is fresh or must be reacquired.

## May NOT

- Query the browser directly.
- Store screenshots, secrets, or unbounded history.
