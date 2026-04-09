"""
Varredura de PDFs para identificar documentos escaneados (sem camada de texto).

Percorre todos os PDFs em data/pdfs/{2016,2021,2022}/, tenta extrair texto
com PyMuPDF e classifica cada arquivo como "tem_texto" ou "escaneado".

Saída: data/scan_report.json
Progresso: data/scan_progress.txt (permite pausar e continuar)

Dependências: pymupdf
    pip install pymupdf

Execução:
    python data/scan_pdfs.py
"""

import json
import sys
import time
from pathlib import Path

import fitz  # PyMuPDF

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDFS_DIR = DATA_DIR / "pdfs"
ANOS = ("2016", "2021", "2022")

REPORT_FILE   = DATA_DIR / "scan_report.json"
PROGRESS_FILE = DATA_DIR / "scan_progress.txt"

MIN_CHARS = 50          # limiar para considerar que há texto extraível
PROGRESSO_INTERVALO = 500  # exibir progresso a cada N arquivos


# ---------------------------------------------------------------------------
# Controle de progresso
# ---------------------------------------------------------------------------

def carregar_progresso() -> set[str]:
    """Retorna conjunto de caminhos (relativos à ROOT) já processados."""
    if not PROGRESS_FILE.exists():
        return set()
    with open(PROGRESS_FILE, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def registrar_progresso(caminho_rel: str) -> None:
    with open(PROGRESS_FILE, "a", encoding="utf-8") as f:
        f.write(caminho_rel + "\n")


# ---------------------------------------------------------------------------
# Classificação de um PDF
# ---------------------------------------------------------------------------

def classificar_pdf(caminho: Path) -> str:
    """
    Retorna "tem_texto" se o PDF contém mais de MIN_CHARS caracteres extraíveis,
    ou "escaneado" caso contrário.
    """
    try:
        doc = fitz.open(str(caminho))
        total_chars = 0
        for page in doc:
            total_chars += len(page.get_text())
            if total_chars > MIN_CHARS:
                doc.close()
                return "tem_texto"
        doc.close()
    except Exception:
        pass  # arquivo corrompido → trata como escaneado
    return "escaneado"


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 65)
    print("  Varredura de PDFs — identificação de documentos escaneados")
    print("=" * 65)

    # Coleta todos os PDFs nas 3 pastas de anos
    todos_pdfs: list[Path] = []
    for ano in ANOS:
        pasta = PDFS_DIR / ano
        if pasta.exists():
            todos_pdfs.extend(sorted(pasta.glob("*.pdf")))

    total = len(todos_pdfs)
    print(f"\nTotal de PDFs encontrados: {total:,}")

    # Carrega progresso anterior
    ja_processados = carregar_progresso()
    pendentes = [p for p in todos_pdfs if str(p.relative_to(ROOT)).replace("\\", "/") not in ja_processados]
    print(f"Já processados anteriormente: {len(ja_processados):,}")
    print(f"Pendentes nesta execução:     {len(pendentes):,}")

    # Carrega resultados parciais se existirem
    tem_texto: list[str] = []
    escaneados: list[str] = []
    por_ano: dict[str, dict[str, int]] = {
        ano: {"tem_texto": 0, "escaneados": 0} for ano in ANOS
    }

    if REPORT_FILE.exists() and ja_processados:
        with open(REPORT_FILE, encoding="utf-8") as f:
            dados = json.load(f)
        tem_texto  = dados.get("tem_texto", [])
        escaneados = dados.get("escaneados", [])
        resumo = dados.get("resumo", {})
        for ano in ANOS:
            por_ano[ano] = resumo.get("por_ano", {}).get(ano, {"tem_texto": 0, "escaneados": 0})

    if not pendentes:
        print("\nTodos os PDFs já foram processados.")
    else:
        print(f"\nIniciando varredura...\n")

    inicio = time.time()
    processados_agora = 0

    for i, caminho in enumerate(pendentes, start=1):
        ano = caminho.parent.name
        caminho_rel = str(caminho.relative_to(ROOT)).replace("\\", "/")

        resultado = classificar_pdf(caminho)

        if resultado == "tem_texto":
            tem_texto.append(caminho_rel)
            por_ano[ano]["tem_texto"] += 1
        else:
            escaneados.append(caminho_rel)
            por_ano[ano]["escaneados"] += 1

        registrar_progresso(caminho_rel)
        processados_agora += 1

        # Progresso a cada PROGRESSO_INTERVALO arquivos
        if processados_agora % PROGRESSO_INTERVALO == 0:
            elapsed = time.time() - inicio
            velocidade = processados_agora / elapsed if elapsed > 0 else 0
            restantes = len(pendentes) - processados_agora
            eta = restantes / velocidade if velocidade > 0 else 0
            total_proc = len(ja_processados) + processados_agora
            print(
                f"  [{total_proc:>6,}/{total:,}] "
                f"+{processados_agora:,} nesta execução | "
                f"escaneados até agora: {len(escaneados)} | "
                f"vel: {velocidade:.0f}/s | "
                f"ETA: {eta/60:.1f} min"
            )
            # Salva relatório parcial
            _salvar_report(tem_texto, escaneados, por_ano, total)

    # Salva relatório final
    _salvar_report(tem_texto, escaneados, por_ano, total)

    # ---------------------------------------------------------------------------
    # Resumo final
    # ---------------------------------------------------------------------------
    total_escaneados = len(escaneados)
    total_tem_texto  = len(tem_texto)
    pct = (total_escaneados / total * 100) if total > 0 else 0.0

    print("\n" + "=" * 65)
    print("  RESUMO FINAL")
    print("=" * 65)
    print(f"  Total de PDFs         : {total:>7,}")
    print(f"  Com texto extraível   : {total_tem_texto:>7,}")
    print(f"  Escaneados (sem texto): {total_escaneados:>7,}  ({pct:.2f}%)")
    print()
    print(f"  {'Ano':<6} {'tem_texto':>10} {'escaneados':>11} {'% esc':>8}")
    print(f"  {'-'*6} {'-'*10} {'-'*11} {'-'*8}")
    for ano in ANOS:
        tt  = por_ano[ano]["tem_texto"]
        esc = por_ano[ano]["escaneados"]
        sub = tt + esc
        p   = (esc / sub * 100) if sub > 0 else 0.0
        print(f"  {ano:<6} {tt:>10,} {esc:>11,} {p:>7.2f}%")
    print()
    print(f"  Relatório salvo em: {REPORT_FILE.relative_to(ROOT)}")
    print("=" * 65)


def _salvar_report(
    tem_texto: list[str],
    escaneados: list[str],
    por_ano: dict[str, dict[str, int]],
    total: int,
) -> None:
    total_esc = len(escaneados)
    pct = round(total_esc / total * 100, 2) if total > 0 else 0.0
    report = {
        "tem_texto":  tem_texto,
        "escaneados": escaneados,
        "resumo": {
            "total":                  total,
            "tem_texto":              len(tem_texto),
            "escaneados":             total_esc,
            "percentual_escaneados":  pct,
            "por_ano":                por_ano,
        },
    }
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
