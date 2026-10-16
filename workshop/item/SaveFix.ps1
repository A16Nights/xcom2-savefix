#Requires -Version 5.1
<#
    XCOM 2 Savefix  -  Beyond 65535
    ================================

    A heavily modded XCOM 2 campaign can push a save's header past 65535 bytes.
    When that happens the game refuses to read the save: the entry shows up red
    in the load list ("SAVE OUT OF DATE") and loading it ends in "LOAD FAILED".

    The refusal is one comparison inside XCom2.exe:

        81 7d 38 00 00 01 00   cmp dword ptr [rbp+0x38], 0x10000

    This script rewrites only that immediate:

        81 7d 38 00 00 01 00   ->   81 7d 38 00 00 40 00
        cmp ..., 0x10000            cmp ..., 0x400000        (4 MiB)

    Exactly one byte of XCom2.exe changes. Save files are never modified, and
    the game's write side was never limited - only reading was.

    The patch site is found by signature, never by a hard-coded address, so it
    relocates correctly and works on both the base game and War of the Chosen.
    If the signature does not match exactly once, nothing is written.

    USAGE
        .\SaveFix.ps1                 # report only (read-only, the default)
        .\SaveFix.ps1 Apply           # patch, raising the limit to 4 MiB
        .\SaveFix.ps1 Apply -MiB 8    # patch, raising the limit to 8 MiB
        .\SaveFix.ps1 Restore         # put the original exe back
        .\SaveFix.ps1 Apply -Exe "D:\Games\XCOM 2\...\XCom2.exe"

    Requires Windows PowerShell 5.1 or newer. No third-party modules.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('Status', 'Apply', 'Restore')]
    [string]$Action = 'Status',

    [string]$Exe,

    [ValidateRange(1, 1024)]
    [int]$MiB = 4,

    [switch]$Yes
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$SCRIPT:SigStrict = '81 7d 38 ?? ?? ?? ?? 0f 87 ?? ?? ?? ?? 83 7b 4c 00 74 29'
$SCRIPT:SigLoose = '81 7d 38 ?? ?? ?? ?? 0f 87'
$SCRIPT:ImmOffset = 3
$SCRIPT:Vanilla = [uint32]0x10000
$SCRIPT:BackupExt = '.65535bak'

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

function Write-Head([string]$Text) {
    Write-Host ''
    Write-Host $Text -ForegroundColor Cyan
    Write-Host ('-' * $Text.Length) -ForegroundColor DarkCyan
}

function Test-AccessDenied([System.Exception]$Error_) {
    # PowerShell wraps .NET method failures, so a plain
    # "catch [System.UnauthorizedAccessException]" would miss them. Walk the
    # inner-exception chain instead.
    $e = $Error_
    $depth = 0
    while ($e -and $depth -lt 8) {
        if ($e -is [System.UnauthorizedAccessException]) { return $true }
        if ($e -is [System.Security.SecurityException]) { return $true }
        $e = $e.InnerException
        $depth++
    }
    return $false
}

function Write-AdminHint {
    Write-Host ''
    Write-Host '  The Steam folder is normally administrator-only, because Steam' -ForegroundColor Yellow
    Write-Host '  installs under "C:\Program Files (x86)" by default.' -ForegroundColor Yellow
    Write-Host ''
    Write-Host '  Fix: right-click SaveFix.bat and choose "Run as administrator".' -ForegroundColor Yellow
    Write-Host '       (SaveFix.bat also offers this automatically when it sees the error.)' -ForegroundColor Yellow
    Write-Host '       If you run SaveFix.ps1 directly, start an administrator PowerShell first.' -ForegroundColor Yellow
    Write-Host ''
}

function Write-Item([string]$Label, [string]$Value, [string]$Color = 'Gray') {
    Write-Host ('  {0,-12} {1}' -f ($Label + ':'), $Value) -ForegroundColor $Color
}

function Format-Bytes([byte[]]$Bytes) {
    (($Bytes | ForEach-Object { $_.ToString('x2') }) -join ' ')
}

