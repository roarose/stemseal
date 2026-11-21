# Releasing

Two kinds of release, both published from GitHub's Releases page by the repository owner. A working session prepares
everything up to a draft; it never creates a tag, publishes a release or signs.

## Cell release (tag `cells-N`)

What users get with `stemseal update`. N starts at 1 and goes up by one.

1. **Pull request (working session).** Add or change cells, then run `stemseal relock --dry-run` (no changes expected for
   cells already shipped) and `stemseal release <N>`. This writes `stemseal/cells/release.json` (format 2, linked to
   release N-1 by its sha256, withdrawn cells carried over; withdraw more with `--revoke cell@version:reason`) and adds
   release N's sha256 to `stemseal/trusted_releases.json`. `stemseal verify` must pass. The pull request says the
   fingerprint (first 8 characters of the sha256) that `stemseal release` printed.
2. **Review**, then the owner merges.
3. **Draft (working session).** On the Releases page: Draft a new release, tag `cells-N` (created on publish), target
   `main`, title "Cells N", body = the cell list and the full sha256. A draft creates no tag.
4. **Sign (owner).** With the main key's USB stick: `tools/signer/서명하기.bat`. It shows the release number, the cells and
   the fingerprint; compare with the pull request, enter the passphrase, and `release.json.sig` appears on the desktop.
   See `tools/signer/README.md`.
5. **Publish (owner).** Drop `release.json.sig` onto the draft and press Publish release. The `cells` workflow checks
   the tag's cells and that `trusted_releases.json` lists its `release.json`.
6. **Check (working session).** `stemseal update --check` sees cells-N.

A release that is not signed with a key in `stemseal/release_keys.json` is not taken by anyone. That file holds public
keys only.

Withdrawn cells: each `release.json` carries every withdrawal of the releases before it; `stemseal release` refuses to
write release N when `stemseal/cells/release.json` is not release N-1 as `trusted_releases.json` lists it. Clients also
keep every withdrawal they have taken, so a release that leaves one out does not bring a cell back.

## When a release key is lost or stolen

The trusted public keys are inside each stemseal version, so a key is retired by a new version:

1. The owner tells the working thread at once (what and when; never the passphrase or the key file).
2. A pull request removes that key from `stemseal/release_keys.json` and raises the version; the owner publishes it.
3. The next cell release is signed with the remaining key and sets `min_client` to that version. Clients on the new
   version no longer accept the retired key; older clients refuse this release and are told to update stemseal.
4. Users are told to update stemseal (README, release notes, an issue).

Limit: a client that stays on an older version keeps trusting the retired key, and so keeps accepting releases signed
with it. Step 4 is what reaches those users. Signing a release that withdraws cells with the spare key withdraws cells
only; it does not retire a key.

## Package release (tag `v*`)

1. Pull request raising the version in `pyproject.toml` and `stemseal/__init__.py`, with `release_keys.json` and
   `trusted_releases.json` as they should ship.
2. The owner publishes a release with tag `vX.Y.Z` from the Releases page, then approves the `pypi` deployment in
   Actions. The `publish` workflow runs only for `v*` tags.

## Moving from 0.2.3

stemseal 0.2.3 and older read `stemseal/cells/index.json` (format 1) from the main branch. That file stays as it is,
with no new cells, for 30 days after 0.2.4 is out, and is then emptied to `{"format": 1, "cells": {}}`. New versions
read only `release.json` at a `cells-N` tag and never fall back to `index.json`.
