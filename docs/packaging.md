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
workflow artifacts. It can be started manually. Pushing a version tag such as `v0.1.0` creates a
clearly labeled unsigned beta release when Apple credentials are absent. If all optional Apple
secrets below are configured, the same workflow signs and notarizes the Mac build before creating
the draft release.

## Optional Apple signing and notarization

The owner chose not to purchase an Apple Developer Program membership for this portfolio beta.
Unsigned Mac builds remain usable through Apple's documented **Privacy & Security → Open Anyway**
process. Do not describe an unsigned build as Apple-reviewed, signed, or notarized.

Future maintainers can enable signing by adding these encrypted GitHub Actions secrets:

- `APPLE_CERTIFICATE_BASE64`: the base64-encoded Developer ID Application `.p12` file.
- `APPLE_CERTIFICATE_PASSWORD`: the password chosen when exporting the `.p12` file.
- `APPLE_NOTARY_KEY_BASE64`: the base64-encoded App Store Connect API `.p8` key.
- `APPLE_NOTARY_KEY_ID`: the API key ID shown in App Store Connect.
- `APPLE_NOTARY_ISSUER_ID`: the issuer ID shown in App Store Connect.

The workflow imports the certificate into a temporary keychain, signs the application with the
hardened runtime and a secure timestamp, submits it through `notarytool`, staples Apple's ticket,
checks it with Gatekeeper, and removes the temporary keychain. Never commit any `.p12`, `.p8`,
password, or private key to the repository.

Installed builds include **Help → Check for Updates…**. This performs a read-only check against the
repository's latest public GitHub Release and opens that release page when a newer version exists.
It deliberately does not replace the running application: unattended installation must wait until
release artifacts can be authenticated and replaced safely. Developers running from source update
with `git pull` and reinstall the editable package only when dependencies change.

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
- Clearly label the macOS bundle as unsigned and unnotarized, with Apple's supported opening steps.
- Clearly label the Windows executable as unsigned and warn that SmartScreen may appear.
- Review bundled dependency licenses and ship required notices.
- Verify each published ZIP against its `.sha256` file.
- Confirm every release draft contains the unsigned-beta warning before publishing it.

The current owner-facing status is tracked in [`release_checklist.md`](release_checklist.md).

Signing credentials must be stored as protected repository or environment secrets. They must never
be committed to the repository or printed in workflow logs.
