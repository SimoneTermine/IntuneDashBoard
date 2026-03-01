<#
.SYNOPSIS
    Creates (or guides creation of) an Azure AD / Entra ID App Registration
    for the Intune Dashboard application.

.DESCRIPTION
    This script helps you create the required app registration in Microsoft Entra ID
    with the correct Microsoft Graph API permissions.

    You can run this interactively or review the permissions list and create
    the registration manually in the Azure portal.

.REQUIREMENTS
    - Microsoft.Graph PowerShell module  (Install-Module Microsoft.Graph)
    - Global Administrator or Application Administrator role
    - PowerShell 5.1+ or PowerShell Core 7+

.USAGE
    .\setup_app_registration.ps1 -TenantId "your-tenant-id" -AppName "Intune Dashboard"
#>

param(
    [Parameter(Mandatory=$false)]
    [string]$TenantId = "",

    [Parameter(Mandatory=$false)]
    [string]$AppName = "Intune Dashboard (Local)",

    [Parameter(Mandatory=$false)]
    [switch]$DryRun = $false,

    [Parameter(Mandatory=$false)]
    [switch]$ShowPermissionsOnly = $false
)

# ─────────────────────────────────────────────────────────────────────────────
# Required permissions
# ─────────────────────────────────────────────────────────────────────────────
$RequiredPermissions = @(
    @{ Name = "DeviceManagementManagedDevices.Read.All";  Type = "Delegated"; Reason = "Read managed devices from Intune" },
    @{ Name = "Device.Read.All";                         Type = "Delegated"; Reason = "Read Entra device directory objects (needed to resolve device-group assignments via /devices/{id}/transitiveMemberOf)" },
    @{ Name = "DeviceManagementConfiguration.Read.All";  Type = "Delegated"; Reason = "Read device configuration policies" },
    @{ Name = "DeviceManagementApps.Read.All";           Type = "Delegated"; Reason = "Read managed apps and install status" },
    @{ Name = "Group.Read.All";                          Type = "Delegated"; Reason = "Read Entra groups used in assignments" },
    @{ Name = "User.Read.All";                           Type = "Delegated"; Reason = "Read user metadata linked to devices" },
    @{ Name = "DeviceManagementRBAC.Read.All";           Type = "Delegated"; Reason = "Read RBAC roles (optional)" },
    @{ Name = "Organization.Read.All";                   Type = "Delegated"; Reason = "Read tenant info for connection test" }
)

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Intune Dashboard - App Registration" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── Show permissions list ────────────────────────────────────────────────────
Write-Host "Required Microsoft Graph API Permissions:" -ForegroundColor Yellow
Write-Host ""
foreach ($perm in $RequiredPermissions) {
    Write-Host "  [$(($perm.Type).PadRight(10))] $($perm.Name)" -ForegroundColor White
    Write-Host "              → $($perm.Reason)" -ForegroundColor Gray
}
Write-Host ""

if ($ShowPermissionsOnly) {
    Write-Host "Run without -ShowPermissionsOnly to create the registration." -ForegroundColor Gray
    exit 0
}

# ── Manual instructions (always shown) ──────────────────────────────────────
Write-Host "MANUAL SETUP INSTRUCTIONS" -ForegroundColor Green
Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
Write-Host ""
Write-Host "1. Go to: https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationsListBlade"
Write-Host ""
Write-Host "2. Click '+ New registration'"
Write-Host "   - Name: $AppName"
Write-Host "   - Supported account types: Accounts in this organizational directory only (Single tenant)"
Write-Host "   - Redirect URI: leave blank (we use Device Code Flow — no redirect needed)"
Write-Host "   - Click 'Register'"
Write-Host ""
Write-Host "3. Note the following values from the Overview page:"
Write-Host "   - Application (client) ID"
Write-Host "   - Directory (tenant) ID"
Write-Host ""
Write-Host "4. Go to 'API permissions' → '+ Add a permission' → 'Microsoft Graph' → 'Delegated permissions'"
Write-Host "   Add all of these:" -ForegroundColor Yellow
foreach ($perm in $RequiredPermissions) {
    Write-Host "   ✓ $($perm.Name)"
}
Write-Host ""
Write-Host "5. Click 'Grant admin consent for <your tenant>'"
Write-Host ""
Write-Host "6. Go to 'Authentication' → '+ Add a platform' → 'Mobile and desktop applications'"
Write-Host "   Enable: https://login.microsoftonline.com/common/oauth2/nativeclient"
Write-Host "   (This enables Device Code Flow)"
Write-Host ""
Write-Host "7. Under 'Advanced settings', set 'Allow public client flows' = YES"
Write-Host ""
Write-Host "8. Enter your Tenant ID and Client ID in the app: Settings → Tenant / Auth"
Write-Host ""

