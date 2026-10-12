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

* **`Description` uses literal newlines**, not `\n` escapes. Writing `\n`
  produces a page with visible backslash-n in it.
* Steam-native BBCode is supported in the body: `[b]`, `[list]`, `[code]`,
  `[url]`. The item page renders these; `ReadMe.txt` is plain text.

The manifest now carries the live id (`publishedFileId=3818684374`). Before the
first publish it was `0`: Steam assigns the real id on first publish, and the
item's folder on disk also gets a `PublishedFileId.ID` file containing it. A
manifest left at `0` is only correct for a brand new item.

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
the preview image straight from the `.vdf` — verified against the live item,
whose page text came out byte-identical to the `description` block in the file.
So nothing has to be retyped in the Steam UI afterwards, and the `.vdf` in this
repository is the authoritative copy of the page copy.

What it does *not* do is rewrite the **description inside `SaveFix.XComMod`**:
that one is read by the launcher's mod list, which will never show this item,
so it is a second copy of the page text kept with the shipped files.

One consequence worth knowing: `steamcmd` **rewrites the `.vdf` it was given**,
reordering keys and filling in the assigned item id. That is normal, and it is
why the id below is already the real one.

---

## Checklist before publishing

- [ ] `SaveFix.XComMod` — title, description, tags present; newlines literal.
- [ ] `ModPreview.jpg` — regenerated, 1024×1024, shows the actual fix.
- [ ] `SaveFix.ps1` — syntax-checks clean, and `Status` / `Apply` / `Restore`
      all behave on a **copy** of the executable.
- [ ] `LICENSE` — present, with the copyright line filled in.
- [ ] No game files in the folder: no `.exe`, `.dll`, `.upk`, `.bin`.
- [ ] No BOM on any text file (Windows tooling is inconsistent about this).
- [ ] The page copy does not claim the item is a mod, and does not claim mods
      can fix this. It is a tool, and it patches one byte.

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
| file size | `152782` bytes — the sum of the six shipped files (1066 + 121113 + 3430 + 1323 + 22965 + 2885) |
| creator | the uploading account, `76561198315647197` |
| banned | `0` |

The file size matching the sum exactly is the check that the whole
`contentfolder` made it up, and that nothing extra went with it. (The first
upload reported `152773`, 9 bytes less: that was before the real item id
replaced the `0` placeholder in the manifest.)
