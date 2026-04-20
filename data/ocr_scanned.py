#!/usr/bin/env python3
"""
ocr_scanned.py — OCR para PDFs escaneados do corpus ANEEL.

Lê data/scan_report.json, aplica Tesseract (língua portuguesa, 300 DPI)
em cada PDF escaneado e gera um JSON por documento em data/corpus/{ano}/,
no mesmo formato do parse.py.

Uso:
    python data/ocr_scanned.py
    python data/ocr_scanned.py --arquivos centro_Oeste_dsp20162634.pdf
    python data/ocr_scanned.py --dpi 200
    python data/ocr_scanned.py --poppler-path "C:/poppler/Library/bin"

Dependências externas:
    pip install pytesseract pdf2image
    Tesseract-OCR instalado com pacote de língua portuguesa (por):
        https://github.com/UB-Mannheim/tesseract/wiki
    Poppler (binários Windows, exigido pelo pdf2image):
        https://github.com/oschwartz10612/poppler-windows/releases/
    Após descompactar o Poppler, forneça o caminho via --poppler-path
    ou adicione a pasta bin ao PATH do sistema.

Saídas:
    data/corpus/{ano}/{arquivo}_ocr_{tipo}.json  — documentos com texto OCR
    data/ocr_errors.json                         — erros por arquivo
    data/ocr_summary.json                        — estatísticas gerais
    data/ocr_parsed.txt                          — controle de progresso (retomada)
"""

import argparse
import json
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

# Importa utilitários do parse.py para evitar duplicação de código
_DATA_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_DATA_DIR))

from parse import (
    _aplicar_ftfy,
    carregar_metadados,
    gerar_ato_id,
    gerar_documento,
    limpar_texto,
    validar_pagina,
    CORPUS_DIR,
    DATA_DIR,
    PDFS_DIR,
    PROJECT_ROOT,
)

SCAN_REPORT_PATH = DATA_DIR / "scan_report.json"
OCR_ERRORS_PATH  = DATA_DIR / "ocr_errors.json"
OCR_SUMMARY_PATH = DATA_DIR / "ocr_summary.json"
OCR_PARSED_TXT   = DATA_DIR / "ocr_parsed.txt"


# ---------------------------------------------------------------------------
# Detecção automática de dependências externas
# ---------------------------------------------------------------------------

