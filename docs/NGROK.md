# Share Northstar through ngrok

Install ngrok with `winget install ngrok --source msstore`, then run `ngrok config add-authtoken YOUR_TOKEN` locally. Get the token from https://dashboard.ngrok.com/get-started/your-authtoken. Do not put it in source control.

Run `start.bat`: it starts the local stack and then automatically runs ngrok to share the frontend and its `/api/` proxy through one HTTPS endpoint. The launcher updates CRM OAuth callback/origin settings and account email links, recreates the API when settings change, refreshes the web proxy, and checks the public health endpoint. It prints all app links and CRM redirect URLs and saves them in `reports/startup/links.txt`. Missing ngrok authentication does not prevent local startup. Open the **public** app URL when connecting a CRM and register the exact displayed redirect URL in the provider's OAuth app. `start-ngrok.bat` remains available for starting just the tunnel after the app is already running.

Options:

Set `NGROK_DOMAIN=your-domain.ngrok-free.dev` in the selected environment file to remember your domain across launches. Command-line `-NgrokDomain` / `-Domain` takes precedence. An `ep_...` endpoint ID is not an ngrok authtoken; the agent still needs account authentication.

- `start-ngrok.bat -Domain your-domain.ngrok-free.dev`: use an assigned ngrok domain.
- `start-ngrok.bat -NoBrowser -NoPause`: unattended launch.
- `start-ngrok.bat -Stop`: stop this app's tunnel and restore the original local URLs.
- `-EnvFile path`: use a different existing environment file (defaults to `.env.launch`).

The ngrok agent runs in the background. This PC, Docker, and the agent must stay running for the public site to remain accessible. Logs and the session's original URL settings are saved in ignored `reports/ngrok/`. HTTP request inspection is disabled so credentials are not stored in the local ngrok traffic inspector.

ngrok exposes the app; it does not change the app's billing permissions. The current Starter workspace still needs CRM entitlement and real provider credentials/consent. Direct object-store uploads currently use the separately configured S3 public endpoint; publishing CRM routes does not expose MinIO or its admin console.
- `start.bat -NoNgrok`: start locally without launching ngrok.
- `start.bat -NgrokDomain your-domain.ngrok-free.dev`: start the app and use an assigned ngrok domain.