function Format-U32([uint32]$Value) {
    '0x{0:X8}  ({1:N0})' -f $Value, $Value
}

# ---------------------------------------------------------------------------
# PE parsing - just enough to map a file offset back to an RVA
# ---------------------------------------------------------------------------

function Get-PeInfo {
    param([byte[]]$Data, [string]$Path)

    if ($Data.Length -lt 0x40) { throw "File is too small to be a PE image: $Path" }

    $peOff = [System.BitConverter]::ToInt32($Data, 0x3C)
    if ($peOff -le 0 -or ($peOff + 24) -ge $Data.Length) { throw "Not a PE file (bad e_lfanew): $Path" }
    if ([System.BitConverter]::ToUInt32($Data, $peOff) -ne 0x00004550) { throw "Not a PE file (missing PE signature): $Path" }

    $machine = [System.BitConverter]::ToUInt16($Data, $peOff + 4)
    $numSec = [System.BitConverter]::ToUInt16($Data, $peOff + 6)
    $optSize = [System.BitConverter]::ToUInt16($Data, $peOff + 20)
    $optOff = $peOff + 24

    if ($optOff + $optSize -gt $Data.Length) { throw "Truncated optional header: $Path" }
    $magic = [System.BitConverter]::ToUInt16($Data, $optOff)
    if ($magic -ne 0x20B) { throw ("Unsupported optional header magic 0x{0:X} (this script expects PE32+): {1}" -f $magic, $Path) }

    $imageBase = [System.BitConverter]::ToUInt64($Data, $optOff + 24)
    $secOff = $optOff + $optSize

    $sections = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $numSec; $i++) {
        $o = $secOff + ($i * 40)
        if (($o + 40) -gt $Data.Length) { break }
        $nameBytes = New-Object byte[] 8
        [System.Array]::Copy($Data, $o, $nameBytes, 0, 8)
        $name = ([System.Text.Encoding]::ASCII.GetString($nameBytes)).TrimEnd([char]0)
        $sections.Add([pscustomobject]@{
                Name           = $name
                VirtualSize    = [System.BitConverter]::ToUInt32($Data, $o + 8)
                VirtualAddress = [System.BitConverter]::ToUInt32($Data, $o + 12)
                RawSize        = [System.BitConverter]::ToUInt32($Data, $o + 16)
                RawPtr         = [System.BitConverter]::ToUInt32($Data, $o + 20)
            })
    }

    [pscustomobject]@{
        Path      = $Path
        ImageBase = $imageBase
        Machine   = $machine
        Sections  = $sections.ToArray()
    }
}

function Convert-OffsetToRva {
    param($PeInfo, [int]$Offset)

    foreach ($s in $PeInfo.Sections) {
        if ($Offset -ge $s.RawPtr -and $Offset -lt ($s.RawPtr + $s.RawSize)) {
            return [uint32]($s.VirtualAddress + ($Offset - $s.RawPtr))
        }
    }
    return [uint32]0xFFFFFFFF
}

# ---------------------------------------------------------------------------
# Signature scan (wildcard "??" bytes allowed)
# ---------------------------------------------------------------------------

