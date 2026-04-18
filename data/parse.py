#!/usr/bin/env python3
"""
parse.py — Parser principal do corpus ANEEL.

Lê os 3 JSONs de metadados, localiza os PDFs/HTMLs/ZIPs em data/pdfs/{ano}/,
extrai texto e gera um JSON por documento em data/corpus/{ano}/.

Uso:
    python data/parse.py
    python data/parse.py --limite 10
    python data/parse.py --ano 2016
    python data/parse.py --arquivos ren2016699.pdf nreh20212869.pdf

Saídas:
    data/corpus/{ano}/{arquivo}_{tipo}.json  — documentos gerados
    data/parse_errors.json                  — erros por arquivo
    data/parse_summary.json                 — estatísticas gerais
    data/skipped_scanned.json               — PDFs escaneados pulados
    data/missing_files.json                 — arquivos não encontrados no disco
    data/parsed.txt                         — controle de progresso (retomada)
"""

import argparse
import json
import re
import time
import traceback
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

try:
    import ftfy as _ftfy
    _FTFY_OK = True
except ImportError:
    _ftfy = None
    _FTFY_OK = False


def _aplicar_ftfy(texto: str) -> tuple[str, bool]:
    """Aplica ftfy.fix_text se disponível. Retorna (texto_corrigido, houve_alteracao)."""
    if not _FTFY_OK or not texto:
        return texto, False
    corrigido = _ftfy.fix_text(texto)
    return corrigido, corrigido != texto


# Caracteres indicadores de encoding errado
_CHARS_SUSPEITOS = re.compile(r"[\ufffd\u25a1\u0000]")

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
PDFS_DIR = DATA_DIR / "pdfs"
CORPUS_DIR = DATA_DIR / "corpus"

SCAN_REPORT_PATH = DATA_DIR / "scan_report.json"
PARSED_TXT       = DATA_DIR / "parsed.txt"
ERRORS_PATH      = DATA_DIR / "parse_errors.json"
SUMMARY_PATH     = DATA_DIR / "parse_summary.json"
SKIPPED_PATH     = DATA_DIR / "skipped_scanned.json"
MISSING_PATH     = DATA_DIR / "missing_files.json"

JSON_METADADOS = [
    (2016, PROJECT_ROOT / "biblioteca_aneel_gov_br_legislacao_2016_metadados.json"),
    (2021, PROJECT_ROOT / "biblioteca_aneel_gov_br_legislacao_2021_metadados.json"),
    (2022, PROJECT_ROOT / "biblioteca_aneel_gov_br_legislacao_2022_metadados.json"),
]

# ---------------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------------

MIN_COLUNAS_TABELA     = 3
MIN_LINHAS_TABELA      = 4
MIN_CHARS_COLUNA       = 3
MIN_CHARS_LINHA_TABELA = 20
GAP_COLUNA_PT          = 15

LIMIAR_ALFA             = 0.55
MIN_CHARS_VALIDAR_PAG   = 50

# ---------------------------------------------------------------------------
# Limpeza — Camada 1: lixo ANEEL
# ---------------------------------------------------------------------------

_LIXO_L1 = [
    (re.compile(r"(?m)^\s*Imprimir\s*$"),                           ""),
    (re.compile(r"(?m)^\s*Voltar\s*$"),                             ""),
    (re.compile(r"(?m)^\s*Topo\s*$"),                               ""),
    (re.compile(r"P[áa]gina\s+\d+\s+de\s+\d+", re.IGNORECASE),     ""),
    (re.compile(r"P[áa]g\.?\s*\d+\b",           re.IGNORECASE),     ""),
    (re.compile(r"pg\.\s*\d+\b",                re.IGNORECASE),     ""),
    (re.compile(r"https?://www2?\.aneel\.gov\.br\S*", re.IGNORECASE), ""),
    (re.compile(r"www2?\.aneel\.gov\.br\S*",    re.IGNORECASE),     ""),
    (re.compile(r"C[ÓO]PIA\s+N[ÃA]O\s+CONTROLADA", re.IGNORECASE), ""),
    (re.compile(r"DOCUMENTO\s+CONTROLADO",      re.IGNORECASE),     ""),
]


def _camada1(texto: str) -> tuple[str, int]:
    antes = len(texto)
    for pat, rep in _LIXO_L1:
        texto = pat.sub(rep, texto)
    return texto, antes - len(texto)


