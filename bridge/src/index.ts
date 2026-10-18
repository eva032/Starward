import { createServer } from "node:http";
import { Spectrum } from "spectrum-ts";
import { imessage } from "@spectrum-ts/imessage";

const FLASK_WEBHOOK = process.env.FLASK_WEBHOOK_URL ?? "http://localhost:5000/webhook/photon";
const TOKEN = process.env.BRIDGE_TOKEN ?? "";
const PORT = Number(process.env.PORT ?? 8787);

const app = await Spectrum({
  projectId: process.env.PROJECT_ID!,
  projectSecret: process.env.PROJECT_SECRET!,
  providers: [imessage.config()],
});

// Outbound: Flask calls POST /send {to, text}
async function sendTo(to: string, text: string) {
  const im = imessage(app);
  const user = await im.user(to);      // UNVERIFIED: check docs for how to resolve a phone number
  const dm = await im.space.create(user);
  await dm.send(text);
}

createServer(async (req, res) => {
  if (req.method !== "POST" || req.url !== "/send") { res.writeHead(404).end(); return; }
  if (TOKEN && req.headers.authorization !== `Bearer ${TOKEN}`) { res.writeHead(401).end(); return; }
  let body = "";
  for await (const chunk of req) body += chunk;
  try {
    const { to, text } = JSON.parse(body);
    await sendTo(to, text);
    res.writeHead(200, { "content-type": "application/json" }).end(JSON.stringify({ ok: true }));
  } catch (e) {
    console.error("send failed:", e);
    res.writeHead(500, { "content-type": "application/json" }).end(JSON.stringify({ ok: false, error: String(e) }));
  }
}).listen(PORT, () => console.log(`bridge listening on ${PORT}`));

// Inbound: forward every text to Flask
for await (const [space, message] of app.messages) {
  if (message.content.type !== "text") continue;
  const payload = { from: message.sender.address, text: message.content.text, platform: message.platform };
  console.log("inbound:", payload);
  try {
    await fetch(FLASK_WEBHOOK, {
      method: "POST",
      headers: { "content-type": "application/json", authorization: `Bearer ${TOKEN}` },
      body: JSON.stringify(payload),
    });
  } catch (e) {
    console.error("flask webhook failed:", e);
  }
}