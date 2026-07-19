import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);
  return worker.fetch(new Request("http://localhost/", { headers: { accept: "text/html" } }), {
    ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) },
    DB: { prepare() { throw new Error("D1 must not be required for the read-only initial render"); } },
  }, { waitUntil() {}, passThroughOnException() {} });
}

test("server-renders the admissions data platform", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);
  const html = await response.text();
  assert.match(html, /<title>특성화고 입시 데이터랩<\/title>/);
  assert.match(html, /흩어진 대학 입결을/);
  assert.match(html, /상담 조건/);
  assert.match(html, /대학·학과별 최신 결과만/);
  assert.match(html, /학생 등급을 입력하면 대학·학과별 최신 결과를 적정·안정·도전 순으로 추천합니다/);
  assert.match(html, /추천군/);
  assert.match(html, /등급 데이터가 있는 결과만/);
  assert.match(html, /82개 대학 수집 현황/);
  assert.doesNotMatch(html, /codex-preview|react-loading-skeleton|Your site is taking shape/);
});

test("ships a populated and traceable result dataset", async () => {
  const data = JSON.parse(await readFile(new URL("../app/data/results.json", import.meta.url), "utf8"));
  assert.ok(data.summary.result_count >= 800);
  assert.ok(data.summary.institution_count >= 25);
  assert.ok(data.summary.grade_result_count >= 50);
  assert.equal(data.results.length, data.summary.result_count);
  const gradeRows = data.results.filter((row) => row.representative_grade !== null);
  assert.ok(gradeRows.every((row) => row.page_number > 0 && /\.(pdf|xlsx|html)$/i.test(row.local_path)));
  assert.ok(data.results.every((row) => /^https:\/\//.test(row.source_url)));
  assert.ok(gradeRows.every((row) => row.representative_grade >= 1 && row.representative_grade <= 9));
  assert.ok(gradeRows.some((row) => row.metrics.some((metric) => metric.code.includes("grade"))));
  const dongaRows = data.results.filter((row) => row.canonical_name === "동아대" && row.admission_year === 2026);
  assert.equal(dongaRows.length, 24);
  assert.equal(dongaRows.filter((row) => row.representative_grade !== null).length, 4);
  assert.ok(dongaRows.every((row) => row.source_url.includes("BOARD_IDX=30600")));
  const ulsanRows = data.results.filter((row) => row.canonical_name === "울산대" && row.admission_year === 2026);
  assert.equal(ulsanRows.length, 10);
  assert.equal(ulsanRows.filter((row) => row.representative_grade !== null).length, 9);
  assert.ok(ulsanRows.every((row) => row.source_url.includes("no=16268")));
});

test("ships the full 82-university collection ledger", async () => {
  const data = JSON.parse(await readFile(new URL("../app/data/target_coverage.json", import.meta.url), "utf8"));
  assert.equal(data.summary.target_universities, 82);
  assert.equal(data.summary.universities_with_source, 82);
  assert.equal(data.universities.length, 82);
  assert.equal(Object.values(data.summary.statuses).reduce((sum, value) => sum + value, 0), 82);
  assert.ok(data.universities.some((row) => row.university === "가천대" && row.status === "grade_available"));
  assert.ok(data.universities.some((row) => row.university === "동아대" && row.status === "grade_available"));
  assert.ok(data.universities.some((row) => row.university === "울산대" && row.status === "grade_available"));
});