# ---------------------------------------------------------------------------
# Limpeza — Camada 2: normalização
# ---------------------------------------------------------------------------

def _camada2(texto: str) -> str:
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)   # hifenização
    texto = texto.replace("\xa0", " ")                 # non-breaking space
    texto = re.sub(r" {2,}", " ", texto)               # espaços múltiplos
    texto = re.sub(r"\n{3,}", "\n\n", texto)           # quebras excessivas
    return "\n".join(l.strip() for l in texto.split("\n")).strip()


# ---------------------------------------------------------------------------
# Limpeza — Camada 3: cabeçalhos/rodapés repetidos
# ---------------------------------------------------------------------------

def detectar_repeticoes(pages_data: list[dict]) -> set[str]:
    """Blocos de até 5 linhas que aparecem em > 30% das páginas."""
    if not pages_data:
        return set()
    threshold = max(2, len(pages_data) * 0.30)
    contagens: Counter = Counter()
    for page in pages_data:
        linhas = [l.strip() for l in page["texto_simples"].split("\n") if l.strip()]
        candidatas = linhas[:3] + (linhas[-3:] if len(linhas) > 3 else [])
        for linha in set(candidatas):
            if len(linha) > 5:
                contagens[linha] += 1
    return {linha for linha, cnt in contagens.items() if cnt >= threshold}


def _camada3(texto: str, padroes: set[str]) -> tuple[str, int]:
    if not padroes:
        return texto, 0
    antes = len(texto)
    linhas = [l for l in texto.split("\n") if l.strip() not in padroes]
    resultado = "\n".join(linhas)
    return resultado, antes - len(resultado)


def limpar_texto(texto: str, padroes: set[str]) -> tuple[str, int]:
    """Aplica as 3 camadas. Retorna (texto_limpo, chars_removidos)."""
    total = 0
    texto, r = _camada1(texto)
    total += r
    texto = _camada2(texto)
    texto, r = _camada3(texto, padroes)
    total += r
    return texto, total


# ---------------------------------------------------------------------------
# Validação de página
# ---------------------------------------------------------------------------

def validar_pagina(texto: str) -> tuple[bool, float]:
    """Retorna (is_suspeita, razao_alfa)."""
    texto = texto.strip()
    if len(texto) < MIN_CHARS_VALIDAR_PAG:
        return False, 1.0
    alfa = sum(1 for c in texto if c.isalpha() or c.isdigit())
    razao = alfa / len(texto)
    return razao < LIMIAR_ALFA, round(razao, 3)


# ---------------------------------------------------------------------------
# Detecção e conversão de tabelas
# ---------------------------------------------------------------------------

def _eh_tabela(linha: str) -> bool:
    linha = linha.strip()
    if len(linha) < MIN_CHARS_LINHA_TABELA:
        return False
    cols = re.split(r" {3,}", linha)
    validas = [c.strip() for c in cols if len(c.strip()) >= MIN_CHARS_COLUNA]
    return len(validas) >= MIN_COLUNAS_TABELA


def _para_markdown(linhas: list[str]) -> str:
    cols_por_linha = [
        [c.strip() for c in re.split(r" {3,}", l.strip()) if c.strip()]
        for l in linhas
    ]
    max_cols = max(len(c) for c in cols_por_linha)

    def pad(cols: list[str]) -> list[str]:
        return cols + [""] * (max_cols - len(cols))

    md = [
        "| " + " | ".join(pad(cols_por_linha[0])) + " |",
        "| " + " | ".join("---" for _ in range(max_cols)) + " |",
    ]
    for cols in cols_por_linha[1:]:
        md.append("| " + " | ".join(pad(cols)) + " |")
    return "\n".join(md)


def reconstruir_pagina(
    linhas_layout: list[str], padroes: set[str]
) -> tuple[str, int, int, int]:
    """Reconstrói conteúdo: texto → tabela → texto.

    Retorna (conteudo, n_tabelas, chars_tabela, lixo_removido).
    """
    segmentos: list[tuple[str, str]] = []
    bloco_tab: list[str] = []
    bloco_txt: list[str] = []
    total_lixo = 0

    def flush_txt() -> None:
        nonlocal total_lixo
        if bloco_txt:
            bruto = "\n".join(bloco_txt)
            limpo, r = limpar_texto(bruto, padroes)
            total_lixo += r
            if limpo.strip():
                segmentos.append(("texto", limpo))
            bloco_txt.clear()

    def flush_tab() -> None:
        if len(bloco_tab) >= MIN_LINHAS_TABELA:
            segmentos.append(("tabela", _para_markdown(bloco_tab)))
        else:
            bloco_txt.extend(bloco_tab)
        bloco_tab.clear()

    em_tab = False
    for linha in linhas_layout:
        if _eh_tabela(linha):
            if not em_tab:
                flush_txt()
                em_tab = True
            bloco_tab.append(linha)
        else:
            if em_tab:
                flush_tab()
                em_tab = False
            bloco_txt.append(linha)

    if em_tab:
        flush_tab()
    flush_txt()

    partes = [c for _, c in segmentos]
    conteudo = "\n\n".join(partes)
    tabelas = [c for t, c in segmentos if t == "tabela"]
    return conteudo, len(tabelas), sum(len(t) for t in tabelas), total_lixo


