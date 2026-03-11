"""
Phase 4c: Auto-Script Generation

Generates executable scripts to fix detected system issues.
Supports PowerShell (Windows) and Bash (Linux/Mac).
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ScriptType(Enum):
    """Script types."""

    POWERSHELL = "powershell"
    BASH = "bash"


class ScriptGenerator:
    """
    Generates executable scripts to fix system issues.
    Creates scripts for:
    - Killing high-memory processes
    - Clearing disk space
    - Optimizing memory
    - Cleaning cache/temp files
    - Restarting services
    - Updating system
    """

    def __init__(self, script_type: ScriptType = ScriptType.POWERSHELL):
        self.script_type = script_type

    def generate_kill_process_script(
        self, process_name: str, pid: Optional[int] = None
    ) -> str:
        """Generate script to kill a high-memory process."""
        if self.script_type == ScriptType.POWERSHELL:
            if pid:
                return f"""
# Kill process {process_name} (PID: {pid})
Write-Host "Stopping {process_name} (PID: {pid})..."
Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue
Write-Host "Process stopped."
"""
            else:
                return f"""
# Kill all instances of {process_name}
Write-Host "Stopping {process_name}..."
Get-Process -Name {process_name.split('.')[0]} -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "All instances stopped."
"""
        else:  # BASH
            if pid:
                return f"""
#!/bin/bash
# Kill process {process_name} (PID: {pid})
echo "Stopping {process_name} (PID: {pid})..."
kill -9 {pid} 2>/dev/null || true
echo "Process stopped."
"""
            else:
                return f"""
#!/bin/bash
# Kill all instances of {process_name}
echo "Stopping {process_name}..."
pkill -9 {process_name.split('.')[0]} 2>/dev/null || true
echo "All instances stopped."
"""

    def generate_clear_disk_space_script(self, min_gb: int = 5) -> str:
        """Generate script to clear disk space."""
        if self.script_type == ScriptType.POWERSHELL:
            return f"""
# Clear disk space
Write-Host "Cleaning up disk space..." -ForegroundColor Cyan

# Empty Recycle Bin
Write-Host "Emptying Recycle Bin..."
$shell = New-Object -ComObject Shell.Application
$shell.Namespace(0x0a).Self.InvokeVerb('Empty')

# Clear temp folders
Write-Host "Clearing temp folders..."
Remove-Item -Path "$env:TEMP\\*" -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -Path "$env:WINDIR\\Temp\\*" -Recurse -Force -ErrorAction SilentlyContinue

# Clear Windows Update cache (requires admin)
Write-Host "Clearing Windows Update cache..."
Remove-Item -Path "C:\\Windows\\SoftwareDistribution\\Download\\*" -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Disk cleanup completed. Free up at least {min_gb}GB." -ForegroundColor Green
"""
        else:  # BASH
            return f"""
#!/bin/bash
# Clear disk space
echo "Cleaning up disk space..."

# Clear package manager cache
echo "Clearing package manager cache..."
sudo apt-get clean 2>/dev/null || true
sudo apt-get autoclean 2>/dev/null || true
sudo apt-get autoremove -y 2>/dev/null || true

# Clear old logs
echo "Clearing old logs..."
sudo find /var/log -type f -name "*.gz" -delete 2>/dev/null || true
sudo find /var/log -type f -name "*.1" -delete 2>/dev/null || true

