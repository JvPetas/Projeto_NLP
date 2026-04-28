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
                                                  (HuggingFace — público)
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

Os chunks do pipeline estão publicados publicamente em:

**[huggingface.co/datasets/JvPetas/aneel-legislacao](https://huggingface.co/datasets/JvPetas/aneel-legislacao)**

| Arquivo | Descrição |
|---|---|
| `chunks_hierarquicos.parquet` | 429.206 chunks prontos para embedding (202 MB) |

---

## Como rodar (Google Colab — recomendado)

### 1. Chaves de API necessárias

Obtenha as chaves gratuitamente:

| Chave | Onde obter | Obrigatória? |
|---|---|---|
| `GROQ_API_KEY` | [console.groq.com/keys](https://console.groq.com/keys) | Sim (LLM) |
| `MARITACA_API_KEY` | [plataforma.maritaca.ai](https://plataforma.maritaca.ai/chaves-api) | Opcional |

### 2. Configure os secrets no Colab

Em cada notebook, vá em **Secrets** (ícone de chave no menu lateral esquerdo) e adicione:

```
GROQ_API_KEY      → sua chave Groq
MARITACA_API_KEY  → sua chave Maritaca (opcional)
```

### 3. Execute os notebooks em ordem

> **Atenção:** Faça upload de cada notebook no Colab antes de rodar.
> Ative GPU em `Runtime > Change runtime type > T4 GPU` antes do Notebook 2.

#### Notebook 1 — Chunking (PULAR — artefatos já no HuggingFace)
Os chunks já estão disponíveis publicamente em `JvPetas/aneel-legislacao`. Não é necessário rodar.

#### Notebook 2 — Embeddings + Indexação Qdrant (~25 min com GPU T4)

```
notebooks/02 embeddings indexacao.ipynb
```

- Baixa os chunks automaticamente do HuggingFace
- Gera embeddings com `multilingual-e5-large-instruct`
- Cria e indexa a coleção Qdrant em disco
- **Requer GPU T4** (`Runtime > Change runtime type > T4 GPU`)

#### Notebook 3 — Pipeline RAG

```
notebooks/03 rag pipeline.ipynb
```

- Restaura o índice Qdrant gerado no Notebook 2
- Monta o Google Drive para carregar o `qdrant_storage.tar.gz`
- Executa retrieval híbrido (dense + BM25 + RRF + reranking)
- Use `ask("sua pergunta")` para consultar o sistema

> O Notebook 3 lê o `qdrant_storage` gerado pelo Notebook 2.
> Se estiver numa sessão nova do Colab, salve o `qdrant_storage.tar.gz` no seu Google Drive
> na pasta `aneel_rag` antes de rodar o Notebook 3.

#### Notebook 4 — Avaliação com RAGAS

```
notebooks/04 avaliacao.ipynb
```

- Avalia o pipeline com benchmark RAGAS
- Métricas: Faithfulness, Answer Relevancy, Context Precision

---

## Fluxo completo resumido

```
Colab (sem GPU):  Notebook 1  →  chunks_hierarquicos.parquet  →  HuggingFace
                                        [já disponível — pular]

Colab (GPU T4):   Notebook 2  →  embeddings + Qdrant indexado  →  qdrant_storage/

Colab:            Notebook 3  →  RAG pipeline pronto para consultas

Colab:            Notebook 4  →  avaliação RAGAS
```

---

## Reproduzir do zero (pipeline completo)

Para refazer todo o pipeline desde a coleta:

```bash
# 1. Coleta dos PDFs (~27.000 documentos)
python data/download.py

# 2. Varredura: identifica PDFs escaneados
python data/scan_pdfs.py

# 3. Parsing: extrai texto de PDFs, HTMLs e ZIPs
python data/parse.py

# 4. OCR nos PDFs escaneados
python data/ocr_scanned.py

# 5. Upload do corpus bruto para o HuggingFace
python data/upload_hf.py

# 6. Chunking hierárquico
# → notebooks/01 chunking hierarquico.ipynb  (~35 min, sem GPU)

# 7. Conversão dos chunks JSON → parquet + upload HF
python data/json_to_parquet.py

# 8. Embeddings + indexação Qdrant
# → notebooks/02 embeddings indexacao.ipynb  (~25 min, GPU T4)

# 9. Pipeline RAG
# → notebooks/03 rag pipeline.ipynb

# 10. Avaliação
# → notebooks/04 avaliacao.ipynb
```

---

## Estrutura do repositório

```
Projeto_NLP/
├── data/
│   ├── download.py               # coleta dos PDFs via curl_cffi
│   ├── retry_failed.py           # retry para URLs com falha
│   ├── scan_pdfs.py              # identifica PDFs escaneados
│   ├── parse.py                  # parsing PDF/HTML/ZIP → JSON
│   ├── ocr_scanned.py            # OCR com Tesseract para PDFs escaneados
│   ├── upload_hf.py              # publica corpus no HuggingFace
│   ├── chunk.py                  # chunking hierárquico (filho + pai)
│   ├── json_to_parquet.py        # converte chunks JSON → parquet + upload HF
│   └── test_sample/
│       └── test_parsing.py       # validação da qualidade do parsing
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
Elimina latência de rede e custo de API. O storage serializado em disco pode ser
comprimido e salvo para restauração em qualquer ambiente sem re-indexação.

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