# ---------------------------------------------------------------------------
# Extração PyMuPDF
# ---------------------------------------------------------------------------

def extrair_paginas(caminho_ou_bytes) -> tuple[list[dict], list[str]]:
    """Extrai páginas de um PDF (caminho Path ou bytes)."""
    import fitz
    pages: list[dict] = []
    erros: list[str] = []
    try:
        if isinstance(caminho_ou_bytes, bytes):
            doc = fitz.open(stream=caminho_ou_bytes, filetype="pdf")
        else:
            doc = fitz.open(str(caminho_ou_bytes))

        for idx, page in enumerate(doc):
            texto_simples = page.get_text()
            words = page.get_text("words")
            grupos: dict[int, list] = defaultdict(list)
            for w in words:
                y_key = round(w[1] / 5) * 5
                grupos[y_key].append((w[0], w[2], w[4]))  # x0, x1, word

            linhas_layout: list[str] = []
            for y_key in sorted(grupos):
                palavras = sorted(grupos[y_key], key=lambda p: p[0])
                partes: list[str] = []
                for i, (x0, x1, word) in enumerate(palavras):
                    partes.append(word)
                    if i < len(palavras) - 1:
                        gap = palavras[i + 1][0] - x1
                        partes.append("   " if gap > GAP_COLUNA_PT else " ")
                linhas_layout.append("".join(partes))

            pages.append({
                "idx": idx,
                "texto_simples": texto_simples,
                "linhas_layout": linhas_layout,
            })
        doc.close()
    except Exception as e:
        erros.append(f"pymupdf: {e}")
    return pages, erros


def processar_pdf(caminho_ou_bytes) -> dict:
    """Extrai texto de PDF. Retorna dict de extração."""
    pages, erros = extrair_paginas(caminho_ou_bytes)
    num_paginas = len(pages)
    padroes = detectar_repeticoes(pages)

    conteudos: list[str] = []
    pags_suspeitas: list[dict] = []
    total_tabs = 0
    total_chars_tab = 0
    total_lixo = 0

    for page in pages:
        suspeita, razao = validar_pagina(page["texto_simples"])
        if suspeita:
            pags_suspeitas.append({"pagina": page["idx"] + 1, "razao_alfa": razao})

        conteudo, n_tab, chars_tab, lixo = reconstruir_pagina(
            page["linhas_layout"], padroes
        )
        total_tabs += n_tab
        total_chars_tab += chars_tab
        total_lixo += lixo
        if conteudo.strip():
            conteudos.append(conteudo)

    texto = "\n\n".join(conteudos)

    # Detecta encoding suspeito e aplica ftfy
    chars_suspeitos = bool(_CHARS_SUSPEITOS.search(texto))
    texto, ftfy_alterou = _aplicar_ftfy(texto)
    if ftfy_alterou or chars_suspeitos:
        encoding_detectado = "latin-1"
    else:
        encoding_detectado = "utf-8"

    return {
        "texto": texto,
        "tem_tabela": total_tabs > 0,
        "paginas": num_paginas,
        "caracteres_extraidos": len(texto),
        "paginas_suspeitas": pags_suspeitas,
        "chars_tabela": total_chars_tab,
        "lixo_removido": total_lixo,
        "encoding_detectado": encoding_detectado,
        "erros": erros,
    }


# ---------------------------------------------------------------------------
# Extração HTML — beautifulsoup4
# ---------------------------------------------------------------------------

