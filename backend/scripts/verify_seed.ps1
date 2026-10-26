param(
    [string]$BackendImage = "scms-backend:day02-slice03-verify",
    [string]$MySqlImage = "mysql:8.4.4"
)

$ErrorActionPreference = "Stop"
$runId = [Guid]::NewGuid().ToString("N").Substring(0, 12)
$networkName = "scms-s05-net-$runId"
$containerName = "scms-s05-mysql-$runId"
$ownershipLabel = "scms.slice05.run=$runId"
$rootPassword = "s05-$([Guid]::NewGuid().ToString('N'))"
$databaseNames = @("scms_seed_verify", "scms_seed_rollback", "scms_seed_conflict")

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

    Write-Host "Creating owned Slice 05 network: $networkName"
    docker network create --label $ownershipLabel $networkName *> $null
    Assert-CommandSucceeded "Failed to create isolated Docker network"

    Write-Host "Starting owned MySQL container: $containerName (no published ports or volumes)"
    docker run --detach --name $containerName --label $ownershipLabel `
        --network $networkName --network-alias mysql `
        --tmpfs /var/lib/mysql:rw,nosuid,size=768m `
        --env "MYSQL_ROOT_PASSWORD=$rootPassword" `
        --env "MYSQL_DATABASE=$($databaseNames[0])" `
        $MySqlImage `
        --character-set-server=utf8mb4 --collation-server=utf8mb4_0900_ai_ci *> $null
    Assert-CommandSucceeded "Failed to start disposable MySQL container"

    $identity = $null
    for ($attempt = 1; $attempt -le 60; $attempt++) {
        $previousErrorActionPreference = $ErrorActionPreference
        $ErrorActionPreference = "SilentlyContinue"
        $identity = docker exec --env "MYSQL_PWD=$rootPassword" $containerName `
            mysql --user=root --database=$($databaseNames[0]) --batch --skip-column-names `
            --execute="SELECT @@version, DATABASE(), @@hostname;" 2> $null
        $probeExitCode = $LASTEXITCODE
        $ErrorActionPreference = $previousErrorActionPreference
        if ($probeExitCode -eq 0 -and $identity) { break }
        Start-Sleep -Seconds 2
    }
    if (-not $identity) {
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
    Write-Host "Verified disposable target: container=$containerName network=$networkName endpoint=mysql:3306 server=$identity"

    docker exec --env "MYSQL_PWD=$rootPassword" $containerName `
        mysql --user=root --database=$($databaseNames[0]) `
        --execute="CREATE DATABASE scms_seed_rollback CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci; CREATE DATABASE scms_seed_conflict CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;"
    Assert-CommandSucceeded "Failed to create isolated rollback and collision databases"

    foreach ($databaseName in $databaseNames) {
        $databaseUrl = "mysql+pymysql://root:$rootPassword@mysql:3306/$databaseName"
        Write-Host "Applying Alembic revision to disposable database: $databaseName"
        docker run --rm --network $networkName --read-only --tmpfs /tmp:rw,nosuid,size=128m `
            --mount "type=bind,source=$PSScriptRoot\..,target=/workspace,readonly" `
            --workdir /workspace --env "DATABASE_URL=$databaseUrl" --env PYTHONPYCACHEPREFIX=/tmp/pycache `
            $BackendImage python -m alembic -c alembic.ini upgrade head
        Assert-CommandSucceeded "Alembic upgrade failed for disposable database: $databaseName"
    }

    $mainUrl = "mysql+pymysql://root:$rootPassword@mysql:3306/$($databaseNames[0])"
    $rollbackUrl = "mysql+pymysql://root:$rootPassword@mysql:3306/$($databaseNames[1])"
    $conflictUrl = "mysql+pymysql://root:$rootPassword@mysql:3306/$($databaseNames[2])"

    Write-Host "Running the explicit seed CLI once against the verified disposable target"
    docker run --rm --network $networkName --read-only --tmpfs /tmp:rw,nosuid,size=128m `
        --mount "type=bind,source=$PSScriptRoot\..,target=/workspace,readonly" `
        --workdir /workspace --env "SCMS_ENV=test" --env "SCMS_ALLOW_DEMO_SEED=1" `
        --env "SCMS_SEED_DATABASE_URL=$mainUrl" --env PYTHONPYCACHEPREFIX=/tmp/pycache `
        $BackendImage python -m scripts.seed
    Assert-CommandSucceeded "Explicit demo seed CLI failed"

    Write-Host "Running seed idempotency, rollback, guard, collision, and invariant tests"
    docker run --rm --network $networkName --read-only --tmpfs /tmp:rw,nosuid,size=256m `
        --mount "type=bind,source=$PSScriptRoot\..,target=/workspace,readonly" `
        --workdir /workspace --env "SCMS_ENV=test" --env "SCMS_ALLOW_DEMO_SEED=1" `
        --env "SCMS_SEED_INTEGRATION_URL=$mainUrl" `
        --env "SCMS_SEED_ROLLBACK_URL=$rollbackUrl" `
        --env "SCMS_SEED_CONFLICT_URL=$conflictUrl" `
        --env PYTHONPYCACHEPREFIX=/tmp/pycache `
        $BackendImage python -m pytest -p no:cacheprovider --basetemp=/tmp/pytest `
        tests/integration/test_seed.py -vv
    Assert-CommandSucceeded "Live MySQL seed verification failed"
}
finally {
    $cleanupErrors = [System.Collections.Generic.List[string]]::new()
    $previousErrorActionPreference = $ErrorActionPreference
    $ErrorActionPreference = "SilentlyContinue"

    $containerByName = docker ps --all --quiet --filter "name=^/$containerName$"
    if ($LASTEXITCODE -ne 0) { $cleanupErrors.Add("Failed to inspect container: $containerName") }
    $ownedContainer = docker ps --all --quiet --filter "name=^/$containerName$" --filter "label=$ownershipLabel"
    if ($LASTEXITCODE -ne 0) { $cleanupErrors.Add("Failed to verify container ownership: $containerName") }
    if ($containerByName -and -not $ownedContainer) { $cleanupErrors.Add("Refusing to remove unverified container: $containerName") }
    if ($ownedContainer) {
        Write-Host "Removing owned container: $containerName"
        docker rm --force $ownedContainer *> $null
        if ($LASTEXITCODE -ne 0) { $cleanupErrors.Add("Failed to remove owned container: $containerName") }
    }

    $networkByName = docker network ls --quiet --filter "name=^$networkName$"
    if ($LASTEXITCODE -ne 0) { $cleanupErrors.Add("Failed to inspect network: $networkName") }
    $ownedNetwork = docker network ls --quiet --filter "name=^$networkName$" --filter "label=$ownershipLabel"
    if ($LASTEXITCODE -ne 0) { $cleanupErrors.Add("Failed to verify network ownership: $networkName") }
    if ($networkByName -and -not $ownedNetwork) { $cleanupErrors.Add("Refusing to remove unverified network: $networkName") }
    if ($ownedNetwork) {
        Write-Host "Removing owned network: $networkName"
        docker network rm $ownedNetwork *> $null
        if ($LASTEXITCODE -ne 0) { $cleanupErrors.Add("Failed to remove owned network: $networkName") }
    }

    $ErrorActionPreference = $previousErrorActionPreference
    if ($cleanupErrors.Count -gt 0) {
        throw "Cleanup failed: $($cleanupErrors -join '; ')"
    }
}
