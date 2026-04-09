"""
Teste de parsing em amostra representativa do corpus ANEEL.

Execução:
    python data/test_sample/test_parsing.py

Saídas:
    data/test_sample/resultados/<nome>.json   — resultado por arquivo
    data/test_sample/paginas_suspeitas.json  — páginas com baixa razão alfanumérica
    data/test_sample/relatorio_teste.md      — relatório consolidado

Estratégia de detecção de tabelas:
    Usa as posições x,y das palavras extraídas pelo PyMuPDF. Quando o gap horizontal
    entre palavras adjacentes supera 15 pontos tipográficos, insere "   " (3 espaços)
    como separador de coluna. Uma linha é tabular quando tem ≥ 3 colunas com ≥ 3 chars
    cada e total ≥ 20 chars. Um bloco tabular requer ≥ 4 linhas consecutivas.
"""

import json
import re
import traceback
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SAMPLE_JSON = PROJECT_ROOT / "data" / "test_sample" / "sample_files.json"
RESULTADOS_DIR = PROJECT_ROOT / "data" / "test_sample" / "resultados"
RELATORIO_PATH = PROJECT_ROOT / "data" / "test_sample" / "relatorio_teste.md"
PAGINAS_SUSPEITAS_PATH = PROJECT_ROOT / "data" / "test_sample" / "paginas_suspeitas.json"

RESULTADOS_DIR.mkdir(parents=True, exist_ok=True)

# Parâmetros de detecção de tabelas
MIN_COLUNAS_TABELA = 3        # mínimo de colunas válidas por linha
MIN_LINHAS_TABELA = 4         # mínimo de linhas consecutivas com padrão tabular
MIN_CHARS_COLUNA = 3          # mínimo de caracteres por coluna
MIN_CHARS_LINHA_TABELA = 20   # mínimo de caracteres totais na linha
GAP_COLUNA_PT = 15            # gap mínimo (pt) para separador de coluna

# Limiar de qualidade de página (razão alfanumérica)
LIMIAR_ALFA = 0.55  # reduzido de 0.60 para não penalizar documentos técnicos com fórmulas
MIN_CHARS_VALIDAR_PAGINA = 50  # páginas abaixo deste tamanho não são avaliadas


# ---------------------------------------------------------------------------
# Limpeza — Camada 1: lixo conhecido do corpus ANEEL
# ---------------------------------------------------------------------------

_LIXO_L1: list[tuple[re.Pattern, str]] = [
    (re.compile(r"(?m)^\s*Imprimir\s*$"), ""),
    (re.compile(r"(?m)^\s*Voltar\s*$"), ""),
    (re.compile(r"(?m)^\s*Topo\s*$"), ""),
    (re.compile(r"P[áa]gina\s+\d+\s+de\s+\d+", re.IGNORECASE), ""),
    (re.compile(r"P[áa]g\.?\s*\d+\b", re.IGNORECASE), ""),
    (re.compile(r"https?://www2?\.aneel\.gov\.br\S*", re.IGNORECASE), ""),
    (re.compile(r"www2?\.aneel\.gov\.br\S*", re.IGNORECASE), ""),
    (re.compile(r"C[ÓO]PIA\s+N[ÃA]O\s+CONTROLADA", re.IGNORECASE), ""),
    (re.compile(r"DOCUMENTO\s+CONTROLADO", re.IGNORECASE), ""),
]


def _limpar_camada1(texto: str) -> tuple[str, int]:
    """Remove padrões de lixo conhecidos. Retorna (texto, chars_removidos)."""
    antes = len(texto)
    for pattern, replacement in _LIXO_L1:
        texto = pattern.sub(replacement, texto)
    return texto, antes - len(texto)


# ---------------------------------------------------------------------------
# Limpeza — Camada 2: normalização
# ---------------------------------------------------------------------------

def _limpar_camada2(texto: str) -> str:
    """Corrige hifenização, espaços, quebras de linha."""
    texto = re.sub(r"(\w)-\n(\w)", r"\1\2", texto)   # "pala-\nvra" → "palavra"
    texto = texto.replace("\xa0", " ")                 # non-breaking space
    texto = re.sub(r" {2,}", " ", texto)               # espaços múltiplos
    texto = re.sub(r"\n{3,}", "\n\n", texto)           # linhas em branco excessivas
    return texto.strip()


