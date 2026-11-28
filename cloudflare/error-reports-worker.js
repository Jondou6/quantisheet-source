// QuantiSheet error-report receiver (Cloudflare Worker).
// Accepts POST /v1/report from the team copy of QuantiSheet (only when a
// tester turned on Help > Send Error Reports Automatically) and stores
// each report as one JSON object in the private R2 bucket bound as
// REPORTS. It never returns a stored report: reading is done in the
// Cloudflare dashboard (or with an R2 key), by the account owner only.
//
// Bindings: REPORTS = R2 bucket "quantisheet-error-reports" (private).
// Route:    reports.quantisheet.com/*

const MAX_BYTES = 64 * 1024;

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname !== "/v1/report") {
      return new Response("not found", { status: 404 });
    }
    if (request.method !== "POST") {
      return new Response("POST only", { status: 405 });
    }
    if (request.headers.get("X-QuantiSheet-Report") !== "1" ||
        !(request.headers.get("Content-Type") || "")
          .startsWith("application/json")) {
      return new Response("bad request", { status: 400 });
    }
    const raw = await request.arrayBuffer();
    if (raw.byteLength === 0 || raw.byteLength > MAX_BYTES) {
      return new Response("too large", { status: 413 });
    }
    let body;
    try {
      body = JSON.parse(new TextDecoder().decode(raw));
    } catch (e) {
      return new Response("bad json", { status: 400 });
    }
    if (!body || body.app !== "quantisheet" ||
        typeof body.report !== "string" ||
        typeof body.version !== "string" || body.version.length > 20) {
      return new Response("bad report", { status: 400 });
    }
    const now = new Date();
    const day = now.toISOString().slice(0, 10);
    const id = crypto.randomUUID();
    // only what the program sent, and when: no IP address, no headers
    const stored = JSON.stringify({
      received: now.toISOString(),
      version: body.version,
      report: body.report,
    });
    await env.REPORTS.put(`reports/${day}/${now.getTime()}-${id}.json`,
      stored, { httpMetadata: { contentType: "application/json" } });
    return new Response(null, { status: 204 });
  },
};
