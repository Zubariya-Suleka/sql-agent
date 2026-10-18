<#
.SYNOPSIS
    Run the Olist Postgres from Windows.

.DESCRIPTION
    Docker Engine runs inside the 'issue-radar' WSL distro, whose disk lives on G:
    (issue-radar D-018). WSL stops a distro ~15 s after its last wsl.exe process exits, which
    would stop Docker and Postgres with it, so 'up' starts a hidden keep-alive and 'down'
    removes it.

    The keep-alive is tagged and deliberately does not look like issue-radar's
    ('sleep infinity'): each project's 'down' stops only its own keep-alive, and the distro
    keeps running while either project still needs it.

.EXAMPLE
    .\scripts\db.ps1 up        # start and wait until healthy
    .\scripts\db.ps1 status
    .\scripts\db.ps1 logs
    .\scripts\db.ps1 psql      # interactive psql as the owner role
    .\scripts\db.ps1 down      # stop (the data volume is kept)
#>
param(
    [Parameter(Mandatory, Position = 0)]
    [ValidateSet("up", "down", "status", "logs", "psql")]
    [string]$Command
)

# Native tools (wsl, docker) write progress to stderr. Windows PowerShell 5.1 would turn
# every such line into an error under "Stop", so failures are judged by exit code instead.
$ErrorActionPreference = "Continue"
$Distro = "issue-radar"
$KeepAliveTag = "sql-agent-keepalive"
$env:WSL_UTF8 = "1"
$RepoWin = Split-Path -Parent $PSScriptRoot
$Repo = (wsl.exe -d $Distro -u root -- wslpath -a ($RepoWin -replace '\\', '/') 2>$null).Trim()

function Invoke-Compose([string[]]$ComposeArgs) {
    wsl.exe -d $Distro -u root --cd $Repo -- docker compose @ComposeArgs 2>&1 |
        ForEach-Object { "$_" } |
        Where-Object { $_ -notmatch "Failed to start the systemd user session" }
    if ($LASTEXITCODE -ne 0) { throw "docker compose $ComposeArgs failed (exit $LASTEXITCODE)" }
}

function Get-KeepAlive {
    Get-CimInstance Win32_Process -Filter "Name = 'wsl.exe'" |
        Where-Object { $_.CommandLine -like "*$KeepAliveTag*" }
}

switch ($Command) {
    "up" {
        if (-not (Get-KeepAlive)) {
            # The trailing tag becomes sh's $0: harmless, and it marks the command line.
            Start-Process wsl.exe -WindowStyle Hidden -ArgumentList `
                "-d $Distro -u root --exec sh -c `"exec sleep 2147483647`" $KeepAliveTag"
        }
        Write-Host "Starting Postgres; waiting until healthy..."
        Invoke-Compose @("--progress", "quiet", "up", "-d", "--wait", "--wait-timeout", "300")
        Invoke-Compose @("ps", "--format", "table {{.Service}}\t{{.Status}}\t{{.Ports}}")
    }
    "down" {
        Invoke-Compose @("down")
        Get-KeepAlive | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
        Write-Host "Postgres stopped (data kept in the 'sql-agent_pgdata' volume)."
    }
    "status" {
        Invoke-Compose @("ps")
        $keepAlive = if (Get-KeepAlive) { "running" } else { "not running" }
        Write-Host "Keep-alive: $keepAlive"
    }
    "logs" {
        Invoke-Compose @("logs", "--tail", "50")
    }
    "psql" {
        wsl.exe -d $Distro -u root --cd $Repo -- docker compose exec postgres psql -U olist_admin -d olist
    }
}
