# Legislação ANEEL — Coleta e Processamento NLP

Projeto de coleta e análise textual dos documentos legislativos publicados pela ANEEL (Agência Nacional de Energia Elétrica), cobrindo os anos de 2016, 2021 e 2022.

## Estrutura do projeto

```
Projeto_NLP/
├── biblioteca_aneel_gov_br_legislacao_2016_metadados.json
├── biblioteca_aneel_gov_br_legislacao_2021_metadados.json
├── biblioteca_aneel_gov_br_legislacao_2022_metadados.json
├── data/
│   ├── download.py               # script de coleta principal
│   ├── retry_failed.py           # retry para URLs com falha
│   ├── failed_final_analysis.md  # análise de impacto das falhas definitivas
│   └── pdfs/                     # arquivos baixados (ignorado pelo git)
│       ├── 2016/
│       ├── 2021/
│       └── 2022/
├── .gitignore
└── README.md
```

Os arquivos JSON na raiz contêm os metadados de cada documento (título, número, data, tipo e links para download). São gerados em etapa anterior de raspagem do portal da ANEEL.

## Dependências

Python 3.10 ou superior.

```bash
pip install curl_cffi
```

> O portal da ANEEL utiliza Cloudflare com verificação de TLS fingerprint. A biblioteca `curl_cffi` com impersonação de navegador é necessária para contornar esse bloqueio de forma legítima durante a coleta de dados públicos.

## Como rodar

```bash
# A partir da raiz do projeto
python data/download.py
```

O script:
- Lê os metadados dos 3 JSONs na raiz do projeto
- Verifica quais URLs já foram baixadas (`data/downloaded.txt`)
- Baixa apenas os arquivos pendentes, com 3 tentativas por URL
- Aguarda entre 1 e 3 segundos entre cada requisição
- Registra falhas em `data/failed.txt`
- Exibe progresso em tempo real e um resumo ao final

Para retentar arquivos que falharam, basta rodar o script novamente — ele pula automaticamente o que já foi baixado com sucesso.

## Etapas do projeto

### Etapa 1: Coleta de documentos

Script `data/download.py` — baixa os ~27.000 documentos a partir dos metadados JSON.

### Etapa 1.1: Retry de downloads com falha (`data/retry_failed.py`)

Script que relê `data/failed.txt`, tenta baixar cada URL com até 5 tentativas
(delay 3–8s, timeout 90s) e classifica as falhas permanentes.

**Resultado:** das 467 URLs com falha inicial, 432 já estavam em `downloaded.txt`
(baixadas com sucesso anteriormente). As 35 realmente pendentes retornaram HTTP 404
definitivo — todos documentos secundários (erratas, adendos, retificações).

**Taxa de cobertura final do corpus:** 99,87% (~26.990 de ~27.025 arquivos).

Análise detalhada: `data/failed_final_analysis.md`

---

### Etapa 2: Varredura de PDFs escaneados (`data/scan_pdfs.py`)

Percorre todos os PDFs nas 3 pastas de anos e classifica cada arquivo:
- **`tem_texto`** — PyMuPDF extraiu mais de 50 caracteres
- **`escaneado`** — menos de 50 caracteres (imagem sem camada de texto, requer OCR)

Suporta pausar e continuar via `data/scan_progress.txt`. Resultado em
`data/scan_report.json` com totais por ano e percentual de escaneados.

```bash
python data/scan_pdfs.py
```

---

### Etapa 3: Teste de parsing em amostra representativa (`data/test_sample/`)

Antes de processar o corpus completo, 15 arquivos representativos foram selecionados
para validar o pipeline de parsing. A amostra cobre:
- PDFs com texto corrido (2016 e 2022)
- PDFs com tabelas sem bordas (detecção por padrão de espaçamento)
- PDF de grande porte (>500 KB, múltiplas páginas)
- PDF pequeno (<50 KB)
- PDF de 2016 para verificação de encoding
- Tipos distintos: DSP (Despacho) e REN (Resolução Normativa)
- Arquivo HTML e arquivo ZIP
- PDFs com conteúdo misto (texto + tabela + texto na mesma página)
- 2 PDFs aleatórios de 2021

