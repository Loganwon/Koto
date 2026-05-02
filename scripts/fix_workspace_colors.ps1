$file = "c:\Users\12524\Desktop\Koto\web\static\css\workspace.css"
$css = Get-Content $file -Raw

# rgba(255,255,255,...) -> CSS custom properties
$css = $css -replace 'rgba\(255,255,255,0\.025\)', 'var(--hover)'
$css = $css -replace 'rgba\(255,255,255,0\.03\)', 'var(--hover)'
$css = $css -replace 'rgba\(255,255,255,0\.04\)', 'var(--hover)'
$css = $css -replace 'rgba\(255,255,255,0\.05\)', 'var(--hover)'
$css = $css -replace 'rgba\(255,255,255,0\.06\)', 'var(--border)'
$css = $css -replace 'rgba\(255,255,255,0\.07\)', 'var(--border)'
$css = $css -replace 'rgba\(255,255,255,\.07\)', 'var(--border)'
$css = $css -replace 'rgba\(255,255,255,0\.08\)', 'var(--surface-hover)'
$css = $css -replace 'rgba\(255,255,255,\.08\)', 'var(--surface-hover)'
$css = $css -replace 'rgba\(255,255,255,0\.09\)', 'var(--border)'
$css = $css -replace 'rgba\(255,255,255,0\.10\)', 'var(--surface-hover)'
$css = $css -replace 'rgba\(255,255,255,0\.1\)', 'var(--scrollbar)'
$css = $css -replace 'rgba\(255,255,255,0\.11\)', 'var(--surface-hover)'
$css = $css -replace 'rgba\(255,255,255,0\.12\)', 'var(--border)'
$css = $css -replace 'rgba\(255,255,255,0\.15\)', 'var(--border)'
$css = $css -replace 'rgba\(255,255,255,0\.16\)', 'var(--surface-hover)'
$css = $css -replace 'rgba\(255,255,255,0\.18\)', 'var(--scrollbar-hover)'

# rgba(79,126,255,...) -> accent CSS vars
$css = $css -replace 'rgba\(79,126,255,0\.04\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.05\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.06\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.07\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.08\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.09\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.10\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.12\)', 'var(--accent-subtle)'
$css = $css -replace 'rgba\(79,126,255,0\.15\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.18\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.20\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.2\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.22\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.25\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.30\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.3\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.35\)', 'var(--accent-medium)'
$css = $css -replace 'rgba\(79,126,255,0\.45\)', 'var(--accent)'
$css = $css -replace 'rgba\(79,126,255,0\.5\)', 'var(--accent)'

# #4f7eff hardcoded hex
$css = $css -replace '#4f7eff22', 'var(--accent-subtle)'
$css = $css -replace '#4f7eff', 'var(--accent)'

# Fallback accent values - clean up
$css = $css -replace 'var\(--accent, #4f7eff\)', 'var(--accent)'

# var(--input-bg, rgba(...)) -> var(--input-bg) 
$css = $css -replace [regex]::Escape('var(--input-bg, rgba(255,255,255,0.06))'), 'var(--input-bg)'
$css = $css -replace [regex]::Escape('var(--input-bg, rgba(255,255,255,0.04))'), 'var(--input-bg)'

Set-Content $file $css -Encoding UTF8 -NoNewline
$remaining = (Select-String -InputObject $css -Pattern 'rgba\(255,255,255,0\.' -AllMatches).Matches.Count
$remaining79 = (Select-String -InputObject $css -Pattern 'rgba\(79,126,255' -AllMatches).Matches.Count
$remaining4f = (Select-String -InputObject $css -Pattern '#4f7eff' -AllMatches).Matches.Count
Write-Host "Done! Remaining rgba(255,...): $remaining | rgba(79,126,...): $remaining79 | #4f7eff: $remaining4f"
Write-Host "File size: $((Get-Item $file).Length) bytes"
