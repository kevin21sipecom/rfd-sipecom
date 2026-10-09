"""Revisión final del Word: Microsoft Word actualiza el índice, exporta a PDF y cuenta páginas."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

# Se ejecuta en PowerShell porque Word sólo se automatiza por COM en Windows.
SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$docx = $args[0]; $pdf = $args[1]
$word = New-Object -ComObject Word.Application
$word.Visible = $false
$word.DisplayAlerts = 0
try {
  $doc = $word.Documents.Open($docx, $false, $false, $false)
  foreach ($toc in $doc.TablesOfContents) { $toc.Update() }
  $doc.Fields.Update() | Out-Null
  $doc.Repaginate()
  $paginas = $doc.ComputeStatistics(2)
  $vacias = @()
  for ($i = 1; $i -le $paginas; $i++) {
    $rango = $doc.GoTo(1, 1, $i)
    $fin = if ($i -lt $paginas) { $doc.GoTo(1, 1, $i + 1).Start } else { $doc.Content.End }
    $texto = $doc.Range($rango.Start, $fin).Text
    if ($texto.Trim().Length -eq 0) { $vacias += $i }
  }
  $doc.Save()
  $doc.ExportAsFixedFormat($pdf, 17)
  $doc.Close($false)
  @{ paginas = $paginas; vacias = $vacias } | ConvertTo-Json -Compress
} finally {
  $word.Quit()
}
"""


def word_disponible() -> bool:
    return sys.platform == "win32" and shutil.which("powershell") is not None


def revisar_con_word(docx: Path, tiempo: int = 300) -> dict[str, Any]:
    """Actualiza índice y campos, guarda, exporta PDF. Devuelve páginas y páginas vacías."""
    if not word_disponible():
        return {"ok": False, "motivo": "Microsoft Word no está disponible en este equipo."}
    docx = docx.resolve()
    pdf = docx.with_suffix(".pdf")
    with tempfile.TemporaryDirectory(prefix="rfd-word-") as temporal:
        script = Path(temporal) / "revisar.ps1"
        script.write_text(SCRIPT, encoding="utf-8-sig")
        try:
            p = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(script), str(docx), str(pdf)],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=tiempo, check=False,
            )
        except subprocess.TimeoutExpired:
            return {"ok": False, "motivo": f"Word no respondió en {tiempo} s."}
    if p.returncode != 0:
        return {"ok": False, "motivo": (p.stderr or p.stdout).strip()[-600:] or "Word no pudo procesar el documento."}
    try:
        datos = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"ok": False, "motivo": "Respuesta de Word no reconocida."}
    vacias = datos.get("vacias") or []
    return {"ok": True, "paginas": datos.get("paginas"), "vacias": vacias if isinstance(vacias, list) else [vacias],
            "pdf": str(pdf) if pdf.is_file() else None}
