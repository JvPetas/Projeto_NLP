#!/usr/bin/env python3
"""
Pipeline RAG completo para consulta à legislação da ANEEL.

Uso interativo: python data/rag.py
Uso direto:     python data/rag.py "Quais penalidades para distribuidoras?"
"""

import os
import sys
import re
import time
import numpy as np
from pathlib import Path

# ─── Configurações ────────────────────────────────────────────────────────────
_BASE = Path(__file__).parent  # data/

QDRANT_PATH     = str(_BASE / 'qdrant_storage')
PARQUET_PATH    = str(_BASE / 'chunks_hierarquicos.parquet')
COLLECTION_NAME = 'aneel_legislacao'
EMBEDDING_MODEL = 'intfloat/multilingual-e5-large-instruct'
RERANKER_MODEL  = 'cross-encoder/mmarco-mMiniLMv2-L12-H384-v1'
TOP_K_DENSE     = 20
TOP_K_SPARSE    = 20
TOP_K_RERANK    = 5
ALPHA_RRF       = 0.6
TIPO_BOOST = {
    'texto_integral': 1.20,
    'nota_tecnica':   1.05,
    'anexo':          1.05,
    'decisao':        1.00,
    'voto':           0.90,
    'outro':          0.85,
}
GROQ_MODEL = 'llama-3.3-70b-versatile'

SYSTEM_PROMPT = (
    'Você é um especialista em regulação do setor elétrico brasileiro.\n'
    'Responda APENAS com base nos trechos fornecidos.\n'
    'Cite obrigatoriamente: título do ato, número e data em cada afirmação.\n'
    'Se a informação não estiver nos trechos, diga explicitamente que '
    'não encontrou nos documentos consultados.\n'
    'Priorize texto_integral e decisao sobre voto e nota_tecnica.\n'
    'Se um documento estiver REVOGADO, sinalize claramente.'
)

# Stopwords mínimas PT-BR — preserva acentuação e termos jurídicos
_STOPWORDS = {
    'a', 'o', 'e', 'de', 'do', 'da', 'em', 'no', 'na', 'um', 'uma',
    'os', 'as', 'dos', 'das', 'que', 'para', 'com', 'por', 'ao', 'à',
    'se', 'sua', 'seu', 'suas', 'seus', 'mas', 'ou', 'ser', 'foi',
    'ele', 'ela', 'eles', 'elas', 'este', 'essa', 'isso', 'pelo', 'pela',
}

# ─── Estado global (inicializado em init()) ───────────────────────────────────
_groq     = None
_embed    = None
_reranker = None
_qdrant   = None
_df       = None
_bm25     = None


# ─── Inicialização ────────────────────────────────────────────────────────────

def _carregar_env() -> str:
    """Carrega .env e retorna GROQ_API_KEY; encerra se ausente."""
    env_file = _BASE.parent / '.env'
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)

    key = os.environ.get('GROQ_API_KEY', '').strip()
    if not key:
        print('[ERRO] GROQ_API_KEY não encontrado no .env')
        print('       Configure a chave e execute novamente.')
        sys.exit(1)
    return key


def init():
    """Inicializa todos os componentes do pipeline. Roda uma vez ao carregar."""
    global _groq, _embed, _reranker, _qdrant, _df, _bm25

    # Qdrant deve existir — guia para setup se ausente
    if not Path(QDRANT_PATH).exists():
        print('[ERRO] data/qdrant_storage/ não encontrado.')
        print('       Execute primeiro: python data/setup.py')
        sys.exit(1)

    groq_key = _carregar_env()

    print('Carregando pipeline RAG...')

    # Embedding
    print(f'  [1/4] Embedding: {EMBEDDING_MODEL}')
    import torch
    from sentence_transformers import SentenceTransformer
    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    _embed = SentenceTransformer(EMBEDDING_MODEL, device=device)
    _embed.max_seq_length = 384

    # Qdrant
    print(f'  [2/4] Qdrant local: {QDRANT_PATH}')
    from qdrant_client import QdrantClient
    _qdrant = QdrantClient(path=QDRANT_PATH)
    n_pontos = _qdrant.get_collection(COLLECTION_NAME).points_count

    # Parquet + BM25
    print(f'  [3/4] BM25 ({PARQUET_PATH})')
    import pandas as pd
    _df = pd.read_parquet(PARQUET_PATH)
    corpus_tokens = [_tokenize(t) for t in _df['texto'].tolist()]
    from rank_bm25 import BM25Okapi
    _bm25 = BM25Okapi(corpus_tokens)

    # Reranker
    print(f'  [4/4] Reranker: {RERANKER_MODEL}')
    from sentence_transformers import CrossEncoder
    _reranker = CrossEncoder(RERANKER_MODEL, max_length=512, device=device)

    # Cliente Groq
    from groq import Groq
    _groq = Groq(api_key=groq_key)

    print(f'\nPipeline pronto — {n_pontos:,} pontos no Qdrant | {len(_df):,} chunks no BM25\n')