def processar_html(caminho: Path) -> dict:
    """Extrai texto de HTML usando beautifulsoup4."""
    erros: list[str] = []
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        erros.append("beautifulsoup4 não instalado: pip install beautifulsoup4")
        return _extracao_vazia(erros)

    try:
        raw = caminho.read_bytes()

        # Detecta encoding via meta charset
        soup_enc = BeautifulSoup(raw[:2000], "html.parser")
        enc = "utf-8"
        meta = soup_enc.find("meta", charset=True)
        if meta:
            enc = meta.get("charset", "utf-8")
        else:
            meta_http = soup_enc.find(
                "meta", {"http-equiv": re.compile(r"content-type", re.I)}
            )
            if meta_http:
                content = meta_http.get("content", "")
                m = re.search(r"charset=([^\s;\"]+)", content, re.I)
                if m:
                    enc = m.group(1)

        try:
            html = raw.decode(enc, errors="replace")
        except (LookupError, UnicodeDecodeError):
            html = raw.decode("utf-8", errors="replace")

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
            tag.decompose()

        texto_bruto = soup.get_text(separator="\n")
        texto, lixo = limpar_texto(texto_bruto, set())
        texto, _ = _aplicar_ftfy(texto)

        suspeita, razao = validar_pagina(texto)
        pags_suspeitas = [{"pagina": 1, "razao_alfa": razao}] if suspeita else []

        return {
            "texto": texto,
            "tem_tabela": False,
            "paginas": 1,
            "caracteres_extraidos": len(texto),
            "paginas_suspeitas": pags_suspeitas,
            "chars_tabela": 0,
            "lixo_removido": lixo,
            "encoding_detectado": enc.lower(),
            "erros": erros,
        }
    except Exception as e:
        erros.append(str(e))
        return _extracao_vazia(erros)


def _extracao_vazia(erros: list[str] = None) -> dict:
    return {
        "texto": "", "tem_tabela": False, "paginas": 0,
        "caracteres_extraidos": 0, "paginas_suspeitas": [],
        "chars_tabela": 0, "lixo_removido": 0,
        "encoding_detectado": "utf-8",
        "erros": erros or [],
    }


# ---------------------------------------------------------------------------
# Decodificação de nomes de arquivo dentro de ZIP
# ---------------------------------------------------------------------------

def _decode_zip_nome(filename: str) -> str:
    """Decodifica nome de arquivo de ZIP criado no Windows.

    Python lê os bytes brutos dos nomes como CP437. Para ZIPs com
    filenames em CP850 (DOS Western European), é necessário re-encodar
    para CP437 e decodificar como CP850.
    """
    try:
        raw = filename.encode("cp437")
    except UnicodeEncodeError:
        return filename  # já é texto Unicode válido (UTF-8 flag ativo)
    for enc in ("utf-8", "cp850", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, ValueError):
            continue
    return filename


# ---------------------------------------------------------------------------
# Geração do ato_id
# ---------------------------------------------------------------------------

_PREFIXOS_STRIP = frozenset("an")


def gerar_ato_id(arquivo: str) -> str:
    """Gera ato_id a partir do nome do arquivo.

    ren2016756.pdf     → ren_756_2016
    dsp20163284.pdf    → dsp_3284_2016
    aren2016756_1.pdf  → ren_756_2016  (remove prefixo 'a')
    nreh20212869.pdf   → reh_2869_2021 (remove prefixo 'n')
    reh20212869ti.pdf  → reh_2869_2021 (sufixo 'ti' ignorado)
    """
    stem = Path(arquivo).stem.lower()
    stem = re.sub(r"_\d+$", "", stem)  # remove _1, _2, _3 …
    m = re.match(r"^([a-z]+)(20\d{2})(\d+)", stem)
    if not m:
        return stem
    tipo_raw, ano, num = m.group(1), m.group(2), m.group(3)
    tipo = tipo_raw[1:] if (len(tipo_raw) > 1 and tipo_raw[0] in _PREFIXOS_STRIP) else tipo_raw
    return f"{tipo}_{num}_{ano}"


# ---------------------------------------------------------------------------
# Normalização do tipo_documento
# ---------------------------------------------------------------------------

