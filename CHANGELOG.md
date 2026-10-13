# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Fixed

* **Corrected the explanation of what causes the overflow.** Earlier revisions
  said the widely-repeated "mod names exceed 65 535" account was simply wrong.
  That was itself wrong, and came from a broken measurement: the header scan
  treated the UE3 `FString` length as excluding the terminating NUL, which
  desynchronised the parse at the first string and produced meaningless
  numbers. Re-measured correctly, name records occupy **97.6 %–99.6 %** of a
  save header, and the list is serialised into it **more than once** (each name
  appears twice in an ordinary save, four or six times in a heavy campaign).
  `README.md`, `README.zh-CN.md`, `docs/TECHNICAL.md`, `docs/SAVE_FORMAT.md`,
  the Workshop page text and the item's `ReadMe.txt` now state the mechanism
  accurately. What is unchanged: `a4 > 65535` is the exact rule, the comparison
  is at `0x140a57d6c`, and the one-byte fix works.
* Workshop page description: the `description` in `workshop_build.vdf` used the
  two-character sequence `\n`, which is not un-escaped anywhere in the SteamCMD
  path, so the published page displayed a literal `\n` throughout instead of
  line breaks. Both copies of the page text now use real newlines.
* **`SaveFix.bat` crashed whenever its own folder contained a `)`** — which is
  the default Steam location, `C:\Program Files (x86)\...`. The script path was
  expanded into the command line unquoted, so `cmd.exe` read the `)` as the end
  of a block and reported `\SaveFix.ps1 was unexpected at this time.` The path
  is now quoted. Reported by Skarsatal 2.0, whose own wrapper script had hidden
  the defect.
* **`.gitattributes` normalised `.bat` files to LF**, which breaks `goto :label`
  in `cmd.exe` — the label lookup walks byte offsets, so a LF-only batch file
  fails with `The system cannot find the batch label specified`. Any clone of
  the repository produced a broken launcher. `*.bat` and `*.cmd` now carry
  `text eol=crlf`.
* **A denied read produced no admin hint.** `ReadAllBytes` at the top of
  `Invoke-Apply` sat outside every typed `catch`, so on an administrator-only
  game folder the script exited `1` with a bare message. The top-level handler
  now walks the inner-exception chain, explains the cause, exits `4`, and the
  batch file offers to re-run elevated.

### Added

* A Chinese section on the Workshop page, describing the problem, the one-byte
  change, and the usage steps.
* `docs/TECHNICAL.md` § 1 now carries the per-save measurements (header
  composition, name-record counts, copies-per-name histograms) and a
  *Correction history* section recording what the earlier wrong conclusion was,
  why the scan produced it, and what replaced it.

### Verified

* The launcher and the PowerShell tool were re-tested end to end on the real
  executable from a path containing both a space and a parenthesis
  (`...\Program Files (x86)\...`): `Status`, `Apply`, an idempotent second
  `Apply`, `Restore` (back to the exact original SHA-256) and the access-denied
  path (`exit 4` + elevation offer) all behave correctly.
* A fresh `git clone` was checked to confirm the working-tree `SaveFix.bat`
  really is CRLF (`bare-LF = 0`), not just the file on the machine that wrote
  it.

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