# ---------------------------------------------------------------------------
# Limpeza — Camada 3: cabeçalhos/rodapés repetidos
# ---------------------------------------------------------------------------

def detectar_cabecalhos_rodapes(pages_data: list[dict]) -> set[str]:
    """Identifica linhas que aparecem em > 30% das páginas (cabeçalho/rodapé).

    Analisa as primeiras 3 e últimas 3 linhas de cada página.
    Exige ao menos 2 ocorrências para evitar falsos positivos em documentos curtos.
    """
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


def _limpar_camada3(texto: str, padroes: set[str]) -> tuple[str, int]:
    """Remove linhas identificadas como cabeçalho/rodapé repetido."""
    if not padroes:
        return texto, 0
    antes = len(texto)
    linhas = [l for l in texto.split("\n") if l.strip() not in padroes]
    resultado = "\n".join(linhas)
    return resultado, antes - len(resultado)


def limpar_texto_completo(texto: str, padroes: set[str]) -> tuple[str, int]:
    """Aplica as 3 camadas em sequência. Retorna (texto_limpo, chars_removidos)."""
    total = 0
    texto, removido = _limpar_camada1(texto)
    total += removido
    texto = _limpar_camada2(texto)
    texto, removido = _limpar_camada3(texto, padroes)
    total += removido
    return texto, total


# ---------------------------------------------------------------------------
# Validação por página
# ---------------------------------------------------------------------------

def validar_pagina(texto: str) -> tuple[bool, float]:
    """Calcula razão de caracteres alfanuméricos.

    Retorna (is_suspeita, razao_alfa).
    Páginas com < MIN_CHARS_VALIDAR_PAGINA chars não são avaliadas (sem evidência).
    """
    texto = texto.strip()
    if len(texto) < MIN_CHARS_VALIDAR_PAGINA:
        return False, 1.0
    total = len(texto)
    alfa_num = sum(1 for c in texto if c.isalpha() or c.isdigit())
    razao = alfa_num / total
    return razao < LIMIAR_ALFA, round(razao, 3)


# ---------------------------------------------------------------------------
# Extração de texto por página — PyMuPDF
# ---------------------------------------------------------------------------

def extrair_paginas_pymupdf(caminho: Path) -> tuple[list[dict], list[str]]:
    """Extrai dados por página.

    Retorna (pages_data, erros).
    Cada página: {idx, texto_simples, linhas_layout}.
    linhas_layout: palavras reconstruídas com gap-based spacing (para tabelas).
    """
    erros: list[str] = []
    pages_data: list[dict] = []
    try:
        import fitz
        doc = fitz.open(str(caminho))
        for idx, page in enumerate(doc):
            texto_simples = page.get_text()

            # Reconstrução de linhas com gaps reais entre palavras
            words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,word_no)
            grupos: dict[int, list[tuple[float, float, str]]] = defaultdict(list)
            for w in words:
                y_key = round(w[1] / 5) * 5
                grupos[y_key].append((w[0], w[2], w[4]))  # x0, x1, word

            linhas_layout: list[str] = []
            for y_key in sorted(grupos):
                palavras_ord = sorted(grupos[y_key], key=lambda p: p[0])
                partes: list[str] = []
                for i, (x0, x1, word) in enumerate(palavras_ord):
                    partes.append(word)
                    if i < len(palavras_ord) - 1:
                        gap = palavras_ord[i + 1][0] - x1
                        partes.append("   " if gap > GAP_COLUNA_PT else " ")
                linhas_layout.append("".join(partes))

            pages_data.append({
                "idx": idx,
                "texto_simples": texto_simples,
                "linhas_layout": linhas_layout,
            })
        doc.close()
    except Exception as e:
        erros.append(f"pymupdf: {e}")
    return pages_data, erros


# ---------------------------------------------------------------------------
# Detecção e extração de tabelas
# ---------------------------------------------------------------------------

def _eh_linha_tabela(linha: str) -> bool:
    """Critério rigoroso para linha tabular:
    - Total ≥ MIN_CHARS_LINHA_TABELA chars
    - ≥ MIN_COLUNAS_TABELA colunas separadas por 3+ espaços
    - Cada coluna com ≥ MIN_CHARS_COLUNA chars
    """
    linha = linha.strip()
    if len(linha) < MIN_CHARS_LINHA_TABELA:
        return False
    colunas = re.split(r" {3,}", linha)
    colunas_validas = [c.strip() for c in colunas if len(c.strip()) >= MIN_CHARS_COLUNA]
    return len(colunas_validas) >= MIN_COLUNAS_TABELA