def normalizar_tipo(tipo_raw: str) -> str:
    """Mapeia o campo tipo do JSON para valor padronizado."""
    tipo = re.sub(r"[:]+\s*$", "", tipo_raw).strip()
    t = tipo.lower()

    # nota_tecnica: "Nota Técnica ..." e prefixo "NT " / "NT."
    if re.search(r"nota\s+t[eé]cnica", t):
        return "nota_tecnica"
    if re.match(r"nt[\s.]", t) or t == "nt":
        return "nota_tecnica"

    # voto
    if t.startswith("voto"):
        return "voto"

    # texto_integral
    if (
        re.search(r"texto\s+i+ntegr", t)
        or t in ("integral", "texto", "pdf")
        or t.startswith("texto original")
        or (t.startswith("texto") and len(t) <= 6)
    ):
        return "texto_integral"

    # decisao
    if re.match(r"decis[aã]o", t) or "decis" in t:
        return "decisao"

    # anexo — nomes explícitos de seções/regiões/planilhas
    if re.match(r"anexo", t):
        return "anexo"
    if re.match(r"sub?m[oó]dulo", t) or re.match(r"m[oó]dulo\b", t):
        return "anexo"
    if any(k in t for k in (
        "base de dado", "base de dao", "planilha",
        "memória de cálculo", "memoria de calculo",
        "exposição de motivos", "exposicao de motivos",
        "programa nodal", "simulador de tarifa",
        "glossário", "glossario",
        "plano anual", "proinfa",
        "rag - resultado", "resultado leilão",
        "região norte", "regiao norte",
        "região sul", "regiao sul",
        "região nordeste", "regiao nordeste",
        "região sudeste", "regiao sudeste",
        "região centro", "regiao centro",
        "site 1",
    )):
        return "anexo"

    return "outro"


# ---------------------------------------------------------------------------
# Extração de metadados dos JSONs
# ---------------------------------------------------------------------------

def _limpar_meta(valor) -> str | None:
    """Limpa campo de metadado: remove prefixo 'Palavra:', normaliza."""
    if valor is None:
        return None
    s = re.sub(r"^[A-ZÀ-ÿa-z\s]+:\s*", "", str(valor), count=1).strip()
    s = s.replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\s*Imprimir\s*$", "", s, flags=re.IGNORECASE).strip()
    return s or None


def _data_iso(valor: str) -> str | None:
    """DD/MM/YYYY → YYYY-MM-DD."""
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", str(valor or ""))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def carregar_metadados() -> dict[str, dict]:
    """Carrega os 3 JSONs. Retorna lookup {arquivo: meta_dict}."""
    lookup: dict[str, dict] = {}
    for ano_json, json_path in JSON_METADADOS:
        if not json_path.exists():
            print(f"  AVISO: JSON não encontrado: {json_path.name}")
            continue
        data: dict = json.load(open(json_path, encoding="utf-8"))
        for _, dia_data in data.items():
            for reg in dia_data.get("registros", []):
                publicacao = _data_iso(reg.get("publicacao", ""))
                try:
                    ano = int(publicacao[:4]) if publicacao else ano_json
                except (TypeError, ValueError):
                    ano = ano_json

                for pdf_entry in reg.get("pdfs", []):
                    arquivo = pdf_entry.get("arquivo", "")
                    if not arquivo:
                        continue
                    lookup[arquivo] = {
                        "ato_id":         gerar_ato_id(arquivo),
                        "tipo_documento": normalizar_tipo(pdf_entry.get("tipo", "")),
                        "titulo":         _limpar_meta(reg.get("titulo")),
                        "ementa":         _limpar_meta(reg.get("ementa")),
                        "assunto":        _limpar_meta(reg.get("assunto")),
                        "situacao":       _limpar_meta(reg.get("situacao")),
                        "publicacao":     publicacao,
                        "autor":          reg.get("autor") or "ANEEL",
                        "ano":            ano,
                        "ano_json":       ano_json,
                    }
    return lookup


# ---------------------------------------------------------------------------
# Construção do documento final
# ---------------------------------------------------------------------------

