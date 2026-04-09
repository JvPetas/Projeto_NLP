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