def _bloco_para_markdown(linhas: list[str]) -> str:
    """Converte bloco de linhas tabulares para Markdown."""
    colunas_por_linha = [
        [c.strip() for c in re.split(r" {3,}", l.strip()) if c.strip()]
        for l in linhas
    ]
    max_cols = max(len(c) for c in colunas_por_linha)

    def padded(cols: list[str]) -> list[str]:
        return cols + [""] * (max_cols - len(cols))

    md = [
        "| " + " | ".join(padded(colunas_por_linha[0])) + " |",
        "| " + " | ".join("---" for _ in range(max_cols)) + " |",
    ]
    for cols in colunas_por_linha[1:]:
        md.append("| " + " | ".join(padded(cols)) + " |")
    return "\n".join(md)


def reconstruir_conteudo_pagina(
    linhas_layout: list[str],
    padroes: set[str],
) -> tuple[str, int, int, int]:
    """Reconstrói conteúdo da página preservando a ordem: texto → tabela → texto.

    Retorna (conteudo, num_tabelas, chars_tabela, chars_lixo_removido).
    Aplica limpeza completa no texto não-tabular.
    """
    segmentos: list[tuple[str, str]] = []  # (tipo, conteudo): "texto" | "tabela"
    bloco_tabela: list[str] = []
    bloco_texto: list[str] = []
    total_lixo = 0

    def flush_texto() -> None:
        nonlocal total_lixo
        if bloco_texto:
            bruto = "\n".join(bloco_texto)
            limpo, removido = limpar_texto_completo(bruto, padroes)
            total_lixo += removido
            if limpo.strip():
                segmentos.append(("texto", limpo))
            bloco_texto.clear()

    def flush_tabela() -> None:
        if len(bloco_tabela) >= MIN_LINHAS_TABELA:
            segmentos.append(("tabela", _bloco_para_markdown(bloco_tabela)))
        else:
            bloco_texto.extend(bloco_tabela)
        bloco_tabela.clear()

    em_tabela = False
    for linha in linhas_layout:
        if _eh_linha_tabela(linha):
            if not em_tabela:
                flush_texto()
                em_tabela = True
            bloco_tabela.append(linha)
        else:
            if em_tabela:
                flush_tabela()
                em_tabela = False
            bloco_texto.append(linha)

    if em_tabela:
        flush_tabela()
    flush_texto()

    partes = [conteudo for _, conteudo in segmentos]
    conteudo_final = "\n\n".join(partes)

    tabelas = [c for tipo, c in segmentos if tipo == "tabela"]
    chars_tabela = sum(len(t) for t in tabelas)

    return conteudo_final, len(tabelas), chars_tabela, total_lixo


# ---------------------------------------------------------------------------
# Métricas de qualidade
# ---------------------------------------------------------------------------

def calcular_metricas(
    num_paginas: int,
    num_chars: int,
    num_tabelas: int,
    chars_tabela: int,
    paginas_suspeitas: int,
    lixo_removido: int,
    pdf_escaneado: bool,
) -> dict:
    """Calcula densidade_texto, razao_tabelas e qualidade_score."""
    densidade = round(num_chars / num_paginas, 1) if num_paginas > 0 else 0.0
    razao_tabelas = round(chars_tabela / num_chars, 3) if num_chars > 0 else 0.0

    if pdf_escaneado or num_chars == 0:
        score = 0.0
    else:
        base = 1.0
        if num_paginas > 0:
            frac_susp = paginas_suspeitas / num_paginas
            base -= min(0.4, frac_susp * 2)      # penalidade máx: 0.4
        if densidade < 100:
            base -= 0.1                            # penalidade por densidade baixa
        score = round(max(0.0, base), 2)

    return {
        "densidade_texto": densidade,
        "razao_tabelas": razao_tabelas,
        "qualidade_score": score,
        "lixo_removido_chars": lixo_removido,
    }


# ---------------------------------------------------------------------------
# Detecção de encoding
# ---------------------------------------------------------------------------

def detectar_encoding(caminho: Path) -> str:
    try:
        import chardet
        with open(str(caminho), "rb") as f:
            amostra = f.read(8192)
        res = chardet.detect(amostra)
        return res.get("encoding") or "desconhecido"
    except Exception:
        return "erro_ao_detectar"