def _detectar_tesseract() -> str | None:
    """Retorna o caminho do executável Tesseract ou None se não encontrado."""
    import shutil
    if shutil.which("tesseract"):
        return "tesseract"
    for candidate in [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\Public\Tesseract-OCR\tesseract.exe",
        r"D:\Program Files\Tesseract-OCR\tesseract.exe",
        r"D:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ]:
        if Path(candidate).exists():
            return candidate
    return None


def _detectar_poppler() -> str | None:
    """Retorna o caminho da pasta bin do Poppler ou None se já está no PATH."""
    import shutil
    if shutil.which("pdftoppm"):
        return None  # já está no PATH
    for candidate in [
        r"C:\poppler\Library\bin",
        r"C:\poppler\bin",
        r"C:\Program Files\poppler\bin",
        r"C:\Program Files (x86)\poppler\bin",
        r"D:\poppler\Library\bin",
        r"D:\poppler\bin",
    ]:
        if Path(candidate, "pdftoppm.exe").exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# OCR de uma imagem de página
# ---------------------------------------------------------------------------

def _ocr_pagina(imagem, tesseract_cmd: str) -> tuple[str, float]:
    """Executa OCR em uma imagem PIL. Retorna (texto, confianca_media_pct)."""
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    # image_to_data para extrair confiança palavra a palavra
    dados = pytesseract.image_to_data(
        imagem,
        lang="por",
        config="--psm 1",
        output_type=pytesseract.Output.DICT,
    )
    texto = pytesseract.image_to_string(imagem, lang="por", config="--psm 1")

    confs = [
        int(c) for c in dados["conf"]
        if str(c).lstrip("-").isdigit() and int(c) >= 0
    ]
    confianca = round(sum(confs) / len(confs), 1) if confs else 0.0
    return texto, confianca


# ---------------------------------------------------------------------------
# Processamento completo de um PDF escaneado
# ---------------------------------------------------------------------------

def processar_ocr(
    caminho: Path,
    tesseract_cmd: str,
    dpi: int,
    poppler_path: str | None,
) -> dict:
    """Converte cada página do PDF para imagem e aplica OCR.

    Retorna dicionário no mesmo formato que processar_pdf() do parse.py,
    com campos extras: confianca_ocr (média de confiança Tesseract, 0–100).
    """
    from pdf2image import convert_from_path

    kwargs: dict = {"dpi": dpi, "fmt": "jpeg"}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path

    try:
        imagens = convert_from_path(str(caminho), **kwargs)
    except Exception as e:
        return {
            "texto": "", "tem_tabela": False, "paginas": 0,
            "caracteres_extraidos": 0, "paginas_suspeitas": [],
            "chars_tabela": 0, "lixo_removido": 0,
            "encoding_detectado": "utf-8", "confianca_ocr": 0.0,
            "erros": [f"pdf2image: {e}"],
        }

    num_paginas = len(imagens)
    conteudos: list[str] = []
    pags_suspeitas: list[dict] = []
    confianças: list[float] = []
    erros: list[str] = []

    for idx, imagem in enumerate(imagens):
        try:
            texto_pag, confianca = _ocr_pagina(imagem, tesseract_cmd)
        except Exception as e:
            erros.append(f"página {idx + 1}: {e}")
            continue

        confianças.append(confianca)
        texto_limpo, _ = limpar_texto(texto_pag, set())
        texto_limpo, _ = _aplicar_ftfy(texto_limpo)

        suspeita, razao = validar_pagina(texto_limpo)
        if suspeita:
            pags_suspeitas.append({"pagina": idx + 1, "razao_alfa": razao})

        if texto_limpo.strip():
            conteudos.append(texto_limpo)

    texto = "\n\n".join(conteudos)
    confianca_media = round(sum(confianças) / len(confianças), 1) if confianças else 0.0

    return {
        "texto": texto,
        "tem_tabela": False,
        "paginas": num_paginas,
        "caracteres_extraidos": len(texto),
        "paginas_suspeitas": pags_suspeitas,
        "chars_tabela": 0,
        "lixo_removido": 0,
        "encoding_detectado": "utf-8",
        "confianca_ocr": confianca_media,
        "erros": erros,
    }


# ---------------------------------------------------------------------------
# Escrita do documento no corpus
# ---------------------------------------------------------------------------

def salvar_doc_ocr(doc: dict, ano_json: int) -> Path:
    ano_doc = doc.get("ano") or ano_json
    out_dir = CORPUS_DIR / str(ano_doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(doc["arquivo_origem"]).stem
    tipo = doc["tipo_documento"]
    out_path = out_dir / f"{stem}_ocr_{tipo}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return out_path


# ---------------------------------------------------------------------------
# Controle de progresso
# ---------------------------------------------------------------------------

def _carregar_ocr_parsed() -> set[str]:
    if OCR_PARSED_TXT.exists():
        return set(OCR_PARSED_TXT.read_text(encoding="utf-8").splitlines())
    return set()


def _registrar_ocr_parsed(caminho_rel: str) -> None:
    with open(OCR_PARSED_TXT, "a", encoding="utf-8") as f:
        f.write(caminho_rel + "\n")


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="OCR para PDFs escaneados do corpus ANEEL")
    parser.add_argument(
        "--arquivos", nargs="+", metavar="ARQUIVO",
        help="Processar apenas estes nomes de arquivo (sem caminho completo)",
    )
    parser.add_argument(
        "--dpi", type=int, default=300,
        help="Resolução de renderização das páginas (padrão: 300)",
    )
    parser.add_argument(
        "--poppler-path", metavar="CAMINHO",
        help="Diretório dos binários do Poppler, ex: C:/poppler/Library/bin",
    )
    args = parser.parse_args()

    t_inicio = time.time()

    # --- Verifica Tesseract ---------------------------------------------------
    tesseract_cmd = _detectar_tesseract()
    if not tesseract_cmd:
        print("ERRO: Tesseract não encontrado.")
        print("  Instale em: https://github.com/UB-Mannheim/tesseract/wiki")
        print("  Marque 'Additional language data > Portuguese' durante a instalação.")
        raise SystemExit(1)
    print(f"Tesseract : {tesseract_cmd}")

    # --- Verifica Poppler ----------------------------------------------------
    poppler_path = args.poppler_path or _detectar_poppler()
    print(f"Poppler   : {poppler_path or 'via PATH'}")

    # --- Carrega lista de PDFs escaneados ------------------------------------
    if not SCAN_REPORT_PATH.exists():
        print(f"ERRO: {SCAN_REPORT_PATH} não encontrado. Rode scan_pdfs.py primeiro.")
        raise SystemExit(1)

    scan_data = json.load(open(SCAN_REPORT_PATH, encoding="utf-8"))
    escaneados = [Path(p) for p in scan_data.get("escaneados", [])]
    print(f"\n{len(escaneados)} PDFs escaneados no scan_report.json")

    if not escaneados:
        print("Nenhum PDF escaneado para processar.")
        return

    # --- Metadados -----------------------------------------------------------
    print("Carregando metadados...")
    lookup = carregar_metadados()
    print(f"  {len(lookup):,} entradas carregadas")

    ocr_parsed_set = _carregar_ocr_parsed()
    filtro = {a.strip() for a in args.arquivos} if args.arquivos else None
    print(f"  {len(ocr_parsed_set)} arquivos já processados (retomada)")

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    erros_por_arquivo: dict[str, list[str]] = {}
    stats = {
        "docs_gerados":   0,
        "paginas_ocr":    0,
        "chars_extraidos": 0,
        "score_1_0":      0,
        "score_05_a_1":   0,
        "score_abaixo_05": 0,
        "erros":          0,
    }

    print(f"\nProcessando (DPI={args.dpi})...\n")

    for caminho_rel_path in escaneados:
        caminho_rel = str(caminho_rel_path).replace("\\", "/")
        nome = caminho_rel_path.name

        if filtro and nome.strip() not in filtro:
            continue

        if not filtro and caminho_rel in ocr_parsed_set:
            continue

        # Extrai ano do caminho relativo (data/pdfs/{ano}/arquivo.pdf)
        partes = caminho_rel.split("/")
        try:
            ano_json = int(partes[partes.index("pdfs") + 1])
        except (ValueError, IndexError):
            print(f"  AVISO: não conseguiu extrair ano de '{caminho_rel}'")
            continue

        caminho_abs = PROJECT_ROOT / caminho_rel_path

        if not caminho_abs.exists():
            print(f"  AUSENTE : {nome}")
            erros_por_arquivo[nome] = ["Arquivo não encontrado no disco"]
            stats["erros"] += 1
            _registrar_ocr_parsed(caminho_rel)
            ocr_parsed_set.add(caminho_rel)
            continue

        meta = lookup.get(nome, {
            "ato_id":         gerar_ato_id(nome),
            "tipo_documento": "outro",
            "titulo": None, "ementa": None, "assunto": None,
            "situacao": None, "publicacao": None,
            "autor": "ANEEL", "ano": ano_json, "ano_json": ano_json,
        })

        print(f"  {nome} ...", end=" ", flush=True)

        try:
            extracao = processar_ocr(caminho_abs, tesseract_cmd, args.dpi, poppler_path)

            if extracao["erros"]:
                erros_por_arquivo[nome] = extracao["erros"]
                stats["erros"] += 1

            doc = gerar_documento(meta, extracao, nome)
            doc["ocr"] = True
            doc["confianca_ocr"] = extracao.get("confianca_ocr", 0.0)

            salvar_doc_ocr(doc, ano_json)

            stats["docs_gerados"]    += 1
            stats["paginas_ocr"]     += extracao.get("paginas", 0)
            stats["chars_extraidos"] += extracao.get("caracteres_extraidos", 0)

            sc   = doc.get("qualidade_score", 0.0)
            conf = doc.get("confianca_ocr", 0.0)
            if sc >= 1.0:
                stats["score_1_0"] += 1
            elif sc >= 0.5:
                stats["score_05_a_1"] += 1
            else:
                stats["score_abaixo_05"] += 1

            print(f"OK ({extracao['paginas']}p | confiança={conf}% | score={sc})")

        except Exception:
            print("ERRO")
            erros_por_arquivo[nome] = [traceback.format_exc()]
            stats["erros"] += 1

        _registrar_ocr_parsed(caminho_rel)
        ocr_parsed_set.add(caminho_rel)

    # --- Salva saídas --------------------------------------------------------
    with open(OCR_ERRORS_PATH, "w", encoding="utf-8") as f:
        json.dump(erros_por_arquivo, f, ensure_ascii=False, indent=2)

    tempo = round(time.time() - t_inicio, 1)
    summary = {
        "data_execucao":         datetime.now().isoformat(),
        "tempo_processamento_s": tempo,
        "docs_gerados":          stats["docs_gerados"],
        "paginas_ocr":           stats["paginas_ocr"],
        "chars_extraidos":       stats["chars_extraidos"],
        "score_1_0":             stats["score_1_0"],
        "score_05_a_1":          stats["score_05_a_1"],
        "score_abaixo_05":       stats["score_abaixo_05"],
        "erros":                 stats["erros"],
        "dpi_usado":             args.dpi,
    }
    with open(OCR_SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("\n" + "=" * 60)
    print("RESUMO FINAL")
    print("=" * 60)
    print(f"Documentos gerados:   {stats['docs_gerados']}")
    print(f"  Score 1.0:          {stats['score_1_0']}")
    print(f"  Score 0.50–0.99:    {stats['score_05_a_1']}")
    print(f"  Score < 0.50:       {stats['score_abaixo_05']}")
    print(f"Páginas processadas:  {stats['paginas_ocr']}")
    print(f"Caracteres extraídos: {stats['chars_extraidos']:,}")
    print(f"Erros:                {stats['erros']}")
    print(f"Tempo total:          {tempo:.1f}s")
    print()
    print(f"Corpus:   {CORPUS_DIR}")
    print(f"Erros:    {OCR_ERRORS_PATH}")
    print(f"Resumo:   {OCR_SUMMARY_PATH}")


if __name__ == "__main__":
    main()
