<#
Keeps DisplayXR's embedded 3D exactly on ParaView's render view.

Publishes the render view's rect (physical client pixels of ParaView's main window) as the
window property DXR_HostedViewRect, which the dev runtime (DisplayXR #2332) re-reads every
250 ms, and follows layout changes (docks, splitters, window moves, maximize). With several
views it uses the largest one. Never takes focus or sends keys: UI Automation reads only.
Exits when ParaView exits.
#>
param([int]$ProcessId = 0)

Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class PvWin {
	[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
	[DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr h, ref POINT p);
	[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern bool SetProp(IntPtr h, string name, IntPtr v);
	[DllImport("user32.dll", CharSet = CharSet.Unicode)] public static extern IntPtr RemoveProp(IntPtr h, string name);
	[DllImport("user32.dll")] public static extern bool IsWindow(IntPtr h);
	public struct POINT { public int X, Y; }
}
"@
# Physical pixels: UIA and the runtime both use them once this process is DPI aware.
[PvWin]::SetProcessDPIAware() | Out-Null

$A = [System.Windows.Automation.AutomationElement]
$Scope = [System.Windows.Automation.TreeScope]
$Prop = "DXR_HostedViewRect"

function Find-ParaView {
	if ($ProcessId) { return Get-Process -Id $ProcessId -ErrorAction SilentlyContinue }
	Get-Process paraview -ErrorAction SilentlyContinue | Where-Object MainWindowHandle -ne 0 | Select-Object -First 1
}

# The render views: Qt names their widgets QVTKOpenGLNativeWidget (AutomationId suffix).
function Find-Views($win) {
	$groups = $win.FindAll($Scope::Descendants,
		(New-Object System.Windows.Automation.PropertyCondition($A::ControlTypeProperty, [System.Windows.Automation.ControlType]::Group)))
	@($groups | Where-Object { $_.Current.AutomationId -like "*.QVTKOpenGLNativeWidget" })
}

$hwnd = [IntPtr]::Zero
$views = @()
$last = 0
$lastScan = [DateTime]::MinValue
while ($true) {
	$p = Find-ParaView
	if (-not $p) { if ($hwnd -ne [IntPtr]::Zero) { break } ; Start-Sleep -Milliseconds 500; continue }
	if ($p.MainWindowHandle -eq 0) { Start-Sleep -Milliseconds 500; continue }
	if ($p.MainWindowHandle -ne $hwnd) { $hwnd = $p.MainWindowHandle; $views = @(); $last = 0 }
	try {
		# Re-scan the tree every 3 s (views get split, closed, re-docked); read rects every 200 ms.
		if ($views.Count -eq 0 -or ((Get-Date) - $lastScan).TotalSeconds -gt 3) {
			$views = Find-Views ($A::FromHandle($hwnd))
			$lastScan = Get-Date
		}
		$best = $null; $area = 0
		foreach ($v in $views) {
			$r = $v.Current.BoundingRectangle
			if (-not $r.IsEmpty -and $r.Width * $r.Height -gt $area) { $best = $r; $area = $r.Width * $r.Height }
		}
		$packed = 0
		if ($best) {
			$pt = New-Object PvWin+POINT
			$pt.X = [int]$best.X; $pt.Y = [int]$best.Y
			[PvWin]::ScreenToClient($hwnd, [ref]$pt) | Out-Null
			if ($pt.X -ge 0 -and $pt.Y -ge 0) {
				$packed = [int64]$pt.X -bor ([int64]$pt.Y -shl 16) -bor ([int64][int]$best.Width -shl 32) -bor ([int64][int]$best.Height -shl 48)
			}
		}
		if ($packed -ne $last) {
			if ($packed -ne 0) { [PvWin]::SetProp($hwnd, $Prop, [IntPtr]$packed) | Out-Null }
			else { [PvWin]::RemoveProp($hwnd, $Prop) | Out-Null }
			$last = $packed
		}
	} catch { $views = @() }
	Start-Sleep -Milliseconds 200
}
