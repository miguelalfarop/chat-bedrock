# Empaqueta la Lambda con sus dependencias en dist\lambda.zip
# Uso:  .\build.ps1
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$build = Join-Path $root "build"
$dist = Join-Path $root "dist"
$zip = Join-Path $dist "lambda.zip"

if (Test-Path $build) { Remove-Item -Recurse -Force $build }
New-Item -ItemType Directory -Force $build, $dist | Out-Null

# Descarga las dependencias compiladas para Linux x86_64 / Python 3.13 (el runtime de Lambda)
python -m pip install -r (Join-Path $root "backend\requirements.txt") `
    --target $build `
    --platform manylinux2014_x86_64 `
    --python-version 3.13 `
    --implementation cp `
    --only-binary=:all: `
    --upgrade --quiet
if ($LASTEXITCODE -ne 0) { throw "pip install fallo" }

Copy-Item (Join-Path $root "backend\lambda_function.py") $build

if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path (Join-Path $build "*") -DestinationPath $zip
$size = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Listo: $zip ($size MB)"
