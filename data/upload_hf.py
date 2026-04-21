#!/usr/bin/env python3
"""
Upload do corpus ANEEL para o Hugging Face Hub.

Uso:
    python data/upload_hf.py
    python data/upload_hf.py --token SEU_TOKEN
    python data/upload_hf.py --dry-run      # valida sem enviar

Dependências:
    pip install datasets huggingface_hub

Token de acesso (qualquer uma das opções abaixo):
    - Argumento --token
    - Variável de ambiente HF_TOKEN
    - Arquivo .env na raiz do projeto com a linha: HF_TOKEN=hf_...
    - Arquivo hf_token.txt na raiz do projeto
"""

import argparse
import glob
import json
import os
import sys
from pathlib import Path

REPO_ID = "JvPetas/aneel-legislacao"
CORPUS_DIR = Path(__file__).parent / "corpus"


def carregar_token(token_arg):
    if token_arg:
        return token_arg

    # Variável de ambiente
    token = os.getenv("HF_TOKEN")
    if token:
        return token

    raiz = Path(__file__).parent.parent

    # Arquivo .env
    env_file = raiz / ".env"
    if env_file.exists():
        for linha in env_file.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha.startswith("HF_TOKEN="):
                return linha.split("=", 1)[1].strip()

    # Arquivo hf_token.txt
    token_file = raiz / "hf_token.txt"
    if token_file.exists():
        return token_file.read_text(encoding="utf-8").strip()

    return None


def carregar_corpus():
    arquivos = sorted(glob.glob(str(CORPUS_DIR / "**" / "*.json"), recursive=True))
    if not arquivos:
        print(f"Erro: nenhum arquivo encontrado em {CORPUS_DIR}", file=sys.stderr)
        sys.exit(1)

    print(f"Carregando {len(arquivos):,} arquivos do corpus...")
    documentos = []
    erros = 0

    for i, fp in enumerate(arquivos, 1):
        if i % 5000 == 0 or i == len(arquivos):
            pct = i / len(arquivos) * 100
            print(f"  {i:,}/{len(arquivos):,} arquivos lidos  ({pct:.0f}%)...", flush=True)
        try:
            with open(fp, encoding="utf-8") as f:
                documentos.append(json.load(f))
        except Exception as e:
            erros += 1
            print(f"  [AVISO] Erro ao ler {fp}: {e}", file=sys.stderr)

    if erros:
        print(f"  {erros} arquivo(s) com erro ignorados.", file=sys.stderr)

    return documentos


DATASET_CARD = """\
---
language:
- pt
license: cc0-1.0
task_categories:
- text-classification
- text-generation
- summarization
pretty_name: ANEEL Legislação (2016, 2021, 2022)
size_categories:
- 10K<n<100K
tags:
- legislation
- regulatory
- energy
- brazil
- aneel
---

# ANEEL Legislação — Corpus NLP

Corpus de documentos legislativos e regulatórios publicados pela
**ANEEL** (Agência Nacional de Energia Elétrica), cobrindo os anos
**2016, 2021 e 2022**.

## Estatísticas

| Métrica | Valor |
|---------|-------|
| Documentos | 27.060 |
| Caracteres extraídos | ~357 milhões |
| Anos cobertos | 2016, 2021, 2022 |
| Score qualidade 1.0 | 97,2% dos documentos |
| Formato | JSON estruturado |

## Tipos de documento

| Tipo | Quantidade |
|------|-----------|
| texto_integral | 18.676 |
| voto | 6.979 |
| nota_tecnica | 781 |
| anexo | 344 |
| decisao | 273 |
| outro | 7 |

## Campos por documento

| Campo | Tipo | Descrição |
|-------|------|-----------|
| `ato_id` | str | Identificador do ato regulatório |
| `tipo_documento` | str | Categoria do documento |
| `titulo` | str | Título completo |
| `ementa` | str | Ementa do ato |
| `assunto` | str | Tema principal |
| `situacao` | str | Situação vigente |
| `publicacao` | str | Data de publicação |
| `autor` | str | Órgão/relator |
| `ano` | int | Ano do documento (2016, 2021 ou 2022) |
| `texto` | str | Texto integral extraído |
| `tem_tabela` | bool | Documento contém tabelas |
| `paginas` | int | Número de páginas |
| `qualidade_score` | float | Score de qualidade de extração (0–1) |
| `caracteres_extraidos` | int | Comprimento do texto extraído |

## Uso

```python
from datasets import load_dataset

ds = load_dataset("JvPetas/aneel-legislacao")

# Filtrar por ano
docs_2016 = ds["train"].filter(lambda x: x["ano"] == 2016)

# Filtrar por tipo
resolucoes = ds["train"].filter(lambda x: x["tipo_documento"] == "texto_integral")
```

## Fonte

Documentos obtidos do portal público da ANEEL:
https://www2.aneel.gov.br/biblioteca/legislacao.cfm
"""


def main():
    parser = argparse.ArgumentParser(
        description="Upload do corpus ANEEL para o Hugging Face Hub."
    )
    parser.add_argument("--token", help="Token de acesso do Hugging Face (HF_TOKEN)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Carrega e valida o corpus localmente sem fazer upload",
    )
    parser.add_argument(
        "--repo-id",
        default=REPO_ID,
        help=f"ID do repositório de destino (padrão: {REPO_ID})",
    )
    args = parser.parse_args()

    token = carregar_token(args.token)

    if not token and not args.dry_run:
        print(
            "Erro: token do Hugging Face não encontrado.\n"
            "Forneça via:\n"
            "  --token hf_...\n"
            "  variável de ambiente HF_TOKEN=hf_...\n"
            "  arquivo .env  com a linha  HF_TOKEN=hf_...\n"
            "  arquivo hf_token.txt na raiz do projeto",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        from datasets import Dataset
        from huggingface_hub import DatasetCard
    except ImportError:
        print(
            "Erro: biblioteca 'datasets' não instalada.\n"
            "Rode: pip install datasets huggingface_hub",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Carregamento ────────────────────────────────────────────────────────
    documentos = carregar_corpus()
    print(f"\nTotal: {len(documentos):,} documentos carregados")

    if args.dry_run:
        print("\n[DRY-RUN] Corpus válido. Nenhum upload realizado.")
        print(f"Destino configurado: https://huggingface.co/datasets/{args.repo_id}")
        return

    # ── Criação do dataset ───────────────────────────────────────────────────
    print("\nCriando objeto Dataset...")
    ds = Dataset.from_list(documentos)
    print(f"Dataset: {ds}")

    # ── Upload ───────────────────────────────────────────────────────────────
    print(f"\nIniciando upload para huggingface.co/datasets/{args.repo_id}")
    print("(pode demorar alguns minutos dependendo da conexão)\n")

    ds.push_to_hub(
        repo_id=args.repo_id,
        token=token,
        commit_message="feat: corpus ANEEL 27.060 documentos (2016/2021/2022)",
    )

    # ── Dataset card ─────────────────────────────────────────────────────────
    print("\nAtualizando card do dataset...")
    card = DatasetCard(DATASET_CARD)
    card.push_to_hub(repo_id=args.repo_id, token=token)

    # ── Resultado ─────────────────────────────────────────────────────────────
    url = f"https://huggingface.co/datasets/{args.repo_id}"
    print("\n" + "=" * 60)
    print("Upload concluído com sucesso!")
    print(f"URL: {url}")
    print(f'Uso: load_dataset("{args.repo_id}")')
    print("=" * 60)


if __name__ == "__main__":
    main()
