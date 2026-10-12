# -*- coding: utf-8 -*-
"""XCOM 2 / War of the Chosen save-header 65535 limit unlock.

Background
----------
A save file whose header length field (the dword at file offset 0x04, called
``a4`` here) exceeds 65535 cannot be loaded: the game shows the save as corrupt
and refuses to load it.  Heavy mod users hit this because the save header
records the full list of active mods.

The limit is *not* in the file format -- every length field in a save file is
32-bit.  It is a single hard-coded comparison in the game executable::

    81 7d 38 <imm32>      cmp  dword ptr [rbp+0x38], <imm32>
    0f 87 <rel32>         ja   <failure>

The writer never enforced it; only this read-side check does.  Raising the
immediate to a larger value lets oversized saves load normally.

This tool locates that instruction by *byte signature* rather than by a
hard-coded address, so it keeps working across game builds.  It supports both
``XCom2.exe`` (base game) and ``XCom2-WarOfTheChosen\\Binaries\\Win64\\XCom2.exe``.

Only one byte is changed in practice (0x10000 -> 0x400000 differs in a single
byte of the little-endian immediate), and the instruction encoding is left
intact, so the executable stays structurally valid.

Usage
-----
    python xcom2_savefix.py status            # inspect: locate site, show state
    python xcom2_savefix.py apply [MiB]       # patch (default 4 MiB), with backup
    python xcom2_savefix.py restore           # restore from backup
    python xcom2_savefix.py saves             # list save files and their a4

Common options:
    --exe PATH      operate on a specific executable
    --all           operate on every XCOM 2 executable found
    --save-dir DIR  override the save directory used by `saves`
    --dry-run       do not write anything (apply/restore)
    --yes           do not ask for confirmation

Notes
-----
* Close the game before patching; a running process locks the executable.
* Steam "verify integrity of game files" and game updates restore the original
  executable.  Re-run ``apply`` afterwards.
* Saves written with a raised limit are still unreadable on an unpatched
  installation.  Use ``restore`` to go back to vanilla behaviour.
"""
from __future__ import annotations

import argparse
import os
import shutil
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from pe_util import PE, PEError, find_all_patterns  # noqa: E402

# --------------------------------------------------------------------- facts
# Signature of the read-side length check.  Wildcards cover the immediate
# (which changes when patched) and the `ja` displacement (which differs
# slightly between the base game and WOTC builds).
SITE_PATTERN = '81 7d 38 ?? ?? ?? ?? 0f 87 ?? ?? ?? ?? 83 7b 4c 00 74 29'
# Looser fallback, in case a future build differs after the `ja`.
SITE_PATTERN_LOOSE = '81 7d 38 ?? ?? ?? ?? 0f 87'

IMM_OFFSET = 3          # the immediate starts 3 bytes into the match
ORIG_LIMIT = 0x10000    # vanilla hard limit (65536)
DEFAULT_MIB = 4

# Build detection reads the file's own version resource rather than its path,
# so a renamed or relocated copy (a backup, say) is still identified correctly.
# "War of the Chosen" appears five times as UTF-16 in the WOTC executable and
# zero times in the base-game executable; "XCOM 2" appears in both.
WOTC_MARKER = 'War of the Chosen'.encode('utf-16-le')
GAME_MARKER = 'XCOM 2'.encode('utf-16-le')

BACKUP_SUFFIX = '.65535bak'

WOTC_REL = os.path.join('XCom2-WarOfTheChosen', 'Binaries', 'Win64', 'XCom2.exe')
BASE_REL = os.path.join('Binaries', 'Win64', 'XCom2.exe')

SAVE_SUBDIRS = [
    os.path.join('my games', 'XCOM2 War of the Chosen', 'XComGame', 'SaveData'),
    os.path.join('my games', 'XCOM2', 'XComGame', 'SaveData'),
]


# ------------------------------------------------------------------ finding
def _registry_documents() -> str | None:
    """Resolve the real Documents folder (it may be redirected to OneDrive)."""
    if os.name != 'nt':
        return None
    try:
        import winreg
    except ImportError:
        return None
    key = r'Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders'
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
            raw, _ = winreg.QueryValueEx(k, 'Personal')
    except OSError:
        return None
    return os.path.expandvars(raw)


