# Dependency license metadata review

The root project declares MIT in `Cargo.toml` and `python/pyproject.toml`; the
repository's `LICENSE` contains the MIT license. This statement describes the
project's declaration only. It does not establish that every dependency or
combination is compatible with every use or distribution.

## Generate the current inventory

The inventory reads `Cargo.lock` through `cargo metadata --locked`, the
installed Python distribution metadata in the selected interpreter, and
`extension/package-lock.json` joined with installed npm package metadata when
available. For release preparation it is generated with:

```sh
python/.venv/bin/python scripts/license_inventory.py \
  --python python/.venv/bin/python \
  --output dist/dependency-licenses.json
```

The report retains each package's declared license value and labels missing
declarations as `unknown` and reciprocal/copyleft expressions for manual review.
SPDX expressions are preserved as metadata; the classifier does not choose an
`OR` alternative or decide whether a dependency is shipped in a particular
artifact. Package files and distribution terms still need human review.

## Initial release-tooling snapshot

The inventory from the installed local development environment contained 220
locked Rust packages, 113 installed Python distributions, and 410 npm lockfile
packages. No missing license declarations were reported in that snapshot. It
flagged the following declarations for review:

- Rust: `r-efi` versions 5.3.0 and 6.0.0 declare
  `MIT OR Apache-2.0 OR LGPL-2.1-or-later`. This records an available LGPL
  option; it does not mean that option was selected.
- Python: `certifi` and `hypothesis` declare MPL-2.0; `orjson` declares
  `MPL-2.0 AND (Apache-2.0 OR MIT)`; `tqdm` declares `MPL-2.0 AND MIT`.
  This installed environment includes test/development extras as well as
  runtime dependencies.
- npm: twelve lockfile entries declare MPL-2.0 through `lightningcss` and its
  platform-specific packages. The lockfile includes optional platform entries;
  the actual extension build's dependency closure must be checked separately.

## Staged release-candidate inventory

After syncing the configured development environment for release preparation,
the staged 0.1.0 candidate inventory reports 220 locked Rust packages, 112
installed Python distributions, and 410 npm lockfile packages. It reports no
unknown license declarations in those inventories and flags 2 Rust, 4 Python,
and 12 npm declarations for manual review. The Python count differs from the
initial 113-distribution snapshot above because the installed environment
changed; the generated `dist/release-0.1.0/reports/dependency-licenses.json`
is the artifact-specific record.

These counts and declarations can change with lockfiles, installed extras,
platform selection, and package metadata. Regenerate the inventory for each
release candidate. It is a convenience report of declared metadata, **not a
legal audit or compatibility determination**.
