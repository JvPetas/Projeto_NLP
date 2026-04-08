"""
Script para download dos documentos legislativos da ANEEL.
Lê os metadados dos JSONs na raiz do projeto e baixa os arquivos
organizados por ano, com controle de progresso e retentativas.

Dependências: curl_cffi
    pip install curl_cffi
"""

import json
import os
import random
import time
from pathlib import Path

from curl_cffi import requests as cffi_requests

# ---------------------------------------------------------------------------
# Configuração de caminhos
# ---------------------------------------------------------------------------

# Raiz do projeto: pasta pai de data/
ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT / "data"
PDFS_DIR = DATA_DIR / "pdfs"
DOWNLOADED_FILE = DATA_DIR / "downloaded.txt"
FAILED_FILE = DATA_DIR / "failed.txt"

JSON_FILES = {
    "2016": ROOT / "biblioteca_aneel_gov_br_legislacao_2016_metadados.json",
    "2021": ROOT / "biblioteca_aneel_gov_br_legislacao_2021_metadados.json",
    "2022": ROOT / "biblioteca_aneel_gov_br_legislacao_2022_metadados.json",
}

# Configurações de download
MAX_RETRIES = 3
DELAY_MIN = 1.0  # segundos
DELAY_MAX = 3.0  # segundos
TIMEOUT = 60      # segundos por requisição

# Headers que imitam um navegador real
HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Funções auxiliares
# ---------------------------------------------------------------------------

def carregar_urls_baixadas() -> set:
    """Lê o arquivo downloaded.txt e retorna um conjunto com as URLs já baixadas."""
    if not DOWNLOADED_FILE.exists():
        return set()
    with open(DOWNLOADED_FILE, "r", encoding="utf-8") as f:
        return {linha.strip() for linha in f if linha.strip()}


def registrar_baixado(url: str) -> None:
    """Acrescenta uma URL ao arquivo downloaded.txt."""
    with open(DOWNLOADED_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def registrar_falha(url: str) -> None:
    """Acrescenta uma URL ao arquivo failed.txt."""
    with open(FAILED_FILE, "a", encoding="utf-8") as f:
        f.write(url + "\n")


def tamanho_pasta(caminho: Path) -> int:
    """Retorna o tamanho total em bytes de todos os arquivos dentro de um diretório."""
    total = 0
    for arquivo in caminho.rglob("*"):
        if arquivo.is_file():
            total += arquivo.stat().st_size
    return total


def formatar_bytes(n: int) -> str:
    """Converte bytes para uma string legível (KB, MB, GB)."""
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n:.1f} PB"


def coletar_tarefas() -> list[dict]:
    """
    Lê os 3 JSONs e monta uma lista de dicionários com as informações
    de cada arquivo a ser baixado:
        {ano, url, nome_arquivo}

    Estrutura dos JSONs:
        { "YYYY-MM-DD": { "registros": [ { "pdfs": [...] } ] } }
    """
    tarefas = []

    for ano, caminho_json in JSON_FILES.items():
        if not caminho_json.exists():
            print(f"[AVISO] JSON não encontrado: {caminho_json}")
            continue

        with open(caminho_json, "r", encoding="utf-8") as f:
            dados = json.load(f)

        # Itera sobre cada data do ano (ex.: "2016-12-30")
        for entrada in dados.values():
            # Cada data tem uma lista "registros" com os documentos daquele dia
            for doc in entrada.get("registros", []):
                for item in doc.get("pdfs", []):
                    url = item.get("url", "").strip()
                    nome_arquivo = item.get("arquivo", "").strip()

                    if not url:
                        continue

                    # Se o JSON não tiver nome de arquivo, deriva da URL
                    if not nome_arquivo:
                        nome_arquivo = url.split("/")[-1].split("?")[0] or "arquivo"

                    tarefas.append({
                        "ano": ano,
                        "url": url,
                        "nome_arquivo": nome_arquivo,
                    })

    return tarefas


