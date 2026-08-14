# Packaging and release

SpendScope uses PyInstaller to produce a native macOS application bundle and a Windows application
directory. PyInstaller must run on the target operating system; the Windows package is built on
Windows and the macOS package on macOS.

## Local development build

Install the packaging dependency group and build from the repository root:

```shell
python -m pip install -e ".[packaging]"
python -m PyInstaller --noconfirm --clean packaging/spendscope.spec
```

On macOS, the result is `dist/SpendScope.app`. Validate it without creating persistent user data:

```shell
QT_QPA_PLATFORM=offscreen ./dist/SpendScope.app/Contents/MacOS/SpendScope --smoke-test
```

On Windows, the result is `dist\SpendScope\SpendScope.exe`:

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\dist\SpendScope\SpendScope.exe --smoke-test
```

The smoke test creates a temporary workspace, runs all database migrations, builds and displays the
main window offscreen, and then removes the temporary data.

## Automated artifacts

The `Package desktop applications` GitHub Actions workflow builds both operating-system packages,
runs the packaged smoke test, creates ZIP archives and SHA-256 checksum files, and uploads them as
workflow artifacts. It can be started manually. Pushing a version tag such as `v0.1.0` additionally
creates a draft GitHub release; it does not publish unsigned applications automatically.

Installed builds include **Help → Check for Updates…**. This performs a read-only check against the
repository's latest public GitHub Release and opens that release page when a newer version exists.
It deliberately does not replace the running application: unattended installation must wait until
release artifacts are consistently signed and notarized. Developers running from source update with
`git pull` and reinstall the editable package only when dependencies change.

## OCR dependency

Receipt OCR is local and uses Tesseract. The development packages currently expect Tesseract to be
installed on the computer or selected through application configuration. The application never
downloads Tesseract or sends receipts to a remote OCR service. Before a public nontechnical-user
release, choose one distribution policy:

1. bundle Tesseract, its language data, notices, and native libraries in each platform package; or
2. ship a signed companion installer and guided in-app diagnostic.

The first option gives the best user experience but requires platform-specific binary and license
maintenance. The release workflow intentionally does not claim that OCR is self-contained until this
owner decision is made.

## Signing and public-release checklist

- Select and add the project license before distributing binaries.
- Set a release version consistently in `pyproject.toml`, `spendscope/branding.py`, and the spec file.
- Test receipt import, OCR, review, storage, and optional Google authorization on clean machines.
- Sign the macOS bundle with an Apple Developer ID certificate and submit it for notarization.
- Sign the Windows executable or installer with the project’s code-signing certificate.
- Review bundled dependency licenses and ship required notices.
- Verify each published ZIP against its `.sha256` file.
- Publish the draft GitHub release only after signed artifacts replace the unsigned development ones.

Signing credentials must be stored as protected repository or environment secrets. They must never
be committed to the repository or printed in workflow logs.
