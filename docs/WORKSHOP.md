# Publishing to the Steam Workshop

This document records how the Workshop item **[WOTC] Savefix — Beyond 65535**
is built and published, and what the constraints are.

The short version: the Workshop is used as a **distribution page for a tool**,
not as a mod. The game never loads the item. It carries no game files.

**Status: published.** The item is live at
<https://steamcommunity.com/sharedfiles/filedetails/?id=3818684374>
(id `3818684374`, public). The upload was done with SteamCMD, as described
under [Two ways to upload](#two-ways-to-upload) below.

---

## Why the Workshop, and why not as a normal mod

The thing this project fixes lives inside `XCom2.exe`. No UnrealScript mod can
reach it:

* The check is native code. `OnlineSaveGame.bIsCorrupt` — the flag behind the
  red "SAVE OUT OF DATE" entry — is only ever **read** in the script tree
  (`UILoadGame.uc`); nothing in UnrealScript writes it.
* The check that actually fails is in `UOnlineSubsystemSteamworks`, reached
  through a vtable slot that no script-level mod can substitute.
* XCOM 2's UE3 build exposes no `DLLBind` mechanism, so a mod cannot carry a
  native helper either — a full name-table scan for `DLLBind`/`DLLImport` and
  friends returns nothing.

So a Workshop item cannot *fix* the problem by loading mod code. What it *can*
do is deliver the tool and the instructions to players who would never find a
GitHub repository.

This is established practice on this game's Workshop: the item
**MemoryAllocationDLL** (id `3151611447`) does exactly this — it ships an
updated `tbbmalloc.dll` and tells subscribers to copy it into their game folder
by hand. Over 800 items were scanned while preparing this one; it is the only
one that ships a binary, and it proves the format works.

---

## Layout

```
workshop/item/            what subscribers receive - the upload source
workshop/workshop_build.vdf   SteamCMD config pointing at workshop/item/
workshop/make_preview.py  regenerates item/ModPreview.jpg (needs Pillow)
```

Only `workshop/item/` is uploaded. Everything else sits beside it, so nothing
development-only can leak into the item by being in the same folder.

## What the item must contain

| File | Required | Purpose |
|---|---|---|
| `SaveFix.XComMod` | yes | The manifest. Steam and the launcher read this. |
| `ModPreview.jpg` | yes | Item thumbnail. 1024×1024 is what other items use. |
| `ReadMe.txt` | yes in practice | The full instructions, shown on the item page. |
| `SaveFix.bat` | — | Double-click launcher, sets execution policy for one run. |
| `SaveFix.ps1` | — | The tool itself. Plain text, readable by subscribers. |
| `LICENSE` | — | MIT, so the terms travel with the download. |

`ModPreview.jpg` is **not** in version control as a binary blob of unknown
origin — it is generated from `make_preview.py`, which is committed alongside
it. Regenerate with:

```console
python workshop/make_preview.py workshop/item/ModPreview.jpg
```

The script needs Pillow, which is why it lives in `workshop/` and not in
`tools/` — everything in `tools/` is standard-library only.

### Manifest format notes

`.XComMod` is an INI file. Two details that are easy to get wrong, both
confirmed against real Workshop items on this machine:

* **`Description` uses real newlines**, not `\n` escapes. Writing the
  two-character sequence `\n` produces a page with a visible `\n` in it —
  nothing in this path un-escapes it.
* Steam-native BBCode is supported in the body: `[b]`, `[list]`, `[code]`,
  `[url]`. The item page renders these; `ReadMe.txt` is plain text.

**The same rule applies to the `description` in `workshop_build.vdf`**, and
that one is easy to miss because the `.vdf` *is* a Steam KeyValues file, where
escape sequences look plausible. They are not processed: the first publish of
this item sent `\n` literally and the page showed it literally. Both copies of
the page text therefore use real line breaks, and both are verified after
upload by reading the text back through the Steam Web API — not by eye, and not
by assuming that because the value arrived it arrived correctly.

The manifest now carries the live id (`publishedFileId=3818684374`). Before the
first publish it was `0`: Steam assigns the real id on first publish, and the
item's folder on disk also gets a `PublishedFileId.ID` file containing it. A
manifest left at `0` is only correct for a brand new item.

### A quote inside the description closes it early

KeyValues delimit strings with plain `"`, and there is no escape for it *inside
a value written by hand*. So an ASCII double quote anywhere in the description
ends the string there. Everything after it is then read as key/value pairs,
which produces an error that names the wrong thing.

This happened on a real upload. The description quoted the launcher's own
prompt, in plain quotes:

    it asks "Raise it to 4 MiB now? [y/N]"

and `steamcmd` refused the file with two messages:

    Bad expression token: y at 1 in y/N]
    Assertion Failed: CKeyValuesSystem::AddStringToPool: key name too long (3450 chars)

