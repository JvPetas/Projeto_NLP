"""
Script de retry para URLs que falharam no download principal.

Lê data/failed.txt, tenta baixar cada URL com até 5 tentativas,
remove sucessos do failed.txt, e salva falhas permanentes em
data/failed_final.txt com o código/motivo de cada erro.

Dependências: curl_cffi
    pip install curl_cffi

Execução:
    python data/retry_failed.py
"""

import json
import os
import random
import re
import time
from pathlib import Path

from curl_cffi import requests as cffi_requests

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
PDFS_DIR = DATA_DIR / "pdfs"

FAILED_FILE      = DATA_DIR / "failed.txt"
DOWNLOADED_FILE  = DATA_DIR / "downloaded.txt"
FAILED_FINAL     = DATA_DIR / "failed_final.txt"

JSON_FILES = {
    "2016": ROOT / "biblioteca_aneel_gov_br_legislacao_2016_metadados.json",
    "2021": ROOT / "biblioteca_aneel_gov_br_legislacao_2021_metadados.json",
    "2022": ROOT / "biblioteca_aneel_gov_br_legislacao_2022_metadados.json",
}

MAX_RETRIES = 5
DELAY_MIN   = 3.0   # segundos entre tentativas
DELAY_MAX   = 8.0
TIMEOUT     = 90    # segundos por requisição

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


# ---------------------------------------------------------------------------
# Mapeamento URL → (ano, nome_arquivo) a partir dos JSONs de metadados
# ---------------------------------------------------------------------------

def construir_mapa_urls() -> dict[str, tuple[str, str]]:
    """Retorna {url: (ano, nome_arquivo)} para todos os documentos dos metadados."""
    mapa: dict[str, tuple[str, str]] = {}
    for ano, caminho in JSON_FILES.items():
        if not caminho.exists():
            continue
        with open(caminho, encoding="utf-8") as f:
            dados = json.load(f)
        for entrada in dados.values():
            for doc in entrada.get("registros", []):
                for item in doc.get("pdfs", []):
                    url = item.get("url", "").strip()
                    nome = item.get("arquivo", "").strip()
                    if not url:
                        continue
                    if not nome:
                        nome = url.split("/")[-1].split("?")[0] or "arquivo"
                    mapa[url] = (ano, nome)
    return mapa


# ---------------------------------------------------------------------------
# Leitura e normalização de failed.txt
# ---------------------------------------------------------------------------

def ler_urls_falhas() -> list[str]:
    """Lê failed.txt e normaliza entradas malformadas (linhas com URL duplicada)."""
    if not FAILED_FILE.exists():
        return []
    urls = []
    with open(FAILED_FILE, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            if not linha:
                continue
            # Linhas malformadas: "http://  http://url_real"
            ocorrencias = re.findall(r"https?://\S+", linha)
            if ocorrencias:
                urls.append(ocorrencias[-1])  # pega a URL mais à direita (a real)
    return list(dict.fromkeys(urls))   # remove duplicatas mantendo ordem


# ---------------------------------------------------------------------------
# Utilitários de I/O
# ---------------------------------------------------------------------------

def carregar_set(caminho: Path) -> set[str]:
    if not caminho.exists():
        return set()
    with open(caminho, encoding="utf-8") as f:
        return {l.strip() for l in f if l.strip()}


def acrescentar_linha(caminho: Path, linha: str) -> None:
    with open(caminho, "a", encoding="utf-8") as f:
        f.write(linha + "\n")


def reescrever_failed(urls_restantes: list[str]) -> None:
    """Substitui failed.txt apenas com as URLs que ainda não foram resolvidas."""
    with open(FAILED_FILE, "w", encoding="utf-8") as f:
        for url in urls_restantes:
            f.write(url + "\n")


def formatar_bytes(n: int) -> str:
    for unidade in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unidade}"
        n /= 1024
    return f"{n:.1f} PB"


# ---------------------------------------------------------------------------
# Classificação de erros
# ---------------------------------------------------------------------------

def classificar_erro(status: int | None, exc: str) -> str:
    """Retorna uma etiqueta de motivo de falha."""
    if status == 404:
        return "HTTP_404_nao_encontrado"
    if status == 403:
        return "HTTP_403_acesso_negado"
    if status == 429:
        return "HTTP_429_rate_limit"
    if status is not None and status >= 500:
        return f"HTTP_{status}_erro_servidor"
    if status is not None and status != 200:
        return f"HTTP_{status}"
    exc_lower = exc.lower()
    if "timeout" in exc_lower or "timed out" in exc_lower:
        return "timeout"
    if "ssl" in exc_lower or "certificate" in exc_lower:
        return "erro_ssl"
    if "connection" in exc_lower or "connect" in exc_lower:
        return "erro_conexao"
    return "erro_desconhecido"


# ---------------------------------------------------------------------------
# Download com retry
# ---------------------------------------------------------------------------