# ─── Tokenização ──────────────────────────────────────────────────────────────

def _tokenize(text: str) -> list:
    """Tokenização PT-BR: lowercase, preserva acentuação, remove stopwords."""
    text = (text or '').lower()
    text = re.sub(r"[^\w\sáéíóúâêîôûãõàèìòùçñ]", ' ', text)
    return [t for t in text.split() if len(t) > 2 and t not in _STOPWORDS]


# ─── Retrieval ────────────────────────────────────────────────────────────────

def _encode_query(pergunta: str) -> list:
    """Embedding da pergunta com prefixo de instrução do e5-instruct."""
    prompt = (
        'Instruct: Given a question about Brazilian electric sector regulations, '
        'retrieve relevant legal passages\n'
        f'Query: {pergunta}'
    )
    return _embed.encode(prompt, normalize_embeddings=True).tolist()


def _dense_search(pergunta: str, tipo_filter=None) -> list:
    """Dense retrieval no Qdrant com filtro opcional por tipo_documento."""
    from qdrant_client.models import Filter, FieldCondition, MatchAny
    q_emb = _encode_query(pergunta)
    filtro = None
    if tipo_filter:
        filtro = Filter(must=[
            FieldCondition(key='tipo_documento', match=MatchAny(any=tipo_filter))
        ])
    results = _qdrant.query_points(
        collection_name=COLLECTION_NAME,
        query=q_emb,
        limit=TOP_K_DENSE,
        query_filter=filtro,
        with_payload=True,
    ).points
    return [(r.id, r.score, r.payload) for r in results]


def _sparse_search(pergunta: str) -> list:
    """BM25 retrieval sobre o corpus completo."""
    tokens = _tokenize(pergunta)
    if not tokens:
        return []
    scores = _bm25.get_scores(tokens)
    top_idx = np.argpartition(scores, -TOP_K_SPARSE)[-TOP_K_SPARSE:]
    top_idx = top_idx[np.argsort(scores[top_idx])[::-1]]
    out = []
    for idx in top_idx:
        if scores[idx] <= 0:
            continue
        row = _df.iloc[int(idx)]
        payload = row.to_dict()
        if 'ano' in payload:
            payload['ano'] = int(payload['ano'])
        out.append((int(idx), float(scores[idx]), payload))
    return out


def _rrf_fuse(dense: list, sparse: list, k: int = 60) -> list:
    """Reciprocal Rank Fusion com peso ALPHA_RRF para dense e 1-ALPHA_RRF para sparse."""
    scores, payloads = {}, {}
    for rank, (idx, _, payload) in enumerate(dense):
        scores[idx] = scores.get(idx, 0.0) + ALPHA_RRF / (k + rank + 1)
        payloads[idx] = payload
    for rank, (idx, _, payload) in enumerate(sparse):
        scores[idx] = scores.get(idx, 0.0) + (1 - ALPHA_RRF) / (k + rank + 1)
        payloads.setdefault(idx, payload)
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return [(idx, score, payloads[idx]) for idx, score in fused]


def _rerank(pergunta: str, candidatos: list) -> list:
    """Cross-encoder com boost por tipo_documento. Retorna top TOP_K_RERANK."""
    if not candidatos:
        return []
    pairs = [(pergunta, c[2].get('texto', '')) for c in candidatos]
    raw = _reranker.predict(pairs, batch_size=32, show_progress_bar=False)
    boosted = []
    for (idx, _, payload), s in zip(candidatos, raw):
        boost = TIPO_BOOST.get(payload.get('tipo_documento', ''), 1.0)
        boosted.append((idx, float(s) * boost, payload, float(s)))
    boosted.sort(key=lambda x: x[1], reverse=True)
    return boosted[:TOP_K_RERANK]


def _expandir_por_ato(reranked: list) -> list:
    """
    Se o top resultado for voto ou nota_tecnica, adiciona o texto_integral
    do mesmo ato_id ao conjunto (expansão contextual).
    """
    if not reranked:
        return reranked
    extras, seen_ids, seen_atos = [], {r[0] for r in reranked}, set()
    for entry in reranked[:3]:
        ato_id = entry[2].get('ato_id')
        tipo   = entry[2].get('tipo_documento', '')
        if tipo in ('voto', 'nota_tecnica') and ato_id and ato_id not in seen_atos:
            seen_atos.add(ato_id)
            mask = (
                (_df['ato_id'] == ato_id) &
                (_df['tipo_documento'] == 'texto_integral')
            )
            for _, row in _df[mask].head(1).iterrows():
                extra_idx = int(row.name)
                if extra_idx not in seen_ids:
                    payload = row.to_dict()
                    if 'ano' in payload:
                        payload['ano'] = int(payload['ano'])
                    extras.append((extra_idx, 0.0, payload, 0.0))
                    seen_ids.add(extra_idx)
    return reranked + extras