The second message is the informative one: the remainder of the description was
being parsed as a **key name**, which is why it was 3450 characters long. The
first message stops at the space inside `y/N]` and says nothing about quotes.
Neither error points at the actual defect, which is a single character tens of
lines earlier.

The fix is to not use a bare `"` in a description at all: the launcher's prompt
is written in `[i]` BBCode instead, and the Chinese section already used full
width quotes. Two useful habits follow:

* **Write prominent quoted text in BBCode or full-width quotes**, so the
  description value never contains a bare `"`.
* **Validate the `.vdf` offline before uploading**, because the authoritative
  parser only tells you after a failed attempt. `tools/check_vdf.py` walks the
  same grammar: it parses quoted tokens and nested `{ }` blocks, reports the
  first thing that would stop Valve's parser, and flags a key name over 200
  characters as the mis-read-value symptom it is. Run it with no argument to
  check the `.vdf` in this repository:

      python tools/check_vdf.py

  A clean file exits `0`. It is also worth reading its *description value
  checks* block, which counts bare double quotes, bare braces, real newlines
  and literal `\n` in the description specifically - the last two are how the
  earlier newline bug was caught.

The same rule bites in the reverse direction: a description that is *entirely*
valid can still be wrong, because nothing in this path un-escapes anything. Both
failures come from the same place - treating a KeyValues value as if it were a
programming-language string literal, where quoting and escaping are normal.

### The launcher: two things that break silently

`SaveFix.bat` is the file subscribers actually double-click, and it has two
failure modes worth recording, because both produce errors that point at the
wrong file:

* **The script path must be quoted.** `cmd.exe` parses the line before it runs
  anything, so an unquoted `%HERE%SaveFix.ps1` inside the default Steam location
  (`C:\Program Files (x86)\...`) has its `)` read as the end of a block. The
  error is `\SaveFix.ps1 was unexpected at this time.` — which is why the first
  report of this blamed `SaveFix.ps1`'s syntax, while the `.ps1` was innocent.
* **The file must be CRLF.** `cmd.exe` reads a batch file as a stream and
  resolves `goto :label` by byte offset. With LF-only endings the jump lands in
  the wrong place and fails with `The system cannot find the batch label
  specified`. Because the repository normalised everything to LF, *every* clone
  produced a broken launcher — hence the `*.bat text eol=crlf` rule in
  `.gitattributes`. Do not remove it.

### The launcher: a third failure that was not a crash

The two bugs above make the launcher fall over. The third one only made it
useless, which is why it survived longer: **the report told double-click users
to run a command they had no way to run.**

The old report ended with `Run ".\SaveFix.ps1 Apply" to raise the limit to
4 MiB.` For someone who got there by double-clicking, that instruction is a
dead end. They have no console window to type into. Double-clicking
`SaveFix.ps1` itself opens Notepad, not PowerShell. And `SaveFix.bat` could not
have taken an argument even if they had a window, because a double-click passes
none. The result was a report that correctly said "this executable can be
patched" and then withheld the means to patch it — one user's words were "Am I
just really stupid? I need someone to explain it like I'm a five year old."

The fix turns the dead end into a question. With **no argument at all**,
`SaveFix.bat` runs the report and then asks:

```
  The original 65,536-byte limit is still in place.

  Raise it to 4 MiB now? [y/N]
```

