# Revisión con administrador del asistente (opcional). La corre una tarea de Windows cada domingo 16:30.
# Solo LEE: estado de la imagen de Windows (DISM CheckHealth), desgaste/temperatura/errores de los discos e
# intentos fallidos de inicio de sesión. Escribe <pesado>\pc\revision_admin.json (config\rutas.json) para el asistente.
$ErrorActionPreference = 'SilentlyContinue'
$raiz = Split-Path (Split-Path (Split-Path $PSCommandPath))      # carpeta del proyecto
$pesado = (Get-Content (Join-Path $raiz 'config\rutas.json') -Raw | ConvertFrom-Json).pesado
if (-not $pesado) { $pesado = Join-Path $raiz 'datos_pesados' }
$carpeta = Join-Path $pesado 'pc'
New-Item -ItemType Directory -Force $carpeta | Out-Null
$imagen = (Repair-WindowsImage -Online -CheckHealth).ImageHealthState
$discos = Get-PhysicalDisk | ForEach-Object {
  $c = $_ | Get-StorageReliabilityCounter
  [pscustomobject]@{ FriendlyName = $_.FriendlyName; Wear = $c.Wear; Temperature = $c.Temperature;
                     ReadErrorsUncorrected = $c.ReadErrorsUncorrected }
}
$eventos = @(Get-WinEvent -FilterHashtable @{LogName='Security'; Id=4625; StartTime=(Get-Date).AddDays(-7)} | ForEach-Object {
  $x = [xml]$_.ToXml(); $d = @{}; $x.Event.EventData.Data | ForEach-Object { $d[$_.Name] = $_.'#text' }
  [pscustomobject]@{ Tipo = "$($d.LogonType)"; IP = "$($d.IpAddress)" } })
$privada = '^(127\.|::1$|-$|$|192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.|fe80)'
$externos = @($eventos | Where-Object { $_.Tipo -eq '10' -or $_.IP -notmatch $privada }).Count
$mias = @(Get-NetIPAddress | ForEach-Object { $_.IPAddress })        # las IP de esta misma PC no cuentan
$propios = @($eventos | Where-Object { $mias -contains $_.IP }).Count
$locales = @($eventos | Where-Object { $mias -notcontains $_.IP } | Where-Object { $_.IP -match '^(192\.168\.|10\.|172\.(1[6-9]|2\d|3[01])\.)' } |
  Group-Object IP | ForEach-Object { [pscustomobject]@{ ip = $_.Name; veces = $_.Count } })
[pscustomobject]@{ imagen = "$imagen"; discos = @($discos); inicios_fallidos = $eventos.Count; externos = $externos;
                   locales = $locales; propios = $propios; fecha = (Get-Date).ToString('s') } | ConvertTo-Json -Depth 4 |
  Set-Content -Path (Join-Path $carpeta 'revision_admin.json') -Encoding UTF8
