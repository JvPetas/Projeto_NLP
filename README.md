# Pipeline RAG — Legislação ANEEL

Sistema de Recuperação e Geração Aumentada (RAG) sobre o acervo legislativo da
ANEEL (Agência Nacional de Energia Elétrica), cobrindo os anos de 2016, 2021 e 2022.

Dado uma pergunta em linguagem natural sobre regulação do setor elétrico brasileiro,
o sistema recupera os trechos mais relevantes da legislação e gera uma resposta
fundamentada, com citação obrigatória da fonte (ato normativo, tipo de documento,
data de publicação).

---

## Arquitetura

```
PDFs / HTMLs / ZIPs          Corpus JSON             Chunks (filho + pai)
da ANEEL (27.060 docs)  →   data/corpus/       →    data/chunks/
     ↓                           ↓                        ↓
download.py              parse.py + ocr_scanned.py     chunk.py
                                                         ↓
                                                  chunks_hierarquicos.parquet
                                                  (HuggingFace + local)
                                                         ↓
                                              embeddings (e5-large-instruct)
                                              + indexação Qdrant (local)
                                                         ↓
                                         retrieval híbrido (dense + BM25 + RRF)
                                         + reranking (cross-encoder mMiniLM)
                                         + expansão por ato_id
                                                         ↓
                                              LLM (Maritaca Sabiá-3 / Groq Llama)
                                                         ↓
                                               resposta com citação de fonte
```

### Componentes principais

| Etapa | Ferramenta | Detalhe |
|---|---|---|
| Coleta | `curl_cffi` | Impersonação de navegador para contornar Cloudflare |
| Parsing | PyMuPDF + BeautifulSoup4 | PDF, HTML, ZIP; detecção de tabelas sem bordas |
| OCR | Tesseract + pdf2image | 9 PDFs escaneados, 300 DPI, língua portuguesa |
| Chunking | tiktoken | Hierárquico 2 níveis, estratégia por tipo de documento |
| Embeddings | `intfloat/multilingual-e5-large-instruct` | 1024 dims, normalizado |
| Índice vetorial | Qdrant (local) | Filtros por tipo, situação, ato_id, ano |
| Sparse retrieval | BM25Okapi | Tokenização preserva termos jurídicos |
| Fusão | Reciprocal Rank Fusion (RRF) | α = 0,6 (semântico) + 0,4 (BM25) |
| Reranking | `mmarco-mMiniLMv2-L12-H384-v1` | Cross-encoder multilíngue com PT-BR |
| LLM | Maritaca Sabiá-3 / Groq Llama 3.3 70B | Gratuitos, prompt jurídico estruturado |
| Avaliação | RAGAS | Faithfulness, Answer Relevancy, Context Precision |

---

## Corpus

| Métrica | Valor |
|---|---|
| Documentos | 27.060 |
| Chunks filhos (indexados) | 429.206 |
| Caracteres extraídos | ~357 milhões |
| Score de qualidade máximo (1.0) | 97,2% dos documentos |
| Cobertura do acervo | 99,87% |
| Anos cobertos | 2016, 2021, 2022 |

**Distribuição dos chunks por tipo:**

| Tipo | Chunks | % |
|---|---|---|
| texto_integral | 182.953 | 42,6% |
| voto | 155.910 | 36,3% |
| nota_tecnica | 73.711 | 17,2% |
| anexo | 11.398 | 2,7% |
| decisao | 5.154 | 1,2% |
| outro | 80 | 0,0% |

---

## Dataset HuggingFace

O corpus e os artefatos do pipeline estão publicados publicamente em:

**[huggingface.co/datasets/JvPetas/aneel-legislacao](https://huggingface.co/datasets/JvPetas/aneel-legislacao)**

```python
from datasets import load_dataset

ds = load_dataset("JvPetas/aneel-legislacao")
```

Artefatos disponíveis no repositório do dataset:

| Arquivo | Descrição |
|---|---|
| `chunks_hierarquicos.parquet` | 429.206 chunks prontos para embedding (201,9 MB) |
| `qdrant_storage.tar.gz` | Índice vetorial Qdrant já indexado |
| `relatorio_avaliacao.json` | Resultados do benchmark RAGAS |

---

## Como rodar

### Pré-requisitos

```
Python 3.10+
Token HuggingFace (leitura): HF_TOKEN no arquivo .env
Chave API Groq (gratuita):   console.groq.com
Chave API Maritaca (opcional): plataforma.maritaca.ai
```

Crie `.env` na raiz do projeto:

```
HF_TOKEN=seu_token_aqui
GROQ_API_KEY=sua_chave_aqui
MARITACA_API_KEY=sua_chave_aqui
```

---

### Opção A — Usar artefatos prontos do HuggingFace (recomendado)

Os notebooks 1 e 3 detectam automaticamente se os artefatos já existem no HF
e os baixam antes de executar. Basta rodar a partir do Notebook 3:

```
notebooks/03_rag_pipeline.ipynb   ← baixa Qdrant e chunks do HF automaticamente
notebooks/04_avaliacao.ipynb      ← avaliação com RAGAS
```

Tempo estimado: ~5 min (download) + tempo de inferência.

---

### Opção B — Reproduzir do zero

Execute em ordem:

```bash
# 1. Coleta dos PDFs (~27.000 documentos)
python data/download.py

# 2. Varredura: identifica PDFs escaneados
python data/scan_pdfs.py

# 3. Parsing: extrai texto de PDFs, HTMLs e ZIPs
python data/parse.py

# 4. OCR nos 9 PDFs escaneados
python data/ocr_scanned.py

# 5. Upload do corpus bruto para o HuggingFace
python data/upload_hf.py

# 6. Conversão dos chunks JSON → parquet + upload HF
python data/json_to_parquet.py
```

Depois, execute os notebooks em ordem:

```
notebooks/01_chunking_hierarquico.ipynb   (~35 min, sem GPU)
notebooks/02_embeddings_indexacao.ipynb   (~25 min, GPU T4)
notebooks/03_rag_pipeline.ipynb
notebooks/04_avaliacao.ipynb
```

---

## Estrutura do repositório

```
Projeto_NLP/
├── .env                          # tokens (não versionado)
├── data/
│   ├── download.py               # coleta dos PDFs via curl_cffi
│   ├── retry_failed.py           # retry para URLs com falha
│   ├── scan_pdfs.py              # identifica PDFs escaneados
│   ├── parse.py                  # parsing PDF/HTML/ZIP → JSON
│   ├── ocr_scanned.py            # OCR com Tesseract para PDFs escaneados
│   ├── upload_hf.py              # publica corpus no HuggingFace
│   ├── chunk.py                  # chunking hierárquico (filho + pai)
│   ├── json_to_parquet.py        # converte chunks JSON → parquet + upload HF
│   ├── chunks/
│   │   ├── filhos/{ano}/         # JSONs dos chunks filhos (indexados)
│   │   └── pais/{ano}/           # JSONs dos chunks pai (contexto)
│   ├── corpus/{ano}/             # JSONs dos documentos parseados
│   └── pdfs/{ano}/               # PDFs baixados (ignorado pelo git)
├── notebooks/
│   ├── README.md
│   ├── 01 chunking hierarquico.ipynb
│   ├── 02 embeddings indexacao.ipynb
│   ├── 03 rag pipeline.ipynb
│   └── 04 avaliacao.ipynb
└── biblioteca_aneel_gov_br_legislacao_{ano}_metadados.json  (2016/2021/2022)
```

---

## Decisões técnicas

**`curl_cffi` para coleta**
O portal da ANEEL usa Cloudflare com verificação de TLS fingerprint. Requests e httpx
são bloqueados. `curl_cffi` com `impersonate="chrome110"` reproduz o handshake de um
navegador real, permitindo a coleta dos documentos públicos sem intervenção manual.

**Chunking estrutural por tipo de documento**
Textos jurídicos têm estrutura previsível (Art., §, seções numeradas). Dividir
mecanicamente por token quebra artigos no meio e prejudica a recuperação. A estratégia
usa marcadores textuais como fronteiras naturais de chunk, com estratégias diferentes
por tipo (`texto_integral`, `voto`, `nota_tecnica`, `anexo`, `decisao`).

**Hierarquia filho/pai**
O chunk filho (≤ 256 tokens) vai para o índice vetorial — granularidade fina para
retrieval preciso. O chunk pai (≤ 512 tokens, = filho anterior + atual + seguinte) é
o que vai para o LLM — contexto suficiente para uma resposta coesa. Isso resolve o
trade-off entre precisão de busca e qualidade de resposta.

**Qdrant local**
Elimina latência de rede e custo de API. O storage serializado em disco é comprimido
e salvo no HuggingFace, permitindo restauração em qualquer ambiente sem re-indexação.

**Retrieval híbrido + reranking**
Dense search (semântico) recupera bem variações de linguagem; BM25 recupera bem termos
jurídicos exatos (número de resolução, artigo específico). RRF combina os dois rankings
sem normalizar scores. O cross-encoder reranqueia os candidatos fusionados com contexto
completo da query. Boost por tipo de documento reduz o viés de distribuição (votos +
notas técnicas somam 53% do índice mas têm peso reduzido frente a textos normativos
definitivos).

---

## Fontes

Documentos obtidos do portal público da ANEEL:
- https://www2.aneel.gov.br/biblioteca/legislacao.cfm
