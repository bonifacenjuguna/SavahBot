// A late 401 must never sign out a newer sign-in, and signing out must close the session on the server.
import test from "node:test";
import assert from "node:assert/strict";

const store = new Map<string, string>();
const g = globalThis as any;
g.localStorage = { getItem: (k: string) => store.get(k) ?? null, setItem: (k: string, v: string) => void store.set(k, v), removeItem: (k: string) => void store.delete(k) };
g.location = { pathname: "/desk", search: "", hash: "" };

const { api, endSession, getToken, loggedOut, setToken } = await import("../src/api.ts");

type Call = { url: string; init: any };
function stubFetch(answer: (call: Call) => Promise<Response> | Response): Call[] {
  const calls: Call[] = [];
  g.fetch = async (url: string, init: any) => { const c = { url, init: init ?? {} }; calls.push(c); return answer(c); };
  return calls;
}
const json = (status: number, body: unknown) => new Response(JSON.stringify(body), { status });
function countOut(): { n: () => number; stop: () => void } {
  let n = 0;
  const f = () => { n += 1; };
  loggedOut.addEventListener("out", f);
  return { n: () => n, stop: () => loggedOut.removeEventListener("out", f) };
}

test("a 401 for the current token ends the session once", async () => {
  setToken("sbs_current");
  const out = countOut();
  stubFetch(() => json(401, { error: "Sign in to continue." }));
  await assert.rejects(api("GET", "/api/status"));
  assert.equal(getToken(), "");
  assert.equal(out.n(), 1);
  out.stop();
});

test("a late 401 for an OLD token does not sign out the newer sign-in", async () => {
  setToken("sbs_old");
  const out = countOut();
  let release!: () => void;
  const gate = new Promise<void>((r) => { release = r; });
  stubFetch(async () => { await gate; return json(401, { error: "Sign in to continue." }); });
  const pending = api("GET", "/api/status");          // sent with sbs_old ...
  setToken("sbs_new");                                // ... the user signs in again while it is in flight
  release();
  await assert.rejects(pending);
  assert.equal(getToken(), "sbs_new");
  assert.equal(out.n(), 0);
  out.stop();
});

test("a 401 for a request that carried no token is not a lost session", async () => {
  setToken("");
  const out = countOut();
  stubFetch(() => json(401, { error: "Sign in to continue." }));
  await assert.rejects(api("GET", "/api/status"));
  assert.equal(out.n(), 0);
  out.stop();
});

test("a wrong password on sign-in is not a lost session", async () => {
  setToken("sbs_current");
  const out = countOut();
  stubFetch(() => json(401, { error: "That password is not right." }));
  await assert.rejects(api("POST", "/api/auth/login", { password: "x" }));
  assert.equal(getToken(), "sbs_current");
  assert.equal(out.n(), 0);
  out.stop();
  setToken("");
});

test("endSession forgets the token and tells the server to close that session", async () => {
  setToken("sbs_mine");
  const calls = stubFetch(() => json(200, { ok: true }));
  endSession();
  assert.equal(getToken(), "");
  assert.equal(calls.length, 1);
  assert.match(calls[0].url, /\/api\/auth\/logout$/);
  assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers.Authorization, "Bearer sbs_mine");
});

test("endSession with nothing to end, or with the server unreachable, does not throw", async () => {
  setToken("");
  const calls = stubFetch(() => json(200, {}));
  endSession();
  assert.equal(calls.length, 0);
  setToken("sbs_x");
  stubFetch(() => { throw new TypeError("network down"); });
  assert.doesNotThrow(() => endSession());
  await new Promise((r) => setTimeout(r, 5));
});