Answering `y` re-invokes the script with `Apply -Yes`, so the confirmation the
user just gave is not asked for twice. **Passing any argument skips the
question entirely**, so every documented command, and every scripted caller,
behaves exactly as before.

That "did the caller pass anything?" test is `if not "%~1"=="" goto :have_args`
— a label jump, not an `if (...)` block, for the parenthesis reason above.

The report needed a way to say "I ran fine, and there is something to do"
without calling it an error. It exits **10** for that case; a status run against
an already-patched executable still exits 0. The launcher maps 10 to its offer
branch and everything else to its report branch.

Elevation now has three separate entry points (`:denied_status`,
`:denied_apply`, `:denied_args`) instead of one shared `:denied`, precisely so
that an elevated retry re-runs *the same thing the user asked for* and nothing
more — an elevated double-click retries the status and offer, an elevated
`Apply` retries `Apply -Yes`, and an elevated `SaveFix.bat Apply -MiB 8`
retries exactly those arguments.

---

## Publishing

### Normal route: ModBuddy

The supported way is Firaxis' own tool, which ships with the **XCOM 2
Development Tools** — a separate Steam app, **id 299990**, not part of the game
install. (It is also the only way to build an actual UnrealScript mod for this
game, since it carries UnrealEd and the un-cooked packages.)

For an item like this one — no `Src/`, no `Script/`, no cooked content — ModBuddy
is heavyweight: the upload dialog only needs a folder and a manifest.

### Scriptable route: steamcmd

`workshop_build.vdf` in this folder is ready for Valve's `steamcmd`:

```console
steamcmd +login <account> +workshop_build_item <path to workshop_build.vdf> +quit
```

* `publishedfileid 0` creates a new item; paste the assigned ID in for later
  updates. The file in this repository already carries the real ID.
* `steamcmd` replaces the item's file set with the contents of `contentfolder`,
  so keep that folder exactly as it should appear to subscribers.
* **Keep the `.vdf` outside `contentfolder`**, or it uploads itself as content.
  That is why `contentfolder` points at `workshop/item/` and not at
  `workshop/`.
* The paths in the `.vdf` are absolute. Adjust them when publishing elsewhere —
  SteamCMD does not resolve them relative to the config file.
* Logging in needs the account password **and** a Steam Guard code. With the
  mobile authenticator, `steamcmd` prints
  `Please enter the current code from your Steam Guard Mobile Authenticator app`
  and accepts one interactively — allow a couple of minutes, the prompt times
  out. Once it has succeeded, credentials are cached and later runs need
  nothing.

`steamcmd` is not bundled with Steam; it is a separate download from Valve.
The full XCOM 2 Development Tools install is not needed for this route — the
70 GB of the SDK is its content depot, and none of it is used here.

### What SteamCMD does and does not do

`steamcmd` **does** upload `title`, `description`, `changenote`, `visibility` and
the preview image straight from the `.vdf`, so nothing has to be retyped in the
Steam UI afterwards. What it does *not* do is interpret anything inside those
values: escaping, markup or otherwise. Whatever is between the quotes is what
lands on the page, which is why the newline rule above matters and why the
`.vdf` in this repository is the authoritative copy of the page copy.

"Arrived" and "arrived correctly" are different claims, and only the second one
is worth making. Verify by fetching the description back and counting: no
literal `\n`, a plausible number of real line breaks, and the expected script
present. Reading the page by eye is what let a page full of literal `\n` pass as
correct on the first publish.

What it does *not* do is rewrite the **description inside `SaveFix.XComMod`**:
that one is read by the launcher's mod list, which will never show this item,
so it is a second copy of the page text kept with the shipped files.

One consequence worth knowing: `steamcmd` **rewrites the `.vdf` it was given**,
reordering keys and filling in the assigned item id. That is normal, and it is
why the id below is already the real one.

---

## Checklist before publishing