function Find-Signature {
    param([byte[]]$Data, [string]$Pattern, [int]$MaxHits = 64)

    $tokens = @($Pattern -split '\s+' | Where-Object { $_ -ne '' })
    $n = $tokens.Count
    $fixed = New-Object byte[] $n
    $isFixed = New-Object bool[] $n

    for ($i = 0; $i -lt $n; $i++) {
        if ($tokens[$i] -match '^[0-9A-Fa-f]{2}$') {
            $fixed[$i] = [Convert]::ToByte($tokens[$i], 16)
            $isFixed[$i] = $true
        }
    }

    # Search with the leading run of fixed bytes as the anchor. IndexOf runs in
    # native code over a Latin-1 (1 byte == 1 char) view of the file, which is
    # what keeps this fast on a 30 MB executable.
    $anchorLen = 0
    while ($anchorLen -lt $n -and $isFixed[$anchorLen]) { $anchorLen++ }
    if ($anchorLen -lt 2) { throw "Pattern needs at least two leading fixed bytes: $Pattern" }

    $latin1 = [System.Text.Encoding]::GetEncoding(28591)
    $haystack = $latin1.GetString($Data)
    $needle = $latin1.GetString($fixed[0..($anchorLen - 1)])

    $hits = New-Object System.Collections.Generic.List[int]
    $searchFrom = 0
    $lastStart = $Data.Length - $n

    while ($searchFrom -le $lastStart) {
        $idx = $haystack.IndexOf($needle, $searchFrom, [System.StringComparison]::Ordinal)
        if ($idx -lt 0) { break }

        $ok = $true
        for ($j = $anchorLen; $j -lt $n; $j++) {
            if ($isFixed[$j] -and $Data[$idx + $j] -ne $fixed[$j]) { $ok = $false; break }
        }
        if ($ok) {
            $hits.Add($idx)
            if ($hits.Count -ge $MaxHits) { break }
        }
        $searchFrom = $idx + 1
    }

    # Wrapped in a PSCustomObject on purpose. A bare array return is expanded by
    # PowerShell's output stream, so "@(Find-Signature ...)" would nest a
    # multi-hit result into a single array element and $hits[0] would come back
    # as an array. A property on an object survives the trip intact.
    return [pscustomobject]@{ Hits = $hits.ToArray() }
}

function Get-Sha256 {
    param([string]$Path)

    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            return ([System.BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '')
        }
        finally { $stream.Dispose() }
    }
    finally { $sha.Dispose() }
}

# ---------------------------------------------------------------------------
# Locating the patch site
# ---------------------------------------------------------------------------

function Get-PatchSite {
    param([byte[]]$Data, $PeInfo)

    $used = 'strict'
    $hits = @((Find-Signature -Data $Data -Pattern $SCRIPT:SigStrict).Hits)

    if ($hits.Count -eq 0) {
        $used = 'loose'
        $hits = @((Find-Signature -Data $Data -Pattern $SCRIPT:SigLoose).Hits)
    }

    if ($hits.Count -eq 0) {
        return [pscustomobject]@{
            Found   = $false
            Reason  = 'signature not found - this is probably not a supported XCom2.exe'
            Pattern = $used
            AllHits = @()
        }
    }

    if ($hits.Count -gt 1) {
        return [pscustomobject]@{
            Found   = $false
            Reason  = ('signature matched {0} times - refusing to guess' -f $hits.Count)
            Pattern = $used
            AllHits = $hits
        }
    }

    $off = $hits[0]
    $imm = [System.BitConverter]::ToUInt32($Data, $off + $SCRIPT:ImmOffset)
    $rva = Convert-OffsetToRva -PeInfo $PeInfo -Offset $off
    $va = $PeInfo.ImageBase + $rva

    $state = if ($imm -eq $SCRIPT:Vanilla) { 'vanilla' } else { 'patched' }

    [pscustomobject]@{
        Found   = $true
        Reason  = ''
        Pattern = $used
        Offset  = $off
        Rva     = $rva
        Va      = $va
        Bytes   = $Data[$off..($off + 6)]
        OldImm  = $imm
        State   = $state
        AllHits = @($off)
    }
}

function Show-Site {
    param($Site, $PeInfo, [string]$BuildLabel)

    Write-Head 'Patch site'

    if (-not $Site.Found) {
        Write-Item 'result' $Site.Reason 'Yellow'
        foreach ($h in $Site.AllHits) {
            Write-Item 'candidate' ('file offset 0x{0:x}' -f $h) 'DarkYellow'
        }
        return
    }

    Write-Item 'build' $BuildLabel
    Write-Item 'file offset' ('0x{0:x}' -f $Site.Offset)
    Write-Item 'RVA' ('0x{0:x}' -f $Site.Rva)
    Write-Item 'VA' ('0x{0:x}' -f $Site.Va)
    Write-Item 'bytes now' (Format-Bytes $Site.Bytes)
    Write-Item 'immediate' (Format-U32 $Site.OldImm)

    if ($Site.State -eq 'vanilla') {
        Write-Item 'state' 'ORIGINAL - limit is 65536 bytes' 'Yellow'
    }
    else {
        Write-Item 'state' ('PATCHED - limit is {0:N0} bytes' -f $Site.OldImm) 'Green'
    }
    Write-Item 'matched by' $Site.Pattern 'DarkGray'
}

