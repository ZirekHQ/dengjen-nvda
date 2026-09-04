#!/usr/bin/env pwsh
$ErrorActionPreference = 'Stop'

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"

# main is protected (PRs + status checks required), so remember where we
# started to detect new commits and publish them via a branch + PR instead
# of pushing directly.
$baseBranch = git symbolic-ref --short HEAD
$baseCommit = git rev-parse HEAD

$rawAddonId = $env:ADDON_ID
if ([string]::IsNullOrWhiteSpace($rawAddonId)) {
    Write-Error "Failed to get addon ID."
    exit 1
}
$addonId = $rawAddonId.Trim()

$rawMinPercentageTranslated = $env:MIN_PERCENTAGE_TRANSLATED
$minPercentageTranslated = 0.0
if (-not [double]::TryParse($rawMinPercentageTranslated, [ref]$minPercentageTranslated) -or
    $minPercentageTranslated -lt 0 -or $minPercentageTranslated -gt 100) {
    Write-Error "MIN_PERCENTAGE_TRANSLATED must be a number between 0 and 100 (got '$rawMinPercentageTranslated')."
    exit 1
}

# --- STEP 1: PREPARATION AND SOURCE UPDATE ---

$xliffFile = "./$addonId.xliff"
$mdFile = "./readme.md"

if (Test-Path $mdFile) {
    if (Test-Path $xliffFile) {
        $tempXliff = [System.IO.Path]::GetTempFileName()
        try {
            Copy-Item "$addonId.xliff" $tempXliff -Force
            Write-Host "DEBUG: Updating XLIFF source based on readme.md..."
            ./l10nUtil.exe md2xliff $mdFile $xliffFile -o $tempXliff
        }
        finally {
            if (Test-Path $tempXliff) {
                Remove-Item $tempXliff -Force
            }
        }
    }
    else {
        Write-Host "DEBUG: XLIFF template not found. Creating new one from readme.md..."
        ./l10nUtil.exe md2xliff $mdFile $xliffFile
    }
}

scons pot
$potFile = "$addonId.pot"

# --- STEP 2: UPLOAD SOURCES TO CROWDIN ---

if (Test-Path $potFile) {
    Write-Host "DEBUG: Uploading updated POT source to Crowdin..."
    ./l10nUtil.exe uploadSourceFile "$potFile" -c $env:L10N_UTIL_CONFIG
}

if (Test-Path $xliffFile) {
    Write-Host "DEBUG: Uploading updated XLIFF source to Crowdin..."
    ./l10nUtil.exe uploadSourceFile "$xliffFile" -c $env:L10N_UTIL_CONFIG

    git add "$xliffFile"
    git diff --staged --quiet

    if ($LASTEXITCODE -ne 0) {
        git commit -m "Update $xliffFile for $addonId"
    }
}

# --- STEP 3: EXPORT AND PROCESS TRANSLATIONS ---

Write-Host "DEBUG: Exporting translations from Crowdin..."
./l10nUtil.exe exportTranslations -o _addonL10n -c $env:L10N_UTIL_CONFIG

New-Item -ItemType Directory -Force -Path addon/locale | Out-Null
New-Item -ItemType Directory -Force -Path addon/doc | Out-Null

$languageMappings = Get-Content -Raw ".github/scripts/languageMappings.json" | ConvertFrom-Json

