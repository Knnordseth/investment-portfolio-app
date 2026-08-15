# Regenerates windows_ca_bundle.pem: certifi's default CA list plus every root/intermediate
# certificate Windows already trusts. Re-run this if yfinance/requests calls start failing
# again with "SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate" — that
# error means some certificate (usually a corporate/antivirus SSL-inspection root) is trusted
# by Windows but missing from Python's bundled cert list, and this file needs a refresh.
#
# Run from anywhere: powershell -File backend\certs\generate_ca_bundle.ps1

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvPython = Join-Path $scriptDir "..\.venv\Scripts\python.exe"
$out = Join-Path $scriptDir "windows_ca_bundle.pem"

$certifiPath = & $venvPython -c "import certifi; print(certifi.where())"

$stores = @(
    "Cert:\LocalMachine\Root", "Cert:\LocalMachine\CA", "Cert:\LocalMachine\AuthRoot",
    "Cert:\CurrentUser\Root", "Cert:\CurrentUser\CA"
)
$sb = New-Object System.Text.StringBuilder
[void]$sb.Append([System.IO.File]::ReadAllText($certifiPath))
foreach ($s in $stores) {
    Get-ChildItem -Path $s -ErrorAction SilentlyContinue | ForEach-Object {
        $b64 = [System.Convert]::ToBase64String($_.RawData, [System.Base64FormattingOptions]::InsertLineBreaks)
        [void]$sb.AppendLine("-----BEGIN CERTIFICATE-----")
        [void]$sb.AppendLine($b64)
        [void]$sb.AppendLine("-----END CERTIFICATE-----")
    }
}
[System.IO.File]::WriteAllText($out, $sb.ToString())
Write-Output "Wrote $out"