**Arquivos:**
- `data/test_sample/sample_files.json` — lista dos 15 arquivos selecionados
- `data/test_sample/test_parsing.py` — script de teste (PyMuPDF + detecção por regex)
- `data/test_sample/relatorio_teste.md` — resultados e recomendações

**Estratégia de detecção de tabelas:** as tabelas do corpus ANEEL não possuem bordas
visíveis. A detecção usa as posições x,y das palavras extraídas pelo PyMuPDF: quando
o gap horizontal entre palavras adjacentes supera 15 pontos tipográficos, é inserido
um separador de coluna. Blocos com 3+ linhas consecutivas e 2+ colunas são convertidos
para Markdown.

**Resultado:** 1 PDF digitalizado identificado (`nreh20223128.pdf`) — candidato a OCR
condicional via `scan_report.json` no pipeline final.

---

### Etapa 3.1: OCR para PDFs escaneados (`data/ocr_scanned.py`)

Os 9 PDFs identificados pelo `scan_pdfs.py` como escaneados (sem camada de texto)
são processados por OCR com Tesseract, gerando documentos no mesmo formato do `parse.py`.

**Estratégia:**
- Cada página é renderizada como imagem JPEG a 300 DPI via `pdf2image` (Poppler)
- Tesseract aplica OCR com modelo de língua portuguesa (`--lang por --psm 1`)
- A confiança média do Tesseract por página é registrada no campo `confianca_ocr`
- Texto extraído passa pelas mesmas 3 camadas de limpeza do `parse.py`
- Documentos gerados incluem `"ocr": true` para identificação downstream

**Campos extras no JSON de saída:**
- `ocr: true` — marca o documento como produto de OCR
- `confianca_ocr` — média de confiança Tesseract (0–100) sobre todas as páginas

```bash
python data/ocr_scanned.py                                    # todos os 9
python data/ocr_scanned.py --arquivos nreh20223128.pdf        # arquivo específico
python data/ocr_scanned.py --dpi 200                          # resolução menor
python data/ocr_scanned.py --poppler-path "C:/poppler/bin"    # caminho do Poppler
```

Dependências: `pip install pytesseract pdf2image`

Binários externos obrigatórios:
- **Tesseract-OCR** com pacote de língua portuguesa: https://github.com/UB-Mannheim/tesseract/wiki
- **Poppler** (Windows): https://github.com/oschwartz10612/poppler-windows/releases/

Saídas: `data/corpus/{ano}/{arquivo}_ocr_{tipo}.json`, `data/ocr_errors.json`,
`data/ocr_summary.json`

Após esta etapa o corpus fica 100% completo (todos os documentos com texto
extraível cobertos).

---

### Etapa 6: Chunking hierárquico em 2 níveis (`data/chunk.py`)

Divide o corpus de 27.060 documentos em chunks para uso em pipelines de RAG.

**Estratégia:**
- **Chunk filho (256 tokens):** unidade de indexação vetorial — retrieval preciso
- **Chunk pai (512 tokens):** contexto enviado ao LLM — filho anterior + atual + seguinte

**Divisão por tipo de documento:**

| Tipo | Estratégia |
|------|-----------|
| `texto_integral` | Marcadores jurídicos (`Art.`, `§`, `CAPÍTULO`, `SEÇÃO`, `Inciso`); cada artigo = 1 filho; sem overlap |
| `voto` | Tamanho fixo; overlap de 50 tokens entre filhos consecutivos |
| `nota_tecnica` | Seções numeradas (`1.`, `1.1`, etc.); tabelas markdown inteiras num chunk próprio; sem overlap |
| `anexo` | Linhas da tabela com cabeçalho repetido em cada chunk; sem overlap |
| `decisao` | Seções fixas (`RELATÓRIO`, `VOTO`, `DECISÃO`, `EMENTA`, `ACÓRDÃO`); sem overlap |

