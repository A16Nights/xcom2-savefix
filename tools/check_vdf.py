"""Validate the Workshop build VDF the way KeyValues would read it.

SteamCMD's own parser is the authority, but running it is an upload attempt -
and a failed attempt is a public no-op at best. This walks the same grammar
offline first: a list of quoted tokens, where each key's value is either a
quoted string or a nested ``{ }`` block, and it reports the first thing that
would stop Valve's parser.

Written after a real failure. A naked double quote inside the ``description``
value closed the string early, so the remainder of the page text was read as a
key name and the upload died with two errors that name the wrong problem:

    Bad expression token: y at 1 in y/N]
    Assertion Failed: key name too long (3450 chars)

The second one is the informative message, and neither points at the quote.

Usage:
    python tools/check_vdf.py [path/to/workshop_build.vdf]

Exit status is 0 when the file parses cleanly, 1 otherwise. The default path is
``workshop/workshop_build.vdf`` next to this repository.
"""
import pathlib
import re
import sys

DEFAULT_VDF = (
    pathlib.Path(__file__).resolve().parent.parent / "workshop" / "workshop_build.vdf"
)

# Valve rejects key names beyond this; the real limit is not documented, but a
# key anywhere near this length means a value was mis-read as a key.
KEY_NAME_LIMIT = 200

REQUIRED = ("appid", "publishedfileid", "contentfolder", "previewfile", "visibility")
TEXT_FIELDS = ("title", "description", "changenote")


class Parser:
    def __init__(self, text: str) -> None:
        self.t = text
        self.i = 0
        self.errors: list[str] = []
        # Once a token cannot be read the position does not advance, so every
        # enclosing block would re-report the same offset. The first error is
        # the informative one; stop there.
        self.stuck = False

    def line_of(self, pos: int) -> int:
        return self.t.count("\n", 0, pos) + 1

    def fail(self, msg: str) -> None:
        """Record the first fatal error only. See self.stuck."""
        if not self.stuck:
            self.errors.append(msg)
            self.stuck = True

    def skip_ws(self) -> None:
        while self.i < len(self.t):
            c = self.t[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif self.t.startswith("//", self.i):
                j = self.t.find("\n", self.i)
                self.i = len(self.t) if j < 0 else j + 1
            else:
                return

    def read_token(self) -> str | None:
        self.skip_ws()
        if self.i >= len(self.t):
            return None
        c = self.t[self.i]
        if c in "{}":
            self.i += 1
            return c
        if c != '"':
            # A naked character where a token should start is exactly the
            # symptom of an unbalanced quote earlier in the file.
            self.fail(
                f"line {self.line_of(self.i)}: expected a quoted token or a "
                f"brace, found {c!r} (offset {self.i}) - an earlier quote is "
                "probably unbalanced"
            )
            return None
        j = self.t.find('"', self.i + 1)
        if j < 0:
            self.fail(f"line {self.line_of(self.i)}: unterminated quoted string")
            return None
        s = self.t[self.i + 1 : j]
        self.i = j + 1
        return s

    def note_long_key(self, key: str) -> None:
        if len(key) > KEY_NAME_LIMIT:
            self.fail(
                f"line {self.line_of(self.i)}: key name is {len(key)} chars - "
                "the parser would reject this (a long value has likely been "
                "read as a key, which means a quote is unbalanced)"
            )

    def parse_block(self) -> int:
        """Parse key/value pairs until the matching }. Returns keys seen."""
        keys = 0
        while not self.stuck:
            tok = self.read_token()
            if self.stuck or tok is None or tok == "}":
                return keys
            key = tok
            if key == "{":
                self.fail(f"line {self.line_of(self.i)}: nested block with no key name")
                return keys
            nxt = self.read_token()
            if self.stuck or nxt is None:
                self.fail(f"line {self.line_of(self.i)}: key {key!r} has no value")
                return keys
            if nxt == "{":
                self.note_long_key(key)
                keys += 1 + self.parse_block()
            elif nxt == "}":
                self.fail(f"line {self.line_of(self.i)}: key {key!r} has no value")
                return keys
            else:
                self.note_long_key(key)
                keys += 1
                if nxt.strip() == "":
                    self.fail(f"line {self.line_of(self.i)}: key {key!r} has an empty value")
        return keys


def main(argv: list[str]) -> int:
    vdf = pathlib.Path(argv[1]) if len(argv) > 1 else DEFAULT_VDF
    if not vdf.is_file():
        print(f"no such file: {vdf}")
        return 1

    raw = vdf.read_bytes()
    text = raw.decode("utf-8")

    print(f"file        : {vdf}")
    print(f"size        : {len(raw)} bytes")
    print(f"lines       : {text.count(chr(10)) + 1}")
    print(f"bare quotes : {text.count(chr(34))}")

    p = Parser(text)
    n = p.parse_block()
    print(f"top-level keys parsed : {n}")
    print(f"bytes consumed        : {p.i} / {len(text)}")

    print()
    for field in REQUIRED:
        m = re.search(rf'"{field}"\s+"([^"]*)"', text)
        print(f"  {field:<16} = {m.group(1) if m else '<MISSING>'}")

    for field in TEXT_FIELDS:
        m = re.search(rf'"{field}"\s+"(.*?)"\s*\n', text, flags=re.S)
        if m:
            val = m.group(1)
            print(f"  {field:<16} {len(val)} chars, {val.count(chr(10)) + 1} lines")

    # The description is the one field long enough, and free-form enough, to
    # contain something that closes its own string.
    desc = re.search(r'"description"\s+"(.*?)"\s*\n\t"changenote"', text, flags=re.S)
    if desc:
        body = desc.group(1)
        print()
        print("description value checks")
        for label, pat in (
            ("naked double quote", r'"'),
            ("stray opening brace", r"\{"),
            ("stray closing brace", r"\}"),
        ):
            hits = [i + 1 for i, ln in enumerate(body.split("\n")) if re.search(pat, ln)]
            print(f"  {label:<22}: {len(hits)}" + (f" (lines {hits})" if hits else ""))
        print(f"  real newlines          : {body.count(chr(10))}")
        print(f"  literal backslash-n    : {body.count(chr(92) + 'n')}")

    if p.errors:
        print()
        print("PROBLEMS")
        for e in p.errors:
            print(f"  {e}")
        print("VERDICT: this file would not parse")
        return 1

    leftover = text[p.i :].strip()
    if leftover:
        print()
        print(f"leftover after parse: {leftover[:120]!r}")
        print("VERDICT: trailing content after the closing brace")
        return 1

    print()
    print("VERDICT: parses cleanly, every key has a value, quotes balance")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
