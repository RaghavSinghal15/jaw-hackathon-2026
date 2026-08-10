# Full pipeline: documents -> observations -> tables -> answers.
# Usage:  .\run_all.ps1                     (corpus at ..\BITS-Hackathon-Dataset)
#         .\run_all.ps1 C:\path\to\corpus
param([string]$Corpus = "..\BITS-Hackathon-Dataset")

$ErrorActionPreference = "Stop"

Write-Host "`n=== extracting ===" -ForegroundColor Cyan
foreach ($m in "company_cert", "client_cert", "reference_letter", "portfolio", "people",
                "financial", "transactions", "tender") {
    Write-Host "--- $m" -ForegroundColor DarkGray
    python src\$m.py $Corpus
}

Write-Host "`n=== merging into tables ===" -ForegroundColor Cyan
python src\merge.py

Write-Host "`n=== scoring against the sample questions ===" -ForegroundColor Cyan
python src\shapes.py $Corpus
