# Собирает deploy.zip для переноса бота на сервер.
# В архиве: код, assets/, data/ (база с историей, выгрузки), .env.
# Без: .venv, .git, __pycache__, .pytest_cache, logs, .claude (локальные настройки), сам deploy.zip.
#
# Запуск: powershell -ExecutionPolicy Bypass -File make_deploy.ps1
# ВНИМАНИЕ: в архиве .env с токеном бота и база с телефонами — не пересылайте его в открытые чаты.

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$zip = Join-Path $root "deploy.zip"
$stage = Join-Path $env:TEMP ("wb-drr-deploy-" + [guid]::NewGuid().ToString("N"))

Write-Host "Папка проекта: $root"
New-Item -ItemType Directory -Force $stage | Out-Null
try {
    # 1. Копия проекта без лишнего. /XD исключает папки на любом уровне вложенности
    robocopy $root $stage /E /NFL /NDL /NJH /NJS /NP `
        /XD .venv .git __pycache__ .pytest_cache logs .claude `
        /XF deploy.zip *.pyc | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy завершился с ошибкой $LASTEXITCODE" }

    # 2. База: согласованный снимок через SQLite backup — бот может работать и писать в неё
    $db = Join-Path $root "data\bot.db"
    $py = Join-Path $root ".venv\Scripts\python.exe"
    if (Test-Path $db) {
        if (Test-Path $py) {
            $dst = Join-Path $stage "data\bot.db"
            & $py -c "import sqlite3,sys; s=sqlite3.connect(sys.argv[1]); d=sqlite3.connect(sys.argv[2]); s.backup(d); d.close(); s.close()" $db $dst
            if ($LASTEXITCODE -ne 0) { throw "не удалось сделать снимок базы" }
            Write-Host "База: согласованный снимок data/bot.db"
        } else {
            Write-Warning "Нет .venv — база скопирована как файл. Остановите бота перед сборкой, иначе снимок может быть неполным."
        }
    } else {
        Write-Warning "data/bot.db не найдена — архив будет без истории"
    }
    if (-not (Test-Path (Join-Path $stage ".env"))) {
        Write-Warning ".env не найден — на сервере его нужно будет создать вручную"
    }

    # 3. Архив с путями через «/» (Compress-Archive в PowerShell 5.1 пишет «\», и unzip на Linux ломает структуру)
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Add-Type -AssemblyName System.IO.Compression, System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::Open($zip, [System.IO.Compression.ZipArchiveMode]::Create)
    try {
        $base = (Resolve-Path $stage).Path.TrimEnd('\') + '\'
        $count = 0
        Get-ChildItem $stage -Recurse -File -Force | ForEach-Object {
            $name = $_.FullName.Substring($base.Length).Replace('\', '/')
            [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
                $archive, $_.FullName, $name, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
            $count++
        }
    } finally {
        $archive.Dispose()
    }

    $size = (Get-Item $zip).Length
    Write-Host ("Готово: {0}" -f $zip)
    Write-Host ("Файлов: {0}, размер: {1:N1} МБ" -f $count, ($size / 1MB))
} finally {
    Remove-Item $stage -Recurse -Force -ErrorAction SilentlyContinue
}
