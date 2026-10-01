[CmdletBinding()]
param(
    [string]$EnvFile = $env:NORTHSTAR_ENV_FILE,
    [switch]$NoBuild,
    [switch]$NoBrowser,
    [switch]$NoPause,
    [switch]$NoNgrok,
    [string]$NgrokDomain = $env:NGROK_DOMAIN,
    [ValidateRange(30, 1800)][int]$TimeoutSeconds = 300
)

$ErrorActionPreference = 'Stop'
$workspaceRoot = Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'startup-links.ps1')
Set-Location -LiteralPath $workspaceRoot
$logDirectory = Join-Path $workspaceRoot 'reports/startup'
New-Item -ItemType Directory -Force -Path $logDirectory | Out-Null
$script:DockerErrorFile = Join-Path $logDirectory 'docker-error.log'
$script:ComposeArgs = @()
$exitCode = 1
$transcribing = $false
$launchLock = $null

function Invoke-Docker {
    param([string[]]$DockerArgs, [switch]$Capture, [switch]$Quiet)
    # Native stderr includes Docker progress. Only its exit code means failure.
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        if ($Capture) { $output = & docker @DockerArgs 2> $script:DockerErrorFile }
        else { & docker @DockerArgs 2>&1 | ForEach-Object { Write-Host $_.ToString() } }
        $nativeExitCode = $LASTEXITCODE
    } finally { $ErrorActionPreference = $previousPreference }
    if ($nativeExitCode -ne 0) {
        if ($Capture -and -not $Quiet -and (Test-Path -LiteralPath $script:DockerErrorFile)) {
            Get-Content -LiteralPath $script:DockerErrorFile -Tail 12 | Out-Host
        }
        throw "Docker $($DockerArgs[0]) failed (exit $nativeExitCode)."
    }
    if ($Capture) { return ($output -join "`n") }
}

function Get-ComposeConfig {
    $json = Invoke-Docker -DockerArgs ($script:ComposeArgs + @('config', '--format', 'json')) -Capture
    # This contains credentials: never print or log the resolved configuration.
    return ($json | ConvertFrom-Json)
}

function Get-LocalUrl {
    param($Service, [int]$ContainerPort)
    $binding = @($Service.ports | Where-Object { [int]$_.target -eq $ContainerPort })
    if ($binding.Count -ne 1 -or -not $binding[0].published) {
        throw "Expected one published port for container port $ContainerPort. Check Compose configuration."
    }
    $bindAddress = $binding[0].host_ip
    if (-not $bindAddress -or $bindAddress -in @('0.0.0.0', '127.0.0.1', '::', '::1')) {
        $bindAddress = 'localhost'
    } elseif ($bindAddress.Contains(':')) { $bindAddress = "[$bindAddress]" }
    return "http://${bindAddress}:$($binding[0].published)"
}

function Wait-Http {
    param([string]$Url, [string]$Label, [int]$ExpectedStatus = 200)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        $status = 0
        try { $status = (Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 5).StatusCode }
        catch { if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode } }
        if ($status -eq $ExpectedStatus) { Write-Host "  $Label is ready."; return }
        if ((Get-Date) -ge $deadline) { throw "$Label did not become ready at $Url within $TimeoutSeconds seconds (last HTTP status: $status)." }
        Start-Sleep -Seconds 2
    } while ($true)
}

