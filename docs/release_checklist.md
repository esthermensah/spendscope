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
- [x] Apple signing and notarization remain available as an optional future workflow.

## Google login

- [x] In Google Cloud Console, open **Google Auth Platform → Audience**.
- [x] Confirm **User type** is **External**.
- [x] Confirm **Publishing status** is **In production**.
- [ ] Open **Data Access** and check whether Google marks any requested scope as sensitive.
- [ ] If Google requires verification, provide its requested homepage, privacy policy, scope explanation,
      and demonstration video, then submit the app for verification.
- [ ] Test Google sign-in using a Google account that is not listed as a test user.

## Distribution decision

- [x] Distribute SpendScope as an unsigned portfolio beta instead of paying for Apple notarization.
- [x] Clearly label Mac and Windows downloads as unsigned.
- [x] Document Apple's supported **Privacy & Security → Open Anyway** process for Mac users.
- [x] Allow version tags to create unsigned beta releases when Apple credentials are absent.
- [x] Keep optional Apple signing and notarization automation available for a future maintainer.

## Other public-release work

- [ ] Decide how ordinary users receive Tesseract. It is currently a separate installation.
- [ ] Optionally sign the Windows package to avoid Windows SmartScreen warnings.
- [ ] Publish a simple app homepage and privacy policy for users and Google verification.
- [ ] Delete the private old-history backup from this Mac when it is no longer needed.
- [ ] Review this checklist together, then explicitly change the GitHub repository to public.
