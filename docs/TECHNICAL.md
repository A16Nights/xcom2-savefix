# Technical analysis

How the 65 535 limit was located, what it actually is, and how that was proven.
Everything here was measured on a legally purchased Steam copy of
*XCOM 2: War of the Chosen* (Windows x64).

---

## 1. What the limit actually counts

The problem is usually described as "the combined length of all mod names
exceeds 65 535". The *cause* in that sentence is right; the *quantity* is not.
The game never sums mod names. It compares one 32-bit field — the length of the
whole save header — against 65 536.

### The save format has no 16-bit fields

A scan of complete save files for any 16-bit word matching a plausible length
value returns nothing — every length and count in the format is a 32-bit
integer. If the limit were a format-level truncation, at least one 16-bit width
field would have to exist. None does. The limit therefore lives in the
executable, and section 2 locates it.

### What fills the header

The header block runs from file offset `0x18` to `a4`. Parsing it as UE3
`FString`s (length is 32-bit and **includes** the terminating NUL; negative
length means UTF-16) accounts for essentially all of it:

| save | `a4` | header block | name records | name bytes | share of block |
|---|---:|---:|---:|---:|---:|
| `save_传承行动 1：任务6，回合1` | 601 | 577 | 12 | 218 | 38 % |
| `save_榴莲_3` | 16 847 | 16 823 | 663 | 16 531 | 98 % |
| `save_Cold Rain_1` | 16 917 | 16 893 | 664 | 16 571 | 98 % |
| `save_铁人：战役85` | 18 742 | 18 718 | 746 | 18 407 | 98 % |
| `save_ZAKO` | 30 313 | 30 289 | 1 351 | 29 993 | 99 % |
| `save_保存 10` | 36 741 | 36 717 | 1 583 | 36 401 | 99 % |
| `save_保存 63_1` | 36 829 | 36 805 | 1 583 | 36 401 | 99 % |
| `save_sora` | 49 663 | 49 639 | 1 976 | 49 344 | 99 % |
| `save_快速保存：战役97，任务16，回合1` | 66 913 | 66 889 | 2 934 | 66 552 | 99 % |
| `save_测试test` | 72 968 | 72 944 | 3 161 | 72 636 | 100 % |

Summed over twelve saves: **400 073 bytes of header, of which 396 103 (99.0 %)
are mod-name records.** The remaining 1 % is genuine metadata — the date/time,
the player's save name, the map URL, a version string, a language tag — and it
does not scale with the campaign.

### Why the header grows so fast: the list is written repeatedly

The name list is not stored once. Counting how often each distinct name occurs
in the header block:

| save | `a4` | distinct names | name records | each name appears |
|---|---:|---:|---:|---:|
| `save_传承行动 1：任务6，回合1` | 601 | 12 | 12 | 1× |
| `save_榴莲_3` | 16 847 | 338 | 663 | 2× |
| `save_Cold Rain_1` | 16 917 | 338 | 664 | 2× |
| `save_铁人：战役85` | 18 742 | 379 | 746 | 2× |
| `save_ZAKO` | 30 313 | 682 | 1 351 | 2× |
| `save_保存 10` | 36 741 | 797 | 1 583 | 2× |
| `save_保存 63_1` | 36 829 | 797 | 1 583 | 2× |
| `save_sora` | 49 663 | 336 | 1 976 | 6× |
| `save_快速保存：战役97，任务16，回合1` | 66 913 | 801 | 2 934 | 4× |
| `save_测试test` | 72 968 | 799 | 3 161 | 4× |

The per-name histogram is near-degenerate, not a long tail: in `save_保存 63_1`
786 of 797 names occur exactly twice and 11 occur once; in `save_sora` 324 of
336 occur exactly six times; in `save_测试test` 785 of 799 occur exactly four
times. The few singletons are the ones added last (the most recent save name,
a fresh autosave slot, and similar), which only made it into the final pass.
So these are not two independent lists — **the same list is serialised N times
into one header**, and `a4` is roughly `N × (one copy) + ~400 bytes`.

That is the mechanism, and it is why a heavy mod list reaches 65 536 so easily:
the cost is not the mod names, it is the mod names multiplied by the number of
times the header is written.

### The writer never enforced it

After patching, the game wrote a brand-new save — `save_测试test`, header length
**72 968** — with no complaint. The write path has no length ceiling at all. The
bottleneck is exclusively on the read path.

### Correction history

