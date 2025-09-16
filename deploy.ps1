Param(
  [string]$ProjectId = "",
  [string]$Region = "us-central1",
  [string]$RepoName = "app-repo",
  [string]$ServiceName = "gvt-agent",
  [string]$ImageTag = "v1",
  [string]$ServiceAccountEmail = "",
  [string]$TwilioAccountSid = "",
  [string]$TwilioAuthToken = "",
  [string]$TwilioNumber = "",
  [string]$YourNumber = "",
  [string]$CallTriggerToken = "",
  [string]$TimeZone = "America/Detroit",
  [string]$EnvFile = "",
  [switch]$DryRun
)

# Load PROJECT_ID from .env if not provided
if (-not $ProjectId -and (Test-Path ".env")) {
    $envContent = Get-Content ".env" | Where-Object { $_ -match "=" -and ($_ -notmatch "^#") }
    foreach ($line in $envContent) {
        $k,$v = $line -split "=",2
        if ($k -eq "PROJECT_ID") { $ProjectId = $v.Trim() }
    }
}
if (-not $ProjectId) { throw "PROJECT_ID is required (pass -ProjectId or set in .env)" }

$ErrorActionPreference = "Stop"

function Require-Cmd($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "Required command '$name' not found on PATH."
  }
}

function Exec {
  param(
    [Parameter(Mandatory=$true)]
    [string] $cmd,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]] $args
  )
  Write-Host "› $cmd $($args -join ' ')" -ForegroundColor Cyan
  if ($DryRun) { return }
  & $cmd @args
  if ($LASTEXITCODE -ne 0) {
    throw "'$cmd $($args -join ' ')' failed with exit code $LASTEXITCODE"
  }
}

Require-Cmd gcloud

# Ensure required services
$apis = @(
  "run.googleapis.com",
  "artifactregistry.googleapis.com",
  "cloudbuild.googleapis.com",
  "secretmanager.googleapis.com"
)
foreach ($api in $apis) {
  Exec gcloud @("services","enable",$api)
}

# Ensure Artifact Registry repo exists
try {
  Exec gcloud @("artifacts","repositories","describe",$RepoName,"--location=$Region") | Out-Null
} catch {
  Exec gcloud @("artifacts","repositories","create",$RepoName,"--repository-format=docker","--location=$Region")
}

# Build & push image
$imagePath = "$Region-docker.pkg.dev/$ProjectId/$RepoName/$($ServiceName):$ImageTag"
Exec gcloud @("builds","submit","--tag",$imagePath)

# Service account
if ([string]::IsNullOrWhiteSpace($ServiceAccountEmail)) {
  $ServiceAccountEmail = "$ServiceName-sa@$ProjectId.iam.gserviceaccount.com"
  try {
    Exec gcloud @("iam","service-accounts","describe",$ServiceAccountEmail) | Out-Null
  } catch {
    Exec gcloud @("iam","service-accounts","create","$ServiceName-sa","--display-name",$("$ServiceName runtime"))
  }
}

# Secret access
$secrets = @("GOOGLE_CREDENTIALS_JSON","GOOGLE_TOKEN_JSON")
foreach ($s in $secrets) {
  Exec gcloud @("secrets","add-iam-policy-binding",$s,"--member=serviceAccount:$ServiceAccountEmail","--role=roles/secretmanager.secretAccessor")
}

# Env vars
$setEnvTokens = @()
if ($EnvFile) {
  if ($EnvFile.ToLower().EndsWith(".env")) {
    # Convert .env -> .yaml for Cloud Run (all values quoted as strings)
    $yamlFile = [System.IO.Path]::ChangeExtension($EnvFile, ".yaml")
    $lines = Get-Content $EnvFile | Where-Object { $_ -match "=" -and ($_ -notmatch "^\s*#") }
    $yaml = foreach ($line in $lines) {
      $k,$v = $line -split "=", 2
      $k = $k.Trim()
      $v = $v.Trim()

      # Strip surrounding quotes in dotenv value if present
      if (($v.StartsWith('"') -and $v.EndsWith('"')) -or ($v.StartsWith("'") -and $v.EndsWith("'"))) {
        $v = $v.Substring(1, $v.Length - 2)
      }

      # Escape single quotes for YAML single-quoted style: ' → ''
      $v = $v -replace "'", "''"

      # Always output as a YAML string
      "${k}: '${v}'"
    }
    $yaml | Set-Content $yamlFile -Encoding UTF8
    Write-Host "Converted $EnvFile to $yamlFile for Cloud Run"
    $setEnvTokens = @("--env-vars-file", $yamlFile)
  }
  elseif ($EnvFile.ToLower().EndsWith(".yaml") -or $EnvFile.ToLower().EndsWith(".yml")) {
    $setEnvTokens = @("--env-vars-file", $EnvFile)
  }
  else {
    throw "Unsupported env file extension. Use .env for dotenv or .yaml/.yml for Cloud Run YAML."
  }
} else {
  $pairs = @()
  if ($TimeZone)         { $pairs += "TIMEZONE=$TimeZone" }
  if ($TwilioAccountSid) { $pairs += "TWILIO_ACCOUNT_SID=$TwilioAccountSid" }
  if ($TwilioAuthToken)  { $pairs += "TWILIO_AUTH_TOKEN=$TwilioAuthToken" }
  if ($TwilioNumber)     { $pairs += "TWILIO_NUMBER=$TwilioNumber" }
  if ($YourNumber)       { $pairs += "YOUR_NUMBER=$YourNumber" }
  if ($CallTriggerToken) { $pairs += "CALL_TRIGGER_TOKEN=$CallTriggerToken" }
  if ($pairs.Count -gt 0) {
    $setEnvTokens = @("--set-env-vars", ($pairs -join ","))
  }
}

# Update-secrets as two separate tokens
$updateSecretsTokens = @(
  "--update-secrets",
  "GOOGLE_CREDENTIALS_FILE=GOOGLE_CREDENTIALS_JSON:latest,GOOGLE_TOKEN_FILE=GOOGLE_TOKEN_JSON:latest"
)

# Deploy args
$deployArgs = @(
  "run","deploy",$ServiceName,
  "--image",$imagePath,
  "--region",$Region,
  "--allow-unauthenticated",
  "--port","8080",
  "--service-account",$ServiceAccountEmail
) + $setEnvTokens + $updateSecretsTokens

Exec gcloud $deployArgs

# Resolve the exact gcloud launcher (use the .cmd on Windows)
$Gcloud = (Get-Command gcloud | Select-Object -ExpandProperty Source)
if (-not $Gcloud) { throw "gcloud not found on PATH" }

# Build the args as a *variable* (not an inline @("..") literal)
$descArgs = @(
  "run","services","describe",
  $ServiceName,
  "--region=$Region",
  "--format=value(status.url)"
)

# Call with explicit path + splatted array
$serviceUrl = & $Gcloud @descArgs

Write-Host "`nService URL: $serviceUrl" -ForegroundColor Green
Write-Host "`nNext:" -ForegroundColor Yellow
Write-Host "• Update Twilio webhook to: POST $serviceUrl/voice"
Write-Host "• Trigger a call: Invoke-WebRequest -Uri '$serviceUrl/call' -Method POST -Raw"