def gerar_documento(
    meta: dict,
    extracao: dict,
    arquivo_origem: str,
    zip_pai: str | None = None,
) -> dict:
    """Combina metadados + extração no documento de saída."""
    num_chars = extracao.get("caracteres_extraidos", 0)
    num_paginas = extracao.get("paginas", 0)
    chars_tab = extracao.get("chars_tabela", 0)
    pags_susp = extracao.get("paginas_suspeitas", [])

    densidade = round(num_chars / num_paginas, 1) if num_paginas > 0 else 0.0
    proporcao_tabela = round(chars_tab / num_chars, 3) if num_chars > 0 else 0.0

    if num_chars == 0:
        score = 0.0
    else:
        base = 1.0
        if num_paginas > 0:
            base -= min(0.4, (len(pags_susp) / num_paginas) * 2)
        if densidade < 100:
            base -= 0.1
        score = round(max(0.0, base), 2)

    return {
        "ato_id":              meta.get("ato_id", gerar_ato_id(arquivo_origem)),
        "tipo_documento":      meta.get("tipo_documento", "outro"),
        "titulo":              meta.get("titulo"),
        "ementa":              meta.get("ementa"),
        "assunto":             meta.get("assunto"),
        "situacao":            meta.get("situacao"),
        "publicacao":          meta.get("publicacao"),
        "autor":               meta.get("autor", "ANEEL"),
        "ano":                 meta.get("ano"),
        "arquivo_origem":      arquivo_origem,
        "zip_pai":             zip_pai,
        "texto":               extracao.get("texto", ""),
        "tem_tabela":          extracao.get("tem_tabela", False),
        "paginas":             num_paginas,
        "qualidade_score":     score,
        "paginas_suspeitas":   pags_susp,
        "caracteres_extraidos": num_chars,
        "densidade_texto":     densidade,
        "proporcao_tabela":    proporcao_tabela,
        "encoding_detectado":  extracao.get("encoding_detectado", "utf-8"),
    }


# ---------------------------------------------------------------------------
# Controle de progresso
# ---------------------------------------------------------------------------

def carregar_parsed() -> set[str]:
    if PARSED_TXT.exists():
        return set(PARSED_TXT.read_text(encoding="utf-8").splitlines())
    return set()


def registrar_parsed(caminho_rel: str) -> None:
    with open(PARSED_TXT, "a", encoding="utf-8") as f:
        f.write(caminho_rel + "\n")


# ---------------------------------------------------------------------------
# Escrita de documento
# ---------------------------------------------------------------------------

