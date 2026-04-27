"""
Converte chunks filhos (JSON) para chunks_hierarquicos.parquet e envia ao HF.

Uso:
    python data/json_to_parquet.py
"""
import json
import os
import re
import sys

import pandas as pd
from dotenv import load_dotenv
from huggingface_hub import HfApi
from tqdm import tqdm

# ─── Configurações ────────────────────────────────────────────────────────────
BASE_FILHOS = "data/chunks/filhos"
OUT_PARQUET = "data/chunks_hierarquicos.parquet"
HF_REPO     = "JvPetas/aneel-legislacao"

NB2_CAMPOS = [
    "texto", "texto_pai", "ato_id", "tipo_documento", "titulo",
    "ementa", "assunto", "situacao", "publicacao", "autor",
    "ano", "contexto_juridico", "arquivo_origem",
]

# ─── Token HF ─────────────────────────────────────────────────────────────────
load_dotenv()
HF_TOKEN = os.environ.get("HF_TOKEN", "")
if not HF_TOKEN:
    print("AVISO: HF_TOKEN não encontrado no .env — upload será pulado.")

# ─── Coleta arquivos ──────────────────────────────────────────────────────────
print(f"Varrendo {BASE_FILHOS}...")
arquivos = []
for ano in sorted(os.listdir(BASE_FILHOS)):
    ano_path = os.path.join(BASE_FILHOS, ano)
    if not os.path.isdir(ano_path):
        continue
    for nome in os.listdir(ano_path):
        if nome.endswith(".json"):
            arquivos.append(os.path.join(ano_path, nome))

print(f"  {len(arquivos):,} arquivos encontrados\n")

# ─── Leitura e conversão ──────────────────────────────────────────────────────
registros = []
erros = 0

for caminho in tqdm(arquivos, desc="Lendo filhos", unit="chunk"):
    try:
        with open(caminho, encoding="utf-8") as f:
            filho = json.load(f)
    except Exception as e:
        erros += 1
        if erros <= 5:
            print(f"\n  ERRO ao ler {caminho}: {e}")
        continue

    # Deriva arquivo_origem a partir do chunk_id
    chunk_id = filho.get("chunk_id", "")
    if chunk_id:
        arquivo_origem = re.sub(r"_c\d+$", "", chunk_id)
    else:
        # Fallback: stem do nome do arquivo JSON
        arquivo_origem = os.path.splitext(os.path.basename(caminho))[0]
        arquivo_origem = re.sub(r"_c\d+$", "", arquivo_origem)

    filho["arquivo_origem"] = arquivo_origem
    registros.append(filho)

print(f"\n  Lidos: {len(registros):,} | Erros: {erros}")

# ─── Monta DataFrame ──────────────────────────────────────────────────────────
df = pd.DataFrame(registros)

# Garante que ano seja int (pode vir como str em alguns JSONs)
if "ano" in df.columns:
    df["ano"] = pd.to_numeric(df["ano"], errors="coerce").fillna(0).astype(int)

# ─── Relatório ────────────────────────────────────────────────────────────────
print(f"\n{'='*60}")
print(f"Total de chunks convertidos: {len(df):,}")

print("\nDistribuição por tipo_documento:")
for tipo, count in df["tipo_documento"].value_counts().items():
    pct = count / len(df) * 100
    print(f"  {tipo:20} {count:>8,}  ({pct:5.1f}%)")

print("\nVerificação de campos esperados pelo Notebook 2:")
ausentes = []
for campo in NB2_CAMPOS:
    presente = campo in df.columns
    status = "OK" if presente else "AUSENTE"
    print(f"  [{status}] {campo}")
    if not presente:
        ausentes.append(campo)

if ausentes:
    print(f"\n  AVISO: campos ausentes: {ausentes}")
    print("  Adicionando com valor vazio...")
    for campo in ausentes:
        df[campo] = ""

# ─── Salva parquet ────────────────────────────────────────────────────────────
print(f"\nSalvando em {OUT_PARQUET}...")
df.to_parquet(OUT_PARQUET, compression="snappy", index=False)
size_mb = os.path.getsize(OUT_PARQUET) / 1e6
print(f"  Tamanho: {size_mb:.1f} MB")

# ─── Upload para HF ───────────────────────────────────────────────────────────
if HF_TOKEN:
    print(f"\nEnviando para {HF_REPO}...")
    api = HfApi(token=HF_TOKEN)
    api.upload_file(
        path_or_fileobj=OUT_PARQUET,
        path_in_repo="chunks_hierarquicos.parquet",
        repo_id=HF_REPO,
        repo_type="dataset",
    )
    remote_size = size_mb
    print(f"  Upload concluido: chunks_hierarquicos.parquet ({remote_size:.1f} MB)")
else:
    print("\nUpload pulado (HF_TOKEN ausente).")

print(f"\n{'='*60}")
print("CONCLUIDO.")
print(f"  Parquet local : {OUT_PARQUET} ({size_mb:.1f} MB)")
print(f"  Chunks totais : {len(df):,}")
print(f"  Colunas       : {list(df.columns)}")