try {
    try {
        $launchLock = [System.IO.File]::Open((Join-Path $logDirectory 'launch.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    } catch [System.IO.IOException] {
        throw 'Another Northstar launcher is already running. Wait for that window to finish starting the stack.'
    }
    Start-Transcript -Path (Join-Path $logDirectory 'latest.log') -Force | Out-Null
    $transcribing = $true
    Write-Host "`nNORTHSTAR AI - APP AND NGROK`n"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw 'Docker is not installed or is not on PATH. Install Docker Desktop with Linux containers, then run start.bat again.'
    }
    Write-Host '[1/6] Checking Docker Desktop...'
    $dockerReady = $false
    try { $engine = Invoke-Docker -DockerArgs @('info', '--format', '{{.OSType}}') -Capture -Quiet; $dockerReady = $true } catch { }
    if (-not $dockerReady) {
        $desktop = Join-Path $env:ProgramFiles 'Docker/Docker/Docker Desktop.exe'
        if (-not (Test-Path -LiteralPath $desktop)) { throw 'Docker is unavailable. Start your Docker engine, then run this launcher again.' }
        if (-not (Get-Process -Name 'Docker Desktop' -ErrorAction SilentlyContinue)) {
            Start-Process -FilePath $desktop -WindowStyle Hidden | Out-Null
        }
        Write-Host '  Waiting for Docker Desktop to start...'
        $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
        do {
            Start-Sleep -Seconds 3
            try { $engine = Invoke-Docker -DockerArgs @('info', '--format', '{{.OSType}}') -Capture -Quiet; $dockerReady = $true } catch { }
        } while (-not $dockerReady -and (Get-Date) -lt $deadline)
        if (-not $dockerReady) { throw 'Docker Desktop did not become ready in time. Check Docker Desktop and its WSL engine.' }
    }
    if ($engine.Trim() -ne 'linux') { throw 'Switch Docker Desktop to Linux containers, then run start.bat again.' }
    Invoke-Docker -DockerArgs @('compose', 'version')

    Write-Host '[2/6] Loading the local stack configuration...'
    if (-not $EnvFile) {
        if (Test-Path -LiteralPath '.env.launch') { $EnvFile = '.env.launch' }
        else {
            $EnvFile = '.env'
            if (-not (Test-Path -LiteralPath $EnvFile)) {
                Copy-Item -LiteralPath '.env.example' -Destination $EnvFile
                Write-Host '  Created .env from .env.example.'
            }
        }
    }
    $EnvFile = (Resolve-Path -LiteralPath $EnvFile).Path
    if (-not $NgrokDomain) {
        $domainLine = [IO.File]::ReadAllLines($EnvFile) | Where-Object { $_ -match '^NGROK_DOMAIN=' } | Select-Object -Last 1
        if ($domainLine) { $NgrokDomain = ($domainLine -split '=', 2)[1].Trim().Trim('"', "'") }
    }
    $script:ComposeArgs = @('compose', '--project-directory', $workspaceRoot, '--env-file', $EnvFile, '-f', (Join-Path $workspaceRoot 'compose.yaml'))
    if (Test-Path -LiteralPath 'compose.override.yaml') {
        $script:ComposeArgs += @('-f', (Join-Path $workspaceRoot 'compose.override.yaml'))
    }
    $config = Get-ComposeConfig
    $uploadOrigin = $config.services.api.environment.S3_PUBLIC_ENDPOINT_URL
    $connectOrigins = @($config.services.web.build.args.WEB_CSP_EXTRA_CONNECT_SRC -split '\s+' | Where-Object { $_ })
    if ($uploadOrigin -and $uploadOrigin -notin $connectOrigins) {
        $env:WEB_CSP_EXTRA_CONNECT_SRC = ($connectOrigins + $uploadOrigin) -join ' '
        $config = Get-ComposeConfig
    }
    $webUrl = Get-LocalUrl -Service $config.services.web -ContainerPort 8080
    $apiUrl = Get-LocalUrl -Service $config.services.api -ContainerPort 8000
    Write-Host "  Environment: $EnvFile"
    Write-Host "  Project: $($config.name)"

    Write-Host '[3/6] Checking configured ports...'
    $ownPorts = @()
    $ids = Invoke-Docker -DockerArgs @('ps', '-q', '--filter', "label=com.docker.compose.project=$($config.name)") -Capture
    if ($ids.Trim()) {
        $containers = (Invoke-Docker -DockerArgs (@('inspect') + ($ids -split '\s+')) -Capture) | ConvertFrom-Json
        foreach ($container in $containers) {
            foreach ($port in $container.NetworkSettings.Ports.PSObject.Properties) {
                foreach ($binding in $port.Value) { if ($binding.HostPort) { $ownPorts += [int]$binding.HostPort } }
            }
        }
    }
    $listeners = @(Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue)
    foreach ($service in $config.services.PSObject.Properties) {
        foreach ($port in $service.Value.ports) {
            if (-not $port.published -or $port.protocol -eq 'udp') { continue }
            $published = [int]$port.published
            if ($published -in $ownPorts) { continue }
            $occupied = @($listeners | Where-Object { $_.LocalPort -eq $published })
            if ($occupied.Count) {
                $owners = ($occupied.OwningProcess | Sort-Object -Unique) -join ', '
                throw "Port $published for $($service.Name) is already used by process $owners outside this stack. Change the matching port in $EnvFile or stop that application."
            }
        }
    }

    Write-Host '[4/6] Starting services (cached builds are reused)...'
    # Local attestations change the image index even for a fully cached build,
    # which makes Compose recreate healthy containers. Keep local image IDs stable.
    # CI/release builds retain their own provenance settings.
    if (-not $NoBuild) { Invoke-Docker -DockerArgs ($script:ComposeArgs + @('build', '--provenance=false', 'api', 'web')) }
    Invoke-Docker -DockerArgs ($script:ComposeArgs + @('up', '-d', '--no-build', '--wait', '--wait-timeout', [string]$TimeoutSeconds))

    Write-Host '[5/6] Verifying the frontend and backend...'
    Wait-Http -Url "$apiUrl/health/ready" -Label 'Backend'
    Wait-Http -Url "$webUrl/healthz" -Label 'Web server'
    Wait-Http -Url "$webUrl/login" -Label 'Frontend'
    Wait-Http -Url "$webUrl/api/v1/agents" -Label 'Frontend API proxy' -ExpectedStatus 401
    Write-Host '[6/6] Starting the public ngrok endpoint...'
    $publicUrl = $null
    $ngrokStatus = 'Skipped by -NoNgrok; local app is ready.'
    if (-not $NoNgrok) {
        $ngrokArguments = @('-NoLogo', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $PSScriptRoot 'start-ngrok.ps1'), '-EnvFile', $EnvFile, '-NoPause', '-NoBrowser')
        if ($NgrokDomain) { $ngrokArguments += @('-Domain', $NgrokDomain) }
        & powershell.exe @ngrokArguments
        if ($LASTEXITCODE -eq 0) {
            $ngrokState = Get-Content -LiteralPath (Join-Path $workspaceRoot 'reports/ngrok/state.json') -Raw | ConvertFrom-Json
            $publicUrl = $ngrokState.publicUrl
            $ngrokStatus = 'Online. Keep this PC, Docker and ngrok running.'
        } else {
            $ngrokStatus = 'Not online. Local app is ready; see the ngrok message above.'
            Write-Host '  ngrok setup: ngrok config add-authtoken YOUR_TOKEN'
            Write-Host '  Token page: https://dashboard.ngrok.com/get-started/your-authtoken'
            Write-Host '  After setup, run start.bat again.'
        }
        # ngrok updates the environment file with the actual public URL.
        $config = Get-ComposeConfig
    }
    $links = @(Get-StartupLinks -Config $config -PublicUrl $publicUrl -NgrokStatus $ngrokStatus -RequestedDomain $NgrokDomain)
    Write-Host "`nNORTHSTAR AI IS READY"
    $links | ForEach-Object { Write-Host $_ }
    $linksPath = Join-Path $logDirectory 'links.txt'
    [IO.File]::WriteAllLines($linksPath, [string[]]$links, (New-Object Text.UTF8Encoding($false)))
    Write-Host "  All links saved to: $linksPath"
    Write-Host "  Login: use SEED_ADMIN_EMAIL and SEED_ADMIN_PASSWORD in $EnvFile"
    Write-Host "  Startup log: $logDirectory/latest.log"
    Write-Host '  You can close this window. Services keep running in Docker.'
    if (-not $NoBrowser -and -not $env:NORTHSTAR_NO_BROWSER) {
        $browserUrl = if ($publicUrl) { "$publicUrl/integrations" } else { $webUrl }
        try { Start-Process -FilePath $browserUrl | Out-Null }
        catch { Write-Host "  Open $browserUrl in your browser." }
    }
    $exitCode = 0
} catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    if ($script:ComposeArgs.Count) {
        try { Invoke-Docker -DockerArgs ($script:ComposeArgs + @('ps', '-a')) } catch { }
        Write-Host "  Diagnose: docker compose --env-file `"$EnvFile`" logs --tail=100"
    }
    Write-Host "  Startup log: $logDirectory/latest.log"
} finally {
    if ($transcribing) { Stop-Transcript | Out-Null }
    if ($launchLock) { $launchLock.Dispose() }
    if (-not $NoPause -and -not $env:NORTHSTAR_NO_PAUSE) { Read-Host 'Press Enter to close' | Out-Null }
}
exit $exitCode
