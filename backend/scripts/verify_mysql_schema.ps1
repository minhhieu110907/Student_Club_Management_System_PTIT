param(
    [string]$BackendImage = "scms-backend:day02-slice03-verify",
    [string]$MySqlImage = "mysql:8.4.4",
    [switch]$SimulatePartialContainerFailure
)

$ErrorActionPreference = "Stop"
$runId = [Guid]::NewGuid().ToString("N").Substring(0, 12)
$networkName = "scms-s04-net-$runId"
$containerName = "scms-s04-mysql-$runId"
$databaseName = "scms_schema_verify"
$rootPassword = "s04-$([Guid]::NewGuid().ToString('N'))"
$ownershipLabel = "scms.slice04.run=$runId"

function Assert-CommandSucceeded([string]$Message) {
    if ($LASTEXITCODE -ne 0) {
        throw $Message
    }
}

try {
    $existingNetwork = docker network ls --quiet --filter "name=^$networkName$"
    Assert-CommandSucceeded "Failed to check for Docker network name collisions"
    if ($existingNetwork) {
        throw "Refusing to reuse existing Docker network: $networkName"
    }
    $existingContainer = docker ps --all --quiet --filter "name=^/$containerName$"
    Assert-CommandSucceeded "Failed to check for Docker container name collisions"
    if ($existingContainer) {
        throw "Refusing to reuse existing Docker container: $containerName"
    }

    Write-Host "Creating owned network: $networkName"
    docker network create --label $ownershipLabel $networkName *> $null
    Assert-CommandSucceeded "Failed to create isolated Docker network"

    if ($SimulatePartialContainerFailure) {
        Write-Host "Creating labeled stopped container for partial-failure cleanup simulation"
        docker create --name $containerName --network $networkName --label $ownershipLabel `
            $BackendImage python --version *> $null
        Assert-CommandSucceeded "Failed to create partial-failure simulation container"
        throw "Simulated partial container-start failure"
    }

    Write-Host "Starting owned MySQL container: $containerName (no published ports or volumes)"
    docker run --detach --name $containerName --label $ownershipLabel `
        --network $networkName --network-alias mysql `
        --tmpfs /var/lib/mysql:rw,nosuid,size=768m `
        --env "MYSQL_ROOT_PASSWORD=$rootPassword" `
        --env "MYSQL_DATABASE=$databaseName" `
        $MySqlImage `
        --character-set-server=utf8mb4 --collation-server=utf8mb4_0900_ai_ci *> $null
    Assert-CommandSucceeded "Failed to start disposable MySQL container"

    $ready = $false
    $identity = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $identity = docker exec --env "MYSQL_PWD=$rootPassword" $containerName `
            mysql --user=root --database=$databaseName --batch --skip-column-names `
            --execute="SELECT @@version, DATABASE(), @@hostname;" 2> $null
        $probeExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($probeExitCode -eq 0 -and $identity) {
            $ready = $true
            break
        }
        Start-Sleep -Seconds 2
    }
    if (-not $ready) {
        throw "Disposable MySQL did not become ready within 120 seconds"
    }
    $publishedPorts = docker port $containerName
    if ($LASTEXITCODE -ne 0 -or $publishedPorts) {
        throw "Disposable MySQL unexpectedly exposes a host port"
    }
    $attachedNetwork = docker inspect --format "{{json .NetworkSettings.Networks}}" $containerName
    if ($LASTEXITCODE -ne 0 -or $attachedNetwork -notmatch [regex]::Escape($networkName)) {
        throw "Disposable MySQL is not attached to its owned network"
    }
    Write-Host "Verified target identity: container=$containerName network=$networkName endpoint=mysql:3306 database=$databaseName server=$identity"

    $databaseUrl = "mysql+pymysql://root:$rootPassword@mysql:3306/$databaseName"
    Write-Host "Applying Alembic revision to the verified disposable database"
    docker run --rm --network $networkName --read-only --tmpfs /tmp:rw,nosuid,size=128m `
        --mount "type=bind,source=$PSScriptRoot\..,target=/workspace,readonly" `
        --workdir /workspace --env "DATABASE_URL=$databaseUrl" --env PYTHONPYCACHEPREFIX=/tmp/pycache `
        $BackendImage python -m alembic -c alembic.ini upgrade head
    Assert-CommandSucceeded "Alembic upgrade failed against disposable MySQL"

    Write-Host "Running live schema and constraint verification"
    docker run --rm --network $networkName --read-only --tmpfs /tmp:rw,nosuid,size=128m `
        --mount "type=bind,source=$PSScriptRoot\..,target=/workspace,readonly" `
        --workdir /workspace --env "SCMS_MYSQL_INTEGRATION_URL=$databaseUrl" --env PYTHONPYCACHEPREFIX=/tmp/pycache `
        $BackendImage python -m pytest -p no:cacheprovider --basetemp=/tmp/pytest `
        tests/integration/test_mysql_schema.py -vv
    Assert-CommandSucceeded "Live MySQL integration verification failed"
}
finally {
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"

    $containerByName = docker ps --all --quiet --filter "name=^/$containerName$"
    if ($LASTEXITCODE -ne 0) {
        $cleanupErrors.Add("Failed to inspect container cleanup target: $containerName")
    }
    $ownedContainer = docker ps --all --quiet --filter "name=^/$containerName$" --filter "label=$ownershipLabel"
    if ($LASTEXITCODE -ne 0) {
        $cleanupErrors.Add("Failed to verify container ownership: $containerName")
    }
    if ($containerByName -and -not $ownedContainer) {
        $cleanupErrors.Add("Refusing to remove unverified container: $containerName")
    }
    if ($ownedContainer) {
        Write-Host "Removing owned container: $containerName"
        docker rm --force $ownedContainer *> $null
        if ($LASTEXITCODE -ne 0) {
            $cleanupErrors.Add("Failed to remove owned container: $containerName")
        }
    }

    $networkByName = docker network ls --quiet --filter "name=^$networkName$"
    if ($LASTEXITCODE -ne 0) {
        $cleanupErrors.Add("Failed to inspect network cleanup target: $networkName")
    }
    $ownedNetwork = docker network ls --quiet --filter "name=^$networkName$" --filter "label=$ownershipLabel"
    if ($LASTEXITCODE -ne 0) {
        $cleanupErrors.Add("Failed to verify network ownership: $networkName")
    }
    if ($networkByName -and -not $ownedNetwork) {
        $cleanupErrors.Add("Refusing to remove unverified network: $networkName")
    }
    if ($ownedNetwork) {
        Write-Host "Removing owned network: $networkName"
        docker network rm $ownedNetwork *> $null
        if ($LASTEXITCODE -ne 0) {
            $cleanupErrors.Add("Failed to remove owned network: $networkName")
        }
    }

    $ErrorActionPreference = $previousErrorActionPreference
    if ($cleanupErrors.Count -gt 0) {
        throw "Cleanup failed: $($cleanupErrors -join '; ')"
    }
}