- [ ] `SaveFix.XComMod` — title, description, tags present; real newlines.
- [ ] `workshop_build.vdf` — `description` uses real newlines too; keys intact.
- [ ] `python tools/check_vdf.py` — exits `0`. Run it before every upload: the
      SteamCMD parser only reports problems after a failed attempt, and its
      message names the wrong thing (see *A quote inside the description closes
      it early* above).
- [ ] `ModPreview.jpg` — regenerated, 1024×1024, shows the actual fix.
- [ ] `SaveFix.ps1` — syntax-checks clean, and `Status` / `Apply` / `Restore`
      all behave on a **copy** of the executable.
- [ ] `SaveFix.bat` — **CRLF line endings, and its own path quoted.** Both are
      load-bearing: an unquoted path breaks on the default Steam location
      (`Program Files (x86)` contains `)`), and a LF-only `.bat` fails `goto`.
      Run it from a folder whose name contains a space *and* a parenthesis.
- [ ] `LICENSE` — present, with the copyright line filled in.
- [ ] No game files in the folder: no `.exe`, `.dll`, `.upk`, `.bin`.
- [ ] No BOM on any text file (Windows tooling is inconsistent about this).
- [ ] The page copy does not claim the item is a mod, and does not claim mods
      can fix this. It is a tool, and it patches one byte.
- [ ] **After publishing**: fetch the description back and check it — literal
      `\n` count is 0 and the expected text is present. Do not eyeball the page.

---

## After publishing

* The item page is the support surface. Point bug reports at
  `https://github.com/A16Nights/xcom2-savefix/issues`.
* If the game updates and the patch site moves, the tool refuses to write and
  says so. Fix once in the repository, then re-upload the folder.
* Steam "Verify integrity of game files" and game updates both revert the
  patch. Re-running the tool is the fix; that is worth saying on the page, and
  it is.

### What the live item actually reports

Published as id `3818684374`, visibility public, uploaded with `steamcmd`:

| Field | Value |
|---|---|
| title | `[WOTC] Savefix - Beyond 65535` |
| file size | `164834` bytes — the sum of the six shipped files (1066 + 121113 + 4678 + 6295 + 25900 + 5782) |
| creator | the uploading account, `76561198315647197` |
| banned | `0` |

The file size matching the sum exactly is the check that the whole
`contentfolder` made it up, and that nothing extra went with it. It has been a
useful tripwire five times: `152773` on the first upload (before the real item
id replaced the `0` placeholder), `152782` once it had, `153909` after the
Chinese section was added to `SaveFix.XComMod`, `160569` for the launcher and
admin-rights fixes, and `164834` for the release that taught a plain
double-click to offer the patch.

The current `164834` is the sum of the six shipped files, measured in the
working tree: `1066` LICENSE + `121113` ModPreview.jpg + `4678` ReadMe.txt +
`6295` SaveFix.bat + `25900` SaveFix.ps1 + `5782` SaveFix.XComMod.

Two notes for comparing these numbers across releases.

**Measure the working tree, not the repository blob.** `.gitattributes`
normalises `.bat`/`.cmd` to LF in the repository and restores CRLF on checkout,
so `SaveFix.bat` legitimately has two sizes — `6121` as a blob, `6295` in the
working tree (`6121` + `174` CRs). SteamCMD uploads the working tree.

**The older `153909` row is correct, and it proves the launcher bug was live.**
Its addends are `1066` LICENSE, `121113` ModPreview.jpg, `3430` ReadMe.txt,
`4012` SaveFix.XComMod, `1323` SaveFix.bat, `22965` SaveFix.ps1 — note that
`4012` belongs to `SaveFix.XComMod`, not to the `.bat`, whose size was `1323`.
The sum is exact, and it is exact *only* for the LF `.bat`: substituting the
CRLF size `1362` would give `153948`, not `153909`. So the launcher Steam was
serving then really did carry LF-only line endings. That second defect is
described in the CHANGELOG, but it was inferred from the repository; this
arithmetic shows it was present in the distributed artifact.

`time_updated` on the item is `1791889845` (2026-10-13 11:10:45 UTC), ~85
seconds *after* the final repository commit `8119343` — the upload was the last
step, not an earlier state that later landed in git.