# ---------------------------------------------------------------------------
# Locating the game
# ---------------------------------------------------------------------------

function Get-SteamLibraries {
    $libs = New-Object System.Collections.Generic.List[string]

    $roots = New-Object System.Collections.Generic.List[string]
    foreach ($key in @('HKCU:\Software\Valve\Steam', 'HKLM:\SOFTWARE\WOW6432Node\Valve\Steam', 'HKLM:\SOFTWARE\Valve\Steam')) {
        try {
            $props = Get-ItemProperty -Path $key -ErrorAction Stop
            foreach ($name in @('SteamPath', 'InstallPath')) {
                if ($props.PSObject.Properties.Name -contains $name) {
                    $value = $props.$name
                    if ($value) { $roots.Add(($value -replace '/', '\')) }
                }
            }
        }
        catch { }
    }

    $vdfRel = 'steamapps\libraryfolders.vdf'
    foreach ($root in $roots) {
        if (-not (Test-Path -LiteralPath $root)) { continue }
        if (-not $libs.Contains($root)) { $libs.Add($root) }

        $vdf = Join-Path $root $vdfRel
        if (Test-Path -LiteralPath $vdf) {
            foreach ($line in [System.IO.File]::ReadAllLines($vdf)) {
                $m = [regex]::Match($line, '"path"\s+"([^"]+)"')
                if ($m.Success) {
                    $p = $m.Groups[1].Value -replace '\\\\', '\'
                    if ((Test-Path -LiteralPath $p) -and (-not $libs.Contains($p))) { $libs.Add($p) }
                }
            }
        }
    }

    if ($libs.Count -eq 0) {
        # Last resort: check the usual locations on every fixed drive.
        foreach ($drive in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
            foreach ($sub in @('Steam', 'SteamLibrary', 'Games\Steam', 'Program Files (x86)\Steam')) {
                $p = Join-Path ($drive.Root + '') $sub
                if ((Test-Path -LiteralPath $p) -and (-not $libs.Contains($p))) { $libs.Add($p) }
            }
        }
    }

    return [pscustomobject]@{ Paths = $libs.ToArray() }
}

function Get-CandidateExes {
    $wanted = @(
        @{ Rel = 'steamapps\common\XCOM 2\XCom2-WarOfTheChosen\Binaries\Win64\XCom2.exe'; Build = 'War of the Chosen' },
        @{ Rel = 'steamapps\common\XCOM 2\Binaries\Win64\XCom2.exe'; Build = 'base game' }
    )

    $found = New-Object System.Collections.Generic.List[object]
    $seen = New-Object System.Collections.Generic.List[string]

    foreach ($lib in (Get-SteamLibraries).Paths) {
        foreach ($w in $wanted) {
            $p = Join-Path $lib $w.Rel
            if (Test-Path -LiteralPath $p) {
                $full = (Resolve-Path -LiteralPath $p).Path
                $key = $full.ToLowerInvariant()
                if (-not $seen.Contains($key)) {
                    $seen.Add($key)
                    $found.Add([pscustomobject]@{ Path = $full; Build = $w.Build })
                }
            }
        }
    }

    return [pscustomobject]@{ Items = $found.ToArray() }
}

function Get-BuildLabel {
    param([byte[]]$Data)

    # "War of the Chosen" as UTF-16LE. It appears only in the WOTC build, which
    # makes it a reliable in-file signal (paths and file names are not).
    # War of the Chosen ships a distinct executable; the "War of the Chosen"
    # UTF-16 marker appears only in that build, so it identifies the file by
    # content. Deriving it from the path would mislabel every renamed or
    # relocated copy (a backup, a Steam library move).
    $needle = [System.Text.Encoding]::Unicode.GetBytes('War of the Chosen')
    $latin1 = [System.Text.Encoding]::GetEncoding(28591)
    $haystack = $latin1.GetString($Data)
    $pattern = $latin1.GetString($needle)

    if ($haystack.IndexOf($pattern, [System.StringComparison]::Ordinal) -ge 0) { return 'War of the Chosen' }
    return 'base game'
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

function Get-TargetExe {
    param([string]$Given)

    if ($Given) {
        if (-not (Test-Path -LiteralPath $Given)) { throw "Executable not found: $Given" }
        $full = (Resolve-Path -LiteralPath $Given).Path
        return [pscustomobject]@{ Path = $full; Build = $null }
    }

    $candidates = @((Get-CandidateExes).Items)
    if ($candidates.Count -eq 0) {
        throw 'Could not find XCom2.exe automatically. Pass it explicitly, e.g. -Exe "D:\Steam\steamapps\common\XCOM 2\XCom2-WarOfTheChosen\Binaries\Win64\XCom2.exe"'
    }

    # Prefer War of the Chosen when both builds are installed.
    foreach ($c in $candidates) { if ($c.Build -eq 'War of the Chosen') { return $c } }
    return $candidates[0]
}

function Invoke-Status {
    param($Target)

    $data = [System.IO.File]::ReadAllBytes($Target.Path)
    $pe = Get-PeInfo -Data $data -Path $Target.Path
    $build = if ($Target.Build) { Get-BuildLabel -Data $data } else { Get-BuildLabel -Data $data }

    Write-Head 'XCOM 2 Savefix - status'
    Write-Item 'executable' $Target.Path
    Write-Item 'size' ('{0:N0} bytes' -f $data.Length)
    Write-Item 'sha256' (Get-Sha256 -Path $Target.Path)
    Write-Item 'build' $build

    $site = Get-PatchSite -Data $data -PeInfo $pe
    Show-Site -Site $site -PeInfo $pe -BuildLabel $build

    $backup = $Target.Path + $SCRIPT:BackupExt
    Write-Head 'Backup'
    if (Test-Path -LiteralPath $backup) {
        Write-Item 'backup' $backup 'Green'
    }
    else {
        Write-Item 'backup' 'none yet (Apply creates one automatically)' 'DarkGray'
    }

    if ($site.Found -and $site.State -eq 'vanilla') {
        Write-Host ''
        Write-Host '  This executable can be patched - run "SaveFix.bat Apply" to do it.' -ForegroundColor Yellow
        # A distinct code so a launcher can tell "nothing to do" from "there is
        # something to do". Not an error: nothing went wrong and nothing changed.
        exit 10
    }
    elseif ($site.Found) {
        Write-Host ''
        Write-Host '  Nothing to do - this executable is already patched.' -ForegroundColor Green
    }
    else {
        Write-Host ''
        Write-Host '  This executable was left untouched.' -ForegroundColor Yellow
    }
}

function Invoke-Apply {
    param($Target, [int]$NewMiB)

    $data = [System.IO.File]::ReadAllBytes($Target.Path)
    $pe = Get-PeInfo -Data $data -Path $Target.Path
    $build = Get-BuildLabel -Data $data

    Write-Head 'XCOM 2 Savefix - apply'
    Write-Item 'executable' $Target.Path
    Write-Item 'build' $build

    $site = Get-PatchSite -Data $data -PeInfo $pe
    Show-Site -Site $site -PeInfo $pe -BuildLabel $build

    if (-not $site.Found) {
        Write-Host ''
        Write-Host ('  ABORTED: ' + $site.Reason) -ForegroundColor Red
        exit 2
    }

    $newImm = [uint32]($NewMiB * 1MB)

    if ($site.OldImm -eq $newImm) {
        Write-Host ''
        Write-Host ('  Already patched to {0} MiB - nothing to do.' -f $NewMiB) -ForegroundColor Green
        exit 0
    }

    if ($site.State -ne 'vanilla') {
        Write-Host ''
        Write-Host ('  ABORTED: the immediate is neither the original 0x10000 nor the requested value,') -ForegroundColor Red
        Write-Host ('           it is 0x{0:X8}. Another tool has modified this file.' -f $site.OldImm) -ForegroundColor Red
        Write-Host '           Restore the backup first, or patch a clean copy.' -ForegroundColor Red
        exit 2
    }

    if (-not $Yes) {
        Write-Host ''
        Write-Host ('  About to change 81 7d 38 {0} -> 81 7d 38 {1}' -f (Format-Bytes $site.Bytes[3..6]), (Format-Bytes ([System.BitConverter]::GetBytes($newImm)[0..3]))) -ForegroundColor White
        $answer = Read-Host '  Proceed? [y/N]'
        if ($answer -notmatch '^(y|yes)$') {
            Write-Host '  Cancelled.' -ForegroundColor DarkGray
            exit 0
        }
    }

    # Back up first, then write, then read back and verify.
    $backup = $Target.Path + $SCRIPT:BackupExt
    if (-not (Test-Path -LiteralPath $backup)) {
        try {
            Copy-Item -LiteralPath $Target.Path -Destination $backup -Force
        }
        catch {
            Write-Host ''
            Write-Host '  FAILED: could not create the backup next to the executable.' -ForegroundColor Red
            Write-Host ('          ' + $_.Exception.Message) -ForegroundColor Red
            Write-Host '          The Steam folder is normally administrator-only. Run this as' -ForegroundColor Yellow
            Write-Host '          administrator (right-click SaveFix.bat -> "Run as administrator"),' -ForegroundColor Yellow
            Write-Host '          or use SaveFix.bat, which asks for it.' -ForegroundColor Yellow
            exit 4
        }
        Write-Item 'backup' ('created ' + $backup) 'Green'
    }
    else {
        Write-Item 'backup' ('kept existing ' + $backup) 'DarkGray'
    }

    $newImmBytes = [System.BitConverter]::GetBytes($newImm)
    $writeOff = $site.Offset + $SCRIPT:ImmOffset

    try {
        $stream = [System.IO.File]::Open($Target.Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        try {
            $stream.Position = $writeOff
            $stream.Write($newImmBytes, 0, 4)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
    }
    catch [System.UnauthorizedAccessException] {
        Write-Host ''
        Write-Host '  FAILED: access denied. The game folder is normally administrator-only' -ForegroundColor Red
        Write-Host '          because Steam installs under "C:\Program Files (x86)".' -ForegroundColor Red
        Write-Host ''
        Write-Host '          Run this as administrator (right-click SaveFix.bat and choose' -ForegroundColor Yellow
        Write-Host '          "Run as administrator"), or use SaveFix.bat, which asks for it.' -ForegroundColor Yellow
        Write-Host '          If XCOM 2 is running, close it first.' -ForegroundColor Yellow
        exit 4
    }
    catch [System.IO.IOException] {
        Write-Host ''
        Write-Host ('  FAILED: ' + $_.Exception.Message) -ForegroundColor Red
        Write-Host '          If XCOM 2 is running, close it first.' -ForegroundColor Red
        Write-Host '          If the message mentions access or permission, run this as' -ForegroundColor Yellow
        Write-Host '          administrator (the Steam folder is normally admin-only).' -ForegroundColor Yellow
        exit 3
    }

    $check = [System.IO.File]::ReadAllBytes($Target.Path)
    $nowImm = [System.BitConverter]::ToUInt32($check, $writeOff)

    Write-Head 'Result'
    Write-Item 'bytes now' (Format-Bytes $check[$site.Offset..($site.Offset + 6)])
    Write-Item 'immediate' (Format-U32 $nowImm)

    if ($nowImm -eq $newImm) {
        Write-Item 'verify' 'OK' 'Green'
        Write-Host ''
        Write-Host ('  Done. The save-header limit is now {0:N0} bytes ({1} MiB).' -f $newImm, $NewMiB) -ForegroundColor Green
        Write-Host '  Start the game and load the save that used to be red.' -ForegroundColor Green
        exit 0
    }

    Write-Item 'verify' 'MISMATCH' 'Red'
    Write-Host ''
    Write-Host '  The write did not stick. Restore from the backup and try again.' -ForegroundColor Red
    exit 3
}

function Invoke-Restore {
    param($Target)

    $backup = $Target.Path + $SCRIPT:BackupExt

    Write-Head 'XCOM 2 Savefix - restore'

    if (-not (Test-Path -LiteralPath $backup)) {
        Write-Item 'backup' ('not found: ' + $backup) 'Red'
        Write-Host ''
        Write-Host '  Nothing to restore from. Use the Steam client option' -ForegroundColor Yellow
        Write-Host '  "Verify integrity of game files" to get a clean executable back.' -ForegroundColor Yellow
        exit 2
    }

    $current = [System.IO.File]::ReadAllBytes($Target.Path)
    $original = [System.IO.File]::ReadAllBytes($backup)
    $pe = Get-PeInfo -Data $current -Path $Target.Path
    $site = Get-PatchSite -Data $current -PeInfo $pe

    Write-Item 'executable' $Target.Path
    Write-Item 'backup' $backup
    Write-Item 'backup size' ('{0:N0} bytes' -f $original.Length)

    if ($current.Length -ne $original.Length) {
        Write-Host ''
        Write-Host '  ABORTED: the backup and the installed executable differ in size.' -ForegroundColor Red
        Write-Host '           The backup does not belong to this file - not touching anything.' -ForegroundColor Red
        exit 2
    }

    $diff = 0
    for ($i = 0; $i -lt $current.Length; $i++) {
        if ($current[$i] -ne $original[$i]) { $diff++ }
    }

    if ($diff -eq 0) {
        Write-Item 'difference' 'none - already the original file' 'Green'
        exit 0
    }

    Write-Item 'difference' ('{0:N0} byte(s)' -f $diff) 'Yellow'

    try {
        Copy-Item -LiteralPath $backup -Destination $Target.Path -Force
    }
    catch {
        Write-Host ''
        Write-Host ('  FAILED: ' + $_.Exception.Message) -ForegroundColor Red
        Write-Host '          Close XCOM 2 if it is running. If the message mentions access' -ForegroundColor Yellow
        Write-Host '          or permission, run this as administrator.' -ForegroundColor Yellow
        exit 3
    }

    $after = [System.IO.File]::ReadAllBytes($Target.Path)
    $same = $true
    if ($after.Length -ne $original.Length) { $same = $false }
    else {
        for ($i = 0; $i -lt $after.Length; $i++) {
            if ($after[$i] -ne $original[$i]) { $same = $false; break }
        }
    }

    Write-Head 'Result'
    if ($same) {
        Write-Item 'verify' 'OK - byte-identical to the backup' 'Green'
        Write-Host ''
        Write-Host '  The original executable is back in place.' -ForegroundColor Green
        exit 0
    }

    Write-Item 'verify' 'MISMATCH' 'Red'
    exit 3
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

try {
    $target = Get-TargetExe -Given $Exe

    switch ($Action) {
        'Status' { Invoke-Status -Target $target }
        'Apply' { Invoke-Apply -Target $target -NewMiB $MiB }
        'Restore' { Invoke-Restore -Target $target }
    }
}
catch {
    Write-Host ''
    if (Test-AccessDenied $_.Exception) {
        Write-Host 'ERROR: access denied.' -ForegroundColor Red
        Write-Host ('       ' + $_.Exception.Message) -ForegroundColor DarkGray
        Write-AdminHint
        exit 4
    }
    Write-Host ('ERROR: ' + $_.Exception.Message) -ForegroundColor Red
    exit 1
}
