# XCOM 2 Savefix — Beyond 65535

Raise the hard-coded **65 535 character limit** on XCOM 2 save headers, so saves
from heavily modded games load normally again.

> **Status:** reverse engineered, patched, and confirmed in-game on
> *War of the Chosen*. The tool locates the patch site by byte signature, so it
> is not tied to one game build.

English | [简体中文](README.zh-CN.md)

---

## The problem

If you run enough mods, XCOM 2 will eventually show your saves as **corrupt**
(red entry in the load list, *"SAVE OUT OF DATE"*, and — clicking *LOAD ANYWAY*
— a *"load failed"* dialog). The save is intact. The game just refuses to read
it.

The community explanation is that the *combined length of all mod names* passed
65 535. **That explanation is wrong.** Measured across a dozen real saves, no
"total name length" quantity predicts which saves break. Exactly one thing does:

| save file | header length field (`a4`) | loads? |
|---|---:|---|
| `save_传承行动 1：任务6，回合1` | 601 | yes |
| `save_榴莲_3` | 16 847 | yes |
| `save_sora` | 49 663 | yes |
| — | **65 535 (the limit)** | — |
| `save_快速保存：战役97，任务16，回合1` | 66 913 | **no** |
| `save_保存 12` | 72 822 | **no** |
| `save_RAN` | 72 822 | **no** |

The dword at **file offset 0x04** in a save file is the length of the save
header. It happens to grow with the mod list, which is why the myth survived.
The actual rule is simply:

> **`a4 > 65535` ⟺ the save cannot be loaded.**

## The cause

Every length field inside a save file is 32-bit — there is not a single 16-bit
field in the format. The limit lives in the game executable, as one hard-coded
comparison in the function that reads a save header:

```asm
81 7d 38 00 00 01 00   cmp  dword ptr [rbp+0x38], 0x10000   ; a4 vs 65536
0f 87 c7 00 00 00      ja   <failure>                        ; over the limit -> bail
```

That is **the only place in the whole executable that compares a save-header
field against 65 535**. Nothing on the write side checks it, which is why a
patched install happily *saves* a 72 968-byte header — the bottleneck was only
ever on the read path.

Full disassembly, function boundaries, hash verification and the evidence trail
are in [`docs/TECHNICAL.md`](docs/TECHNICAL.md).

## The fix

One byte of the immediate changes:

```
before:  81 7d 38 00 00 01 00     cmp ..., 0x00010000   (64 KiB)
after:   81 7d 38 00 00 40 00     cmp ..., 0x00400000   (4 MiB)
                    ^^
                 only this byte (01 -> 40)
```

The instruction encoding is untouched, so the executable remains structurally
valid. A byte-for-byte diff of a patched executable against the original backup
shows **exactly one differing byte**.

## Usage

There are two implementations of the same patch. Both locate the site by byte
signature, both back up before writing, both are equally verified.

**PowerShell** — no Python needed, works on any current Windows:

```console
powershell -ExecutionPolicy Bypass -File tools\SaveFix.ps1 Status
powershell -ExecutionPolicy Bypass -File tools\SaveFix.ps1 Apply
```

**Python 3.8+** — standard library only, no `pip install`:

```console
# Get the repository
git clone https://github.com/A16Nights/xcom2-savefix.git
cd xcom2-savefix

# 1. See what the tool finds, and whether your game is already patched
python tools/xcom2_savefix.py status

# 2. Patch (default 4 MiB). Close the game first — it locks the executable.
python tools/xcom2_savefix.py apply

# 3. Check your saves
python tools/xcom2_savefix.py saves
```

A backup is written next to the executable as `XCom2.exe.65535bak` before
anything is modified.

```console
# Choose a different ceiling (any value from 1 to 4096 MiB)
python tools/xcom2_savefix.py apply 16

# Undo everything
python tools/xcom2_savefix.py restore

# Show what would happen without writing
python tools/xcom2_savefix.py apply 8 --dry-run
```