An earlier revision of this document claimed that *no* "total name length"
quantity predicts failure, on the strength of a scan that summed every string in
the header. That scan was wrong: it treated the `FString` length as excluding
the terminator, which desynchronised the parse at the very first string, and it
did not account for UTF-16 doubling or for the repeated copies. The correct
metric — name bytes including `FString` framing, times the number of copies —
reproduces `a4` to within a few hundred bytes on every save tested. The
correction was prompted by a Workshop commenter who had originally established
the mod-list explanation; they were right about the cause.

What survives from the earlier analysis, unchanged: `a4 > 65535 ⟺ failure`, the
location of the comparison, and the one-byte fix.

## 2. Locating the check

### Technique

1. **Derive addresses from the PE file, never from a guessed base.** The single
   most expensive mistake in this analysis was mapping virtual addresses as
   `image_base + file_offset`. Because the first section (`.text`) has
   `PointerToRawData = 0x600`, that introduces a systematic ~0xA00 error and
   silently produces "zero cross-references" for everything. The correct mapping
   is per-section:

   ```
   file_offset → RVA :  RVA = sec.VirtualAddress + (off - sec.PointerToRawData)
   ```

   Any scanner must be validated against a positive control (a reference you
   already know resolves) before its negative results can be trusted.

2. **Use `.pdata` for function boundaries, not linear disassembly.** The PE
   exception directory holds one 12-byte `RUNTIME_FUNCTION` per function
   `{BeginRVA, EndRVA, UnwindInfoRVA}` — 94 751 entries here. An optimised MSVC
   build splits large functions into several `.pdata` chunks, so "disassemble
   until `ret`" reports a fragment, not the function.

3. **Scan for the comparison, not for the constant.** A naive search for
   `0x10000` (or any `0xFFFF` immediate) finds hundreds of unrelated hits —
   mostly `mov word ptr [...], 0xffff` sentinels. What matters is the *shape*:
   a memory operand compared against 65 536, followed by a jump.

### Result

In the `.text` section of the WOTC executable there are 378 instructions
carrying the immediate `0x10000`; 66 of those are `cmp`. Exactly **one** of
them has a memory operand:

```asm
; War of the Chosen — VA 0x140a57d6c, file offset 0xa5736c
81 7d 38 00 00 01 00   cmp  dword ptr [rbp+0x38], 0x10000
0f 87 c7 00 00 00      ja   0x140a57e40
```

The other 65 are `cmp reg, 0x10000` — register-versus-64 KiB checks, unrelated
to saves.

## 3. The containing function

```text
function    : VA 0x140a57b90 – 0x140a57e5f   (719 bytes, from .pdata)
limit site  : VA 0x140a57d6c                 (+0x1dc into the function)
vtable slot : 0x800 of the UOnlineSubsystemSteamworks vtable (0x1416b6118)
```

The function is reached as a **virtual call**. It has exactly one reference: an
8-byte pointer at `.rdata` `0x1416b6918`, which is slot `0x800` of the
`UOnlineSubsystemSteamworks` virtual table. In Unreal Engine 3 the
`exec<Name>` script-facing entry points are thin forwarders that read arguments
off the bytecode frame and tail-call the real implementation through this
table, which is why the limit could not be found by following script calls.

### Reconstruction

```asm
0x140a57bfc   mov  eax, [rbp+0x40]        ; file offset 0x00 = format version (22)
0x140a57c08   cmp  eax, 0x13              ; >= 19 uses the modern layout
              jge  <modern>
              ...
0x140a57d59   read 4 bytes -> [rbp+0x38]  ; file offset 0x04 = header length (a4)
0x140a57d6c   cmp  dword ptr [rbp+0x38], 0x10000   ; <<< THE LIMIT
0x140a57d73   ja   0x140a57e40            ; over the limit -> report failure
              ...
0x140a57da8   read 4 bytes -> [rbp+0x48]  ; file offset 0x08 = stored checksum
              allocate a4 bytes, seek to 0, read a4 bytes
0x140a57e17   mov  dword ptr [r14+8], esi ; zero the checksum field in the buffer
0x140a57e24   call 0x1401886c0            ; compute checksum over the header
0x140a57e2b   cmp  [rbp+0x48], eax        ; compare against the stored value
```

The function reads the version, then the header length, refuses anything over
the limit, then reads the header and validates its checksum. The checksum
routine at `0x1401886c0` is a sliced CRC-32 over eight lookup tables
(`.rdata` `0x141daf560`); its entry point does `movsxd r11, edx`, i.e. it
widens the length to 64 bits — **not** a place where a 16-bit truncation could
occur.

