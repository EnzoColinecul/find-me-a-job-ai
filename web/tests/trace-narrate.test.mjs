import assert from "node:assert/strict";
import test from "node:test";
import { currentAction, narrate } from "../src/lib/trace-narrate.ts";

const search = {
  search_id: "synthetic-trace-check",
  status: "running",
  params: { lat: 0, lng: 0, radius_km: 5, roles: ["chef"] },
  results: [], total: 0, progress: { done: 0, total: 1 }, steps: [],
};
const step = (tag, meta) => ({
  tool: "report", tag, meta, text: "Acme", at: "2026-10-13T07:00:00Z",
});

test("a missing report differs from tool-budget exhaustion in live and completed traces", () => {
  for (const status of ["running", "completed"]) {
    const view = { ...search, status };
    const missing = narrate(step("checking", "model stopped without a final report"), view);
    const exhausted = narrate(step("checking", "tool-call budget reached"), view);
    assert.match(missing, /ended before a final report/);
    assert.doesNotMatch(missing, /limit|budget|nothing useful/);
    assert.match(exhausted, /reached its tool limit/);
    assert.doesNotMatch(exhausted, /nothing useful/);
    assert.match(missing, status === "running" ? /preparing/ : /prepared/);
  }
});

test("a report being prepared cannot claim a completed empty result", () => {
  const message = narrate(step("checking", "unknown reason"), search);
  assert.match(message, /Preparing the result/);
  assert.doesNotMatch(message, /Done|nothing useful|worth contacting/);
});

test("partial leads and failed checks retain the coverage warning", () => {
  for (const status of ["running", "degraded", "failed"]) {
    const view = { ...search, status };
    assert.match(narrate(step("found", "verified partial lead; check incomplete"), view),
      /check is incomplete, but a verified lead/);
    const failed = narrate(step("skipping", "check incomplete; no verified lead"), view);
    assert.match(failed, /could not finish/);
    assert.doesNotMatch(failed, /nothing useful/);
  }
});

test("ordinary final findings and genuine empty results keep their completion wording", () => {
  assert.match(narrate(step("found", "careers page"), search), /Done with Acme — worth contacting/);
  assert.match(narrate(step("skipping", "none"), search), /Done with Acme — nothing useful/);
});

test("the current-action summary uses the same truthful report wording", () => {
  const latest = step("checking", "model stopped without a final report");
  assert.equal(currentAction({ ...search, steps: [latest] }), narrate(latest, search));
});

test("web-source failures do not invent budget exhaustion", () => {
  for (const status of ["running", "completed"]) {
    const view = { ...search, status };
    const failed = { ...step("skipping", "SerpAPI unavailable"), tool: "web_search" };
    assert.match(narrate(failed, view), /couldn't complete a web search/);
    assert.doesNotMatch(narrate(failed, view), /limit|budget/);
    failed.meta = "budget reached: 10 web_search calls for this search";
    assert.match(narrate(failed, view), /web search limit was reached/);
  }
});

test("failed page and contact checks do not describe successful reads", () => {
  for (const tool of ["fetch_page", "extract_jobs", "seek.company", "extract_contact"]) {
    const failed = { ...step("skipping", "source refused the request"), tool };
    assert.match(narrate(failed, search), /couldn't/);
    assert.doesNotMatch(narrate(failed, search), /has a website|has openings|publishes/);
  }
});

test("provider errors do not imply that recovered partial leads were discarded", () => {
  for (const tool of ["triage", "analysis"]) {
    const failed = { ...step("skipping", "error: TimeoutError"), tool };
    const message = narrate(failed, search);
    assert.match(message, /incomplete/);
    assert.doesNotMatch(message, /leaving it out|left it out/);
  }
});

test("a discovered careers page does not claim live vacancies", () => {
  for (const status of ["running", "completed"]) {
    const careers = { ...step("found", "careers page"), tool: "extract_jobs" };
    const message = narrate(careers, { ...search, status });
    assert.match(message, /Found a careers page/);
    assert.doesNotMatch(message, /has openings|has vacancies|live listing/);
  }
});