def baixar_arquivo(url: str, destino: Path) -> bool:
    """
    Tenta baixar um arquivo com curl_cffi impersonando o Chrome 120.
    Retorna True em caso de sucesso, False em caso de falha.
    Faz até MAX_RETRIES tentativas com espera exponencial entre elas.
    """
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resposta = cffi_requests.get(
                url,
                headers=HEADERS,
                impersonate="chrome120",
                timeout=TIMEOUT,
                allow_redirects=True,
            )

            if resposta.status_code == 200:
                destino.parent.mkdir(parents=True, exist_ok=True)
                with open(destino, "wb") as f:
                    f.write(resposta.content)
                return True

            print(f"    HTTP {resposta.status_code} na tentativa {tentativa}/{MAX_RETRIES}")

        except Exception as e:
            print(f"    Erro na tentativa {tentativa}/{MAX_RETRIES}: {e}")

        # Espera exponencial entre tentativas (2s, 4s, 8s...)
        if tentativa < MAX_RETRIES:
            time.sleep(2 ** tentativa)

    return False


# ---------------------------------------------------------------------------
# Execução principal
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Download de legislação ANEEL")
    print("=" * 60)

    # Garante que as pastas de destino existam
    for ano in JSON_FILES:
        (PDFS_DIR / ano).mkdir(parents=True, exist_ok=True)

    # Carrega todas as tarefas e filtra as já baixadas
    print("\nLendo metadados dos JSONs...")
    tarefas = coletar_tarefas()
    total_geral = len(tarefas)
    print(f"Total de arquivos nos metadados: {total_geral:,}")

    urls_baixadas = carregar_urls_baixadas()
    pendentes = [t for t in tarefas if t["url"] not in urls_baixadas]

    ja_baixados = total_geral - len(pendentes)
    print(f"Já baixados anteriormente:       {ja_baixados:,}")
    print(f"Pendentes nesta sessão:          {len(pendentes):,}")

    if not pendentes:
        print("\nNada a fazer. Todos os arquivos já foram baixados.")
        return

    print("\nIniciando downloads...\n")

    baixados_sessao = 0
    falhas_sessao = 0

    for i, tarefa in enumerate(pendentes, start=1):
        url = tarefa["url"]
        ano = tarefa["ano"]
        nome_arquivo = tarefa["nome_arquivo"]
        destino = PDFS_DIR / ano / nome_arquivo

        # Progresso
        restantes = len(pendentes) - i + 1
        print(
            f"[{i:>6}/{len(pendentes)}] "
            f"Baixados: {baixados_sessao}  Falhas: {falhas_sessao}  "
            f"Restantes: {restantes}"
        )
        print(f"  -> {nome_arquivo}")
        print(f"     {url}")

        # Pula se o arquivo já existir no disco (mesmo sem estar no downloaded.txt)
        if destino.exists():
            registrar_baixado(url)
            baixados_sessao += 1
            print("     [OK] Arquivo já existe no disco. Pulando.")
            continue

        sucesso = baixar_arquivo(url, destino)

        if sucesso:
            registrar_baixado(url)
            baixados_sessao += 1
            print(f"     [OK] Salvo em: {destino.relative_to(ROOT)}")
        else:
            registrar_falha(url)
            falhas_sessao += 1
            print(f"     [FALHA] URL adicionada a failed.txt")

        # Delay aleatório entre requisições
        if i < len(pendentes):
            espera = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(espera)

    # Resumo final
    print("\n" + "=" * 60)
    print("  RESUMO FINAL")
    print("=" * 60)
    print(f"  Baixados nesta sessão : {baixados_sessao:,}")
    print(f"  Falhas nesta sessão   : {falhas_sessao:,}")
    print(f"  Total já no disco     : {ja_baixados + baixados_sessao:,} / {total_geral:,}")

    espaco = tamanho_pasta(PDFS_DIR)
    print(f"  Espaço ocupado        : {formatar_bytes(espaco)}")

    if falhas_sessao > 0:
        print(f"\n  URLs com falha salvas em: {FAILED_FILE.relative_to(ROOT)}")
        print("  Rode o script novamente para retentar os arquivos que falharam.")

    print("=" * 60)


if __name__ == "__main__":
    main()
