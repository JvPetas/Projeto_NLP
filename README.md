# Legislação ANEEL — Coleta e Processamento NLP

Projeto de coleta e análise textual dos documentos legislativos publicados pela ANEEL (Agência Nacional de Energia Elétrica), cobrindo os anos de 2016, 2021 e 2022.

## Estrutura do projeto

```
Projeto_NLP/
├── biblioteca_aneel_gov_br_legislacao_2016_metadados.json
├── biblioteca_aneel_gov_br_legislacao_2021_metadados.json
├── biblioteca_aneel_gov_br_legislacao_2022_metadados.json
├── data/
│   ├── download.py        # script de coleta
│   └── pdfs/              # arquivos baixados (ignorado pelo git)
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
