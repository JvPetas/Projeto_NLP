#!/usr/bin/env python3
"""
chunk.py — Chunking hierárquico em 2 níveis para o corpus ANEEL.

Níveis:
  Filho (256 tokens): unidade indexada para retrieval vetorial.
  Pai   (512 tokens): contexto enviado ao LLM (filho anterior + atual + seguinte).

Uso:
    python data/chunk.py                    # processa todo o corpus
    python data/chunk.py --ano 2016         # apenas 2016
    python data/chunk.py --limite 100       # primeiros 100 documentos
    python data/chunk.py --teste            # 5 docs representativos com saída detalhada
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Optional

import tiktoken

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

ROOT             = Path(__file__).parent.parent
CORPUS_DIR       = ROOT / "data" / "corpus"
CHUNKS_DIR       = ROOT / "data" / "chunks"
FILHOS_DIR       = CHUNKS_DIR / "filhos"
PAIS_DIR         = CHUNKS_DIR / "pais"
CHUNKED_FILE     = ROOT / "data" / "chunked.txt"
SUMMARY_FILE     = ROOT / "data" / "chunk_summary.json"
TRUNCATED_LOG    = ROOT / "data" / "chunks_truncados.json"

# ---------------------------------------------------------------------------
# Parâmetros
# ---------------------------------------------------------------------------

FILHO_MAX = 256
PAI_MAX   = 512
OVERLAP   = 50

TIPO_ABREV = {
    "texto_integral": "ti",
    "voto":           "vo",
    "nota_tecnica":   "nt",
    "anexo":          "an",
    "decisao":        "de",
    "outro":          "ou",
}

# Limite máximo de chunks filho por documento, por tipo
MAX_CHUNKS_POR_TIPO = {
    "texto_integral": 200,
    "voto":           150,
    "nota_tecnica":   200,
    "anexo":          50,
    "decisao":        100,
    "outro":          50,
}

ENC = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(ENC.encode(text))


def truncate_tokens(text: str, max_tokens: int) -> str:
    tokens = ENC.encode(text)
    if len(tokens) <= max_tokens:
        return text
    return ENC.decode(tokens[:max_tokens])


# ---------------------------------------------------------------------------
# Primitivas de splitting
# ---------------------------------------------------------------------------

def split_fixed(text: str, max_tokens: int, overlap: int = 0) -> list:
    """Janela deslizante de tokens com overlap opcional."""
    tokens = ENC.encode(text)
    if not tokens:
        return []
    step   = max(1, max_tokens - overlap)
    chunks = []
    i = 0
    while i < len(tokens):
        chunks.append(ENC.decode(tokens[i : i + max_tokens]))
        if i + max_tokens >= len(tokens):
            break
        i += step
    return chunks


TABLE_LINE = re.compile(r"^\s*\|.*\|\s*$")


def split_table_rows(table: str, max_tokens: int) -> list:
    """
    Divide tabela markdown por linhas de dados, repetindo o cabeçalho
    (todas as linhas até e incluindo a linha separadora |---|) em cada chunk.
    """
    lines = table.split("\n")
    header_lines = []
    data_lines   = []
    in_header    = True
    for line in lines:
        if in_header:
            header_lines.append(line)
            if re.match(r"^\s*\|[-:| ]+\|\s*$", line):
                in_header = False
        else:
            data_lines.append(line)

    header = "\n".join(header_lines)
    if not data_lines:
        return [table]

    chunks = []
    batch  = []
    for row in data_lines:
        candidate = header + "\n" + "\n".join(batch + [row])
        if count_tokens(candidate) <= max_tokens:
            batch.append(row)
        else:
            if batch:
                chunks.append(header + "\n" + "\n".join(batch))
            batch = [row]
    if batch:
        chunks.append(header + "\n" + "\n".join(batch))
    return chunks or [table]


def extract_table_blocks(text: str) -> list:
    """
    Separa o texto em blocos (texto_normal, False) e (tabela_markdown, True).
    """
    lines  = text.split("\n")
    blocks = []
    i = 0
    while i < len(lines):
        if TABLE_LINE.match(lines[i]):
            j = i
            while j < len(lines) and TABLE_LINE.match(lines[j]):
                j += 1
            blocks.append(("\n".join(lines[i:j]), True))
            i = j
        else:
            j = i
            while j < len(lines) and not TABLE_LINE.match(lines[j]):
                j += 1
            bloco = "\n".join(lines[i:j]).strip()
            if bloco:
                blocks.append((bloco, False))
            i = j
    return blocks


def fit_segments(segs: list, ctxs: list, max_tokens: int) -> tuple:
    """
    Garante que cada segmento caiba em max_tokens.
    Segmentos grandes são subdivididos por linha e depois por tokens.
    """
    out_c = []
    out_x = []
    for seg, ctx in zip(segs, ctxs):
        if count_tokens(seg) <= max_tokens:
            out_c.append(seg)
            out_x.append(ctx)
            continue
        paras = [p.strip() for p in seg.split("\n") if p.strip()]
        cur   = ""
        for para in paras:
            candidate = (cur + "\n" + para).strip() if cur else para
            if count_tokens(candidate) <= max_tokens:
                cur = candidate
            else:
                if cur:
                    out_c.append(cur)
                    out_x.append(ctx)
                subs = split_fixed(para, max_tokens, 0) if count_tokens(para) > max_tokens else [para]
                out_c.extend(subs)
                out_x.extend([ctx] * len(subs))
                cur = ""
        if cur:
            out_c.append(cur)
            out_x.append(ctx)
    return out_c, out_x


# ---------------------------------------------------------------------------
# Padrões jurídicos
# ---------------------------------------------------------------------------

ART_START = re.compile(
    r"^(Art\.\s*\d[\d\.ºo]*|§\s*\d+|Parágrafo\s+[Úú]nico|Inciso\s+[IVXLCDM]+|"
    r"CAPÍTULO\s+[IVXLCDM]+|SEÇÃO\s+[IVXLCDM]+|SUBSEÇÃO\s+[IVXLCDM]+)",
    re.IGNORECASE,
)

ART_SPLIT = re.compile(
    r"(?m)(?=^(?:Art\.\s*\d|§\s*\d|Parágrafo\s+[Úú]nico|Inciso\s+[IVXLCDM]|"
    r"CAPÍTULO\s+[IVXLCDM]|SEÇÃO\s+[IVXLCDM]|SUBSEÇÃO\s+[IVXLCDM]))",
    re.IGNORECASE,
)

_NT_SPLIT = re.compile(
    r"(?m)(?=^(?:\d+(?:\.\d+)*\.?\s+[A-ZÁÉÍÓÚÂÊÎÔÛÃÕ]|"
    r"[IVXLCDM]+(?:\.\d+)?\s*[–\-—]\s*))",
)
_NT_CTX = re.compile(r"^(\d+(?:\.\d+)*\.?|[IVXLCDM]+(?:\.\d+)?\s*[–\-—]?)")

_DECISAO_NAMED = re.compile(
    r"(?m)(?=^(?:RELATÓRIO|VOTO|DECISÃO|EMENTA|ACÓRDÃO)\b)",
    re.IGNORECASE,
)
_DECISAO_ROMAN = re.compile(
    r"(?m)(?=^\s*[IVXLCDM]+\s*[-–—]\s*[A-ZÁÉÍÓÚÂÊÎÔÛÃÕA-Z])",
)
_DECISAO_CTX = re.compile(
    r"^(RELATÓRIO|VOTO|DECISÃO|EMENTA|ACÓRDÃO|[IVXLCDM]+(?:\s*[-–—]\s*\w+)?)",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Chunkers por tipo
# ---------------------------------------------------------------------------

def chunk_texto_integral(texto: str) -> tuple:
    segs = [s.strip() for s in ART_SPLIT.split(texto) if s.strip()]
    if len(segs) <= 1:
        chunks = split_fixed(texto, FILHO_MAX, 0)
        return chunks, [""] * len(chunks)
    ctxs = []
    for seg in segs:
        m = ART_START.match(seg)
        ctxs.append(m.group(1).strip() if m else "")
    return fit_segments(segs, ctxs, FILHO_MAX)


def chunk_voto(texto: str) -> tuple:
    chunks = split_fixed(texto, FILHO_MAX, OVERLAP)
    return chunks, [""] * len(chunks)


def chunk_nota_tecnica(texto: str) -> tuple:
    blocks = extract_table_blocks(texto)
    all_c  = []
    all_x  = []
    for bloco, is_table in blocks:
        if is_table:
            if count_tokens(bloco) <= FILHO_MAX:
                all_c.append(bloco)
                all_x.append("[tabela]")
            else:
                subs = split_table_rows(bloco, FILHO_MAX)
                all_c.extend(subs)
                all_x.extend(["[tabela]"] * len(subs))
        else:
            segs = [s.strip() for s in _NT_SPLIT.split(bloco) if s.strip()]
            if len(segs) <= 1:
                subs = split_fixed(bloco, FILHO_MAX, 0)
                all_c.extend(subs)
                all_x.extend([""] * len(subs))
            else:
                ctxs = []
                for seg in segs:
                    m = _NT_CTX.match(seg)
                    ctxs.append(m.group(1).strip() if m else "")
                c, x = fit_segments(segs, ctxs, FILHO_MAX)
                all_c.extend(c)
                all_x.extend(x)
    return all_c, all_x


def chunk_anexo(texto: str) -> tuple:
    blocks = extract_table_blocks(texto)
    all_c  = []
    all_x  = []
    for bloco, is_table in blocks:
        if is_table:
            # Correção 4: só dividir se realmente maior que FILHO_MAX
            if count_tokens(bloco) <= FILHO_MAX:
                all_c.append(bloco)
                all_x.append("[tabela]")
            else:
                subs = split_table_rows(bloco, FILHO_MAX)
                all_c.extend(subs)
                all_x.extend(["[tabela]"] * len(subs))
        else:
            if bloco.strip():
                subs = split_fixed(bloco, FILHO_MAX, 0)
                all_c.extend(subs)
                all_x.extend([""] * len(subs))
    if not all_c:
        chunks = split_fixed(texto, FILHO_MAX, 0)
        return chunks, [""] * len(chunks)
    return all_c, all_x


def chunk_decisao(texto: str) -> tuple:
    for pattern in (_DECISAO_NAMED, _DECISAO_ROMAN):
        segs = [s.strip() for s in pattern.split(texto) if s.strip()]
        if len(segs) > 1:
            break
    if len(segs) <= 1:
        chunks = split_fixed(texto, FILHO_MAX, 0)
        return chunks, [""] * len(chunks)
    ctxs = []
    for seg in segs:
        m = _DECISAO_CTX.match(seg)
        ctxs.append(m.group(1).strip().upper() if m else "")
    return fit_segments(segs, ctxs, FILHO_MAX)


def chunk_outro(texto: str) -> tuple:
    chunks = split_fixed(texto, FILHO_MAX, OVERLAP)
    return chunks, [""] * len(chunks)


CHUNKERS = {
    "texto_integral": chunk_texto_integral,
    "voto":           chunk_voto,
    "nota_tecnica":   chunk_nota_tecnica,
    "anexo":          chunk_anexo,
    "decisao":        chunk_decisao,
}


# ---------------------------------------------------------------------------
# Construção dos pais
# ---------------------------------------------------------------------------

def build_parents(child_texts: list) -> list:
    n = len(child_texts)
    parents = []
    for i in range(n):
        parts = []
        if i > 0:
            parts.append(child_texts[i - 1])
        parts.append(child_texts[i])
        if i < n - 1:
            parts.append(child_texts[i + 1])
        parents.append(truncate_tokens("\n".join(parts), PAI_MAX))
    return parents


# ---------------------------------------------------------------------------
# Log de truncamentos
# ---------------------------------------------------------------------------

def log_truncated(info: dict) -> None:
    existing = []
    if TRUNCATED_LOG.exists():
        try:
            existing = json.loads(TRUNCATED_LOG.read_text(encoding="utf-8"))
        except Exception:
            existing = []
    existing.append(info)
    TRUNCATED_LOG.write_text(
        json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Processamento de um documento
# ---------------------------------------------------------------------------

def process_doc(doc: dict, stem: str = "") -> tuple:
    """
    Retorna (filhos, pais, truncation_info).
    truncation_info é None se não houve truncamento.
    stem é o nome do arquivo sem extensão; usado como prefixo do chunk_id.
    """
    ato_id = doc.get("ato_id", "")
    tipo   = doc.get("tipo_documento", "outro")
    texto  = doc.get("texto", "")

    # Correção 1: usar stem do arquivo como prefixo, garantindo unicidade
    prefix = stem if stem else ato_id

    if not texto or not texto.strip():
        return [], [], None

    abrev   = TIPO_ABREV.get(tipo, "ou")
    chunker = CHUNKERS.get(tipo, chunk_outro)

    child_texts, contexts = chunker(texto)
    if not child_texts:
        return [], [], None

    # Correção 2: aplicar limite máximo de chunks por tipo
    max_chunks     = MAX_CHUNKS_POR_TIPO.get(tipo, 50)
    total_tokens   = count_tokens(texto)
    truncation_info = None

    if len(child_texts) > max_chunks:
        truncation_info = {
            "arquivo":         stem,
            "tipo":            tipo,
            "chunks_gerados":  len(child_texts),
            "chunks_mantidos": max_chunks,
            "tokens_totais":   total_tokens,
        }
        child_texts = child_texts[:max_chunks]
        contexts    = contexts[:max_chunks]

    parent_texts = build_parents(child_texts)
    n = len(child_texts)

    meta = {
        "ato_id":         ato_id,
        "tipo_documento": tipo,
        "titulo":         doc.get("titulo", ""),
        "ementa":         doc.get("ementa", ""),
        "assunto":        doc.get("assunto", ""),
        "situacao":       doc.get("situacao", ""),
        "publicacao":     doc.get("publicacao", ""),
        "autor":          doc.get("autor", ""),
        "ano":            doc.get("ano"),
    }

    filhos = []
    pais   = []

    for i, (ctexto, ctx, ptexto) in enumerate(zip(child_texts, contexts, parent_texts)):
        num      = i + 1
        # Correção 1: chunk_id baseado no stem do arquivo, não no ato_id
        chunk_id = f"{prefix}_{abrev}_c{num:03d}"
        pai_id   = f"{prefix}_{abrev}_p{num:03d}"

        filho = {
            "chunk_id":          chunk_id,
            "chunk_pai_id":      pai_id,
            **meta,
            "contexto_juridico": ctx,
            "numero_chunk":      num,
            "total_chunks":      n,
            "posicao_relativa":  round(num / n, 4),
            # Correção 1: referências entre chunks também usam prefix
            "chunk_anterior_id": f"{prefix}_{abrev}_c{num - 1:03d}" if i > 0 else None,
            "chunk_proximo_id":  f"{prefix}_{abrev}_c{num + 1:03d}" if i < n - 1 else None,
            "texto":             ctexto,
            "texto_pai":         ptexto,
        }

        # Correção 3: aviso em anexos truncados
        if truncation_info and tipo == "anexo":
            filho["aviso"] = "documento truncado por exceder limite de chunks para tipo anexo"

        filhos.append(filho)

        pai = {
            "chunk_pai_id": pai_id,
            "chunk_id":     chunk_id,
            **meta,
            "numero_chunk": num,
            "total_chunks": n,
            "texto_pai":    ptexto,
        }
        pais.append(pai)

    return filhos, pais, truncation_info


# ---------------------------------------------------------------------------
# Controle de progresso  (chave = stem do arquivo, único por ficheiro)
# ---------------------------------------------------------------------------

def load_processed() -> set:
    if not CHUNKED_FILE.exists():
        return set()
    return set(CHUNKED_FILE.read_text(encoding="utf-8").splitlines())


def mark_processed(key: str) -> None:
    with CHUNKED_FILE.open("a", encoding="utf-8") as f:
        f.write(key + "\n")


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------

def save_chunks(filhos: list, pais: list, ano: int) -> None:
    fd = FILHOS_DIR / str(ano)
    pd = PAIS_DIR   / str(ano)
    fd.mkdir(parents=True, exist_ok=True)
    pd.mkdir(parents=True, exist_ok=True)
    for filho in filhos:
        (fd / f"{filho['chunk_id']}.json").write_text(
            json.dumps(filho, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    for pai in pais:
        (pd / f"{pai['chunk_pai_id']}.json").write_text(
            json.dumps(pai, ensure_ascii=False, indent=2), encoding="utf-8"
        )


# ---------------------------------------------------------------------------
# Coleta de caminhos
# ---------------------------------------------------------------------------

def collect_paths(anos: Optional[list] = None) -> list:
    paths = []
    if not CORPUS_DIR.exists():
        print(f"Corpus não encontrado: {CORPUS_DIR}", file=sys.stderr)
        return paths
    for ano_dir in sorted(CORPUS_DIR.iterdir()):
        if not ano_dir.is_dir():
            continue
        try:
            ano_int = int(ano_dir.name)
        except ValueError:
            continue
        if anos and ano_int not in anos:
            continue
        paths.extend(sorted(ano_dir.glob("*.json")))
    return paths


# ---------------------------------------------------------------------------
# Modo teste
# ---------------------------------------------------------------------------

_TIPOS_TESTE = ["texto_integral", "voto", "nota_tecnica", "anexo", "decisao"]


def find_test_docs() -> list:
    """Encontra 1 exemplo de cada tipo com texto substancial."""
    found = {}
    for ano_dir in sorted(CORPUS_DIR.iterdir()):
        if not ano_dir.is_dir():
            continue
        for jf in sorted(ano_dir.glob("*.json")):
            if len(found) == len(_TIPOS_TESTE):
                break
            try:
                with jf.open(encoding="utf-8", errors="replace") as f:
                    doc = json.load(f)
            except Exception:
                continue
            tipo  = doc.get("tipo_documento", "outro")
            texto = doc.get("texto", "")
            if tipo in _TIPOS_TESTE and tipo not in found and count_tokens(texto) >= 80:
                found[tipo] = jf
        if len(found) == len(_TIPOS_TESTE):
            break
    return [(t, found[t]) for t in _TIPOS_TESTE if t in found]


def run_teste() -> None:
    print("=" * 70)
    print("MODO TESTE — 5 documentos representativos")
    print("=" * 70)

    docs = find_test_docs()
    if not docs:
        print("Nenhum documento encontrado para teste.")
        return

    for tipo, path in docs:
        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                doc = json.load(f)
        except Exception as e:
            print(f"Erro ao ler {path}: {e}")
            continue

        ato_id = doc.get("ato_id", "")
        titulo = doc.get("titulo", "")

        print(f"\n{'─' * 60}")
        print(f"Tipo:      {tipo}")
        print(f"Documento: {ato_id}")
        print(f"Título:    {titulo[:80]}")
        print(f"Arquivo:   {path.name}")

        filhos, pais, trunc = process_doc(doc, stem=path.stem)
        print(f"Filhos gerados : {len(filhos)}")
        print(f"Pais gerados   : {len(pais)}")

        if trunc:
            print(
                f"  *** TRUNCADO: {trunc['chunks_gerados']} → {trunc['chunks_mantidos']} chunks "
                f"({trunc['tokens_totais']:,} tokens)"
            )
            log_truncated(trunc)

        if filhos:
            f0 = filhos[0]
            p0 = pais[0]
            print(f"\n  → Filho 1  (chunk_id={f0['chunk_id']})")
            print(f"     contexto_juridico : {f0['contexto_juridico']!r}")
            print(f"     tokens            : {count_tokens(f0['texto'])}")
            preview = f0["texto"][:220].replace("\n", "↵")
            print(f"     texto             : {preview!r}")

            print(f"\n  → Pai 1  (chunk_pai_id={p0['chunk_pai_id']})")
            print(f"     tokens            : {count_tokens(p0['texto_pai'])}")
            preview = p0["texto_pai"][:220].replace("\n", "↵")
            print(f"     texto_pai         : {preview!r}")

    print(f"\n{'=' * 70}")


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def run(anos: Optional[list] = None, limite: Optional[int] = None) -> None:
    paths = collect_paths(anos)
    if limite:
        paths = paths[:limite]

    total       = len(paths)
    processados = load_processed()

    print(f"Documentos encontrados : {total}")
    print(f"Já processados (stems) : {len(processados)}")

    t0       = time.time()
    n_docs   = 0
    n_filhos = 0
    n_pais   = 0
    n_erros  = 0
    n_trunc  = 0

    stats_tipo: dict = {}
    max_doc = ("", 0)
    min_doc = ("", float("inf"))

    for path in paths:
        file_key = path.stem
        if file_key in processados:
            continue

        try:
            with path.open(encoding="utf-8", errors="replace") as f:
                doc = json.load(f)
        except Exception as e:
            print(f"ERRO ao ler {path.name}: {e}", file=sys.stderr)
            n_erros += 1
            mark_processed(file_key)
            processados.add(file_key)
            continue

        ato_id = doc.get("ato_id", path.stem)

        try:
            filhos, pais, trunc = process_doc(doc, stem=path.stem)
        except Exception as e:
            print(f"ERRO ao chunkar {ato_id} ({path.name}): {e}", file=sys.stderr)
            n_erros += 1
            mark_processed(file_key)
            processados.add(file_key)
            continue

        if trunc:
            log_truncated(trunc)
            n_trunc += 1

        if filhos:
            try:
                ano = int(doc.get("ano") or path.parent.name)
            except (ValueError, TypeError):
                ano = int(path.parent.name)
            save_chunks(filhos, pais, ano)

            tipo = doc.get("tipo_documento", "outro")
            nc   = len(filhos)
            stats_tipo[tipo] = stats_tipo.get(tipo, 0) + nc
            if nc > max_doc[1]:
                max_doc = (ato_id, nc)
            if nc < min_doc[1]:
                min_doc = (ato_id, nc)
            n_filhos += nc
            n_pais   += len(pais)

        mark_processed(file_key)
        processados.add(file_key)
        n_docs += 1

        if n_docs % 500 == 0:
            elapsed = time.time() - t0
            print(
                f"Progresso: {n_docs}/{total} | "
                f"chunks gerados: {n_filhos} | "
                f"truncamentos: {n_trunc} | "
                f"tempo: {elapsed:.0f}s"
            )

    elapsed = time.time() - t0
    media   = n_filhos / max(n_docs, 1)

    print("\n" + "=" * 60)
    print("RESUMO FINAL")
    print("=" * 60)
    print(f"Documentos processados:       {n_docs}")
    print(f"Total de chunks filhos:       {n_filhos}")
    print(f"Total de chunks pai:          {n_pais}")
    print(f"Média de chunks/documento:    {media:.1f}")
    print(f"Documentos truncados:         {n_trunc}")
    print(f"Erros:                        {n_erros}")
    print(f"Tempo total:                  {elapsed:.1f}s")

    if stats_tipo:
        print("\nDistribuição por tipo_documento:")
        for tipo, nc in sorted(stats_tipo.items(), key=lambda x: -x[1]):
            print(f"  {tipo:<20} {nc:>8} chunks")

    if max_doc[0]:
        print(f"\nDocumento com mais chunks:    {max_doc[0]} ({max_doc[1]})")
    if min_doc[0] and min_doc[1] < float("inf"):
        print(f"Documento com menos chunks:   {min_doc[0]} ({int(min_doc[1])})")

    total_bytes = sum(
        f.stat().st_size for f in CHUNKS_DIR.rglob("*.json") if f.is_file()
    ) if CHUNKS_DIR.exists() else 0
    print(f"\nEspaço em data/chunks/:       {total_bytes / 1_048_576:.1f} MB")

    summary = {
        "total_docs_processados": n_docs,
        "total_filhos":           n_filhos,
        "total_pais":             n_pais,
        "media_chunks_por_doc":   round(media, 2),
        "distribuicao_tipo":      stats_tipo,
        "doc_mais_chunks":        {"ato_id": max_doc[0], "chunks": max_doc[1]},
        "doc_menos_chunks": {
            "ato_id": min_doc[0],
            "chunks": int(min_doc[1]) if min_doc[1] < float("inf") else 0,
        },
        "docs_truncados":  n_trunc,
        "tempo_segundos":  round(elapsed, 1),
        "espaco_MB":       round(total_bytes / 1_048_576, 1),
    }
    SUMMARY_FILE.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print("Sumário salvo em data/chunk_summary.json")
    if n_trunc:
        print(f"Log de truncamentos em data/chunks_truncados.json ({n_trunc} entradas)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="Chunking hierárquico em 2 níveis para o corpus ANEEL."
    )
    parser.add_argument("--ano",    type=int, nargs="+", help="Processar apenas estes anos.")
    parser.add_argument("--limite", type=int,             help="Limitar a N documentos.")
    parser.add_argument("--teste",  action="store_true",  help="5 docs representativos.")
    args = parser.parse_args()

    if args.teste:
        run_teste()
    else:
        run(anos=args.ano, limite=args.limite)


if __name__ == "__main__":
    main()
