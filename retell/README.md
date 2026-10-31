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

## 2. Tell the backend which salon the phone number belongs to

Each location's **phone** field (Locations in the dashboard, or `PATCH /locations/{id}`) must be the number the caller dials, in international format (for example `+92211234567`). The backend matches the number Retell reports as dialled to the location, whatever spacing it uses. Two locations with the same number are ambiguous and the call is refused, so keep them unique.

For a single test agent with no phone number, pin the location instead: add a dynamic variable `location_id` (the location's id) to the agent.

## 3. Create the agent in Retell

1. Create a **Single Prompt** agent. Paste [agent-prompt.md](agent-prompt.md) (everything below the first rule line) as the general prompt.
2. Add the built-in **End Call** function.
3. Add each function in [tools.json](tools.json) as a **Custom Function**: name, description, URL (replace `BASE_URL`), and the parameters schema. Set **Payload: args only** to **off**. Keep the timeout short (10 seconds is plenty).
4. Set the agent's **webhook URL** to `BASE_URL/webhooks/retell` and enable `call_started`, `call_ended` and `call_analyzed`.
5. Pick a voice and language. Turn on a short "backchannel"/interruption sensitivity you like; nothing in the backend depends on it.

## 4. Test

- In Retell, use **Test → Web call**. Say "I'd like a haircut tomorrow afternoon."
- In the dashboard, the booking appears on the calendar with source **voice**, and the call appears on the **Calls** page with its transcript and outcome.
- Try the unhappy paths: a time that is already taken, a cancel inside the notice period, a wrong name. The agent must say it could not do it.

## What the tools guarantee

- Every tool answers `{ "success": true|false, "message": "...", ... }`. `success: true` means the database changed.
- A repeated tool call in the same call (Retell retries) returns the same booking, never a second one.
- The agent acts as a manager of **one location** and can never override the cancellation notice period.
- Rescheduling and cancelling need the booking reference, the caller's name and the booking's phone number to all match.

## If something does not work

| Symptom | Likely cause |
|---|---|
| Tool results say `unknown_salon` | The dialled number doesn't match any location's phone, or two locations share it. |
| `401 invalid_signature` in the server log | The key on the server isn't the key of the Retell account (or the clock is more than 5 minutes off). |
| `503 voice_not_configured` | `RETELL_API_KEY` isn't set on the server. |
| Agent never finds the caller's bookings | "Payload: args only" is still on, so caller ID isn't sent. |
| Agent says it booked but nothing exists | It ignored the rules in the prompt: check the prompt was pasted whole and the tool results show `success: false`. |
