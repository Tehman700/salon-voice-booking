# Connecting the voice agent

The backend side is built and tested with simulated Retell requests. These steps connect a real Retell account to it.

## What you need

- A Retell AI account and its **API key** (Settings → API Keys).
- The API address, for example `https://43-205-17-140.sslip.io`.
- A phone number for the agent (optional for first tests: the Retell dashboard can place a web call).

## 1. Give the server the key

Retell signs every request with the API key; the backend refuses anything it can't verify. Until the key is set, `/retell/*` and `/webhooks/retell` answer `503 voice_not_configured`.

On the demo server (no secrets in the repo):

```bash
bash infra/ec2/remote.sh "echo 'RETELL_API_KEY=<paste key>' >> /opt/salon/.env"
GIT_REF=main bash infra/ec2/update.sh
```

(The command is recorded in AWS Systems Manager's command history, which is acceptable for a demo; for a real launch store the key in Secrets Manager instead.)

Locally, put `RETELL_API_KEY=...` in `backend/.env`.

## 2. Tell the backend which salon the agent answers for

The backend finds the salon for each call in this order:

1. **`?location_id=` in the tool and webhook URLs** (recommended: one agent per location). This always works, including for Retell's browser test calls, which have no phone number. [tools.json](tools.json) already puts `?location_id=LOCATION_ID` on every URL: replace `LOCATION_ID` with the location's id (`GET /locations` lists them).
2. A `location_id` dynamic variable on the call.
3. The dialled number matched to a location's **phone** field (international format, e.g. `+92211234567`). Two locations with the same number are ambiguous and the call is refused, so keep them unique. This suits one agent answering several numbers.

Add `?location_id=...` to the webhook URL too, so call logs are filed under the right salon.

## 3. Create the agent in Retell

1. Create a **Single Prompt** agent. Paste [agent-prompt.md](agent-prompt.md) (everything below the first rule line) as the general prompt.
2. Add the built-in **End Call** function.
3. Add each function in [tools.json](tools.json) as a **Custom Function**: name, description, URL (replace `BASE_URL`), and the parameters schema. Set **Payload: args only** to **off**. Keep the timeout short (10 seconds is plenty).
4. Set the agent's **webhook URL** to `BASE_URL/webhooks/retell?location_id=LOCATION_ID` and enable `call_started`, `call_ended` and `call_analyzed`.
5. Pick a voice and language. Turn on a short "backchannel"/interruption sensitivity you like; nothing in the backend depends on it.

## 4. Test

- In Retell, use **Test → Web call**. Say "I'd like a haircut tomorrow afternoon."
- In the dashboard, the booking appears on the calendar with source **voice**, and the call appears on the **Calls** page with its transcript and outcome.
- Try the unhappy paths: a time that is already taken, a cancel inside the notice period, a wrong name. The agent must say it could not do it.

## 5. Connect a real phone number (Twilio SIP trunk)

The demo line is a Twilio US number connected to Retell over SIP. Credentials stay in Twilio and Retell, never in this repo.

1. **Twilio:** buy a number, create an **Elastic SIP Trunk**, set its origination URI to `sip:sip.retellai.com`, give termination a credential list (`<SIP_USERNAME>` / `<SIP_PASSWORD>`), and attach the number to the trunk.
2. **Retell:** Phone Numbers → **Connect via SIP trunking** (custom telephony), enter the number in E.164 (`+1XXXXXXXXXX`) and the termination details, then pick the agent as the number's **inbound agent**.
3. **Backend:** set the location's **phone** to the same number (dashboard → Settings → the location → Phone, or `PATCH /locations/{id}` with `{"phone": "+1XXXXXXXXXX"}`). With `?location_id=` in the agent's URLs this is only the fallback route, but it is also the number the agent and the emails give customers as "the salon's number".

The only server setting the voice agent needs is `RETELL_API_KEY` (the workspace key Retell signs with). The public address is not a setting: it is written into the agent's tool and webhook URLs.

## 6. Check a real call

While you dial the number, watch the server log:

```bash
bash infra/ec2/remote.sh "docker logs salon-api-1 --since 10m 2>&1 | grep -E 'retell|webhooks|Refused|routed'"
```

A good call shows, in order: `POST /webhooks/retell?location_id=... 200` (call started), `POST /retell/functions/get_salon_info?... 200`, then the tools used (`check_availability`, `create_booking`, ...), and two more webhook lines after you hang up (call ended, call analysed). `Refused ...` means a signature problem; `could not be routed` means the location could not be worked out.

Afterwards:

- **Dashboard → Voice calls:** the call with your number as the caller, its duration, outcome and transcript (the summary arrives a few seconds after hang-up).
- **Dashboard → Bookings / Calendar:** the booking with source **Voice**.
- **Email:** the salon's booking-alerts address gets "New booking ... by phone (voice agent)".
- **Database:** `call_logs` (one row per call, `retell_call_id`), `appointments` (`source = 'voice'`, `call_id` set), `notification_outbox` (the alert, `status = 'sent'`).

## 7. Call from the browser (Twilio Voice SDK)

The **Call the receptionist** button on the dashboard's Voice calls page places a call from the browser through Twilio to the salon line, so a demo needs no phone and no international call.

In the Twilio console (credentials never go in the repo):

1. **API key:** Account → API keys & tokens → **Create API key** (Standard). Copy its **SID** (`SK...`) and **secret** (shown once).
2. **TwiML App:** Voice → TwiML → TwiML Apps → **Create**. Voice request URL `https://<API host>/twilio/voice`, method `POST`. Copy its **SID** (`AP...`).

On the server, add to `/opt/salon/.env` (then `GIT_REF=main bash infra/ec2/update.sh`):

```
TWILIO_ACCOUNT_SID=AC...
TWILIO_API_KEY_SID=SK...
TWILIO_API_KEY_SECRET=<secret>
TWILIO_TWIML_APP_SID=AP...
TWILIO_AUTH_TOKEN=<auth token>   # verifies Twilio's webhook signature
TWILIO_DIAL_TO=+1XXXXXXXXXX      # the salon line
```

A **trial** Twilio account may refuse to dial out to a number that is not verified. If the button connects and then fails, set `TWILIO_DIAL_TO=sip:+1XXXXXXXXXX@sip.retellai.com` and `TWILIO_CALLER_ID=+1XXXXXXXXXX` to go straight to Retell over SIP, or upgrade the account.



- Every tool answers `{ "success": true|false, "message": "...", ... }`. `success: true` means the database changed.
- A repeated tool call in the same call (Retell retries) returns the same booking, never a second one.
- The agent acts as a manager of **one location** and can never override the cancellation notice period.
- Rescheduling and cancelling need the booking reference, the caller's name and the booking's phone number to all match.

## If something does not work

| Symptom | Likely cause |
|---|---|
| Tool results say `unknown_salon` | The tool URL has no `?location_id=`, and the dialled number doesn't match any location's phone (or two locations share it). The server log says what the call carried. |
| `401 invalid_signature` | The key on the server isn't the one Retell signs with. Use the workspace's own (webhook-badged) API key, not a newly created one. The server log says why it refused. |
| `503 voice_not_configured` | `RETELL_API_KEY` isn't set on the server. |
| Agent never finds the caller's bookings | "Payload: args only" is still on, so caller ID isn't sent. |
| Agent says it booked but nothing exists | It ignored the rules in the prompt: check the prompt was pasted whole and the tool results show `success: false`. |
