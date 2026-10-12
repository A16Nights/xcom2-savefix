# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.0] — 2026-10-12

First public release.

### Added

* `tools/xcom2_savefix.py` — patch tool with four sub-commands:
  * `status` — locate the limit site and report whether the executable is
    vanilla or patched
  * `apply [MiB]` — raise the limit (default 4 MiB), creating a backup first
  * `restore` — revert the executable from its backup
  * `saves` — list save files with their header length field and whether the
    current executable can read each one
* `tools/pe_util.py` — dependency-free PE32/PE32+ reader, RVA/offset mapping,
  `.pdata` function-boundary lookup, and wildcard byte-pattern scanner
* Signature-based patch-site location — no hard-coded addresses, so the tool
  survives game updates
* Support for both the base game and *War of the Chosen*, with Steam library
  auto-detection via the registry and `libraryfolders.vdf`
* `docs/TECHNICAL.md` — full reverse-engineering write-up with disassembly and
  the evidence trail
* `docs/SAVE_FORMAT.md` — observed save-header layout
* `tools/SaveFix.ps1` — the same patch tool in PowerShell 5.1, so Windows users
  need neither Python nor any download
* `workshop/` — Steam Workshop item: manifest, ReadMe, launcher, preview image,
  and the SteamCMD upload config
* `docs/WORKSHOP.md` — why the Workshop item is a tool rather than a loadable
  mod, what the item must contain, and the two upload routes

### Published

* Steam Workshop item **[WOTC] Savefix — Beyond 65535**, id `3818684374`:
  https://steamcommunity.com/sharedfiles/filedetails/?id=3818684374
  The item ships the PowerShell tool; subscribers run it against their own
  executable, so the item contains no game files.

### Verified

* The site is the only memory-operand `cmp ..., 0x10000` in the executable.
* Signature resolves to exactly one location in both supported executables.
* A patched executable differs from the original by exactly one byte.
* Runtime instrumentation recorded 52/52 successful header reads, 52/52
  checksum matches, and 24 reads that the original limit would have rejected.
* With no injection running, the patched immediate reads back from the mapped
  executable — the change comes from the file on disk.
* Saves that previously failed to load now load normally in game.
