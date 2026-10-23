[CmdletBinding()]
param(
    [ValidateSet('Install', 'Upgrade', 'Rollback', 'Backups', 'Status', 'Recover')]
    [string]$Action = 'Install',

    [Parameter(Mandatory = $true)]
    [string]$Destination,

    [string]$Source = $PSScriptRoot,
    [string]$BackupId,
    [string]$PythonExecutable = 'python'
)

$ErrorActionPreference = 'Stop'
$installer = Join-Path $PSScriptRoot 'scripts/manage_install.py'
$installerArgs = @('-B', '-X', 'utf8', $installer,
    '--action', $Action, '--destination', $Destination, '--source', $Source)
if ($BackupId) {
    $installerArgs += @('--backup-id', $BackupId)
}
& $PythonExecutable @installerArgs
exit $LASTEXITCODE
