# GitHub Pages demo

The demo extracts the existing Web Studio from `services/api/static/`. The live API UI is unchanged. It has no build dependencies beyond Python 3 and uses plain ES modules in the browser.

```bash
python3 scripts/build_demo.py
python3 -m http.server 8001 --directory dist/pages
```

Open http://localhost:8001. The generated site is in `dist/pages/` (ignored by Git). All asset URLs are relative and navigation uses hash routes, so the same site works at `/xCAST/`, `/thinking_in_code/`, or a custom domain. No hard-coded Pages base path is needed.

## What visitors can try

- Overview walkthrough, Studio options, theme, responsive layout and command palette.
- **Listen to sample**: finished fictional episode with prerecorded speech, decoded waveform, seeking, speed controls and synced SRT captions.
- **Try script review**: editable speakers, titles, narration and page citation snippets; approve or reject the sample. Clicking it again resets this sample review.
- Select a PDF to start a simulated job, optionally pausing for review. PDF validation stays in the browser; the document is never uploaded or processed. Tone, duration and language record UI settings but do not change the sample.
- Download scripts and text transcripts with review edits. Audio and captions remain the original sample. Demo reports explicitly contain no measured production metrics.
- Feedback downloads as JSON; nothing is submitted to a server.

Demo jobs and edits use an isolated `xcast.demo.jobs.v1` localStorage key; up to 15 custom jobs are retained. Recent IDs use the existing UI storage. Clear browser site data to reset. The fictional sleep-and-memory paper and narration are authored demonstration content, not scientific evidence. The bundled 66-second speech was generated locally with macOS system voices and requires no voice service at runtime. Google Fonts is the only optional external runtime resource; system fonts are the fallback.

## Publish later — manual action only

Nothing is published by building locally, pushing this branch, or opening a PR. There is no push-triggered deployment. The workflow defaults to build-only.

1. Commit and push the changes when ready, then merge into your default branch.
2. In the repository, open **Settings → Pages → Build and deployment → Source**, and select **GitHub Actions**.
3. Open **Actions → Static demo — build or publish manually → Run workflow** on the default branch.
4. Check **Publish the demo to GitHub Pages** only when you want to publish, then run it.

The URL follows the repository name. This repository is `KOKUTBON/xCAST`, so its project site will be `https://kokutbon.github.io/xCAST/`. To serve the root URL `https://kokutbon.github.io/`, the publishing repository must be named `kokutbon.github.io`. Upload only `dist/pages/` if deploying the built site through another method.

The source repository can stay private. For a repository owned by the personal account `reiidoda`, private-repository Pages requires GitHub Pro; GitHub Team applies to organization-owned repositories. The published Pages site is public even when its source repository is private. See [GitHub's plans](https://docs.github.com/en/get-started/learning-about-github/githubs-plans) and [Pages site types](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages).

The workflow follows [GitHub's custom Pages workflow documentation](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

## Verify

```bash
node --test demo/tests/runtime.test.mjs
python3 scripts/build_demo.py
node --check dist/pages/app.js
node --check dist/pages/demo-runtime.js
```

The extraction script fails if important live UI anchors change, rather than silently emitting a partially adapted demo. The source app must not be edited in `dist/pages/`; put demo behavior in `demo/demo-runtime.js` and extraction changes in `scripts/build_demo.py`, then rebuild.
