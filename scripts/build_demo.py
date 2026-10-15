"""Extract the live UI into a dependency-free GitHub Pages demo."""

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dist" / "pages"
SOURCE_URL = "https://github.com/KOKUTBON/xCAST"


def replace_once(text, old, new):
    if old not in text:
        raise ValueError(f"UI extraction anchor missing: {old[:80]}")
    return text.replace(old, new, 1)


def build():
    OUT.mkdir(parents=True, exist_ok=True)
    shutil.copytree(ROOT / "assets" / "branding", OUT / "assets" / "branding", dirs_exist_ok=True)
    shutil.copytree(ROOT / "demo" / "assets", OUT / "assets", dirs_exist_ok=True)
    shutil.copy(ROOT / "demo" / "demo-runtime.js", OUT / "demo-runtime.js")
    shutil.copy(ROOT / "services/api/static/styles.css", OUT / "styles.css")
    html = (ROOT / "services/api/static/index.html").read_text()
    html = html.replace('="/assets/', '="./assets/').replace('="/static/', '="./')
    html = html.replace('href="/docs"', f'href="{SOURCE_URL}#cli--python-sdk-tic"')
    html = html.replace('href="/redoc"', f'href="{SOURCE_URL}#architecture--how-it-works"')
    html = html.replace("https://github.com/KOKUTBON/xCAST", SOURCE_URL)
    html = html.replace("<title>xCAST — Studio</title>", "<title>xCAST — Interactive demo</title>")
    html = html.replace(
        "Files go only to this server.",
        "Your PDF stays in your browser. This demo uses a fictional sample.",
    )
    html = html.replace(
        'name="pause_at_script" data-pause', 'name="pause_at_script" data-pause checked'
    )
    banner = """<div class="wrap demo-banner" role="note">
      <b>Interactive demo</b><span>Explore a fictional sample. No server, PDF processing, or AI generation. Edits affect text exports; audio and captions use the original sample.</span>
      <a class="btn btn-soft" href="#/job/demo-listen" data-demo-sample>Listen to sample</a>
      <button class="btn btn-soft" type="button" data-demo-review>Try script review</button>
    </div>"""
    html = replace_once(
        html, '<main id="main" tabindex="-1">', '<main id="main" tabindex="-1">' + banner
    )
    start = html.index("  <!-- Connection dialog -->")
    end = html.index("  <!-- Reject dialog -->")
    html = (
        html[:start]
        + """<dialog class="dialog" data-conn-dialog aria-labelledby="conn-title">
      <form method="dialog" class="dialog-body"><h2 id="conn-title">Browser demo</h2>
      <p>This static site uses fictional sample data and prerecorded audio. Selected PDFs are inspected locally and never uploaded. Tone, language and duration are recorded as settings; they do not change the sample.</p>
      <p>Demo jobs and script edits are saved in this browser. To process your own papers, run the full project locally.</p>
      <button class="btn btn-primary" type="submit">Close</button></form></dialog>\n"""
        + html[end:]
    )
    start = html.index('          <section id="data">')
    end = html.index('          <section id="keys">')
    html = (
        html[:start]
        + """<section id="data"><h2>Demo data &amp; privacy</h2>
      <p>All jobs are simulated in your browser using a fictional sleep-and-memory paper. A selected PDF is validated locally but its contents are not used to write a script. Settings demonstrate the real UI; sample narration is always English.</p>
      <p>Edits persist on this device and appear in downloaded scripts and text transcripts. Audio and SRT captions remain the original prerecorded sample. Reports are labeled as demo data.</p>
      <p>Clear site data in your browser to reset saved jobs. Feedback is downloaded as JSON for you to share; it is never sent to a server.</p></section>
      <section id="trouble"><h2>Using the demo</h2><p>Choose Listen to sample for a finished episode, or Try script review for an editable draft. Selecting your own PDF starts a simulated job. For real generation, follow the local setup instructions above.</p></section>
"""
        + html[end:]
    )
    html = html.replace(
        "The studio talks to the API on this origin. Jobs only move once a worker is running.",
        "This page is a static demo. To process real PDFs, clone the source repository and run the API and worker locally.",
    )
    html = html.replace(
        "Saved as JSON in <code>data/feedback/</code> on this server — it goes to whoever runs it.",
        "Download your feedback as JSON, then share it with the project maintainers yourself.",
    )
    html = html.replace("Send feedback</button>", "Download feedback</button>")
    (OUT / "index.html").write_text(html)
    app = (ROOT / "services/api/static/app.js").read_text()
    app = 'import { demoApi, createDemoJob, initDemo } from "./demo-runtime.js";\n' + app
    start = app.index("async function api(")
    end = app.index("async function downloadArtifact", start)
    app = (
        app[:start]
        + """async function api(path, options = {}) {
  if (path.startsWith("./assets/")) {
    const res = await fetch(path, { signal: options.signal });
    if (!res.ok) throw new ApiError(res.status, "Sample asset unavailable.");
    return options.raw ? res : res.json();
  }
  return demoApi(path, options);
}

"""
        + app[end:]
    )
    start = app.index("function setConn(")
    end = app.index(
        "/* =========================================================================\n   Theme",
        start,
    )
    app = (
        app[:start]
        + """function initConnection() {
  state.conn = "ok";
  $("[data-conn-dot]").dataset.state = "ok";
  $("[data-conn-label]").textContent = "Demo · browser only";
  $$("[data-conn-open]").forEach(btn => btn.addEventListener("click", () => {
    $("[data-menu]").close(); $("[data-conn-dialog]").showModal();
  }));
}

"""
        + app[end:]
    )
    start = app.index("    const fd = new FormData();", app.index("  const doSubmit"))
    end = app.index("\n  };", start)
    app = (
        app[:start]
        + """    const data = createDemoJob({file: file.name, language, style, secs, pause});
    recent.upsert(data.job_id, {
      file: file.name, size: file.size, pages: fileInfo.pages, language, style, secs, pause,
      status: "queued", created: new Date().toISOString(),
    });
    toast("Demo started. Your PDF stays here; the script uses the fictional sample.");
    setFile(null);
    location.hash = `#/job/${data.job_id}`;"""
        + app[end:]
    )
    start = app.index("    // EventSource can't send headers")
    end = app.index("    schedulePoll(0);", start)
    app = app[:start] + app[end:]
    start = app.index('      await api("/v1/feedback",')
    end = app.index("      form.reset();", start)
    app = (
        app[:start]
        + """      const blob = new Blob([JSON.stringify(Object.fromEntries(fd), null, 2)], {type: "application/json"});
      const url = URL.createObjectURL(blob);
      const link = h("a", {href: url, download: "xcast-feedback.json"});
      document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
"""
        + app[end:]
    )
    app = app.replace(
        "Thanks — feedback received.",
        "Feedback downloaded. Share the JSON file yourself; nothing was sent.",
    )
    app = app.replace('"/assets/branding/app-icon.png"', '"./assets/branding/app-icon.png"')
    app = app.replace('window.open("/docs",', f'window.open("{SOURCE_URL}#cli--python-sdk-tic",')
    app = app.replace('hint: "/docs"', 'hint: "Source"').replace(
        "Connection & API key", "About this demo"
    )
    app = app.replace('"Jobs on this server"', '"Demo jobs on this device"')
    app = app.replace(
        "No job with this ID exists on this server. It may have been purged.",
        "No demo job with this ID is saved on this device. Open a sample or start another demo.",
    )
    app = app.replace(
        '"Waiting for a worker", "If this stays queued, make sure a worker is running (make worker)."',
        '"Starting the demo", "Progress is simulated in this browser. Your PDF is not processed."',
    )
    app = app.replace(
        "Script approved. Audio synthesis queued.",
        "Sample approved. Loading the original prerecorded audio.",
    )
    app = app.replace('"episode.mp3 · Space', '"episode.wav · Prerecorded sample · Space')
    app = app.replace(
        'new Blob([arrayBuffer], { type: "audio/mpeg" })',
        'new Blob([arrayBuffer], { type: "audio/wav" })',
    )
    app = app.replace("initShell();", "initDemo();\ninitShell();")
    app = app.replace(
        "Caption timings are estimated from word counts and may drift from the audio.",
        "Captions follow the original prerecorded sample; script edits appear in text exports only.",
    )
    app = app.replace('"Waiting for a worker"', '"Simulated queue"')
    (OUT / "app.js").write_text(app)
    with (OUT / "styles.css").open("a") as css:
        css.write(
            "\n.demo-banner { display:flex; flex-wrap:wrap; align-items:center; gap:12px; padding:20px; margin-top:16px; border:1px solid var(--line); border-radius:16px; background:var(--violet-soft); }\n.demo-banner > span { flex:1 1 320px; font-size:14px; }\n"
        )
    (OUT / ".nojekyll").touch()
    print(f"Static demo ready: {OUT}")


if __name__ == "__main__":
    build()