## 4. The patch

Change the immediate from `0x10000` to a larger value. Only one byte differs:

```text
before : 81 7d 38 00 00 01 00    cmp dword ptr [rbp+0x38], 0x00010000
after  : 81 7d 38 00 00 40 00    cmp dword ptr [rbp+0x38], 0x00400000
                   ^^
              file offset 0xa57371 : 01 → 40
```

A byte-for-byte comparison of a patched executable against its original backup
(32 006 600 bytes each) reports **one** differing byte at offset `0xa57371`.
The instruction encoding is untouched, so the image stays structurally valid;
no relocation, checksum, or signature inside the file is affected.

### Choosing a value

| value | bytes at the site | ceiling |
|---|---|---|
| `0x10000` | `... 00 00 01 00` | 65 536 (vanilla) |
| `0x100000` | `... 00 00 10 00` | 1 MiB |
| `0x400000` | `... 00 00 40 00` | 4 MiB (default) |
| `0x800000` | `... 00 00 80 00` | 8 MiB |

The value is not structurally constrained. 4 MiB is roughly 57× the observed
worst-case header (72 968 bytes) and leaves a wide margin; the tool accepts
1–4096 MiB.

## 5. Signature-based location

Hard-coding addresses would break on every game update. The tool searches for
the instruction *shape* instead:

```text
81 7d 38 ?? ?? ?? ??   cmp  dword ptr [rbp+0x38], <imm32>
0f 87 ?? ?? ?? ??      ja   <rel32>
83 7b 4c 00            cmp  dword ptr [rbx+0x4c], 0x00
74 29                  je   <...>
```

Wildcards cover the immediate (which the patch changes) and the jump
displacement (which differs slightly between builds).

| build | matches | RVA | function |
|---|---:|---|---|
| War of the Chosen | 1 | `0xa57d6c` | `0xa57b90`–`0xa57e5f` |
| base game | 1 | `0xa0617c` | `0xa05fb0`–`0xa0626e` |

The surrounding 79 bytes are nearly identical between the two builds — only six
differ, all of them relative jump offsets. A looser fallback pattern
(`81 7d 38 ?? ?? ?? ?? 0f 87`) is tried if the strict one finds nothing. If a
search returns **zero or more than one** match, the tool reports the candidate
addresses and **refuses to modify anything** rather than guessing.

## 6. Evidence

### Static

* The site is the only memory-operand `cmp ..., 0x10000` in `.text`.
* Its containing function is confirmed by `.pdata`, not by heuristics.
* The signature resolves to exactly one location in both executables.
* A patched executable differs from its backup by exactly one byte.
* `restore` reproduces the original file hash exactly.

### Runtime

With the function's entry instrumented and the header fields recorded:

```text
header reads observed      : 52
limit checks reached       : 52
checksum comparisons       : 52
function returns           : 52

returned success (0)       : 52 / 52
checksum matched           : 52 / 52
would have failed originally: 24
```

Every oversized header passed through, with a valid checksum — the header data
was never corrupt; the game simply refused to look at it.

### The patch comes from the file, not from a debugger

The decisive test: **stop all injection**, launch the game through Steam
normally, then read the mapped executable from another process without writing
to it. The bytes at the site read back as the patched immediate. That rules out
a live runtime hook and proves the change originates in the executable on disk.

### In game

Saves that previously appeared red in the load list — and that failed with a
"load failed" dialog even after clicking through the warning — load normally.

## 7. Why a mod is not enough

An UnrealScript mod cannot fix this. The check lives in native code, and the
script layer can only *observe* its effect: `OnlineSaveGame.bIsCorrupt` is
**read** in exactly one place in the entire script tree
(`UILoadGame.uc:456`, which shows the red *"SAVE OUT OF DATE"* dialog) and is
**written nowhere**. Its value is set natively by the save-header parser.

The observable symptom chain is:

```text
native header parse fails
      ↓
OnlineSaveGame.bIsCorrupt = 1
      ↓
UILoadGame.uc:456 → red "SAVE OUT OF DATE" entry
      ↓
user clicks "LOAD ANYWAY" → LoadSelectedSlot()
      ↓
ONLINEEVENTMGR.LoadGame() → native read → fails again → "load failed"
```

There is no script-layer hook at any point where the limit is applied. The
Workshop mod *[WOTC] Too Many Mods* accepts this and works around it by
truncating the mod list written into the save, keeping the header under the
limit. That cannot exceed the limit; only patching the executable can.
