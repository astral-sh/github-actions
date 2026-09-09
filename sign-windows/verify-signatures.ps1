# Require every file in the signing directory to have a trusted Authenticode
# signature from the configured publisher and a signing timestamp.

param(
    [Parameter(Mandatory)]
    [string] $Directory,
    [Parameter(Mandatory)]
    [string] $CertificateSubject
)

$ErrorActionPreference = 'Stop'

$binaries = @(Get-ChildItem $Directory -File -Recurse -Force)
if ($binaries.Count -eq 0) { throw 'No executables to verify' }
foreach ($binary in $binaries) {
    $signature = Get-AuthenticodeSignature $binary.FullName
    if ($signature.Status -ne 'Valid' -or $null -eq $signature.TimeStamperCertificate -or
        $signature.SignerCertificate.Subject -ne $CertificateSubject) {
        throw "Expected a timestamped signature from the configured publisher: $($binary.FullName)"
    }
}
