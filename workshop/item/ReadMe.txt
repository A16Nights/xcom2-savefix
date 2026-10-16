SaveFix - Beyond 65535
======================

Lets XCOM 2 read saves whose header has grown past 65,535 bytes.

WHY
---
A heavily modded campaign eventually makes a save header larger than 65535
bytes. The game then refuses to read that save: it appears red in the load
list, and even "LOAD ANYWAY" ends in "LOAD FAILED". Nothing is wrong with the
save - the loader's own size check is rejecting it.

The save header is mostly the mod list: measured across real saves, name
records fill 97-99% of it. And that list is not stored once - in an ordinary
save every mod name appears exactly twice, and in a heavy campaign the whole
list is serialised four or six times. That is why the header grows several
times faster than your mod collection and long-running campaigns cross the
line.

What the game compares, though, is the header's own length - a 32-bit field at
file offset 4 - against 65536. Raising that one comparison lets any header
through, however many mods it describes.

This is NOT a mod in the usual sense. The game never loads it and it cannot be
turned on or off in the launcher. It is a tool that patches YOUR OWN copy of
XCom2.exe, once. No game files are redistributed here.


QUICK START
-----------
1. Close XCOM 2. (It locks the executable while the game is running.)
2. Open this folder (where Steam downloaded this item).
3. Double-click  SaveFix.bat
      -> read-only report. It tells you whether your executable is original
         or already patched, and what the current limit is.
4. If it says ORIGINAL it then asks:
         Raise it to 4 MiB now? [y/N]
   Type  y  and press Enter. One byte of XCom2.exe changes.
5. Start the game and load the save that used to be red.

Steps 3 and 4 are one double-click and one keystroke. You do not need a
command prompt. If you want a different limit, or to script the tool, use the
commands below instead - passing any argument skips the question.


COMMANDS
--------
    SaveFix.bat                     report, then offer to patch (double-click this)
    SaveFix.bat Apply               raise the limit to 4 MiB (default)
    SaveFix.bat Apply -MiB 8        raise it to 8 MiB instead
    SaveFix.bat Restore             put the original executable back

Options:

    -Exe "<path>"    use a specific XCom2.exe (auto-detected otherwise)
    -Yes             skip the confirmation prompt

The first line is what a double-click does. Any argument at all skips the
question and behaves exactly as documented above.


UNDOING IT
----------
    SaveFix.bat Restore

A copy of your original executable is written to XCom2.exe.65535bak next to
the game's executable before the first change, and Restore puts it back
byte-for-byte. "Verify integrity of game files" in Steam has the same effect.

Steam verifying files, or a game update, will undo the patch. Running the tool
again re-applies it - it is not cumulative or destructive.


WHAT IT ACTUALLY CHANGES
------------------------
One instruction inside XCom2.exe:

    before:  81 7d 38 00 00 01 00    cmp dword [rbp+0x38], 0x10000    (65536)
    after:   81 7d 38 00 00 40 00    cmp dword [rbp+0x38], 0x400000   (4 MiB)

Saved files are not modified, not rewritten, and not re-hashed. The game's
save-writing path was never limited in the first place - only reading was.

The tool finds that instruction by byte signature, never by a fixed address,
so it keeps working if the address moves and it works on both the base game
and War of the Chosen. If the signature does not match exactly once, the tool
refuses to write anything.


REQUIREMENTS AND CAVEATS
------------------------
- Windows, with PowerShell 5.1 (present on any current Windows).
- If your game is under "C:\Program Files (x86)" - the Steam default - the
  folder is usually administrator-only, so the tool cannot read or write
  XCom2.exe. It will say so and offer to retry elevated; say yes, or
  right-click SaveFix.bat and choose "Run as administrator".
- Modifies a game executable. That is your decision to make; it is why this
  is a manual install rather than an ordinary mod.
- Antivirus software may flag any tool that writes to an .exe. The script is
  plain text - open SaveFix.ps1 in Notepad and read it before running it.
- Tested against the Steam builds of XCOM 2 and War of the Chosen. It will
  refuse to act on an executable it does not recognise.


MORE
----
Source, full technical writeup, save-format notes, and an alternative Python
implementation:

    https://github.com/A16Nights/xcom2-savefix


LICENSE
-------
MIT. See the repository. XCOM 2 is a trademark of Take-Two Interactive; this
project is unaffiliated with and not endorsed by Firaxis Games or 2K Games.
