# Save file header layout

Observed by reading real *War of the Chosen* saves directly. Everything here is
a description of the file format as it appears on disk; no game data is
included in this repository.

A save file is a fixed-size header followed by a standard Unreal Engine 3
package. The dword at offset `0x04` — called `a4` throughout this project — is
the size of that header, and it is what the game compares against the 65 535
limit.

## Outer header

All integers are little-endian 32-bit unless noted.

| offset | type | meaning |
|---:|---|---|
| `0x00` | int32 | header format version — **22** in every observed save |
| `0x04` | int32 | **`a4` — header length** (the field the game compares to 65 535) |
| `0x08` | int32 | stored checksum of the header |
| `0x0C` | int32 | always 0 in observed saves |
| `0x10` | int32 | campaign number |
| `0x14` | int32 | mission / turn counter |
| `0x18` | FString | `date\ntime\nsave name\nmission\naction\nmap URL` |
| … | bytes | header body: binary fields, build version, map resource name |
| `0x168` | FStrings | DLC name list, each a length-prefixed string |
| `a4` | — | **end of header.** A UE3 package tag `C1 83 2A 9E` begins here |

### The key invariant

> **`a4` is exactly the file offset of the first UE3 package tag.**

Verified on 11 independent saves with no exceptions. This confirms `a4` is the
header length and that the header is followed by an ordinary UE3 package — the
save is not a bespoke container.

### FStrings

UE3 `FString` serialisation:

* **positive** length `N` → `N` bytes of ANSI/UTF-8 text, **including** a NUL
* **negative** length `N` → `|N|` UTF-16LE code units, including a NUL

The save name field is typically a negative (UTF-16) string, because save names
routinely contain characters outside ASCII.

### Worked example

`save_传承行动 1：任务6，回合1` (240 638 bytes total):

```
0x00  16 00 00 00          version = 22
0x04  59 02 00 00          a4 = 601
0x08  3F A1 F2 8C          checksum
0x0C  00 00 00 00
0x10  01 00 00 00          campaign 1
0x14  06 00 00 00          mission 6
0x18  D6 FF FF FF          FString length = -42  → 42 UTF-16 code units
0x1C  ...                  "2026-…\n…\n传承行动 1：任务6，回合1\n…"
…
0xD0  01 01 01 00          flags
0xE0  43 48 4E             "CHN"  (language)
0xF0  ...                  build version 845 / licensee 120
0x100 ...                  version string + map resource name
0x168 ...                  DLC name list
0x259 C1 83 2A 9E          UE3 package tag — a4 = 0x259 = 601 ✔
```

## What the header contains

The header duplicates the metadata the save-list UI needs, so the game can
populate the load screen without parsing a multi-megabyte package:

* date, time, save name, mission and turn labels
* campaign and mission counters
* game build version and language
* the map the save was taken on
* the required-DLC list
* the required-mod list — **this is the field that grows without bound**, and
  why heavily modded games eventually cross the limit

All of it is length-prefixed with **32-bit** lengths. There is no 16-bit width
field anywhere in the format, which is why raising the executable's comparison
is sufficient: nothing downstream truncates.

## Why the header grows so fast

The mod list lives in the header, and measured across a dozen saves it occupies
**97.6 %–99.6 %** of the whole header block. The metadata listed above is a few
hundred bytes and barely moves between campaigns; the mod list is everything
else.

It is also written **more than once**. Counting each distinct name's occurrences
inside the header block:

| save | `a4` | distinct names | name records | each name appears |
|---|---:|---:|---:|---:|
| `save_榴莲_3` | 16 847 | 338 | 663 | 2× |
| `save_保存 63_1` | 36 829 | 797 | 1 583 | 2× |
| `save_sora` | 49 663 | 336 | 1 976 | 6× |
| `save_测试test` | 72 968 | 799 | 3 161 | 4× |

The distribution is near-degenerate rather than a long tail: in `save_保存 63_1`,
786 of 797 names occur exactly twice; in `save_sora`, 324 of 336 occur exactly
six times. The handful of singletons are names added during the final pass.
So the header holds N serialised copies of one list, and

```
a4  ≈  N × (one copy of the list)  +  a few hundred bytes of metadata
```

This is why a large mod collection crosses 65 535 so quickly: the cost is the
mod list multiplied by the number of times the header is written.

## Measuring it yourself

To reproduce the numbers above on your own saves, parse the header block
(`0x18` … `a4`) as UE3 `FString`s:

* a **negative** length `n` means UTF-16 — the string is `-n` code units
  **including** the terminating NUL, so it occupies `4 + (-n) * 2` bytes;
* a **positive** length `n` means ANSI/Latin-1 — `n` bytes **including** the
  NUL, so `4 + n` bytes.

The "including the NUL" detail is easy to get wrong and silently desynchronises
the parse at the first string, which is exactly what produced a wrong
conclusion in an earlier revision of [`TECHNICAL.md`](TECHNICAL.md) — see its
*Correction history* section.

## Verifying saves yourself

```console
python tools/xcom2_savefix.py saves
```

This reads the first 24 bytes of each save in the detected save directory and
prints `a4` alongside the vanilla limit, plus whether the current executable
can read it. Any save with `a4 > 65535` is one that an unpatched game refuses
to load.