# Clear temp
echo "Clearing temp directories..."
sudo rm -rf /tmp/* 2>/dev/null || true
sudo rm -rf /var/tmp/* 2>/dev/null || true

echo "Disk cleanup completed. Free up at least {min_gb}GB."
"""

    def generate_restart_service_script(self, service_name: str) -> str:
        """Generate script to restart a service."""
        if self.script_type == ScriptType.POWERSHELL:
            return f"""
# Restart {service_name} service
Write-Host "Restarting {service_name} service..." -ForegroundColor Cyan

try {{
    Restart-Service -Name {service_name} -Force
    Write-Host "{service_name} service restarted successfully." -ForegroundColor Green
}} catch {{
    Write-Host "Failed to restart {service_name}: $_" -ForegroundColor Red
    exit 1
}}
"""
        else:  # BASH
            return f"""
#!/bin/bash
# Restart {service_name} service
echo "Restarting {service_name} service..."

if sudo systemctl restart {service_name} 2>/dev/null; then
    echo "{service_name} service restarted successfully."
else
    echo "Failed to restart {service_name}"
    exit 1
fi
"""

    def generate_memory_cleanup_script(self) -> str:
        """Generate script to optimize memory usage."""
        if self.script_type == ScriptType.POWERSHELL:
            return """
# Memory cleanup script
Write-Host "Optimizing memory..." -ForegroundColor Cyan

# Force garbage collection
[System.GC]::Collect()
[System.GC]::WaitForPendingFinalizers()

# Clear Windows prefetch cache
Write-Host "Clearing Windows prefetch cache..."
Remove-Item -Path "C:\\Windows\\Prefetch\\*" -Force -ErrorAction SilentlyContinue

# Empty clipboard
Write-Host "Clearing clipboard..."
$null | Set-Clipboard

Write-Host "Memory optimization completed." -ForegroundColor Green
"""
        else:  # BASH
            return """
#!/bin/bash
# Memory cleanup script
echo "Optimizing memory..."

# Sync and clear caches (Linux)
if [ -f /proc/sys/vm/drop_caches ]; then
    echo "Dropping caches..."
    sudo sync
    sudo sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || true
fi

echo "Memory optimization completed."
"""

    def generate_check_disk_health_script(self) -> str:
        """Generate script to check disk health."""
        if self.script_type == ScriptType.POWERSHELL:
            return """
# Disk health check
Write-Host "Checking disk health..." -ForegroundColor Cyan

# Get disk usage
Get-Volume | Select-Object DriveLetter, SizeRemaining, Size | ForEach-Object {
    if ($_.DriveLetter) {
        $percent = [math]::Round((($.Size - $_.SizeRemaining) / $.Size) * 100, 2)
        Write-Host "$($_.DriveLetter): $percent% used (" + [math]::Round($_.SizeRemaining/1GB) + "GB free)"
    }
}

# Check for disk errors (Windows)
Write-Host "Running disk check..."
chkdsk C: /scan /SpotFix /perf 2>/dev/null

Write-Host "Disk health check completed." -ForegroundColor Green
"""
        else:  # BASH
            return """
#!/bin/bash
# Disk health check
echo "Checking disk health..."

# Get disk usage
df -h | awk 'NR>1 {print $1 ": " $5 " used (" $4 " free)"}'

# Check for disk errors (Linux SMART)
for disk in /dev/sda /dev/sdb /dev/nvme0n1; do
    if [ -e $disk ]; then
        echo "Checking SMART status for $disk..."
        sudo smartctl -H $disk 2>/dev/null || echo "smartctl not available"
    fi
done

echo "Disk health check completed."
"""

    def generate_fix_script(self, issue_type: str, **kwargs) -> Dict[str, Any]:
        """
        Generate an appropriate fix script based on issue type.

        Args:
            issue_type: Type of issue ('cpu_high', 'memory_high', 'disk_full', etc.)
            **kwargs: Additional parameters for the script

        Returns:
            Dict with script content, description, and execution info
        """
        scripts = {}

        if issue_type == "cpu_high":
            scripts["cpu_high"] = self._generate_cpu_fix(
                process_name=kwargs.get("process_name")
            )
        elif issue_type == "memory_high":
            scripts["memory_high"] = self.generate_memory_cleanup_script()
        elif issue_type == "disk_full":
            scripts["disk_full"] = self.generate_clear_disk_space_script(
                min_gb=kwargs.get("min_gb", 5)
            )
        elif issue_type == "process_memory_high":
            scripts["process_memory_high"] = self.generate_kill_process_script(
                process_name=kwargs.get("process_name", "process"),
                pid=kwargs.get("pid"),
            )
        elif issue_type == "service_restart":
            scripts["service_restart"] = self.generate_restart_service_script(
                service_name=kwargs.get("service_name", "service")
            )
        elif issue_type == "disk_health":
            scripts["disk_health"] = self.generate_check_disk_health_script()
        else:
            return {"status": "error", "message": f"Unknown issue type: {issue_type}"}

        script_content = scripts[issue_type]
        extension = ".ps1" if self.script_type == ScriptType.POWERSHELL else ".sh"

        return {
            "status": "success",
            "issue_type": issue_type,
            "script_type": self.script_type.value,
            "script": script_content,
            "filename": f"fix_{issue_type}{extension}",
            "description": self._get_script_description(issue_type),
            "run_command": self._get_run_command(extension),
            "requires_admin": self._requires_admin(issue_type),
        }

    def _generate_cpu_fix(self, process_name: Optional[str] = None, **kwargs) -> str:
        """Generate CPU high usage fix script."""
        if self.script_type == ScriptType.POWERSHELL:
            if process_name:
                return f"""
# Fix high CPU usage - kill {process_name}
Write-Host "Fixing high CPU usage..." -ForegroundColor Cyan
{self.generate_kill_process_script(process_name)}
Write-Host "CPU usage should normalize in few seconds." -ForegroundColor Green
"""
            else:
                return """
# Fix high CPU usage
Write-Host "Fixing high CPU usage..." -ForegroundColor Cyan
Write-Host "Finding CPU-consuming processes..."
Get-Process | Sort-Object CPU -Descending | Select-Object -First 5 | ForEach-Object {{
    Write-Host "Process: $($_.Name) - CPU: $($_.CPU)s"
}}
Write-Host "Please identify and kill the problematic process."
"""
        else:
            if process_name:
                return f"""
#!/bin/bash
# Fix high CPU usage - kill {process_name}
echo "Fixing high CPU usage..."
{self.generate_kill_process_script(process_name)}
echo "CPU usage should normalize in few seconds."
"""
            else:
                return """
#!/bin/bash
# Find CPU-consuming processes
echo "Fixing high CPU usage..."
echo "Finding CPU-consuming processes..."
ps aux --sort=-%cpu | head -6
echo "Please identify and kill the problematic process: kill -9 <PID>"
"""

    def _get_script_description(self, issue_type: str) -> str:
        """Get human-readable script description."""
        descriptions = {
            "cpu_high": "Identifies and stops high CPU processes",
            "memory_high": "Clears memory caches and optimizes RAM usage",
            "disk_full": "Removes temporary files and unused data",
            "process_memory_high": "Kills a specific high-memory process",
            "service_restart": "Restarts a system service",
            "disk_health": "Checks disk space and health status",
        }
        return descriptions.get(issue_type, "Fix script for detected issue")

    def _get_run_command(self, extension: str) -> str:
        """Get command to run the script."""
        if extension == ".ps1":
            return "Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process; .\\<filename>"
        else:
            return "bash <filename>"

    def _requires_admin(self, issue_type: str) -> bool:
        """Check if script requires admin privileges."""
        admin_required = ["disk_full", "memory_high", "disk_health", "service_restart"]
        return issue_type in admin_required