def hybrid_retrieve(pergunta: str, tipo_filter=None) -> list:
    """
    Pipeline de recuperação híbrida completo.

    Dense + BM25 → RRF (alpha=ALPHA_RRF) → boost por tipo →
    reranking cross-encoder → expansão por ato_id → top TOP_K_RERANK.

    Retorna lista de tuplas (idx, score_boosted, payload, score_raw).
    """
    dense    = _dense_search(pergunta, tipo_filter)
    sparse   = _sparse_search(pergunta)
    fused    = _rrf_fuse(dense, sparse)[:TOP_K_DENSE]
    reranked = _rerank(pergunta, fused)
    reranked = _expandir_por_ato(reranked)
    return reranked[:TOP_K_RERANK]


# ─── Geração ──────────────────────────────────────────────────────────────────

def _formatar_contexto(chunks: list) -> str:
    """Monta o contexto estruturado para o LLM usando texto_pai de cada chunk."""
    blocos = []
    for i, entry in enumerate(chunks, 1):
        p = entry[2]
        texto = p.get('texto_pai') or p.get('texto', '')
        bloco = (
            f"━━━ DOCUMENTO {i} ━━━\n"
            f"Título:      {p.get('titulo', '')}\n"
            f"Tipo:        {p.get('tipo_documento', '').upper()}\n"
            f"Publicação:  {p.get('publicacao', '')}\n"
            f"Situação:    {p.get('situacao', '')}\n"
            f"Localização: {p.get('contexto_juridico', '')}\n"
            f"\nTRECHO:\n{texto}\n"
        )
        blocos.append(bloco)
    return '\n'.join(blocos)


def ask(pergunta: str, verbose: bool = False) -> str:
    """
    Executa o pipeline RAG completo e retorna a resposta formatada.
    Se verbose=True, exibe os chunks recuperados antes da resposta.
    """
    chunks = hybrid_retrieve(pergunta)

    if verbose:
        print('\n--- Chunks recuperados ---')
        for i, entry in enumerate(chunks, 1):
            p = entry[2]
            print(
                f"  {i}. [{p.get('tipo_documento', '?'):14}] "
                f"{str(p.get('ato_id', ''))[:30]:30} | "
                f"{p.get('publicacao', '')} | score={entry[1]:.3f}"
            )
        print()

    if not chunks:
        return 'Não encontrei documentos relevantes para esta pergunta no acervo.'

    contexto = _formatar_contexto(chunks)
    user_msg = (
        f"DOCUMENTOS RECUPERADOS:\n\n{contexto}\n\n"
        f"{'═' * 50}\n"
        f"PERGUNTA: {pergunta}\n\n"
        "Responda com base exclusivamente nos documentos acima, citando as fontes."
    )

    try:
        resp = _groq.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user',   'content': user_msg},
            ],
            max_tokens=1024,
            temperature=0.1,
        )
        resposta = resp.choices[0].message.content
    except Exception as e:
        return f'Erro ao consultar o modelo: {e}'

    sep = '=' * 60
    return f'\n{sep}\n{resposta}\n{sep}'


# ─── Interface de linha de comando ────────────────────────────────────────────

_AJUDA = """
Comandos:
  sair / exit   — encerra o programa
  verbose       — alterna exibição dos chunks recuperados
  ajuda         — exibe esta mensagem
"""

_BANNER = """
╔══════════════════════════════════════════════════════════╗
║   RAG — Legislação ANEEL                                 ║
║   Modelo: Llama 3.3 70B via Groq                         ║
║   Digite 'ajuda' para ver os comandos disponíveis.       ║
╚══════════════════════════════════════════════════════════╝
"""


def _loop_interativo():
    print(_BANNER)
    verbose = False
    while True:
        try:
            pergunta = input('Pergunta: ').strip()
        except (EOFError, KeyboardInterrupt):
            print('\nEncerrando. Até logo!')
            break

        if not pergunta:
            continue

        cmd = pergunta.lower()
        if cmd in ('sair', 'exit'):
            print('Encerrando. Até logo!')
            break
        if cmd == 'verbose':
            verbose = not verbose
            print(f'Modo verbose: {"ATIVADO" if verbose else "DESATIVADO"}')
            continue
        if cmd == 'ajuda':
            print(_AJUDA)
            continue

        t0 = time.time()
        resposta = ask(pergunta, verbose=verbose)
        elapsed = time.time() - t0
        print(resposta)
        print(f'[{elapsed:.1f}s]\n')


def main():
    init()

    # Modo linha de comando: python data/rag.py "pergunta aqui"
    if len(sys.argv) > 1:
        pergunta = ' '.join(sys.argv[1:])
        print(ask(pergunta, verbose=False))
        return

    # Modo interativo
    _loop_interativo()


if __name__ == '__main__':
    main()