# ---------------------------------------------------------------------------
# Processamento de PDF
# ---------------------------------------------------------------------------

def processar_pdf(caminho: Path) -> tuple[dict, list[dict]]:
    pages_data, erros = extrair_paginas_pymupdf(caminho)
    num_paginas = len(pages_data)

    # Detectar cabeçalhos/rodapés antes de processar (requer todas as páginas)
    padroes = detectar_cabecalhos_rodapes(pages_data)

    conteudo_total: list[str] = []
    paginas_suspeitas_doc: list[dict] = []
    total_tabelas = 0
    total_chars_tabela = 0
    total_lixo = 0

    for page in pages_data:
        # Validação da qualidade da página
        suspeita, razao_alfa = validar_pagina(page["texto_simples"])
        if suspeita:
            paginas_suspeitas_doc.append({
                "arquivo": caminho.name,
                "pagina": page["idx"] + 1,
                "razao_alfa": razao_alfa,
            })

        # Reconstrói conteúdo com tabelas em ordem correta
        conteudo_pag, n_tab, chars_tab, lixo_pag = reconstruir_conteudo_pagina(
            page["linhas_layout"], padroes
        )
        total_tabelas += n_tab
        total_chars_tabela += chars_tab
        total_lixo += lixo_pag
        if conteudo_pag.strip():
            conteudo_total.append(conteudo_pag)

    texto_final = "\n\n".join(conteudo_total)
    num_chars = len(texto_final)
    pdf_escaneado = num_chars == 0 and num_paginas > 0

    if pdf_escaneado:
        erros.append(
            "PDF sem camada de texto — provável documento digitalizado. "
            "OCR será aplicado condicionalmente via scan_report.json."
        )

    metricas = calcular_metricas(
        num_paginas, num_chars, total_tabelas, total_chars_tabela,
        len(paginas_suspeitas_doc), total_lixo, pdf_escaneado,
    )

    resultado = {
        "tem_texto": num_chars > 0,
        "caracteres_extraidos": num_chars,
        "pdf_escaneado": pdf_escaneado,
        "tem_tabela": total_tabelas > 0,
        "paginas": num_paginas,
        "paginas_suspeitas": len(paginas_suspeitas_doc),
        "encoding_detectado": detectar_encoding(caminho),
        "texto_preview": texto_final[:300],
        "tabelas_encontradas": total_tabelas,
        "tabelas_markdown": [],  # amostras não são persistidas no JSON individual
        "erros": erros,
        **metricas,
    }
    return resultado, paginas_suspeitas_doc


# ---------------------------------------------------------------------------
# Processamento de HTML
# ---------------------------------------------------------------------------

def processar_html(caminho: Path) -> tuple[dict, list[dict]]:
    erros: list[str] = []
    try:
        from html.parser import HTMLParser

        class TextExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self.partes: list[str] = []
                self._skip = False

            def handle_starttag(self, tag, attrs):
                if tag in ("script", "style"):
                    self._skip = True

            def handle_endtag(self, tag):
                if tag in ("script", "style"):
                    self._skip = False

            def handle_data(self, data):
                if not self._skip:
                    self.partes.append(data)

        encoding = detectar_encoding(caminho)
        with open(str(caminho), encoding=encoding or "utf-8", errors="replace") as f:
            conteudo = f.read()

        extractor = TextExtractor()
        extractor.feed(conteudo)
        texto_bruto = " ".join(extractor.partes)
        texto_limpo, lixo = limpar_texto_completo(texto_bruto, set())

        suspeita, razao_alfa = validar_pagina(texto_limpo)
        paginas_suspeitas_doc: list[dict] = []
        if suspeita:
            paginas_suspeitas_doc.append({
                "arquivo": caminho.name, "pagina": 1, "razao_alfa": razao_alfa,
            })

        metricas = calcular_metricas(
            1, len(texto_limpo), 0, 0, len(paginas_suspeitas_doc), lixo, False
        )

        return {
            "tem_texto": len(texto_limpo) > 0,
            "caracteres_extraidos": len(texto_limpo),
            "pdf_escaneado": False,
            "tem_tabela": False,
            "paginas": 1,
            "paginas_suspeitas": len(paginas_suspeitas_doc),
            "encoding_detectado": encoding,
            "texto_preview": texto_limpo[:300],
            "tabelas_encontradas": 0,
            "tabelas_markdown": [],
            "erros": erros,
            **metricas,
        }, paginas_suspeitas_doc

    except Exception as e:
        return {
            "tem_texto": False, "caracteres_extraidos": 0, "pdf_escaneado": False,
            "tem_tabela": False, "paginas": 0, "paginas_suspeitas": 0,
            "encoding_detectado": "erro", "texto_preview": "",
            "tabelas_encontradas": 0, "tabelas_markdown": [], "erros": [str(e)],
            "densidade_texto": 0.0, "razao_tabelas": 0.0,
            "qualidade_score": 0.0, "lixo_removido_chars": 0,
        }, []