**Saídas:**
- `data/chunks/filhos/{ano}/` — JSONs dos chunks filhos (indexados)
- `data/chunks/pais/{ano}/` — JSONs dos chunks pai (contexto)
- `data/chunk_summary.json` — estatísticas gerais
- `data/chunked.txt` — controle de progresso (permite pausar e continuar)

```bash
python data/chunk.py                    # processa todo o corpus
python data/chunk.py --ano 2016         # apenas 2016
python data/chunk.py --limite 100       # primeiros 100 documentos
python data/chunk.py --teste            # 5 docs representativos com saída detalhada
```

Dependências: `pip install tiktoken`

---

### Etapa 5: Upload para Hugging Face (`data/upload_hf.py`)

Publica o corpus completo no Hugging Face Hub como dataset público.

- **27.060 documentos** públicos da ANEEL (2016, 2021, 2022)
- **~357 milhões de caracteres** extraídos
- **97,2%** dos documentos com score de qualidade máximo (1.0)
- Dataset disponível em: https://huggingface.co/datasets/JvPetas/aneel-legislacao

```python
from datasets import load_dataset

ds = load_dataset("JvPetas/aneel-legislacao")
```

```bash
# Token via .env, hf_token.txt ou variável de ambiente HF_TOKEN
python data/upload_hf.py

# Validar sem fazer upload
python data/upload_hf.py --dry-run
```

Dependências: `pip install datasets huggingface_hub`

---

### Etapa 4: Parsing e extração de texto (`data/parse.py`)

Parser principal do corpus. Para cada documento nos 3 JSONs de metadados, localiza o
arquivo em `data/pdfs/{ano}/`, extrai o texto e gera um JSON estruturado em
`data/corpus/{ano}/`.

**Estratégia de extração:**
- PDFs: PyMuPDF (`fitz`) para texto corrido + detecção de tabelas por posicionamento
  espacial de palavras (gap > 15pt entre palavras = separador de coluna)
- HTMLs: BeautifulSoup4 removendo `nav`, `header`, `footer`, `script`, `style`
- ZIPs: cada PDF interno é processado em memória e vira documento separado

**Limpeza em 3 camadas:**
1. Padrões específicos ANEEL: "Imprimir", "Pág. X de Y", URLs, "CÓPIA NÃO CONTROLADA"
2. Normalização: hifenização, `\xa0`, espaços duplos, quebras excessivas
3. Cabeçalhos/rodapés repetidos: linhas que aparecem em > 30% das páginas

**Score de qualidade por documento (0 a 1):**
- `0.00` — vazio ou escaneado
- `0.50–0.99` — texto com páginas suspeitas (razão alfanumérica < 55%)
- `1.00` — texto limpo e bem estruturado

**9 PDFs escaneados** identificados pelo `scan_report.json` são pulados e registrados
em `data/skipped_scanned.json` para tratamento manual posterior.

```bash
python data/parse.py                          # processa tudo
python data/parse.py --ano 2016               # apenas 2016
python data/parse.py --limite 100             # primeiros 100 arquivos
python data/parse.py --arquivos arq1.pdf arq2.zip  # arquivos específicos
```

Saídas: `data/corpus/{ano}/*.json`, `data/parse_summary.json`,
`data/parse_errors.json`, `data/skipped_scanned.json`, `data/missing_files.json`

Dependências adicionais: `pip install pymupdf beautifulsoup4`

---

## Volume esperado

| Ano  | Documentos |
|------|-----------|
| 2016 | ~9.000    |
| 2021 | ~9.000    |
| 2022 | ~9.000    |
| **Total** | **~27.000** |

O espaço em disco necessário varia conforme o mix de PDFs, HTMLs e ZIPs, mas estimamos entre 10 GB e 40 GB.

## Fontes

Os documentos são obtidos do portal público da ANEEL:
- https://www2.aneel.gov.br/biblioteca/legislacao.cfm
