# Releases

Signed builds of SavahBot's companion apps. **Write-once:** every version lives in its own folder and is never edited,
replaced or deleted. A new build is a new version folder.

```
releases/
  savahlive/
    1.5.0/
      SavahLive-1.5.0.apk    the signed release APK
      SHA256SUMS             its SHA-256 checksum
      RELEASE.md             version, date, size, checksum, signing certificate, what changed
```

**Install:** download `SavahLive-<version>.apk` on the phone, open it, and allow "Install unknown apps" for your browser or file
manager when Android asks. To update, install the newer APK over the old one (same signing key, so pairing is kept).

**Check it is genuine:** the SHA-256 of the file must match `SHA256SUMS`.
Windows: `Get-FileHash SavahLive-1.5.0.apk -Algorithm SHA256`. Mac/Linux: `sha256sum -c SHA256SUMS`.

How a release is made and protected: `docs/RELEASING.md`.
