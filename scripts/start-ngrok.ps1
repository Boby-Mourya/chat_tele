[CmdletBinding()]
param(
    [string]$EnvFile = '.env.launch',
    [string]$Domain = $env:NGROK_DOMAIN,
    [switch]$Stop,
    [switch]$NoBrowser,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $workspaceRoot
$runtimeDirectory = Join-Path $workspaceRoot 'reports/ngrok'
New-Item -ItemType Directory -Force -Path $runtimeDirectory | Out-Null
$stateFile = Join-Path $runtimeDirectory 'state.json'
$processStarted = $null
$adoptedProcessId = $null
$launchLock = $null
$exitCode = 1

function Set-EnvironmentValues {
    param([string]$Path, [System.Collections.IDictionary]$Values)
    $lines = @([IO.File]::ReadAllLines($Path))
    foreach ($key in $Values.Keys) {
        $pattern = '^' + [regex]::Escape($key) + '='
        $lines = @($lines | Where-Object { $_ -notmatch $pattern })
        if ($null -ne $Values[$key]) { $lines += "$key=$($Values[$key])" }
    }
    [IO.File]::WriteAllLines($Path, $lines, (New-Object Text.UTF8Encoding($false)))
}

function Invoke-Compose {
    param([string[]]$Command)
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & docker @script:composeArgs @Command 2>&1 | ForEach-Object { Write-Host $_.ToString() }
        $result = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($result -ne 0) { throw 'Docker could not apply the public URL settings.' }
}

function Refresh-PublicConfiguration {
    param([switch]$RestartWeb)
    Invoke-Compose -Command @('up', '-d', '--no-build', '--wait', '--wait-timeout', '120', 'api')
    if ($RestartWeb) { Invoke-Compose -Command @('restart', 'web') }
}

try {
    $launchLock = [IO.File]::Open((Join-Path $runtimeDirectory 'launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    $EnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    if (-not $Domain) {
        $domainLine = [IO.File]::ReadAllLines($EnvFile) | Where-Object { $_ -match '^NGROK_DOMAIN=' } | Select-Object -Last 1
        if ($domainLine) { $Domain = ($domainLine -split '=', 2)[1].Trim().Trim('"', "'") }
    }
    $script:composeArgs = @('compose', '--env-file', $EnvFile, '-f', 'compose.yaml')
    if (Test-Path -LiteralPath 'compose.override.yaml') { $script:composeArgs += @('-f', 'compose.override.yaml') }

    if ($Stop) {
        if (-not (Test-Path -LiteralPath $stateFile)) { throw 'There is no saved Northstar ngrok session to stop.' }
        $state = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        if ($state.envFile -ne $EnvFile) { throw "This session uses $($state.envFile). Pass that file using -EnvFile." }
        $process = Get-CimInstance Win32_Process -Filter "ProcessId = $($state.processId)" -ErrorAction SilentlyContinue
        if ($process -and $process.Name -eq 'ngrok.exe' -and $process.CommandLine -like '*northstar-chat*') {
            Stop-Process -Id $process.ProcessId
        }
        $original = @{}
        foreach ($property in $state.original.PSObject.Properties) { $original[$property.Name] = $property.Value }
        Set-EnvironmentValues -Path $EnvFile -Values $original
        Refresh-PublicConfiguration -RestartWeb
        Remove-Item -LiteralPath $stateFile
        Write-Host 'ngrok stopped. Local CRM callback settings restored.'
    } else {
        $ngrok = Get-Command ngrok -ErrorAction SilentlyContinue
        if (-not $ngrok) { throw 'Install ngrok first: winget install ngrok --source msstore' }
        # Let ngrok locate its configuration: Microsoft Store installations can
        # virtualize the path, making PowerShell Test-Path incorrectly fail.
        if (-not $env:NGROK_AUTHTOKEN) {
            $null = & $ngrok.Source config check 2>&1
            if ($LASTEXITCODE -ne 0) {
                throw 'Configure ngrok first: ngrok config add-authtoken YOUR_TOKEN (get the token at https://dashboard.ngrok.com/get-started/your-authtoken). Keep the token local.'
            }
        }
        if ($Domain -and $Domain -notmatch '^(https://)?[a-zA-Z0-9.-]+$') { throw 'Domain must be an ngrok hostname or an HTTPS origin.' }
        $envLines = [IO.File]::ReadAllLines($EnvFile)
        $portLine = $envLines | Where-Object { $_ -match '^WEB_PORT=' } | Select-Object -Last 1
        $webPort = if ($portLine) { [int]($portLine -split '=', 2)[1].Trim('"', "'") } else { 3000 }
        $upstream = "http://localhost:$webPort"
        try { $null = Invoke-WebRequest -UseBasicParsing -Uri "$upstream/healthz" -TimeoutSec 5 }
        catch { throw 'The local app is not ready. Run start.bat first, then start-ngrok.bat.' }

        $existingState = if (Test-Path -LiteralPath $stateFile) { Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json } else { $null }
        $tunnel = $null
        if ($existingState) {
            if ($existingState.envFile -ne $EnvFile) { throw 'Stop the existing ngrok session before using a different environment file.' }
            if ($Domain -and $existingState.publicUrl -ne "https://$($Domain -replace '^https://', '')") { throw 'Stop the existing ngrok session before changing its domain: start-ngrok.bat -Stop' }
            try {
                $tunnel = (Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3).tunnels | Where-Object { $_.public_url -eq $existingState.publicUrl -and $_.config.addr -eq $upstream } | Select-Object -First 1
            } catch { }
            if (-not $tunnel) {
                try {
                    $activeTunnels = @((Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 3).tunnels | Where-Object { $_.proto -eq 'https' -and $_.config.addr -eq $upstream })
                    $processPattern = "(?i)\bhttp\s+(?:https?://)?(?:localhost:|127\.0\.0\.1:)?$([regex]::Escape([string]$webPort))\b"
                    $matchingProcesses = @(Get-CimInstance Win32_Process -Filter "Name = 'ngrok.exe'" | Where-Object { $_.CommandLine -match $processPattern })
                    if ($activeTunnels.Count -eq 1 -and $matchingProcesses.Count -eq 1) {
                        $candidateUrl = ([uri]$activeTunnels[0].public_url).GetLeftPart([UriPartial]::Authority)
                        $expectedUrl = if ($Domain) { "https://$($Domain -replace '^https://', '')" } else { $null }
                        if ($expectedUrl -and $candidateUrl -ne $expectedUrl) { throw 'The active tunnel does not match the configured ngrok domain.' }
                        $tunnel = $activeTunnels[0]
                        $adoptedProcessId = $matchingProcesses[0].ProcessId
                        Write-Host 'Recovered the active Northstar ngrok tunnel and refreshed its saved session.'
                    }
                } catch {
                    if ($_.Exception.Message -like 'The active tunnel does not match*') { throw }
                }
            }
        }
        if (-not $tunnel) {
            if (Get-NetTCPConnection -LocalPort 4040 -State Listen -ErrorAction SilentlyContinue) { throw 'Port 4040 is used by another tunnel. Stop that ngrok session before starting this app.' }
            $arguments = @('http', $upstream, '--inspect=false', '--metadata=northstar-chat', '--log=stdout', '--log-format=json')
            if ($Domain) { $arguments += "--url=https://$($Domain -replace '^https://', '')" }
            $processStarted = Start-Process -FilePath $ngrok.Source -ArgumentList $arguments -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runtimeDirectory 'agent.log') -RedirectStandardError (Join-Path $runtimeDirectory 'agent-error.log')
            $deadline = (Get-Date).AddSeconds(40)
            do {
                Start-Sleep -Milliseconds 500
                $processStarted.Refresh()
                if ($processStarted.HasExited) {
                    # Report actionable error codes without printing logs that
                    # could contain authentication material.
                    $failureLog = Get-Content -LiteralPath (Join-Path $runtimeDirectory 'agent-error.log') -Raw -ErrorAction SilentlyContinue
                    if ($failureLog -match 'ERR_NGROK_334') {
                        throw 'ERR_NGROK_334: Your ngrok domain is already online on another endpoint/session. Authentication succeeded. Open https://dashboard.ngrok.com/endpoints, stop the endpoint using this domain, then run start-ngrok.bat again. If it is a Cloud Endpoint, remove that conflicting endpoint before starting this direct app tunnel.'
                    }
                    $failureCode = if ($failureLog -match 'ERR_NGROK_\d+') { $Matches[0] } else { 'unknown error' }
                    throw "ngrok could not connect ($failureCode). See reports/ngrok/agent-error.log for details."
                }
                try {
                    $tunnel = (Invoke-RestMethod -Uri 'http://127.0.0.1:4040/api/tunnels' -TimeoutSec 2).tunnels | Where-Object { $_.proto -eq 'https' -and $_.config.addr -eq $upstream } | Select-Object -First 1
                } catch { }
            } until ($tunnel -or (Get-Date) -gt $deadline)
            if (-not $tunnel) { throw 'ngrok did not return a public HTTPS URL. Check reports/ngrok/agent.log.' }
        }
        $publicUrl = ([uri]$tunnel.public_url).GetLeftPart([UriPartial]::Authority)
        if ($publicUrl -notmatch '^https://') { throw 'ngrok must provide an HTTPS endpoint.' }
        $values = [ordered]@{
            TELEGRAM_PUBLIC_BASE_URL = $publicUrl
            CRM_OAUTH_PUBLIC_BASE_URL = $publicUrl
            CRM_OAUTH_FRONTEND_ORIGIN = $publicUrl
            APP_CORS_ORIGINS = '["' + $publicUrl + '","http://localhost:3100","http://127.0.0.1:3100"]'
            EMAIL_VERIFICATION_FRONTEND_URL = "$publicUrl/verify-email"
            PASSWORD_RESET_FRONTEND_URL = "$publicUrl/reset-password"
            WORKSPACE_INVITATION_FRONTEND_URL = "$publicUrl/workspace-invitation"
            ZOHO_OAUTH_FRONTEND_URL = "$publicUrl/integrations"
        }
        $original = @{}
        if ($existingState) {
            foreach ($property in $existingState.original.PSObject.Properties) { $original[$property.Name] = $property.Value }
        } else {
            foreach ($key in $values.Keys) {
                $line = $envLines | Where-Object { $_ -match ('^' + [regex]::Escape($key) + '=') } | Select-Object -Last 1
                $original[$key] = if ($line) { ($line -split '=', 2)[1] } else { $null }
            }
        }
        $processId = if ($processStarted) { $processStarted.Id } elseif ($adoptedProcessId) { $adoptedProcessId } else { $existingState.processId }
        @{ envFile = $EnvFile; processId = $processId; publicUrl = $publicUrl; original = $original } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $stateFile -Encoding UTF8
        $settingsChanged = $false
        foreach ($key in $values.Keys) {
            if ($envLines -notcontains "$key=$($values[$key])") { $settingsChanged = $true }
        }
        if ($settingsChanged -or $processStarted) {
            Set-EnvironmentValues -Path $EnvFile -Values $values
            Write-Host 'Applying the public CRM callback and account URLs...'
            Refresh-PublicConfiguration -RestartWeb
        } else {
            Write-Host 'Reusing the existing ngrok endpoint and public URL settings.'
            Refresh-PublicConfiguration
        }
        $managerTokenLine = $envLines | Where-Object { $_ -match '^TELEGRAM_MANAGER_BOT_TOKEN=' } | Select-Object -Last 1
        $managerSecretLine = $envLines | Where-Object { $_ -match '^TELEGRAM_MANAGER_WEBHOOK_SECRET=' } | Select-Object -Last 1
        $managerToken = if ($managerTokenLine) { ($managerTokenLine -split '=', 2)[1].Trim().Trim('"', "'") } else { '' }
        $managerSecret = if ($managerSecretLine) { ($managerSecretLine -split '=', 2)[1].Trim().Trim('"', "'") } else { '' }
        if ($managerToken -and $managerSecret) {
            Write-Host 'Registering and verifying the Telegram manager webhook...'
            Invoke-Compose -Command @('exec', '-T', 'api', 'python', '-m', 'northstar_api.services.telegram_manager_setup')
        }
        $headers = @{ 'ngrok-skip-browser-warning' = 'northstar-readiness-check' }
        $deadline = (Get-Date).AddSeconds(40)
        $publicReady = $false
        do {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri "$publicUrl/healthz" -Headers $headers -TimeoutSec 10
                $body = if ($response.Content -is [byte[]]) { [Text.Encoding]::UTF8.GetString($response.Content) } else { [string]$response.Content }
                if ($response.StatusCode -eq 200 -and $body.Trim() -eq 'ok') { $publicReady = $true; break }
            } catch { }
            Start-Sleep -Seconds 1
        } until ((Get-Date) -gt $deadline)
        if (-not $publicReady) { throw 'The public endpoint is not ready. The ngrok session is saved; rerun this launcher to retry.' }
        Write-Host "`nPUBLIC APP: $publicUrl/integrations"
        Write-Host "ZOHO REDIRECT URL: $publicUrl/api/v1/crm/oauth/zoho/callback"
        Write-Host 'Keep this PC and Docker running. The ngrok agent runs in the background.'
        Write-Host 'To stop sharing and restore localhost callbacks: start-ngrok.bat -Stop'
        Write-Host 'Use the public app URL when authorizing CRM accounts.'
        if (-not $NoBrowser) { Start-Process -FilePath "$publicUrl/integrations" | Out-Null }
    }
    $exitCode = 0
} catch {
    Write-Host "[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if ($processStarted -and -not (Test-Path -LiteralPath $stateFile)) { Stop-Process -Id $processStarted.Id -ErrorAction SilentlyContinue }
} finally {
    if ($launchLock) { $launchLock.Dispose() }
    if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
}
exit $exitCode
