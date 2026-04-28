#!/usr/bin/env python3
"""
Prepara o ambiente local baixando artefatos do HuggingFace.

Uso: python data/setup.py
"""

import os
import sys
import tarfile
from pathlib import Path

# ─── Caminhos ─────────────────────────────────────────────────────────────────
DATA_DIR    = Path(__file__).parent          # data/
PROJECT_DIR = DATA_DIR.parent               # raiz do projeto

HF_REPO         = 'JvPetas/aneel-legislacao'
QDRANT_TAR_NAME = 'qdrant_storage.tar.gz'
PARQUET_NAME    = 'chunks_hierarquicos.parquet'

QDRANT_TAR   = DATA_DIR / QDRANT_TAR_NAME
QDRANT_DIR   = DATA_DIR / 'qdrant_storage'
PARQUET_PATH = DATA_DIR / PARQUET_NAME


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _pip_install(*pkgs):
    os.system(f'{sys.executable} -m pip install {" ".join(pkgs)} -q')


def _mb(path: Path) -> float:
    return path.stat().st_size / 1e6


def _banner(text: str):
    print(f'\n--- {text} ---')


# ─── Etapas ───────────────────────────────────────────────────────────────────

def verificar_env() -> str | None:
    """Verifica .env e retorna HF_TOKEN (ou None se ausente)."""
    env_file = PROJECT_DIR / '.env'
    if not env_file.exists():
        print('[AVISO] .env não encontrado em', PROJECT_DIR)
        return None

    from dotenv import load_dotenv
    load_dotenv(env_file)

    hf_token = os.environ.get('HF_TOKEN', '').strip()
    groq_key  = os.environ.get('GROQ_API_KEY', '').strip()

    print('[OK]    HF_TOKEN:     ' + ('encontrado' if hf_token else 'NÃO encontrado (usando acesso público)'))
    print('[OK]    GROQ_API_KEY: ' + ('encontrado' if groq_key  else 'NÃO encontrado — necessário para rag.py'))

    return hf_token or None


def baixar_qdrant(hf_token: str | None) -> bool:
    """Baixa e extrai qdrant_storage.tar.gz."""

    # Já extraído
    if QDRANT_DIR.exists() and any(QDRANT_DIR.iterdir()):
        print('[PULAR] data/qdrant_storage/ já existe — pulando download e extração')
        return True

    # Tar já baixado — só extrair
    if QDRANT_TAR.exists() and _mb(QDRANT_TAR) > 10:
        print(f'[INFO]  qdrant_storage.tar.gz já existe ({_mb(QDRANT_TAR):.1f} MB) — pulando download')
    else:
        print('[1/2]  Baixando qdrant_storage.tar.gz do HuggingFace...')
        try:
            from huggingface_hub import hf_hub_download
            hf_hub_download(
                repo_id=HF_REPO,
                filename=QDRANT_TAR_NAME,
                repo_type='dataset',
                token=hf_token,
                local_dir=str(DATA_DIR),
                local_dir_use_symlinks=False,
            )
            print(f'       Baixado: {_mb(QDRANT_TAR):.1f} MB')
        except Exception as e:
            print(f'[ERRO]  Falha ao baixar {QDRANT_TAR_NAME}: {e}')
            return False

    # Extração
    print('[1/2]  Extraindo qdrant_storage.tar.gz...')
    try:
        with tarfile.open(QDRANT_TAR, 'r:gz') as tar:
            tar.extractall(path=DATA_DIR)
        print(f'[OK]   Qdrant extraído em {QDRANT_DIR}')
        # Mantém o tar para evitar re-download
        return True
    except tarfile.TarError as e:
        print(f'[ERRO]  Falha na extração: {e}')
        print('        O arquivo pode estar corrompido. Delete-o e execute novamente.')
        return False


def baixar_parquet(hf_token: str | None) -> bool:
    """Baixa chunks_hierarquicos.parquet."""

    if PARQUET_PATH.exists():
        print(f'[PULAR] data/chunks_hierarquicos.parquet já existe ({_mb(PARQUET_PATH):.1f} MB) — pulando download')
        return True

    print('[2/2]  Baixando chunks_hierarquicos.parquet do HuggingFace...')
    try:
        from huggingface_hub import hf_hub_download
        hf_hub_download(
            repo_id=HF_REPO,
            filename=PARQUET_NAME,
            repo_type='dataset',
            token=hf_token,
            local_dir=str(DATA_DIR),
            local_dir_use_symlinks=False,
        )
        print(f'[OK]   Parquet baixado: {_mb(PARQUET_PATH):.1f} MB')
        return True
    except Exception as e:
        print(f'[ERRO]  Falha ao baixar {PARQUET_NAME}: {e}')
        return False


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print('=' * 60)
    print('  Setup do Pipeline RAG — ANEEL Legislação')
    print('=' * 60)

    # Garante dependências mínimas antes de importar dotenv/huggingface_hub
    try:
        import dotenv  # noqa: F401
    except ImportError:
        print('[INFO]  Instalando python-dotenv...')
        _pip_install('python-dotenv')

    try:
        import huggingface_hub  # noqa: F401
    except ImportError:
        print('[INFO]  Instalando huggingface_hub...')
        _pip_install('huggingface-hub')

    _banner('Verificando .env')
    hf_token = verificar_env()

    _banner('Configurando Qdrant')
    qdrant_ok = baixar_qdrant(hf_token)

    _banner('Configurando Parquet')
    parquet_ok = baixar_parquet(hf_token)

    # Resumo
    print('\n' + '=' * 60)
    print('  Resumo')
    print('=' * 60)
    print(f'  Qdrant storage:  {"[OK]   " if qdrant_ok  else "[ERRO] "} data/qdrant_storage/')
    print(f'  Parquet chunks:  {"[OK]   " if parquet_ok else "[ERRO] "} data/chunks_hierarquicos.parquet')

    if qdrant_ok and parquet_ok:
        print('\n  Tudo pronto! Execute:')
        print('    python data/rag.py                  (modo interativo)')
        print('    python data/rag.py "sua pergunta"   (resposta direta)')
    elif qdrant_ok or parquet_ok:
        print('\n  Setup parcial — verifique os erros acima.')
    else:
        print('\n  Setup falhou — verifique a conexão e o HF_TOKEN.')
    print('=' * 60)


if __name__ == '__main__':
    main()