def candidate_save_dirs() -> list[str]:
    out = []
    docs = _registry_documents()
    homes = [d for d in (docs, os.path.join(os.path.expanduser('~'), 'Documents'),
                         os.path.join(os.path.expanduser('~'), 'OneDrive', 'Documents'))
             if d]
    for home in homes:
        for sub in SAVE_SUBDIRS:
            p = os.path.join(home, sub)
            if p not in out:
                out.append(p)
    return out


def find_save_dir(explicit: str | None = None) -> str | None:
    if explicit:
        return explicit if os.path.isdir(explicit) else None
    for p in candidate_save_dirs():
        if os.path.isdir(p):
            return p
    return None


def _steam_roots() -> list[str]:
    """Locate Steam installation roots from the registry."""
    roots = []
    if os.name != 'nt':
        return roots
    try:
        import winreg
    except ImportError:
        return roots
    for hive, key, name in (
        (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\WOW6432Node\Valve\Steam', 'InstallPath'),
        (winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\Valve\Steam', 'InstallPath'),
    ):
        try:
            with winreg.OpenKey(hive, key) as k:
                val, _ = winreg.QueryValueEx(k, name)
        except OSError:
            continue
        if val and os.path.isdir(val) and val not in roots:
            roots.append(val)
    return roots


def _library_folders(steam_root: str) -> list[str]:
    """Read libraryfolders.vdf to enumerate every Steam library on the system."""
    out = [steam_root]
    vdf = os.path.join(steam_root, 'steamapps', 'libraryfolders.vdf')
    if not os.path.isfile(vdf):
        return out
    try:
        with open(vdf, 'r', encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError:
        return out
    import re
    for m in re.finditer(r'"path"\s*"([^"]+)"', text):
        p = m.group(1).replace('\\\\', '\\')
        if os.path.isdir(p) and p not in out:
            out.append(p)
    return out


def candidate_exes(explicit: str | None = None) -> list[str]:
    """Every plausible XCOM 2 executable, deduplicated, existing only.

    The same install is reachable through several routes (Steam registry key,
    libraryfolders.vdf, conventional paths), and Windows paths differ only by
    case, so dedupe on the normalised real path rather than the string.
    """
    if explicit:
        return [explicit] if os.path.isfile(explicit) else []

    found: list[str] = []
    seen: set[str] = set()

    def add(p: str) -> None:
        p = os.path.normpath(p)
        try:
            key = os.path.normcase(os.path.realpath(p))
        except OSError:
            key = os.path.normcase(p)
        if key in seen or not os.path.isfile(p):
            return
        seen.add(key)
        found.append(p)

    for root in _steam_roots():
        for lib in _library_folders(root):
            common = os.path.join(lib, 'steamapps', 'common', 'XCOM 2')
            for rel in (WOTC_REL, BASE_REL):
                add(os.path.join(common, rel))

    # Fall back to a few conventional install paths.
    for drive in ('C:', 'D:', 'E:', 'F:', 'G:'):
        for base in (r'Program Files (x86)\Steam', r'Program Files\Steam',
                     r'Steam', r'Games\Steam', r'SteamLibrary'):
            common = os.path.join(drive + os.sep, base, 'steamapps', 'common', 'XCOM 2')
            for rel in (WOTC_REL, BASE_REL):
                add(os.path.join(common, rel))
    return found


# -------------------------------------------------------------------- site
class Site:
    """The located length check inside one executable."""

    def __init__(self, pe: PE, rva: int, match_len: int, limit: int, loose: bool):
        self.pe = pe
        self.rva = rva
        self.match_len = match_len
        self.limit = limit
        self.loose = loose

    @property
    def va(self) -> int:
        return self.pe.image_base + self.rva

    @property
    def offset(self) -> int | None:
        return self.pe.rva_to_off(self.rva)

    @property
    def state(self) -> str:
        if self.limit == ORIG_LIMIT:
            return 'vanilla'
        if self.limit > ORIG_LIMIT:
            return 'patched'
        return 'unknown'

    def bounds(self):
        return self.pe.function_bounds(self.rva)

    def describe(self) -> str:
        lines = []
        lines.append('  limit site  : RVA 0x%x  VA 0x%x  file offset %s'
                     % (self.rva, self.va,
                        ('0x%x' % self.offset) if self.offset is not None else '?'))
        raw = self.pe.read(self.rva, self.match_len)
        lines.append('  bytes       : %s' % ' '.join('%02x' % b for b in raw))
        lines.append('  decoded     : cmp dword ptr [rbp+0x38], 0x%x  (%d = %s)'
                     % (self.limit, self.limit, human(self.limit)))
        b = self.bounds()
        if b:
            lines.append('  owner func  : RVA 0x%x-0x%x  VA 0x%x-0x%x  (%d bytes), site at +0x%x'
                         % (b[0], b[1], self.pe.image_base + b[0],
                            self.pe.image_base + b[1], b[1] - b[0], self.rva - b[0]))
        else:
            lines.append('  owner func  : (not covered by .pdata)')
        lines.append('  match       : %d bytes%s'
                     % (self.match_len, '  [loose pattern]' if self.loose else ''))
        lines.append('  state       : %s' % self.state.upper())
        return '\n'.join(lines)


def locate(pe: PE):
    """Find the limit site.  Returns (Site, note) or (None, reason)."""
    for pattern, loose in ((SITE_PATTERN, False), (SITE_PATTERN_LOOSE, True)):
        hits = find_all_patterns(pe.data, pattern)
        if len(hits) == 1:
            rva = pe.off_to_rva(hits[0])
            if rva is None:
                return None, 'match is not inside a mapped section'
            limit = struct.unpack_from('<I', pe.data, hits[0] + IMM_OFFSET)[0]
            return Site(pe, rva, len(pattern.split()), limit, loose), None
        if len(hits) > 1:
            note = ('%d matches for %s pattern -- refusing to guess; '
                    'please report this build' % (len(hits), 'loose' if loose else 'strict'))
            note += '\n' + '\n'.join('    RVA 0x%x' % (pe.off_to_rva(h) or 0) for h in hits[:10])
            return None, note
    return None, 'limit site not found (unsupported game build?)'


def human(n: int) -> str:
    if n >= 1024 * 1024 and n % (1024 * 1024) == 0:
        return '%d MiB' % (n // (1024 * 1024))
    if n >= 1024 and n % 1024 == 0:
        return '%d KiB' % (n // 1024)
    return '%d bytes' % n


def load_pe(path: str) -> PE:
    with open(path, 'rb') as f:
        data = f.read()
    return PE(data, path)


def detect_build(pe: PE) -> str:
    """Identify the build from the file's own contents, never from its path."""
    if WOTC_MARKER in pe.data:
        return 'War of the Chosen'
    if GAME_MARKER in pe.data:
        return 'base game'
    return 'unknown (not an XCOM 2 executable?)'


# ----------------------------------------------------------------- commands
def cmd_status(args) -> int:
    exes = candidate_exes(args.exe)
    if not exes:
        print('No XCOM 2 executable found.')
        print('Pass one explicitly:  --exe "D:\\path\\to\\XCom2.exe"')
        return 2

    print('XCOM 2 save-limit unlock -- status')
    print('=' * 72)
    rc = 0
    for path in exes:
        print()
        print('executable : %s' % path)
        try:
            pe = load_pe(path)
        except (OSError, PEError) as e:
            print('  cannot read: %s' % e)
            rc = max(rc, 3)
            continue
        print('  size       : %d bytes   image base 0x%x   sections %d'
              % (len(pe.data), pe.image_base, len(pe.sections)))
        kind = detect_build(pe)
        print('  build      : %s' % kind)
        site, note = locate(pe)
        if site is None:
            print('  !! %s' % note)
            rc = max(rc, 3)
            continue
        print(site.describe())
        backup = path + BACKUP_SUFFIX
        print('  backup     : %s'
              % (backup if os.path.isfile(backup) else '(none)'))

    print()
    print('-' * 72)
    d = find_save_dir(args.save_dir)
    if d:
        print('save dir   : %s' % d)
    else:
        print('save dir   : (not found; pass --save-dir to point at it)')
    return rc


def _confirm(question: str, assume_yes: bool) -> bool:
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        return False
    try:
        reply = input('%s [y/N] ' % question).strip().lower()
    except EOFError:
        return False
    return reply in ('y', 'yes')


def cmd_apply(args) -> int:
    if not (1 <= args.mib <= 4096):
        print('!! --mib must be between 1 and 4096')
        return 2
    new_limit = args.mib * 1024 * 1024
    if new_limit <= ORIG_LIMIT:
        print('!! the new limit must be greater than the vanilla 65536')
        return 2
    if not new_limit % 0x10000:
        pass  # not required, but nice

    exes = candidate_exes(args.exe)
    if not exes:
        print('No XCOM 2 executable found.  Pass one with --exe PATH')
        return 2

    print('XCOM 2 save-limit unlock -- apply (new limit = %d = %s)'
          % (new_limit, human(new_limit)))
    print('=' * 72)
    rc = 0
    for path in exes:
        print()
        print('executable : %s' % path)
        try:
            pe = load_pe(path)
        except (OSError, PEError) as e:
            print('  cannot read: %s' % e)
            rc = max(rc, 3)
            continue
        site, note = locate(pe)
        if site is None:
            print('  !! %s' % note)
            rc = max(rc, 3)
            continue
        print(site.describe())
        off = site.offset
        if off is None:
            print('  !! site is not backed by file data')
            rc = max(rc, 3)
            continue

        if site.limit == new_limit:
            print('  already patched to this value -- nothing to do')
            continue
        if site.limit < ORIG_LIMIT:
            print('  !! current immediate (0x%x) is below the vanilla limit;'
                  ' this does not look like the expected instruction' % site.limit)
            rc = max(rc, 3)
            continue

        backup = path + BACKUP_SUFFIX
        if os.path.isfile(backup):
            print('  backup     : %s (already exists, keeping it)' % backup)
        elif args.dry_run:
            print('  backup     : would create %s' % backup)
        else:
            print('  backup     : creating %s' % backup)
            shutil.copy2(path, backup)

        old = pe.data[off:off + 7]
        new = old[:IMM_OFFSET] + struct.pack('<I', new_limit)
        print('  bytes now  : %s' % ' '.join('%02x' % b for b in old))
        print('  bytes new  : %s' % ' '.join('%02x' % b for b in new))
        changed = sum(1 for a, b in zip(old, new) if a != b)
        print('  changed    : %d byte(s)' % changed)

        if args.dry_run:
            print('  dry run    : not writing')
            continue

        try:
            with open(path, 'r+b') as f:
                f.seek(off)
                f.write(new)
        except PermissionError:
            print('  !! permission denied -- close the game and retry')
            rc = max(rc, 4)
            continue

        verify = load_pe(path)
        got = verify.data[off:off + 7]
        if got == new:
            print('  verify     : OK -- saved with limit 0x%x' % new_limit)
        else:
            print('  verify     : !! unexpected bytes after write: %s'
                  % ' '.join('%02x' % b for b in got))
            rc = max(rc, 5)

    print()
    print('-' * 72)
    print('Done.  Start the game normally; oversized saves should load.')
    return rc


def cmd_restore(args) -> int:
    exes = candidate_exes(args.exe)
    if not exes:
        print('No XCOM 2 executable found.  Pass one with --exe PATH')
        return 2
    rc = 0
    for path in exes:
        backup = path + BACKUP_SUFFIX
        print('executable : %s' % path)
        if not os.path.isfile(backup):
            print('  no backup at %s -- nothing to restore' % backup)
            print('  (Steam "verify integrity of game files" also restores the original)')
            rc = max(rc, 3)
            continue
        if args.dry_run:
            print('  dry run    : would copy %s -> %s' % (backup, path))
            continue
        try:
            shutil.copy2(backup, path)
        except PermissionError:
            print('  !! permission denied -- close the game and retry')
            rc = max(rc, 4)
            continue
        pe = load_pe(path)
        site, _note = locate(pe)
        if site and site.state == 'vanilla':
            print('  restored   : limit is back to 0x%x (vanilla)' % site.limit)
        elif site:
            print('  restored, but limit reads 0x%x' % site.limit)
        else:
            print('  restored (limit site not found -- check the game install)')
    return rc


def cmd_saves(args) -> int:
    d = find_save_dir(args.save_dir)
    if not d:
        print('Save directory not found.')
        print('Pass one with --save-dir, e.g.')
        print(r'  --save-dir "%USERPROFILE%\Documents\my games\XCOM2 War of the Chosen\XComGame\SaveData"')
        return 2

    print('save dir : %s' % d)
    print()
    head = '%-46s %11s %9s  %-9s %-9s' % ('file', 'size', 'a4', '>vanilla', 'fits new')
    print(head)
    print('-' * len(head))

    rows, over, still = [], [], []
    for name in sorted(os.listdir(d)):
        p = os.path.join(d, name)
        if not os.path.isfile(p) or os.path.getsize(p) < 0x18:
            continue
        try:
            with open(p, 'rb') as f:
                head_bytes = f.read(0x18)
            ver, a4 = struct.unpack_from('<ii', head_bytes, 0)
        except (OSError, struct.error):
            continue
        if ver != 22:
            continue
        rows.append((name, os.path.getsize(p), a4))
        if a4 > ORIG_LIMIT:
            over.append(name)
            if a4 <= DEFAULT_MIB * 1024 * 1024:
                pass
            else:
                still.append(name)

    new_limit = None
    for path in candidate_exes(args.exe):
        try:
            pe = load_pe(path)
        except (OSError, PEError):
            continue
        site, _ = locate(pe)
        if site:
            new_limit = site.limit
            print('(current executable limit: 0x%x = %s)'
                  % (new_limit, human(new_limit)))
        break

    for name, size, a4 in rows:
        fits = ''
        if a4 > ORIG_LIMIT and new_limit:
            fits = 'yes' if a4 <= new_limit else 'NO'
        print('%-46s %11d %9d  %-9s %-9s'
              % (name[:46], size, a4, 'yes' if a4 > ORIG_LIMIT else '', fits))

    print()
    print('a4 = header length field at file offset 0x04 (the dword the game compares)')
    print('saves over the vanilla limit: %d' % len(over))
    if new_limit is None:
        print('(run `status` to see whether the current executable is patched)')
    elif still:
        print('!! %d save(s) still exceed the current limit -- raise --mib'
              % len(still))
        for n in still:
            print('     %s' % n)
    return 0


# --------------------------------------------------------------------- main
def add_common_options(parser: argparse.ArgumentParser) -> None:
    """Options accepted both before and after the sub-command.

    argparse gives the sub-parser its own defaults, which would clobber a value
    already parsed by the top-level parser, so these use SUPPRESS and `main`
    fills in the real defaults afterwards.
    """
    parser.add_argument('--exe', metavar='PATH', default=argparse.SUPPRESS,
                        help='operate on this executable instead of auto-detecting')
    parser.add_argument('--save-dir', metavar='DIR', default=argparse.SUPPRESS,
                        help='save directory to inspect (used by `saves`)')
    parser.add_argument('--dry-run', action='store_true', default=argparse.SUPPRESS,
                        help='report what would change without writing')
    parser.add_argument('-y', '--yes', action='store_true', default=argparse.SUPPRESS,
                        help='do not ask for confirmation')


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='xcom2_savefix.py',
        description='Raise the XCOM 2 save-header size limit above 65535.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split('Usage\n-----', 1)[-1].strip())
    add_common_options(p)
    sub = p.add_subparsers(dest='cmd')

    sub.add_parser('status', help='locate the limit site and report its state',
                   parents=[_sub_common()])
    ap = sub.add_parser('apply', help='patch the executable (creates a backup)',
                        parents=[_sub_common()])
    ap.add_argument('mib', nargs='?', type=int, default=None,
                    help='new limit in MiB (default %d)' % DEFAULT_MIB)
    sub.add_parser('restore', help='restore the original executable from backup',
                   parents=[_sub_common()])
    sub.add_parser('saves', help='list save files and their header length field',
                   parents=[_sub_common()])
    return p


def _sub_common() -> argparse.ArgumentParser:
    """A reusable parent holding the same options, for use after the command."""
    parent = argparse.ArgumentParser(add_help=False)
    add_common_options(parent)
    return parent


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    for name, default in (('exe', None), ('save_dir', None),
                          ('dry_run', False), ('yes', False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    cmd = args.cmd or 'status'

    if cmd == 'apply':
        mib = args.mib if args.mib is not None else DEFAULT_MIB
        args.mib = mib
        print('This will modify a game executable on disk.')
        print('A backup is created next to it before any write.')
        if not _confirm('Continue?', args.yes):
            print('Aborted (pass --yes to skip this prompt).')
            return 1
        return cmd_apply(args)
    if cmd == 'restore':
        return cmd_restore(args)
    if cmd == 'saves':
        return cmd_saves(args)
    return cmd_status(args)


if __name__ == '__main__':
    sys.exit(main())
