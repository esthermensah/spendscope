# ADR 0005: Store OAuth refresh tokens in the OS credential store

**Status:** Proposed

Use the `keyring` library to delegate token storage to Keychain on macOS and Credential Manager on Windows. SQLite holds no secret token material. Disconnecting an account deletes the credential-store entry and disables pending sync work until reconnection.
