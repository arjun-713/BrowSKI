# Local release preparation checklist

The current package version is `0.1.0`. This checklist prepares local release
artifacts; it does not publish them. Do not describe a capability or platform as
supported without the corresponding integration evidence.

## Before building

- Confirm the Rust crate versions, `python/pyproject.toml`, and
  `extension/package.json` all use the same version.
- Review the current milestone status in `ARCHITECTURE_PLAN.md`, the product
  claims in `README.md`, and open limitations in `docs/development/roadmap.md`.
- Run the required repository test and lint gates on the release candidate.
- Verify the exact supported Linux distribution/architecture and browser build
  against `docs/user/install.md`; do not infer Chrome for Testing's profile or
  Native Messaging paths from Chromium defaults.
- Confirm no API keys, browser profiles, local databases, generated traces, or
  unreviewed local configuration are included in staged artifacts.
- Review `docs/security/dependency-license-review.md` and regenerate the locked
  package metadata inventory for the current release environment.

## Prepare artifacts

From the repository root, run:

```sh
bash scripts/prepare-release.sh
```

The script builds the locked Rust workspace, syncs the Python development
environment from `python/uv.lock`, builds a wheel through the configured
`python/pyproject.toml`, builds the production Chrome extension, and writes the
artifacts under the ignored `dist/release-0.1.0/` directory. It does not
publish, install globally, or modify user configuration. It uses local Python
and npm environments. The uv and npm caches default to
`/tmp/browski-release-uv-cache` and `/tmp/browski-release-npm-cache`.

The output includes:

- Python wheel containing the configured PyO3 extension;
- unpacked production extension under `extension/chrome-mv3/`;
- deterministic extension ZIP with normalized file times and sorted entries;
- release metadata, project `LICENSE`, and dependency declaration inventory;
- sorted `SHA256SUMS` for each artifact file except the checksum file itself.

To deliberately replace the generated `dist/release-0.1.0/` directory after a
successful rebuild, pass `--replace`. The script builds in a temporary sibling
directory first; failed builds leave the prior release directory untouched.

Verify the result locally:

```sh
cd dist/release-0.1.0
sha256sum --check SHA256SUMS
```

Then inspect the wheel contents and extension `manifest.json`, install the
unpacked extension in the supported browser, and run the documented local
acceptance flow. Build success alone is not browser acceptance.

## Before any publication

- Confirm release tests and install/upgrade/uninstall flows on every claimed
  platform and browser version.
- Confirm the changelog and README accurately describe implemented and partial
  capabilities; resolve all release-blocking roadmap items.
- Resolve or document each unknown, reciprocal, and copyleft declaration with
  package-specific review. The metadata report is not a legal audit.
- Check generated checksums from the exact files intended for distribution.
- Obtain the project's normal release approval and publish only the reviewed
  artifacts. This repository-local script intentionally stops before that step.
