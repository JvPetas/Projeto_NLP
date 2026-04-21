#!/usr/bin/env python3
"""
Download e parsing dos 33 anexos tarifários de distribuidoras — DSP 2634/2016.

Extrai URLs dos hiperlinks internos das 5 capas regionais, baixa os PDFs,
processa e salva JSONs de corpus com campos extras: regiao e distribuidora.
"""

import json
import re
import sys
import time
from pathlib import Path

import pdfplumber
from curl_cffi import requests as cffi_requests

sys.path.insert(0, str(Path(__file__).parent))
from parse import processar_pdf, gerar_documento, CORPUS_DIR

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PDFS_2016    = PROJECT_ROOT / "data" / "pdfs" / "2016"

CAPAS = [
    (PROJECT_ROOT / "data/pdfs/2016/centro_Oeste_dsp20162634.pdf", "centro_oeste"),
    (PROJECT_ROOT / "data/pdfs/2016/norte_dsp20162634.pdf",        "norte"),
    (PROJECT_ROOT / "data/pdfs/2016/sul_dsp20162634.pdf",          "sul"),
    (PROJECT_ROOT / "data/pdfs/2016/nordeste_dsp20162634.pdf",     "nordeste"),
    (PROJECT_ROOT / "data/pdfs/2016/sudeste_dsp20162634.pdf",      "sudeste"),
]

ATO_ID = "dsp_2634_2016"
TIPO   = "anexo"
ANO    = 2016


def extrair_urls_das_capas() -> list[tuple[str, str]]:
    """Retorna lista de (url_https, regiao)."""
    resultado = []
    for capa_path, regiao in CAPAS:
        with pdfplumber.open(capa_path) as pdf:
            for page in pdf.pages:
                for a in (page.annots or []):
                    uri = a.get("uri")
                    if uri:
                        url = uri.replace("http://", "https://")
                        resultado.append((url, regiao))
    return resultado


def nome_distribuidora(url: str) -> str:
    """Extrai nome da distribuidora do nome do arquivo na URL."""
    nome = Path(url).stem  # e.g. ANEXO_2016_COPEL_dsp20162634
    # Remove prefixo ANEXO_2016_ e sufixo _dsp20162634
    nome = re.sub(r"^ANEXO_\d{4}_", "", nome)
    nome = re.sub(r"_dsp\d+$", "", nome)
    return nome


def baixar_pdf(url: str, destino: Path, tentativas: int = 3) -> bool:
    for tentativa in range(1, tentativas + 1):
        try:
            resp = cffi_requests.get(
                url,
                impersonate="chrome120",
                timeout=60,
                verify=False,
            )
            if resp.status_code == 200 and len(resp.content) > 1000:
                destino.write_bytes(resp.content)
                return True
            print(f"    HTTP {resp.status_code}, tamanho {len(resp.content)} bytes")
        except Exception as exc:
            print(f"    Tentativa {tentativa} erro: {exc}")
        if tentativa < tentativas:
            time.sleep(3)
    return False


def salvar_doc_anexo(doc: dict, regiao: str, distribuidora: str) -> Path:
    doc["regiao"]        = regiao
    doc["distribuidora"] = distribuidora
    ano_doc = doc.get("ano") or ANO
    out_dir = CORPUS_DIR / str(ano_doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(doc["arquivo_origem"]).stem
    out_path = out_dir / f"{stem}_{TIPO}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    return out_path


def main() -> None:
    print("Extraindo URLs das capas regionais...")
    urls_regioes = extrair_urls_das_capas()
    print(f"  {len(urls_regioes)} URLs encontradas\n")

    baixados_ok  = 0
    baixados_err = 0
    processados  = []

    for url, regiao in urls_regioes:
        arquivo   = Path(url).name
        destino   = PDFS_2016 / arquivo
        distrib   = nome_distribuidora(url)

        print(f"[{regiao}] {arquivo}", end=" ... ", flush=True)

        # Download
        if destino.exists() and destino.stat().st_size > 1000:
            print("já existe, pulando download", end=" ... ", flush=True)
        else:
            ok = baixar_pdf(url, destino)
            if not ok:
                print("ERRO no download — pulando")
                baixados_err += 1
                continue

        # Parse
        try:
            extracao = processar_pdf(destino)
        except Exception as exc:
            print(f"ERRO no parse: {exc}")
            baixados_err += 1
            continue

        meta = {
            "ato_id":         ATO_ID,
            "tipo_documento": TIPO,
            "titulo":         None,
            "ementa":         None,
            "assunto":        None,
            "situacao":       None,
            "publicacao":     None,
            "autor":          "ANEEL",
            "ano":            ANO,
        }
        doc = gerar_documento(meta, extracao, arquivo)
        out_path = salvar_doc_anexo(doc, regiao, distrib)

        score  = doc["qualidade_score"]
        chars  = doc["caracteres_extraidos"]
        tabela = doc["tem_tabela"]
        print(f"score={score} chars={chars:,} tabela={tabela} -> {out_path.name}")

        baixados_ok += 1
        processados.append(doc)
        time.sleep(0.5)

    # Resumo
    score_1 = sum(1 for d in processados if d["qualidade_score"] == 1.0)
    tabelas = sum(1 for d in processados if d["tem_tabela"])
    chars_t = sum(d["caracteres_extraidos"] for d in processados)

    print("\n" + "="*60)
    print(f"Baixados com sucesso : {baixados_ok}/{len(urls_regioes)}")
    print(f"Erros                : {baixados_err}")
    print(f"Score 1.0            : {score_1}/{baixados_ok}")
    print(f"Tabelas detectadas   : {tabelas}/{baixados_ok}")
    print(f"Total chars extraídos: {chars_t:,}")
    print("="*60)

    by_regiao: dict[str, list] = {}
    for d in processados:
        r = d.get("regiao", "?")
        by_regiao.setdefault(r, []).append(d)
    for r, docs in sorted(by_regiao.items()):
        print(f"  {r}: {len(docs)} docs, chars={sum(d['caracteres_extraidos'] for d in docs):,}")


if __name__ == "__main__":
    main()