The tool auto-detects the game through the Steam registry and
`libraryfolders.vdf`, and handles both the base game and *War of the Chosen*.
Point it somewhere explicitly with `--exe PATH` if it guesses wrong.

### Supported executables

| build | limit site | site state in a fresh install |
|---|---|---|
| War of the Chosen | RVA `0xa57d6c`, file offset `0xa5736c` | `cmp ..., 0x10000` |
| base game | RVA `0xa0617c`, file offset `0xa0557c` | `cmp ..., 0x10000` |

Addresses are shown for reference only — the tool finds the site by signature
(`81 7d 38 ?? ?? ?? ?? 0f 87 ?? ?? ?? ?? 83 7b 4c 00 74 29`), which resolves to
exactly one location in both executables. It refuses to act if a search returns
zero or multiple matches, rather than guessing.

## What you should know before using this

* **Close the game before patching.** Steam holds a lock on the executable.
* **Steam "Verify integrity of game files" and game updates restore the
  original executable.** Re-run `apply` afterwards.
* **Saves are not made forward compatible.** A save written with the raised
  limit will not load on an unpatched install. `restore` returns you to vanilla
  behaviour.
* **Multiplayer / Challenge Mode ladders.** This patch is for single-player
  play. Do not use it for ranked or shared-save modes; a modified executable is
  not something the other side agreed to.
* **This is an unsupported modification.** It is not affiliated with, endorsed
  by, or supported by Firaxis Games, 2K, or Take-Two. See
  [`DISCLAIMER.md`](DISCLAIMER.md).

## How it was verified

* **Static.** The site is the only memory-operand `cmp ..., 0x10000` in the
  entire `.text` section; its containing function is confirmed by the PE
  exception directory (`.pdata`), and the pattern resolves uniquely in both the
  base game and WOTC builds.
* **Runtime.** With the limit check instrumented, **52 of 52** save-header reads
  returned success, **52 of 52** header hashes matched, and **24** reads would
  have been rejected by the original rule. Every one of the oversized headers
  (`66913`, `72690`, `72822`, `72834`, `72838`, `72870`, `72880`, `72902`) was
  passed through.
* **File level.** After patching on disk with no process injection running,
  reading the mapped executable back showed the patched immediate — proving the
  change comes from the file, not from a running debugger.
* **In game.** Previously-unloadable saves (red in the list) load normally.

## Repository layout

```
tools/xcom2_savefix.py    the patch tool, Python (status / apply / restore / saves)
tools/pe_util.py          dependency-free PE reader and byte-pattern scanner
tools/SaveFix.ps1         the same patch tool in PowerShell, no Python needed
workshop/item/            exactly what subscribers receive: manifest, ReadMe,
                          launcher, tool and preview image
workshop/workshop_build.vdf  SteamCMD upload config for that folder
workshop/make_preview.py  regenerates ModPreview.jpg (needs Pillow)
docs/TECHNICAL.md         how the limit was located, with disassembly and evidence
docs/SAVE_FORMAT.md       save-file header layout
docs/WORKSHOP.md          why the Workshop item is a tool, and how it is published
README.zh-CN.md           简体中文说明
DISCLAIMER.md             legal notice
```

`workshop/item/` holds the files published to the Steam Workshop as
**[WOTC] Savefix — Beyond 65535**:

> https://steamcommunity.com/sharedfiles/filedetails/?id=3818684374

The Workshop item ships the PowerShell tool; subscribers run it against their
own executable, so the item contains no game files at all. There is no second
copy of these files anywhere: the repository folder *is* the upload source, and
`workshop_build.vdf` points at it, so re-running SteamCMD updates the live item
from a fresh clone.

## Related work

The Steam Workshop mod **[WOTC] Too Many Mods** takes a different approach: it
truncates the mod list written into the save so the header stays under the
limit. That *works around* the problem and can silently drop mods that matter.
This project *removes the limit* instead.

## License

[MIT](LICENSE) for the code in this repository. No game code, game binaries, or
game assets are included or redistributed.
