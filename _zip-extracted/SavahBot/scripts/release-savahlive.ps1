<#
.SYNOPSIS
  Builds the signed SavahLive release APK and files it under releases\savahlive\<version>\ . It never overwrites a release.

.DESCRIPTION
  Run from anywhere:   .\scripts\release-savahlive.ps1
  Needs: android\keystore.properties (see android\README.md), the Android SDK (ANDROID_HOME), and the Gradle wrapper in android\.
  Steps: read versionName -> refuse if that release already exists -> gradlew clean assembleRelease -> check the signature with apksigner
         -> copy the APK to releases\savahlive\<version>\SavahLive-<version>.apk -> write SHA256SUMS and RELEASE.md -> make them read-only.
  Then it prints the git commands. To release again, raise the version first:  python scripts\bump_version.py 1.5.1
#>
$ErrorActionPreference = 'Stop'

$repo    = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$android = Join-Path $repo 'android'
$gradle  = Get-Content (Join-Path $android 'app\build.gradle.kts') -Raw

if ($gradle -notmatch 'versionName\s*=\s*"(\d+\.\d+\.\d+)"') { throw 'Could not read versionName from android\app\build.gradle.kts' }
$version = $Matches[1]
$dest = Join-Path $repo "releases\savahlive\$version"

if (Test-Path $dest) {
    throw "releases\savahlive\$version already exists. Releases are never overwritten. Raise the version first: python scripts\bump_version.py <new version>"
}
if (-not (Test-Path (Join-Path $android 'keystore.properties'))) {
    throw 'android\keystore.properties is missing, so the APK would be unsigned. Create it as described in android\README.md (section 6).'
}
if (-not (Test-Path (Join-Path $android 'gradlew.bat'))) {
    throw 'android\gradlew.bat is missing. Generate the wrapper once: cd android; gradle wrapper --gradle-version 8.7'
}
$sdk = $env:ANDROID_HOME
if (-not $sdk) { $sdk = $env:ANDROID_SDK_ROOT }
$apksigner = if ($sdk) { Join-Path $sdk 'build-tools\34.0.0\apksigner.bat' } else { '' }
if (-not $apksigner -or -not (Test-Path $apksigner)) { throw 'apksigner.bat not found. Check ANDROID_HOME and that build-tools;34.0.0 is installed.' }

$dirty = git -C $repo status --porcelain -- android backend frontend docs CHANGELOG.md
if ($dirty) {
    Write-Warning "You have uncommitted changes. A release should be built from committed code:`n$dirty"
    $answer = Read-Host 'Continue anyway? (y/N)'
    if ($answer -notmatch '^[yY]') { throw 'Stopped. Commit your changes first.' }
}

Write-Host "Building SavahLive $version (release)..." -ForegroundColor Cyan
Push-Location $android
try {
    & .\gradlew.bat clean assembleRelease
    if ($LASTEXITCODE -ne 0) { throw 'The Gradle build failed. Read the first "What went wrong" message above.' }
} finally {
    Pop-Location
}

$built = Join-Path $android 'app\build\outputs\apk\release\app-release.apk'
if (-not (Test-Path $built)) { throw 'app-release.apk was not produced. If you see app-release-unsigned.apk the signing settings were not applied: check keystore.properties.' }

Write-Host 'Checking the signature...' -ForegroundColor Cyan
$previous = $ErrorActionPreference
$ErrorActionPreference = 'Continue'      # Windows PowerShell 5.1 treats any text on stderr as an error when it is redirected
$verify = (& $apksigner verify --verbose --print-certs $built 2>&1 | Out-String)
$signerExit = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($signerExit -ne 0) { throw "apksigner says this APK is not validly signed:`n$verify" }
$cert = ''
if ($verify -match 'Signer #1 certificate SHA-256 digest:\s*([0-9a-fA-F]+)') { $cert = $Matches[1].ToLower() }
if ($verify -match 'CN=Android Debug') { throw 'This APK is signed with the Android DEBUG key. Use your own release key (keystore.properties).' }

New-Item -ItemType Directory -Path $dest | Out-Null
$apkName = "SavahLive-$version.apk"
$apk = Join-Path $dest $apkName
Copy-Item $built $apk
$hash = (Get-FileHash $apk -Algorithm SHA256).Hash.ToLower()
$size = [math]::Round((Get-Item $apk).Length / 1MB, 2)

$utf8 = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText((Join-Path $dest 'SHA256SUMS'), "$hash *$apkName`n", $utf8)

$notes = ''
$changelog = Get-Content (Join-Path $repo 'CHANGELOG.md') -Raw
$pattern = '(?ms)^## ' + [regex]::Escape($version) + '\s*\r?\n(.*?)(?=^## |\z)'
if ($changelog -match $pattern) { $notes = $Matches[1].Trim() } else { $notes = '(No CHANGELOG.md section was found for this version.)' }
$commit = (git -C $repo rev-parse --short HEAD)
$date = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm') + ' UTC'
$release = @"
# SavahLive $version

| | |
|---|---|
| File | $apkName |
| Size | $size MB |
| SHA-256 | $hash |
| Signing certificate (SHA-256) | $cert |
| Built | $date from commit $commit |
| Needs | Android 8.0 or newer |

**Install:** download the APK on the phone, open it and allow "Install unknown apps" if Android asks. Installing over an older SavahLive keeps your pairing (same signing key).

**Verify:** ``Get-FileHash $apkName -Algorithm SHA256`` must print the SHA-256 above (also in ``SHA256SUMS``).

## What changed

$notes
"@
[System.IO.File]::WriteAllText((Join-Path $dest 'RELEASE.md'), ($release -replace "`r`n", "`n"), $utf8)

foreach ($f in Get-ChildItem $dest -File) { $f.IsReadOnly = $true }    # a gentle guard against accidents; the real protection is in Git (docs\RELEASING.md)

Write-Host ''
Write-Host "Done: releases\savahlive\$version\$apkName  ($size MB)" -ForegroundColor Green
Write-Host "SHA-256: $hash"
Write-Host ''
Write-Host 'Next, to publish it:' -ForegroundColor Cyan
Write-Host "  git add releases/savahlive/$version"
Write-Host "  git commit -m `"SavahLive $version release APK`""
Write-Host "  git tag savahlive-v$version"
Write-Host '  git push --follow-tags'
