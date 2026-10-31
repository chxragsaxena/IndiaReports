// Get a Gmail refresh token for IndiaReports, straight from YOUR Google OAuth client, so the two always match.
//
//   node infra/gmail-token.cjs
//
// It reads GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET (and GMAIL_SENDER, to preselect the account) from .env, opens Google's
// consent page in your browser, waits for the redirect on this computer, and writes GMAIL_REFRESH_TOKEN into .env.
// The token is never printed. The OAuth client must list http://localhost under "Authorized redirect URIs" in Google
// Cloud Console (this script listens on port 80 for it, so nothing else on this computer may be using port 80).
const fs = require("fs");
const http = require("http");
const path = require("path");
const crypto = require("crypto");
const { exec } = require("child_process");

const ENV = path.join(__dirname, "..", ".env");
const PORT = 80;
const REDIRECT = "http://localhost"; // exactly what is registered with Google: the address, no port, no path
const SCOPE = "https://mail.google.com/";

function readEnv() {
  const values = {};
  for (const line of fs.readFileSync(ENV, "utf8").split(/\r?\n/)) {
    const m = line.match(/^([A-Za-z_][A-Za-z0-9_]*)=(.*)$/);
    if (m) values[m[1]] = m[2].trim().replace(/^["']|["']$/g, "");
  }
  return values;
}

function writeToken(token) {
  let text = fs.readFileSync(ENV, "utf8");
  const eol = text.includes("\r\n") ? "\r\n" : "\n";
  const line = `GMAIL_REFRESH_TOKEN=${token}`;
  text = /^GMAIL_REFRESH_TOKEN=.*$/m.test(text)
    ? text.replace(/^GMAIL_REFRESH_TOKEN=.*$/m, line)
    : text.replace(/\s*$/, "") + eol + line + eol;
  fs.writeFileSync(ENV, text);
}

const env = readEnv();
if (!env.GMAIL_CLIENT_ID || !env.GMAIL_CLIENT_SECRET) {
  console.error("GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET must be set in .env first.");
  process.exit(1);
}

const state = crypto.randomBytes(16).toString("hex");
const params = new URLSearchParams({
  client_id: env.GMAIL_CLIENT_ID,
  redirect_uri: REDIRECT,
  response_type: "code",
  scope: SCOPE,
  access_type: "offline", // asks Google for a refresh token
  prompt: "consent", // and makes it issue a NEW one even if you approved this app before
  state,
});
if (env.GMAIL_SENDER) params.set("login_hint", env.GMAIL_SENDER);
const url = `https://accounts.google.com/o/oauth2/v2/auth?${params}`;

const server = http.createServer(async (req, res) => {
  const u = new URL(req.url, `http://localhost:${PORT}`);
  if (u.pathname !== "/" || !(u.searchParams.has("code") || u.searchParams.has("error"))) {
    res.writeHead(404).end();
    return;
  }
  const finish = (code, message, exitCode) => {
    res.writeHead(code, { "Content-Type": "text/html; charset=utf-8" });
    res.end(`<body style="font-family:system-ui;padding:2em"><h2>${message}</h2><p>You can close this tab.</p></body>`);
    console.log(message);
    server.close();
    setTimeout(() => process.exit(exitCode), 200);
  };
  if (u.searchParams.get("state") !== state) return finish(400, "Refused: the answer did not match this request.", 1);
  if (u.searchParams.get("error")) return finish(400, `Google said: ${u.searchParams.get("error")}`, 1);
  try {
    const r = await fetch("https://oauth2.googleapis.com/token", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams({
        code: u.searchParams.get("code"),
        client_id: env.GMAIL_CLIENT_ID,
        client_secret: env.GMAIL_CLIENT_SECRET,
        redirect_uri: REDIRECT,
        grant_type: "authorization_code",
      }),
    });
    const body = await r.json();
    if (!r.ok || !body.refresh_token) {
      const why = body.error ? `${body.error}: ${body.error_description || ""}` : "no refresh token came back";
      return finish(400, `Could not get a refresh token (${why}).`, 1);
    }
    writeToken(body.refresh_token);
    finish(200, `Done. A new refresh token (${body.refresh_token.length} characters) was saved to .env as GMAIL_REFRESH_TOKEN.`, 0);
  } catch (e) {
    finish(500, `Something went wrong: ${e.message}`, 1);
  }
});

server.on("error", (e) => {
  console.error(e.code === "EADDRINUSE" || e.code === "EACCES" ? `Port ${PORT} is not available (${e.code}). Close whatever uses it, or register another redirect address and change PORT and REDIRECT here.` : e.message);
  process.exit(1);
});

server.listen(PORT, "127.0.0.1", () => {
  console.log("Opening Google's consent page. If it does not open, paste this address into your browser:\n");
  console.log(url + "\n");
  exec(process.platform === "win32" ? `start "" "${url}"` : process.platform === "darwin" ? `open "${url}"` : `xdg-open "${url}"`);
  console.log(`Waiting up to 5 minutes for you to approve (redirect: ${REDIRECT}) ...`);
  setTimeout(() => {
    console.log("Timed out waiting for approval.");
    process.exit(1);
  }, 5 * 60 * 1000);
});
