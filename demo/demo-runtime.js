// Browser-only demo transport. No PDF contents, API keys or feedback are sent anywhere.
const KEY = 'xcast.demo.jobs.v1';
export const sampleSegments = [
  {speaker: 'Alex', title: 'Welcome', text: 'Welcome to xCAST. This short sample shows how a research paper becomes a conversation with citations. We are using an illustrative paper about sleep and memory.'},
  {speaker: 'Sam', title: 'The question', text: 'The question is simple: can sleeping after learning help us remember? In this fictional example, participants learn a list of words, then either sleep or stay awake.'},
  {speaker: 'Alex', title: 'The result', text: 'The sleep group recalls more words the next morning. The important distinction is that this example illustrates the interface. These numbers are not findings from a real research study.'},
  {speaker: 'Sam', title: 'Review the evidence', text: 'Every citation opens the supporting passage and its page. Before approving a real episode, check that the script accurately reflects the original paper, including its limitations.'},
  {speaker: 'Alex', title: 'Keep the limitations', text: 'A small sample and a short follow up would limit the conclusions. A useful podcast explains those caveats instead of presenting a single result as a universal rule.'},
  {speaker: 'Sam', title: 'Take it with you', text: 'You can now listen, seek through the waveform, read the synchronized captions, and download the sample artifacts. To process your own papers, run the full xCAST project locally.'},
].map((s, i) => ({...s, citations: [{page: i < 2 ? 2 : i < 4 ? 3 : 4, source: 'sleep-and-memory.pdf (fictional demo)', snippet: ['Illustrative question: sleep after learning and next-day recall.', 'Illustrative method: compare a sleep group with an awake group.', 'Illustrative result: higher recall in the sleep group. No real study is represented.', 'Claims should be checked against their supporting source passage.', 'Illustrative limitations: small sample and short follow-up.', 'This fictional document is included only to demonstrate the workflow.'][i]}]}));
const clone = v => JSON.parse(JSON.stringify(v));
let jobs = {};
try { jobs = JSON.parse(localStorage.getItem(KEY) || '{}'); } catch {}
const save = () => { try { localStorage.setItem(KEY, JSON.stringify(jobs)); } catch {} };
function makeJob(id, pause, completed = false) {
  return {id, pause, started: Date.now(), completed, segments: clone(sampleSegments), language: 'en', style: 'everyday', secs: 90, file: 'sleep-and-memory.pdf'};
}
if (!jobs['demo-listen']) jobs['demo-listen'] = makeJob('demo-listen', false, true);
if (!jobs['demo-review']) jobs['demo-review'] = {...makeJob('demo-review', true), started: Date.now() - 6000};
export function createDemoJob(options) {
  const id = `demo-${globalThis.crypto?.randomUUID?.() || Date.now().toString(36)}`;
  jobs[id] = {...makeJob(id, options.pause), ...options};
  const ids = Object.keys(jobs).filter(k => !['demo-listen', 'demo-review'].includes(k));
  ids.slice(0, Math.max(0, ids.length - 15)).forEach(k => delete jobs[k]);
  save();
  return {job_id: id, status: 'queued'};
}
function status(job) {
  const elapsed = Date.now() - (job.approved || job.started);
  let state, stage, detail;
  if (job.rejected) [state, stage, detail] = ['failed', 'rejected', job.notes || 'Sample script rejected.'];
  else if (job.completed || elapsed >= (job.approved ? 3000 : 4500) && (!job.pause || job.approved)) [state, stage, detail] = ['succeeded', 'done', 'Sample artifacts ready. Audio is the original prerecorded demo.'];
  else if (job.approved) [state, stage, detail] = ['running', 'tts', 'Simulating voicing and mixing — using prerecorded sample audio.'];
  else if (elapsed < 1500) [state, stage, detail] = ['queued', 'queued', 'Starting a simulated job in this browser.'];
  else if (elapsed < 4500) [state, stage, detail] = ['running', 'script', 'Loading the fictional sample script — your PDF is not processed.'];
  else [state, stage, detail] = ['awaiting_review', 'awaiting_review', 'Edit and approve the fictional sample.'];
  return {job_id: job.id, status: state, stage, detail, updated_at: new Date(job.approved || job.started).toISOString()};
}
function error(code, message) { const e = new Error(message); e.status = code; throw e; }
const title = 'Sleep & memory — illustrative sample';
function files(job) {
  const segments = job.segments;
  const transcript = segments.map(s => `${s.speaker}: ${s.text}`).join('\n\n');
  return {
    'script.json': ['script_json', JSON.stringify({demo: true, title, segments}, null, 2)],
    'script.md': ['script_markdown', `# ${title}\n\nFictional demo. Audio uses the original sample; edits apply to text exports only.\n\n` + segments.map(s => `## ${s.title}\n\n**${s.speaker}:** ${s.text}\n\n` + s.citations.map(c => `Source: p.${c.page} — ${c.snippet}`).join('\n')).join('\n\n')],
    'transcript.txt': ['transcript_txt', transcript],
    'job_metrics.json': ['job_metrics', JSON.stringify({demo: true, note: 'Simulated stages; no backend timing measurements.'}, null, 2)],
    'audio_quality.json': ['audio_quality', JSON.stringify({demo: true, note: 'Prerecorded speech sample; no production QA performed.'}, null, 2)],
  };
}
export async function demoApi(path, {method = 'GET', json, raw = false, signal} = {}) {
  signal?.throwIfAborted();
  if (path === '/v1/metrics/summary') {
    const counts = {};
    Object.values(jobs).forEach(j => { const s = status(j).status; counts[s] = (counts[s] || 0) + 1; });
    return {job_counts: counts, queue_depth: counts.queued || 0, queue_mode: 'browser demo', audio_metrics: {}, stage_metrics: {}};
  }
  const match = path.match(/^\/v1\/jobs\/([^/]+)\/(status|script|result|review|artifacts|files\/([^/]+))$/);
  if (!match) error(404, 'This operation is unavailable in the static demo.');
  const job = jobs[decodeURIComponent(match[1])];
  if (!job) error(404, 'Demo job not found on this device. Open a sample or start another demo.');
  const action = match[2];
  if (action === 'status') return status(job);
  if (action === 'script') return {title, segments: clone(job.segments)};
  if (action === 'result') return {title};
  if (action === 'review') {
    if (method !== 'POST' || status(job).status !== 'awaiting_review') error(409, 'This sample is not awaiting review.');
    if (json.action === 'approve') { job.segments = clone(json.segments); job.approved = Date.now(); }
    else if (json.action === 'reject') { job.rejected = true; job.notes = json.notes; }
    else error(422, 'Unknown review action.');
    save(); return status(job);
  }
  const audio = {name: 'episode.wav', kind: 'audio_mp3', download_url: `./assets/episode.wav`};
  const captions = {name: 'transcript.srt', kind: 'transcript_srt', download_url: './assets/transcript.srt'};
  const texts = files(job);
  if (action === 'artifacts') return {artifacts: [audio, captions, ...Object.entries(texts).map(([name, [kind, text]]) => ({name, kind, size_bytes: new Blob([text]).size, download_url: `/v1/jobs/${job.id}/files/${name}`}))]};
  if (raw && match[3] && texts[match[3]]) return new Response(texts[match[3]][1]);
  error(404, 'Sample artifact not found.');
}
export function initDemo() {
  document.querySelector('[data-demo-sample]').addEventListener('click', () => { location.hash = '#/job/demo-listen'; });
  document.querySelector('[data-demo-review]').addEventListener('click', () => {
    jobs['demo-review'] = {...makeJob('demo-review', true), started: Date.now() - 6000}; save();
    if (location.hash === '#/job/demo-review') location.reload(); else location.hash = '#/job/demo-review';
  });
}