# ---------------------------------------------------------------------------
# Processamento de ZIP
# ---------------------------------------------------------------------------

def processar_zip(caminho: Path) -> tuple[dict, list[dict]]:
    erros: list[str] = []
    nomes: list[str] = []
    try:
        with zipfile.ZipFile(str(caminho)) as z:
            for info in z.infolist():
                nome = info.filename
                try:
                    nome = info.filename.encode("cp437").decode("utf-8")
                except (UnicodeDecodeError, UnicodeEncodeError):
                    try:
                        nome = info.filename.encode("cp437").decode("latin-1")
                    except Exception:
                        erros.append(
                            f"encoding inválido no nome '{info.filename[:40]}' — mantido como está"
                        )
                nomes.append(nome)
    except zipfile.BadZipFile as e:
        erros.append(f"ZIP inválido ou corrompido: {e}")
    except Exception as e:
        erros.append(f"Erro ao abrir ZIP: {e}")

    preview = (
        f"Conteúdo ({len(nomes)} arquivo(s)): " + ", ".join(nomes[:10])
        if nomes else "ZIP vazio ou não lido"
    )
    return {
        "tem_texto": False, "caracteres_extraidos": 0, "pdf_escaneado": False,
        "tem_tabela": False, "paginas": 0, "paginas_suspeitas": 0,
        "encoding_detectado": "n/a", "texto_preview": preview,
        "tabelas_encontradas": 0, "tabelas_markdown": [], "erros": erros,
        "densidade_texto": 0.0, "razao_tabelas": 0.0,
        "qualidade_score": 0.0, "lixo_removido_chars": 0,
    }, []


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

PROCESSADORES = {
    "pdf": processar_pdf,
    "html": processar_html,
    "htm": processar_html,
    "zip": processar_zip,
}

_FALLBACK_CAMPOS: dict = {
    "tem_texto": False, "caracteres_extraidos": 0, "pdf_escaneado": False,
    "tem_tabela": False, "paginas": 0, "paginas_suspeitas": 0,
    "encoding_detectado": "n/a", "texto_preview": "",
    "tabelas_encontradas": 0, "tabelas_markdown": [],
    "densidade_texto": 0.0, "razao_tabelas": 0.0,
    "qualidade_score": 0.0, "lixo_removido_chars": 0,
}


def processar_arquivo(entrada: dict) -> tuple[dict, list[dict]]:
    caminho_rel = entrada["caminho"]
    caminho = PROJECT_ROOT / caminho_rel
    ext = caminho.suffix.lstrip(".").lower()
    processador = PROCESSADORES.get(ext)

    base = {
        "arquivo": caminho.name,
        "caminho": caminho_rel,
        "ano": entrada.get("ano"),
        "tipo_arquivo": ext,
        "motivo_selecao": entrada.get("motivo_selecao"),
        "tamanho_bytes": caminho.stat().st_size if caminho.exists() else 0,
    }

    if not caminho.exists():
        base.update({**_FALLBACK_CAMPOS, "erros": ["Arquivo não encontrado"]})
        return base, []

    if processador is None:
        base.update({**_FALLBACK_CAMPOS, "erros": [f"Tipo não suportado: .{ext}"]})
        return base, []

    dados, suspeitas = processador(caminho)
    base.update(dados)
    return base, suspeitas


# ---------------------------------------------------------------------------
# Geração do relatório
# ---------------------------------------------------------------------------

