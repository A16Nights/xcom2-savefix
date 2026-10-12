---
name: Game build report
about: Your executable is a build the tool does not recognise
title: 'Unsupported build: <build / version>'
labels: build-support
assignees: ''
---

The tool refuses to patch when its signature search finds zero or more than one
match, instead of guessing. If that happened to you, this report is how the
build gets supported.

## What to paste

Run this and paste the whole output:

```console
python tools/xcom2_savefix.py status
```

If it reports multiple candidate addresses, that list is the important part.

## Build details

- Executable size in bytes:
- Base game or War of the Chosen:
- Store (Steam / GOG / Microsoft Store / other):
- Language of the game install:
- Any prior modifications to the executable:

## If you can dig a little deeper (optional)

If you have a disassembler, the instruction being looked for is a dword
comparison against 65536 followed by a jump — in the WOTC build it reads:

```asm
cmp  dword ptr [rbp+0x38], 0x10000
ja   ...
```

(the register and displacement may differ on your build). The byte shape is:

```text
81 7d 38 ?? ?? ?? ?? 0f 87
```

Reporting the address of the equivalent instruction in your build is enough to
add support for it.

**Do not attach the executable itself**, or any game file. See
[`DISCLAIMER.md`](../../DISCLAIMER.md).
