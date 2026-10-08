# BridgeClip Custom

This personal fork uses upstream's title-overlay option, with **Burn in headline** off by default in **Create > Automatic > Captions**. Captions remain independent. The review screen shows the headline setting. Starting another video preserves the choice during the session; reopening the app starts with headlines off. Assistant-created jobs also default to no headline unless requested.

Review & edit exports already omit title overlays. Titles remain available as Library metadata. Existing rendered files are unchanged and need to be regenerated to remove burned-in text.

## Offline Review Recovery

Editor previews disable the inherited camera timecode (`tmcd`) track. With microsecond frame timestamps, that single track's duration can exceed FFmpeg's signed 32-bit packet-duration limit on videos longer than approximately 35m47s, aborting MP4 finalization after encoding has finished. Video/audio and precise source-frame timestamps are retained; the original source is unchanged.

Review projects now checkpoint the candidate edits, framing and Jev results before encoding the editor preview. A failed local preview no longer loses these completed reviews.

Do not restart the entire creation workflow just to retry a failed preview: that repeats paid transcription/planning/review calls. With the app closed, a stopped review run that still contains `editor-source.mp4` and `transcript.json` can instead be recovered locally:

```sh
LOCAL_MODE=true PYTHONPATH=engine PATH="$PWD/engine-bin:$PATH" \
  engine-venv/bin/python3 -m clip_engine.recover_review "$HOME/BridgeClip/RUN_ID"
```

This command makes no provider requests, reuses the source, and publishes the Library result only after a valid preview exists. It preserves the original failure record and audit, and refuses to replace a completed result. Existing project checkpoints retain their settings and reviews.

For older failures without a project checkpoint, it reconstructs suggestions from the saved planner response. Lost Jev judgments and automatic framing cannot be recovered; these candidates are explicitly unreviewed, with editable full-frame framing, 9:16 output, captions off and normal speed. Use `--aspect-ratio 16:9` or `--captions` to change those recovery defaults. Existing rendered videos are not changed. In the app, open the recovered project from Library; manual edits and baking are local, while pressing **Review again** requests a new Jev evaluation.

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
engine-venv/bin/python3 -m pytest -q engine/tests/test_review_recovery.py
```

The engine test command needs pytest installed separately from the runtime lock. End-to-end tests use isolated settings and mock job submission, without sending a video to a provider.