# ── Automated creation via Microsoft.Graph ───────────────────────────────────
if (-not $DryRun) {
    $proceed = Read-Host "Would you like to attempt automated creation via Microsoft.Graph PowerShell? [y/N]"
    if ($proceed -ne "y" -and $proceed -ne "Y") {
        Write-Host "Skipping automated creation. Follow the manual steps above." -ForegroundColor Gray
        exit 0
    }

    # Check module
    if (-not (Get-Module -ListAvailable -Name "Microsoft.Graph")) {
        Write-Host "Microsoft.Graph module not found. Installing..." -ForegroundColor Yellow
        try {
            Install-Module Microsoft.Graph -Scope CurrentUser -Force -ErrorAction Stop
        } catch {
            Write-Host "Failed to install Microsoft.Graph: $_" -ForegroundColor Red
            Write-Host "Please install manually: Install-Module Microsoft.Graph" -ForegroundColor Yellow
            exit 1
        }
    }

    Import-Module Microsoft.Graph.Applications
    Import-Module Microsoft.Graph.Authentication

    Write-Host ""
    Write-Host "Connecting to Microsoft Graph..." -ForegroundColor Cyan

    try {
        if ($TenantId) {
            Connect-MgGraph -TenantId $TenantId -Scopes "Application.ReadWrite.All","Directory.ReadWrite.All" -ErrorAction Stop
        } else {
            Connect-MgGraph -Scopes "Application.ReadWrite.All","Directory.ReadWrite.All" -ErrorAction Stop
        }
    } catch {
        Write-Host "Connection failed: $_" -ForegroundColor Red
        exit 1
    }

    $context = Get-MgContext
    Write-Host "Connected as: $($context.Account) to tenant: $($context.TenantId)" -ForegroundColor Green
    Write-Host ""

    # Get Graph service principal ID
    $graphSP = Get-MgServicePrincipal -Filter "appId eq '00000003-0000-0000-c000-000000000000'"
    $graphSpId = $graphSP.Id

    # Collect permission IDs
    $permObjects = @()
    foreach ($perm in $RequiredPermissions) {
        $oauth2perm = $graphSP.Oauth2PermissionScopes | Where-Object { $_.Value -eq $perm.Name }
        if ($oauth2perm) {
            $permObjects += @{
                id   = $oauth2perm.Id
                type = "Scope"
            }
            Write-Host "  Found permission: $($perm.Name) [$($oauth2perm.Id)]" -ForegroundColor Gray
        } else {
            Write-Host "  WARNING: Permission not found: $($perm.Name)" -ForegroundColor Yellow
        }
    }

    # Create the app registration
    Write-Host ""
    Write-Host "Creating app registration '$AppName'..." -ForegroundColor Cyan

    $appParams = @{
        DisplayName            = $AppName
        SignInAudience         = "AzureADMyOrg"
        IsFallbackPublicClient = $true
        PublicClient           = @{
            RedirectUris = @("https://login.microsoftonline.com/common/oauth2/nativeclient")
        }
        RequiredResourceAccess = @(
            @{
                ResourceAppId  = "00000003-0000-0000-c000-000000000000"
                ResourceAccess = $permObjects
            }
        )
    }

    try {
        $newApp = New-MgApplication @appParams -ErrorAction Stop

        Write-Host ""
        Write-Host "✅ App registration created successfully!" -ForegroundColor Green
        Write-Host ""
        Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
        Write-Host "  Application (Client) ID : $($newApp.AppId)" -ForegroundColor Cyan
        Write-Host "  Directory (Tenant) ID   : $($context.TenantId)" -ForegroundColor Cyan
        Write-Host "─────────────────────────────────────────────────────────" -ForegroundColor Gray
        Write-Host ""
        Write-Host "IMPORTANT: You still need to grant admin consent!" -ForegroundColor Yellow
        Write-Host "  Go to: https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/CallAnAPI/appId/$($newApp.AppId)"
        Write-Host "  → API permissions → Grant admin consent for $($context.TenantDomain ?? $context.TenantId)"
        Write-Host ""
        Write-Host "Then enter these values in Intune Dashboard → Settings → Tenant / Auth:"
        Write-Host "  Tenant ID : $($context.TenantId)"
        Write-Host "  Client ID : $($newApp.AppId)"
        Write-Host ""

        # Optionally save to a file
        $outputFile = Join-Path $PSScriptRoot "app_registration_info.txt"
        @"
Intune Dashboard - App Registration Info
Generated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

Tenant ID:  $($context.TenantId)
Client ID:  $($newApp.AppId)
App Name:   $AppName

NOTE: Grant admin consent at:
https://portal.azure.com/#view/Microsoft_AAD_RegisteredApps/ApplicationMenuBlade/~/CallAnAPI/appId/$($newApp.AppId)
"@ | Set-Content $outputFile
        Write-Host "Registration info saved to: $outputFile" -ForegroundColor Gray

    } catch {
        Write-Host "Failed to create app registration: $_" -ForegroundColor Red
        exit 1
    }

    Disconnect-MgGraph | Out-Null
}