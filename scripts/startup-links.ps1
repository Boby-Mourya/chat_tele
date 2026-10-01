function Get-StartupLinks {
    param($Config, [string]$PublicUrl, [string]$NgrokStatus, [string]$RequestedDomain)
    $web = Get-LocalUrl -Service $Config.services.web -ContainerPort 8080
    $api = Get-LocalUrl -Service $Config.services.api -ContainerPort 8000
    $apiPrefix = $Config.services.api.environment.APP_API_PREFIX
    if (-not $apiPrefix) { $apiPrefix = '/api/v1' }

    'LOCAL APP'
    "  App:                      $web"
    "  Login:                    $web/login"
    "  Integrations:             $web/integrations"
    "  Connection management:    $web/integrations/advanced"
    "  CRM workflow:             $web/crm-workflow"
    "  Agent deployment:         $web/deploy"
    "  Plan settings:            $web/workspace?section=billing"
    ''
    'LOCAL API AND HEALTH'
    "  API base:                 $api$apiPrefix"
    "  API docs:                 $api/docs"
    "  OpenAPI schema:           $api/openapi.json"
    "  API readiness:            $api/health/ready"
    "  Web health:               $web/healthz"
    "  Frontend API proxy:       $web$apiPrefix"
    ''
    "NGROK: $NgrokStatus"
    if ($PublicUrl) {
        $PublicUrl = $PublicUrl.TrimEnd('/')
        "  Public app:               $PublicUrl"
        "  Public login:             $PublicUrl/login"
        "  Public integrations:      $PublicUrl/integrations"
        "  Public management:        $PublicUrl/integrations/advanced"
        "  Public API base:          $PublicUrl$apiPrefix"
        "  Public web health:        $PublicUrl/healthz"
        '  Local tunnel dashboard:   http://127.0.0.1:4040'
        '  Stop public sharing:      start-ngrok.bat -Stop'
    } else {
        '  Public URL:               Not started or not verified.'
        if ($RequestedDomain) { "  Requested ngrok domain:   $($RequestedDomain -replace '^https://', '') (not verified online)" }
        '  ngrok account setup:      https://dashboard.ngrok.com/get-started/your-authtoken'
    }
    ''
    'CONFIGURED CRM OAUTH CALLBACKS (register these in provider app settings)'
    $callbackBase = $Config.services.api.environment.CRM_OAUTH_PUBLIC_BASE_URL
    if (-not $callbackBase) { $callbackBase = $api }
    $callbackBase = $callbackBase.TrimEnd('/')
    "  Frontend return origin:   $($Config.services.api.environment.CRM_OAUTH_FRONTEND_ORIGIN)"
    foreach ($provider in @('zoho', 'salesforce', 'hubspot', 'dynamics365', 'pipedrive')) {
        "  $($provider.PadRight(24)) $callbackBase$apiPrefix/crm/oauth/$provider/callback"
    }
    if (-not $PublicUrl -and $callbackBase -match '^https://') {
        '  The configured public callback is not verified online by this launch.'
    }
    ''
    'WEBHOOKS'
    $webhookBase = if ($PublicUrl) { $PublicUrl } else { $api }
    "  WhatsApp webhook:         $webhookBase$apiPrefix/webhooks/whatsapp"
    "  Channel webhook template: $webhookBase$apiPrefix/webhooks/channels/{tenant_id}/{provider}/{public_id}"
    "  CRM webhook template:     $webhookBase$apiPrefix/webhooks/crm/{tenant_id}/{provider}/{public_id}"
    '  Copy exact connection-specific webhook URLs from Integrations > Manage.'
    ''
    'LOCAL SERVICE CONSOLES (not exposed through ngrok)'
    foreach ($service in @(
        @{ name = 'minio'; port = 9001; label = 'MinIO console' },
        @{ name = 'minio'; port = 9000; label = 'Object storage API' },
        @{ name = 'rabbitmq'; port = 15672; label = 'RabbitMQ console' }
    )) {
        $value = $Config.services.($service.name)
        if ($value -and @($value.ports | Where-Object { [int]$_.target -eq $service.port -and $_.published }).Count) {
            $url = Get-LocalUrl -Service $value -ContainerPort $service.port
            "  $($service.label.PadRight(24)) $url"
        }
    }
}
