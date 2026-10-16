param([string]$PythonImage = 'python:3.12.14-slim')
$ErrorActionPreference = 'Stop'
python -m pip download --only-binary=:all: --platform manylinux2014_x86_64 --python-version 312 --implementation cp --abi cp312 --dest sandbox/wheels fastapi==0.136.3 httpx==0.28.1 pytest==8.3.4
if ($LASTEXITCODE -ne 0) { throw 'Linux wheel download failed' }
docker build --pull=false --build-arg "PYTHON_IMAGE=$PythonImage" -t repopilot-sandbox:local -f sandbox/Dockerfile.offline .
if ($LASTEXITCODE -ne 0) { throw 'Offline sandbox build failed' }