def salvar_doc(doc: dict, ano_json: int) -> None:
    ano_doc = doc.get("ano") or ano_json
    out_dir = CORPUS_DIR / str(ano_doc)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(doc["arquivo_origem"]).stem
    tipo = doc["tipo_documento"]
    out_path = out_dir / f"{stem}_{tipo}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Parser do corpus ANEEL")
    parser.add_argument("--limite", type=int, default=0,
                        help="Máximo de arquivos-fonte a processar (0 = todos)")
    parser.add_argument("--ano", type=int, choices=[2016, 2021, 2022],
                        help="Processar apenas um ano específico")
    parser.add_argument("--arquivos", nargs="+", metavar="ARQUIVO",
                        help="Processar apenas estes arquivos específicos (ignora parsed.txt)")
    args = parser.parse_args()

    t_inicio = time.time()

    print("Carregando metadados...")
    lookup = carregar_metadados()
    print(f"  {len(lookup):,} entradas de metadados carregadas")

    # PDFs escaneados a pular
    escaneados_set: set[str] = set()
    if SCAN_REPORT_PATH.exists():
        scan_data = json.load(open(SCAN_REPORT_PATH, encoding="utf-8"))
        for p in scan_data.get("escaneados", []):
            escaneados_set.add(Path(p).name)
    print(f"  {len(escaneados_set)} PDFs escaneados identificados para pular")

    # Progresso anterior
    parsed_set = carregar_parsed()
    filtro_arquivos = set(args.arquivos) if args.arquivos else None
    print(f"  {len(parsed_set)} arquivos já processados (retomada)")

    CORPUS_DIR.mkdir(parents=True, exist_ok=True)

    # Acumuladores
    erros_por_arquivo: dict[str, list[str]] = {}
    missing_files: list[dict] = []
    skipped_scanned: list[dict] = []
    chars_removidos_total = 0

    stats = {
        "docs_gerados": 0,
        "score_1_0": 0, "score_05_a_1": 0, "score_abaixo_05": 0,
        "tabelas_detectadas": 0, "escaneados_pulados": 0,
        "arquivos_nao_encontrados": 0, "erros": 0,
        "por_ano": defaultdict(int),
    }

    arquivos_processados = 0
    anos_processar = [args.ano] if args.ano else [2016, 2021, 2022]

    for ano_json in anos_processar:
        json_path = next((p for a, p in JSON_METADADOS if a == ano_json), None)
        if not json_path or not json_path.exists():
            continue

        data: dict = json.load(open(json_path, encoding="utf-8"))
        print(f"\nProcessando ano {ano_json}...")

        parar = False
        for _, dia_data in data.items():
            if parar:
                break
            for reg in dia_data.get("registros", []):
                if parar:
                    break
                for pdf_entry in reg.get("pdfs", []):
                    if args.limite and arquivos_processados >= args.limite:
                        parar = True
                        break

                    arquivo = pdf_entry.get("arquivo", "")
                    if not arquivo:
                        continue

                    # Filtro por arquivo específico
                    if filtro_arquivos and arquivo not in filtro_arquivos:
                        continue

                    caminho_rel = f"data/pdfs/{ano_json}/{arquivo}"

                    # Pular se já processado (exceto quando filtro explícito)
                    if not filtro_arquivos and caminho_rel in parsed_set:
                        continue

                    caminho_abs = PDFS_DIR / str(ano_json) / arquivo

                    # PDF escaneado
                    if arquivo in escaneados_set:
                        meta = lookup.get(arquivo, {})
                        skipped_scanned.append({
                            "arquivo":  arquivo,
                            "caminho":  caminho_rel,
                            "ato_id":   meta.get("ato_id", gerar_ato_id(arquivo)),
                            "motivo":   "PDF escaneado sem camada de texto",
                        })
                        stats["escaneados_pulados"] += 1
                        print(f"  ESCANEADO (pulando): {arquivo}")
                        registrar_parsed(caminho_rel)
                        parsed_set.add(caminho_rel)
                        continue

                    # Arquivo não encontrado no disco
                    if not caminho_abs.exists():
                        meta = lookup.get(arquivo, {})
                        missing_files.append({
                            "arquivo": arquivo,
                            "caminho": caminho_rel,
                            "ato_id":  meta.get("ato_id", gerar_ato_id(arquivo)),
                        })
                        stats["arquivos_nao_encontrados"] += 1
                        registrar_parsed(caminho_rel)
                        parsed_set.add(caminho_rel)
                        continue

                    meta = lookup.get(arquivo, {
                        "ato_id":         gerar_ato_id(arquivo),
                        "tipo_documento": normalizar_tipo(pdf_entry.get("tipo", "")),
                        "titulo": None, "ementa": None, "assunto": None,
                        "situacao": None, "publicacao": None,
                        "autor": "ANEEL", "ano": ano_json, "ano_json": ano_json,
                    })

                    ext = caminho_abs.suffix.lstrip(".").lower()
                    print(f"  {arquivo} ...", end=" ", flush=True)

                    try:
                        docs_gerados: list[dict] = []

                        if ext == "pdf":
                            extracao = processar_pdf(caminho_abs)
                            chars_removidos_total += extracao.get("lixo_removido", 0)
                            if extracao["erros"]:
                                erros_por_arquivo[arquivo] = extracao["erros"]
                                stats["erros"] += 1
                            docs_gerados.append(
                                gerar_documento(meta, extracao, arquivo)
                            )

                        elif ext in ("html", "htm"):
                            extracao = processar_html(caminho_abs)
                            chars_removidos_total += extracao.get("lixo_removido", 0)
                            if extracao["erros"]:
                                erros_por_arquivo[arquivo] = extracao["erros"]
                                stats["erros"] += 1
                            docs_gerados.append(
                                gerar_documento(meta, extracao, arquivo)
                            )

                        elif ext == "zip":
                            try:
                                with zipfile.ZipFile(str(caminho_abs)) as z:
                                    for info in z.infolist():
                                        nome = _decode_zip_nome(info.filename)
                                        nome_base = Path(nome).name
                                        if not nome_base.lower().endswith(".pdf"):
                                            continue

                                        if nome_base in escaneados_set:
                                            skipped_scanned.append({
                                                "arquivo": nome_base,
                                                "caminho": f"{caminho_rel}/{nome_base}",
                                                "ato_id":  meta["ato_id"],
                                                "motivo":  "PDF escaneado dentro de ZIP",
                                            })
                                            stats["escaneados_pulados"] += 1
                                            continue

                                        try:
                                            pdf_bytes = z.read(info.filename)
                                            extr = processar_pdf(pdf_bytes)
                                            chars_removidos_total += extr.get("lixo_removido", 0)
                                            if extr["erros"]:
                                                k = f"{arquivo}/{nome_base}"
                                                erros_por_arquivo[k] = extr["erros"]
                                                stats["erros"] += 1
                                            docs_gerados.append(
                                                gerar_documento(
                                                    meta.copy(), extr,
                                                    arquivo_origem=nome_base,
                                                    zip_pai=arquivo,
                                                )
                                            )
                                        except Exception as e_int:
                                            k = f"{arquivo}/{nome_base}"
                                            erros_por_arquivo[k] = [str(e_int)]
                                            stats["erros"] += 1

                            except zipfile.BadZipFile as e_zip:
                                erros_por_arquivo[arquivo] = [f"ZIP inválido: {e_zip}"]
                                stats["erros"] += 1

                        else:
                            erros_por_arquivo[arquivo] = [f"Tipo não suportado: .{ext}"]
                            stats["erros"] += 1

                        # Salva documentos e atualiza estatísticas
                        for doc in docs_gerados:
                            salvar_doc(doc, ano_json)
                            stats["docs_gerados"] += 1
                            stats["por_ano"][doc.get("ano") or ano_json] += 1
                            sc = doc.get("qualidade_score", 0.0)
                            if sc >= 1.0:
                                stats["score_1_0"] += 1
                            elif sc >= 0.5:
                                stats["score_05_a_1"] += 1
                            else:
                                stats["score_abaixo_05"] += 1
                            if doc.get("tem_tabela"):
                                stats["tabelas_detectadas"] += 1

                        print(f"OK ({len(docs_gerados)} doc(s))")
                        arquivos_processados += 1
                        if arquivos_processados % 100 == 0:
                            decorrido = round(time.time() - t_inicio, 1)
                            print(
                                f"\n--- Progresso: {arquivos_processados} arquivos "
                                f"| {stats['docs_gerados']} docs "
                                f"| {decorrido}s ---\n"
                            )

                    except Exception:
                        print("ERRO")
                        erros_por_arquivo[arquivo] = [traceback.format_exc()]
                        stats["erros"] += 1

                    registrar_parsed(caminho_rel)
                    parsed_set.add(caminho_rel)

    # -----------------------------------------------------------------------
    # Salvar saídas auxiliares
    # -----------------------------------------------------------------------
    for path, obj in [
        (SKIPPED_PATH, skipped_scanned),
        (MISSING_PATH, missing_files),
        (ERRORS_PATH,  erros_por_arquivo),
    ]:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)

    corpus_bytes = sum(f.stat().st_size for f in CORPUS_DIR.rglob("*.json"))
    corpus_mb = round(corpus_bytes / 1024 / 1024, 1)
    tempo = round(time.time() - t_inicio, 1)

    summary = {
        "data_execucao":            datetime.now().isoformat(),
        "tempo_processamento_s":    tempo,
        "docs_gerados":             stats["docs_gerados"],
        "score_1_0":                stats["score_1_0"],
        "score_05_a_1":             stats["score_05_a_1"],
        "score_abaixo_05":          stats["score_abaixo_05"],
        "tabelas_detectadas":       stats["tabelas_detectadas"],
        "chars_removidos_limpeza":  chars_removidos_total,
        "escaneados_pulados":       stats["escaneados_pulados"],
        "arquivos_nao_encontrados": stats["arquivos_nao_encontrados"],
        "erros":                    stats["erros"],
        "por_ano":                  dict(stats["por_ano"]),
        "corpus_tamanho_mb":        corpus_mb,
    }
    with open(SUMMARY_PATH, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # -----------------------------------------------------------------------
    # Resumo final
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("RESUMO FINAL")
    print("=" * 60)
    print(f"Documentos gerados:         {stats['docs_gerados']:,}")
    print(f"  Score 1.0:                {stats['score_1_0']:,}")
    print(f"  Score 0.50–0.99:          {stats['score_05_a_1']:,}")
    print(f"  Score < 0.50:             {stats['score_abaixo_05']:,}")
    print(f"Tabelas detectadas:         {stats['tabelas_detectadas']:,}")
    print(f"Chars removidos (limpeza):  {chars_removidos_total:,}")
    print(f"Escaneados pulados:         {stats['escaneados_pulados']}")
    print(f"Arquivos não encontrados:   {stats['arquivos_nao_encontrados']:,}")
    print(f"Erros:                      {stats['erros']:,}")
    print(f"Tempo de processamento:     {tempo:.1f}s")
    print(f"Espaço corpus gerado:       {corpus_mb} MB")
    print()
    print(f"Corpus:      {CORPUS_DIR}")
    print(f"Resumo:      {SUMMARY_PATH}")
    print(f"Erros:       {ERRORS_PATH}")
    print(f"Escaneados:  {SKIPPED_PATH}")
    print(f"Ausentes:    {MISSING_PATH}")


if __name__ == "__main__":
    main()