def baixar_com_retry(
    url: str, destino: Path
) -> tuple[bool, str]:
    """
    Tenta baixar a URL com até MAX_RETRIES tentativas.
    Retorna (sucesso, motivo_falha).
    motivo_falha é vazio string em caso de sucesso.
    """
    ultimo_status: int | None = None
    ultimo_erro = ""

    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            resp = cffi_requests.get(
                url,
                headers=HEADERS,
                impersonate="chrome120",
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            ultimo_status = resp.status_code

            if resp.status_code == 200:
                destino.parent.mkdir(parents=True, exist_ok=True)
                with open(destino, "wb") as f:
                    f.write(resp.content)
                return True, ""

            print(f"      HTTP {resp.status_code} — tentativa {tentativa}/{MAX_RETRIES}")

            # 404/403 definitivos: não adianta retentar
            if resp.status_code in (404, 403):
                break

        except Exception as exc:
            ultimo_erro = str(exc)
            print(f"      Erro na tentativa {tentativa}/{MAX_RETRIES}: {exc}")

        if tentativa < MAX_RETRIES:
            espera = random.uniform(DELAY_MIN, DELAY_MAX)
            print(f"      Aguardando {espera:.1f}s antes da próxima tentativa...")
            time.sleep(espera)

    return False, classificar_erro(ultimo_status, ultimo_erro)


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main() -> None:
    print("=" * 65)
    print("  Retry de downloads com falha — ANEEL")
    print("=" * 65)

    # Carrega mapeamento de URLs conhecidas
    print("\nLendo metadados dos JSONs...")
    mapa_urls = construir_mapa_urls()
    print(f"  URLs mapeadas: {len(mapa_urls):,}")

    # Lê e normaliza failed.txt
    urls_falha = ler_urls_falhas()
    if not urls_falha:
        print("\nfailed.txt está vazio ou não existe. Nada a fazer.")
        return

    print(f"\nURLs a processar: {len(urls_falha)}")

    urls_ja_baixadas = carregar_set(DOWNLOADED_FILE)
    urls_pendentes = [u for u in urls_falha if u not in urls_ja_baixadas]
    print(f"  Já baixadas (ignorando): {len(urls_falha) - len(urls_pendentes)}")
    print(f"  Realmente pendentes:     {len(urls_pendentes)}")

    if not urls_pendentes:
        print("\nTodas as URLs do failed.txt já constam em downloaded.txt.")
        reescrever_failed([])
        return

    print(f"\nIniciando retry com até {MAX_RETRIES} tentativas e "
          f"delay {DELAY_MIN:.0f}–{DELAY_MAX:.0f}s...\n")

    recuperados = 0
    falhas_finais: list[tuple[str, str]] = []   # (url, motivo)
    urls_ainda_pendentes: list[str] = []         # URLs que falharam novamente

    for i, url in enumerate(urls_pendentes, start=1):
        nome_arquivo = url.split("/")[-1].split("?")[0] or "arquivo"
        print(f"[{i:>4}/{len(urls_pendentes)}] {nome_arquivo}")
        print(f"          {url}")

        # Determina destino a partir do mapeamento; fallback: extrai ano da URL
        if url in mapa_urls:
            ano, nome_arquivo = mapa_urls[url]
        else:
            m = re.search(r"(2016|2021|2022)", url)
            ano = m.group(1) if m else "outros"
            # nome_arquivo já derivado acima

        destino = PDFS_DIR / ano / nome_arquivo

        # Arquivo já existe no disco
        if destino.exists():
            print("          [OK] Arquivo já existe no disco.")
            acrescentar_linha(DOWNLOADED_FILE, url)
            recuperados += 1
            continue

        sucesso, motivo = baixar_com_retry(url, destino)

        if sucesso:
            acrescentar_linha(DOWNLOADED_FILE, url)
            recuperados += 1
            print(f"          [OK] Salvo em: {destino.relative_to(ROOT)}")
        else:
            falhas_finais.append((url, motivo))
            urls_ainda_pendentes.append(url)
            print(f"          [FALHA DEFINITIVA] motivo: {motivo}")

        if i < len(urls_pendentes):
            espera = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(espera)

    # Atualiza failed.txt (remove os que foram resolvidos)
    reescrever_failed(urls_ainda_pendentes)

    # Grava failed_final.txt com motivo de erro
    if falhas_finais:
        with open(FAILED_FINAL, "w", encoding="utf-8") as f:
            for url, motivo in falhas_finais:
                f.write(f"{motivo}\t{url}\n")

    # ---------------------------------------------------------------------------
    # Resumo final
    # ---------------------------------------------------------------------------
    print("\n" + "=" * 65)
    print("  RESUMO")
    print("=" * 65)
    print(f"  Recuperados com sucesso : {recuperados:>4}")
    print(f"  Falhas definitivas      : {len(falhas_finais):>4}")

    if falhas_finais:
        from collections import Counter
        contagem = Counter(motivo for _, motivo in falhas_finais)
        print("\n  Distribuição de erros:")
        for motivo, cnt in contagem.most_common():
            print(f"    {motivo:<35} {cnt:>4}")
        print(f"\n  Falhas gravadas em: {FAILED_FINAL.relative_to(ROOT)}")

    if recuperados > 0:
        espaco = sum(
            f.stat().st_size for f in PDFS_DIR.rglob("*") if f.is_file()
        )
        print(f"\n  Espaço total em disco: {formatar_bytes(espaco)}")

    print("=" * 65)


if __name__ == "__main__":
    main()
