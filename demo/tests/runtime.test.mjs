import {test} from 'node:test';
import assert from 'node:assert/strict';
import {demoApi, createDemoJob} from '../demo-runtime.js';

test('completed sample includes cited script and downloadable text', async () => {
  assert.equal((await demoApi('/v1/jobs/demo-listen/status')).status, 'succeeded');
  const {segments} = await demoApi('/v1/jobs/demo-listen/script');
  assert.equal(segments.length, 6);
  assert.ok(segments.every(s => s.citations[0].snippet));
  const {artifacts} = await demoApi('/v1/jobs/demo-listen/artifacts');
  assert.equal(artifacts.length, 7);
  const script = artifacts.find(a => a.name === 'script.json');
  const response = await demoApi(script.download_url, {raw: true});
  assert.equal((await response.json()).demo, true);
});

test('review persists edited text and resumes simulated audio', async () => {
  const {segments} = await demoApi('/v1/jobs/demo-review/script');
  segments[0].text = 'An edited sample narration.';
  await demoApi('/v1/jobs/demo-review/review', {method: 'POST', json: {action: 'approve', segments}});
  assert.equal((await demoApi('/v1/jobs/demo-review/status')).status, 'running');
  assert.equal((await demoApi('/v1/jobs/demo-review/script')).segments[0].text, segments[0].text);
  const transcript = await demoApi('/v1/jobs/demo-review/files/transcript.txt', {raw: true});
  assert.match(await transcript.text(), /An edited sample narration/);
  await assert.rejects(demoApi('/v1/jobs/demo-review/review', {method: 'POST', json: {action: 'reject'}}), e => e.status === 409);
});

test('unknown jobs and server-only operations fail locally', async () => {
  await assert.rejects(demoApi('/v1/jobs/missing/status'), e => e.status === 404);
  await assert.rejects(demoApi('/v1/feedback', {method: 'POST'}), e => e.status === 404);
  const abort = new AbortController(); abort.abort();
  await assert.rejects(demoApi('/v1/jobs/demo-listen/status', {signal: abort.signal}), e => e.name === 'AbortError');
});

test('PDF selection creates a simulated job without upload', async () => {
  const {job_id} = createDemoJob({file: 'my-paper.pdf', pause: true, language: 'it', secs: 480, style: 'academic'});
  assert.equal((await demoApi(`/v1/jobs/${job_id}/status`)).status, 'queued');
  assert.equal((await demoApi(`/v1/jobs/${job_id}/script`)).segments[0].speaker, 'Alex');
});

test('simulated stages reach review or completion and rejection is terminal', async t => {
  let now = 2000000000000;
  t.mock.method(Date, 'now', () => now);
  const reviewed = createDemoJob({pause: true}).job_id;
  const direct = createDemoJob({pause: false}).job_id;
  now += 2000;
  assert.equal((await demoApi(`/v1/jobs/${reviewed}/status`)).status, 'running');
  now += 3000;
  assert.equal((await demoApi(`/v1/jobs/${reviewed}/status`)).status, 'awaiting_review');
  assert.equal((await demoApi(`/v1/jobs/${direct}/status`)).status, 'succeeded');
  await demoApi(`/v1/jobs/${reviewed}/review`, {method: 'POST', json: {action: 'reject', notes: 'Needs revision'}});
  const result = await demoApi(`/v1/jobs/${reviewed}/status`);
  assert.equal(result.status, 'failed');
  assert.equal(result.stage, 'rejected');
  assert.equal(result.detail, 'Needs revision');
});