def gerar_relatorio(resultados: list[dict], paginas_suspeitas: list[dict]) -> str:
    linhas = [
        "# Relatório de Teste de Parsing — Corpus ANEEL",
        "",
        "Amostra de 15 documentos testados com PyMuPDF (extração de texto).",
        "Detecção de tabelas por posicionamento espacial de palavras: gap > 15pt = separador de coluna,",
        "blocos com ≥ 4 linhas e ≥ 3 colunas (≥ 3 chars cada) são convertidos para Markdown.",
        "",
        "## Tabela Resumo",
        "",
        "| # | Arquivo | Ano | Tipo | KB | Pág | Chars | Tabelas | Escaneado | Score | Erros |",
        "|---|---------|-----|------|----|-----|-------|---------|-----------|-------|-------|",
    ]

    problemas: list[str] = []
    recomendacoes: set[str] = set()
    escaneados: list[str] = []

    for i, r in enumerate(resultados, 1):
        nome = r.get("arquivo", "?")
        ano = r.get("ano", "—")
        tipo = r.get("tipo_arquivo", "—").upper()
        kb = r.get("tamanho_bytes", 0) // 1024
        pag = r.get("paginas", "—")
        chars = r.get("caracteres_extraidos", 0)
        tabelas = r.get("tabelas_encontradas", 0)
        escaneado = "Sim" if r.get("pdf_escaneado") else "Não"
        score = r.get("qualidade_score", 0.0)
        erros = r.get("erros", [])
        tem_erro = "Sim" if erros else "Não"

        linhas.append(
            f"| {i} | `{nome}` | {ano} | {tipo} | {kb} | {pag} "
            f"| {chars:,} | {tabelas} | {escaneado} | {score:.2f} | {tem_erro} |"
        )

        for e in erros:
            problemas.append(f"- **{nome}**: {e}")

        if r.get("pdf_escaneado"):
            escaneados.append(nome)

        # Recomendações automáticas
        if r.get("pdf_escaneado"):
            recomendacoes.add(
                "PDFs digitalizados detectados. OCR condicional com pytesseract/ocrmypdf; "
                "candidatos registrados em `scan_report.json`."
            )
        if tabelas > 0:
            recomendacoes.add(
                "Tabelas detectadas por padrão de espaçamento. Validar amostras manualmente — "
                "falsos positivos são possíveis em fórmulas e parágrafos com recuo."
            )
        if tipo == "ZIP":
            recomendacoes.add(
                "Arquivos ZIP presentes: definir política — extrair PDFs internos ou "
                "registrar apenas metadados do conteúdo."
            )
        if tipo in ("HTML", "HTM"):
            recomendacoes.add(
                "HTMLs em dois formatos (D*.htm e ren*.html): validar cobertura do "
                "parser HTML para ambas as variações de template."
            )
        if kb > 10_000:
            recomendacoes.add(
                "PDFs > 10 MB presentes: processar por chunks de páginas no pipeline "
                "em lote para controlar consumo de memória."
            )
        if r.get("paginas_suspeitas", 0) > 0:
            recomendacoes.add(
                "Páginas suspeitas detectadas (razão alfanumérica < 60%): ver "
                "`paginas_suspeitas.json` para detalhes por arquivo e página."
            )

    # Seção: Scores e métricas
    linhas += [
        "",
        "## Scores de Qualidade e Métricas por Documento",
        "",
        "| Arquivo | Score | Densidade (chars/pág) | % Tabela | Pág. Suspeitas | Lixo Removido |",
        "|---------|-------|----------------------|----------|----------------|---------------|",
    ]
    for r in resultados:
        linhas.append(
            f"| `{r.get('arquivo', '?')}` "
            f"| {r.get('qualidade_score', 0.0):.2f} "
            f"| {r.get('densidade_texto', 0.0):.0f} "
            f"| {r.get('razao_tabelas', 0.0):.1%} "
            f"| {r.get('paginas_suspeitas', 0)} "
            f"| {r.get('lixo_removido_chars', 0):,} chars |"
        )

    # Seção: Problemas
    linhas += ["", "## Problemas Encontrados", ""]
    linhas += problemas if problemas else ["Nenhum erro crítico encontrado na amostra."]

    # Seção: PDFs escaneados
    linhas += ["", "## PDFs Digitalizados — Candidatos a OCR", ""]
    if escaneados:
        linhas.append(
            "Os arquivos abaixo não retornaram texto via PyMuPDF. No pipeline final, "
            "serão registrados em `scan_report.json` para OCR condicional."
        )
        linhas.append("")
        for nome in escaneados:
            linhas.append(f"- `{nome}`")
    else:
        linhas.append("Nenhum PDF digitalizado encontrado na amostra.")

    # Seção: Páginas suspeitas
    linhas += ["", "## Páginas Suspeitas (razão alfanumérica < 60%)", ""]
    susp_por_arq: dict[str, list[dict]] = defaultdict(list)
    for p in paginas_suspeitas:
        susp_por_arq[p["arquivo"]].append(p)

    if susp_por_arq:
        for arq, pags in sorted(susp_por_arq.items()):
            linhas.append(f"**{arq}** — {len(pags)} página(s) suspeita(s):")
            for p in pags[:5]:
                linhas.append(f"  - Pág. {p['pagina']}: {p['razao_alfa']:.1%} alfanumérico")
            if len(pags) > 5:
                linhas.append(f"  - ... e mais {len(pags) - 5} página(s)")
            linhas.append("")
    else:
        linhas.append("Nenhuma página suspeita encontrada na amostra.")

    # Seção: Recomendações
    linhas += ["", "## Recomendações para o Parser Final", ""]
    for rec in sorted(recomendacoes):
        linhas.append(f"- {rec}")

    # Seção: Limitações conhecidas
    linhas += [
        "",
        "## Limitações Conhecidas",
        "",
        "- **Tabelas sem padrão regular de espaçamento**: tabelas com colunas de largura "
        "variável ou texto justificado podem não ser detectadas pelo critério de gap > 15pt.",
        "- **Falsos positivos**: listas numeradas, fórmulas matemáticas e parágrafos com "
        "recuo largo podem ser interpretados erroneamente como tabelas.",
        "- **PDF digitalizado confirmado**: `nreh20223128.pdf` — 0 chars extraídos. "
        "OCR necessário via `scan_report.json` no pipeline final.",
        "- **ZIPs com nomes corrompidos**: filenames com encoding CP437 tratados com "
        "`try/except` e fallback para Latin-1; o pipeline não trava.",
        "- **Detecção de cabeçalhos/rodapés em documentos curtos**: requer ≥ 2 ocorrências "
        "e ≥ 30% das páginas — pode não funcionar em documentos com menos de 7 páginas.",
    ]

    # Seção: Preview de texto
    linhas += ["", "## Pré-visualização de Texto (primeiros 300 chars)", ""]
    for r in resultados:
        preview = r.get("texto_preview", "").replace("\n", " ")
        enc = r.get("encoding_detectado", "?")
        linhas.append(f"**{r.get('arquivo', '?')}** (`{enc}`):")
        linhas.append(f"> {preview}" if preview else "> *(sem texto)*")
        linhas.append("")

    return "\n".join(linhas)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    with open(SAMPLE_JSON, encoding="utf-8") as f:
        sample = json.load(f)

    resultados: list[dict] = []
    todas_suspeitas: list[dict] = []

    for entrada in sample["arquivos"]:
        nome = Path(entrada["caminho"]).name
        print(f"Processando: {nome} ...", end=" ", flush=True)
        try:
            resultado, suspeitas = processar_arquivo(entrada)
            resultados.append(resultado)
            todas_suspeitas.extend(suspeitas)
            avisos = len(resultado.get("erros", []))
            print("OK" if avisos == 0 else f"AVISO ({avisos} aviso(s))")
        except Exception:
            print("ERRO INESPERADO")
            traceback.print_exc()
            resultados.append({
                "arquivo": nome,
                "caminho": entrada["caminho"],
                "erros": [traceback.format_exc()],
            })

        # Salva resultado individual
        saida = RESULTADOS_DIR / (Path(nome).stem + ".json")
        with open(saida, "w", encoding="utf-8") as f:
            json.dump(resultado, f, ensure_ascii=False, indent=2)

    # Salva páginas suspeitas (log global)
    with open(PAGINAS_SUSPEITAS_PATH, "w", encoding="utf-8") as f:
        json.dump(todas_suspeitas, f, ensure_ascii=False, indent=2)

    # Gera relatório
    relatorio = gerar_relatorio(resultados, todas_suspeitas)
    with open(RELATORIO_PATH, "w", encoding="utf-8") as f:
        f.write(relatorio)

    print(f"\nResultados:      {RESULTADOS_DIR}")
    print(f"Pág. suspeitas:  {PAGINAS_SUSPEITAS_PATH}")
    print(f"Relatório:       {RELATORIO_PATH}")


if __name__ == "__main__":
    main()
