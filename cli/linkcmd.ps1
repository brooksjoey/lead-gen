function linkcmd {
  [CmdletBinding()]
  param([Parameter(Mandatory=$true)][string]$CommandKey)
  & "\.venv\Scripts\python.exe" "\link_records.py" $CommandKey
}
