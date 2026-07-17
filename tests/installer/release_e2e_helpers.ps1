# Shared process helpers for installer and portable release validation.

function Start-KotoWithoutDeveloperEnvironment {
    param(
        [Parameter(Mandatory = $true)][string]$ExePath,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory
    )

    $names = @(
        "PATH",
        "PYTHONHOME",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "NODE_PATH",
        "JAVA_HOME"
    )
    $saved = @{}
    foreach ($name in $names) {
        $saved[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
    }

    try {
        [Environment]::SetEnvironmentVariable(
            "PATH",
            "$env:SystemRoot\System32;$env:SystemRoot",
            "Process"
        )
        foreach ($name in $names | Where-Object { $_ -ne "PATH" }) {
            [Environment]::SetEnvironmentVariable($name, $null, "Process")
        }
        return Start-Process `
            -FilePath $ExePath `
            -WorkingDirectory $WorkingDirectory `
            -PassThru
    }
    finally {
        foreach ($name in $names) {
            [Environment]::SetEnvironmentVariable($name, $saved[$name], "Process")
        }
    }
}
