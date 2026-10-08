# BridgeClip Custom

This personal fork uses upstream's title-overlay option, with **Burn in headline** off by default in **Create > Automatic > Captions**. Captions remain independent. The review screen shows the headline setting. Starting another video preserves the choice during the session; reopening the app starts with headlines off. Assistant-created jobs also default to no headline unless requested.

Review & edit exports already omit title overlays. Titles remain available as Library metadata. Existing rendered files are unchanged and need to be regenerated to remove burned-in text.

## Build on macOS

Install dependencies with `npm ci`, then stage the Python runtime and media tools as described in [Development](development.md). When the installed official app's `engine/requirements.lock` matches this checkout, its bundled runtime can be reused:

```sh
diff /Applications/BridgeClip.app/Contents/Resources/engine/requirements.lock engine/requirements.lock
cp -R /Applications/BridgeClip.app/Contents/Resources/engine-venv ./engine-venv
cp -R /Applications/BridgeClip.app/Contents/Resources/engine-bin ./engine-bin
npm run dist:custom:mac
```

Run this only with matching runtime dependencies and CPU architecture, and when the destination runtime folders do not already exist. Alternatively, use the upstream resource preparation script.

The output is `dist/mac-arm64/BridgeClip Custom.app` on Apple silicon, or `dist/mac/BridgeClip Custom.app` on Intel. It has a separate bundle ID and settings directory from the official app. Enter your OpenRouter key in the custom app on first launch. The default output folder remains `~/BridgeClip`, so existing Library content is available.

This local build is ad-hoc signed, not signed or notarized by BridgeMind. Its custom entitlements allow Electron to load the locally signed frameworks. The existing macOS updater detects the unofficial signature and disables automatic updates; the custom packaging configuration also disables publishing. The official app is not replaced. MIT and bundled third-party notices are retained.

If macOS reports signing errors about resource forks or Finder metadata in a synced build folder, build outside that folder:

```sh
npm run dist:custom:mac -- --config.directories.output=/private/tmp/bridgeclip-custom-build
```

## Checks

```sh
npm run typecheck
npm run lint
npm test
node --test tests/main/headline.e2e.cjs
engine-venv/bin/python3 -m pytest -q engine/tests/test_audit_render.py
```

The engine test command needs pytest installed separately from the runtime lock. End-to-end tests use isolated settings and mock job submission, without sending a video to a provider.
