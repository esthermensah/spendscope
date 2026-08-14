# SpendScope release checklist

This is the plain-English list to check before making SpendScope public.

## Already done

- [x] Private GitHub repository recreated with clean history.
- [x] Personal receipt details and personal commit email removed from GitHub.
- [x] Apache 2.0 open-source license added.
- [x] Mac and Windows beta packages build successfully.
- [x] Automated tests pass on macOS, Windows, and Linux with Python 3.11 and 3.12.
- [x] Google OAuth client configuration is stored as an encrypted GitHub secret.
- [x] Public-download installation flow was tested, then the repository was returned to private.
- [x] Apple signing and notarization steps are prepared in the package workflow.

## Google login

- [x] In Google Cloud Console, open **Google Auth Platform → Audience**.
- [x] Confirm **User type** is **External**.
- [x] Confirm **Publishing status** is **In production**.
- [ ] Open **Data Access** and check whether Google marks any requested scope as sensitive.
- [ ] If Google requires verification, provide its requested homepage, privacy policy, scope explanation,
      and demonstration video, then submit the app for verification.
- [ ] Test Google sign-in using a Google account that is not listed as a test user.

## Apple notarization — blocked until owner setup

- [ ] Enroll in the Apple Developer Program.
- [ ] Install full Xcode from the Mac App Store and open it once to finish setup.
- [ ] Create and install a **Developer ID Application** certificate.
- [ ] Export that certificate and private key from Keychain Access as a password-protected `.p12` file.
- [ ] Create an App Store Connect API key that can submit software for notarization.
- [ ] Add the five Apple values listed in `docs/packaging.md` as encrypted GitHub Actions secrets.
- [ ] Push a new version tag and confirm that signing, notarization, stapling, and Gatekeeper checks pass.
- [ ] Download the resulting Mac ZIP on a different Mac and open it normally.

## Other public-release work

- [ ] Decide how ordinary users receive Tesseract. It is currently a separate installation.
- [ ] Sign the Windows package to avoid Windows SmartScreen warnings.
- [ ] Publish a simple app homepage and privacy policy for users and Google verification.
- [ ] Delete the private old-history backup from this Mac when it is no longer needed.
- [ ] Review this checklist together, then explicitly change the GitHub repository to public.
