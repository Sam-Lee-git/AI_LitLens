param(
    [Parameter(Mandatory=$true)][string]$Source,
    [Parameter(Mandatory=$true)][string]$Output
)
$ErrorActionPreference = 'Stop'
$sourcePath = (Resolve-Path -LiteralPath $Source).Path
$outputPath = [IO.Path]::GetFullPath($Output)
if ([IO.Path]::GetExtension($sourcePath) -ne '.pptx') { throw 'Only PPTX is supported.' }
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$snapshotPath = Join-Path $outputPath 'source-snapshot.pptx'
if ($sourcePath -eq $snapshotPath) { throw 'Source must not be the snapshot destination.' }
Copy-Item -LiteralPath $sourcePath -Destination $snapshotPath -Force
$imagePath = Join-Path $outputPath 'slides'
New-Item -ItemType Directory -Force -Path $imagePath | Out-Null
$powerpoint = $null
$presentation = $null
$wasEmpty = $false
try {
    $powerpoint = New-Object -ComObject PowerPoint.Application
    $wasEmpty = $powerpoint.Presentations.Count -eq 0
    # Open our own read-only snapshot without a window. Never save or close the user's deck.
    $presentation = $powerpoint.Presentations.Open($snapshotPath, -1, 0, 0)
    $slides = @()
    $width = 2560
    $height = [int][Math]::Round($width * $presentation.PageSetup.SlideHeight / $presentation.PageSetup.SlideWidth)
    for ($i = 1; $i -le $presentation.Slides.Count; $i++) {
        $slide = $presentation.Slides.Item($i)
        $filename = 'slide-{0:D2}.png' -f $i
        $slide.Export((Join-Path $imagePath $filename), 'PNG', $width, $height)
        $slides += @{number=$i; image=$filename; hidden=($slide.SlideShowTransition.Hidden -eq -1)}
        Write-Output ('Exported slide {0}/{1}' -f $i, $presentation.Slides.Count)
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($slide)
    }
    $manifest = @{
        sourceName=[IO.Path]::GetFileName($sourcePath)
        sourceSha256=(Get-FileHash -LiteralPath $snapshotPath -Algorithm SHA256).Hash.ToLowerInvariant()
        slideCount=$slides.Count
        width=$width
        height=$height
        renderer='Microsoft PowerPoint read-only snapshot export'
        slides=$slides
    }
    $json = $manifest | ConvertTo-Json -Depth 6
    [IO.File]::WriteAllText((Join-Path $outputPath 'deck.json'), $json, [Text.UTF8Encoding]::new($false))
} finally {
    if ($null -ne $presentation) {
        $presentation.Close()
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation)
    }
    if ($null -ne $powerpoint) {
        if ($wasEmpty -and $powerpoint.Presentations.Count -eq 0) { $powerpoint.Quit() }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerpoint)
    }
}