foreach ($dir in Get-ChildItem -Path "_addonL10n/$addonId" -Directory) {

    $langCode = $dir.Name

    if ($langCode -eq "en") {
        continue
    }

    $crowdinLang = $null

    if ($languageMappings.PSObject.Properties.Name -contains $langCode) {
        $crowdinLang = $languageMappings."$langCode"
    }

    if (-not $crowdinLang) {
        $crowdinLang = $langCode.Replace('_', '-')
    }

    Write-Host "--- Processing Language: $langCode (Crowdin: $crowdinLang) ---" -ForegroundColor Cyan

    $remoteXliff = Join-Path $dir.FullName "$addonId.xliff"
    $remotePo = Join-Path $dir.FullName "$addonId.po"

    $localMdDir = "addon/doc/$langCode"
    $localMd = "$localMdDir/readme.md"

    $localPoPath = "addon/locale/$langCode/LC_MESSAGES/nvda.po"

    # --- 3.1 PO FILE PROCESSING ---
    $poImported = $false
    $scorePo = 0.0
    $threshold = $minPercentageTranslated

    if (Test-Path $remotePo) {

        Write-Host "DEBUG: Evaluating Remote PO score..."

        $res = python .github/scripts/checkTranslation.py "$addonId.po" $crowdinLang

        $scorePo = [double](
            ($res | Select-String "poScore=").ToString().Split("=")[1]
        )

        Write-Host "DEBUG: PO Score -> $scorePo"

        if ($scorePo -ge $threshold) {

            Write-Host "SUCCESS: Remote PO is above threshold. Importing to $localPoPath"

            New-Item -ItemType Directory -Force -Path (Split-Path $localPoPath) | Out-Null

            Move-Item $remotePo $localPoPath -Force

            $poImported = $true
        }
        else {

            Write-Host "WARNING: Remote PO score is below threshold ($threshold)."
        }
    }

    if (-not $poImported -and (Test-Path $localPoPath)) {

        Write-Host "ACTION: Uploading local legacy PO to Crowdin ($crowdinLang) as fallback."

        ./l10nUtil.exe uploadTranslationFile $crowdinLang "$addonId.po" $localPoPath -c $env:L10N_UTIL_CONFIG
    }

    # --- 3.2 DOCUMENTATION PROCESSING (XLIFF ONLY) ---

    $scoreXliff = 0.0

    if (Test-Path $remoteXliff) {

        Write-Host "DEBUG: Evaluating Remote XLIFF score..."

        $res = python .github/scripts/checkTranslation.py "$addonId.xliff" $crowdinLang

        $scoreXliff = [double](
            ($res | Select-String "xliffScore=").ToString().Split("=")[1]
        )
    }
    else {
        Write-Host "DEBUG: No remote XLIFF file found for this language."
    }

    Write-Host "DEBUG: XLIFF Score -> $scoreXliff"

    $threshold = $minPercentageTranslated
    $docImported = $false

    if ($scoreXliff -ge $threshold) {

        if (!(Test-Path $localMdDir)) {
            New-Item -ItemType Directory -Force -Path $localMdDir | Out-Null
        }

        Write-Host "SUCCESS: Importing documentation from XLIFF ($langCode)..."

        ./l10nUtil.exe xliff2md $remoteXliff $localMd

        $docImported = $true
    }
    else {

        Write-Host "WARNING: Remote XLIFF score is below threshold ($threshold)."
    }

    # No Markdown fallback upload anymore.
    # XLIFF is now the single translation source in Crowdin.
}

# --- STEP 4: COMMIT UPDATED TRANSLATIONS ---

git add addon/locale addon/doc

git diff --staged --quiet

if ($LASTEXITCODE -ne 0) {

    git commit -m "Update translations for $addonId from Crowdin (Automatic Sync)"

    Write-Host "SUCCESS: Translations committed."
}
else {

    Write-Host "DEBUG: No changes in translations to commit."
}

# --- STEP 5: PUBLISH NEW COMMITS VIA PULL REQUEST ---
# $baseBranch (e.g. main) requires PRs + passing status checks, so new
# commits are pushed to a dedicated branch and opened/updated as a PR
# instead of being pushed directly.

$repository = $env:GITHUB_REPOSITORY
$headCommit = git rev-parse HEAD

if ($headCommit -eq $baseCommit) {

    Write-Host "DEBUG: No new commits to publish."
}
elseif ([string]::IsNullOrWhiteSpace($env:PR_SYNC_TOKEN)) {

    Write-Host "WARNING: PR_SYNC_TOKEN is not set; skipping publish. New commits exist only in this run's checkout."
}
else {

    $env:GH_TOKEN = $env:PR_SYNC_TOKEN
    $l10nBranch = "l10n/crowdin-sync"

    git branch -f $l10nBranch HEAD
    git push --force origin "${l10nBranch}:${l10nBranch}"

    $existingPr = gh pr list --repo $repository --base $baseBranch --head $l10nBranch --state open --json number --jq ".[0].number"

    if ([string]::IsNullOrWhiteSpace($existingPr)) {

        gh pr create --repo $repository --base $baseBranch --head $l10nBranch `
            --title "l10n: sync translations from Crowdin" `
            --body "Automated translation sync from Crowdin. Review before merging."

        Write-Host "SUCCESS: Opened a new translation sync PR."
    }
    else {

        Write-Host "SUCCESS: Updated existing translation sync PR #$existingPr."
    }
}
