# Análise de Falhas Definitivas de Download — ANEEL

Gerado em: 2026-04-09
Script de retry: `data/retry_failed.py`

---

## Resumo Executivo

| Métrica | Valor |
|---------|-------|
| URLs com falha inicial (`failed.txt`) | 467 |
| Já presentes em `downloaded.txt` (ignoradas) | 432 |
| Realmente pendentes para retry | 35 |
| Recuperados com sucesso no retry | 0 |
| Falhas definitivas (`failed_final.txt`) | **35** |
| Tipo de erro | 100% HTTP 404 |

Das 467 URLs marcadas como falha no download principal, **432 (92,5%)** já constavam
em `downloaded.txt` — provavelmente foram baixadas com sucesso em execuções anteriores
ou no próprio script principal após a gravação de `failed.txt`. As 35 restantes
retornaram HTTP 404 em todas as tentativas.

---

## Distribuição por Tipo de Erro

| Código de erro | Quantidade | Descrição |
|----------------|------------|-----------|
| `HTTP_404_nao_encontrado` | 35 | Recurso não existe no servidor |

Todos os arquivos retornaram 404 imediatamente na primeira tentativa, sem qualquer
flutuação de disponibilidade. Isso indica que os documentos foram **removidos ou nunca
existiram** no servidor `www2.aneel.gov.br/cedoc/`.

---

## Distribuição por Ano

| Ano | Arquivos com 404 | % do total de falhas |
|-----|-----------------|----------------------|
| 2016 | 14 | 40,0% |
| 2021 | 3 | 8,6% |
| 2022 | 18 | 51,4% |
| **Total** | **35** | **100%** |

---

## Distribuição por Tipo de Documento

| Prefixo | Tipo de documento | Quantidade |
|---------|-------------------|------------|
| `area` | Ato de Retificação / Errata de Ato | 10 |
| `adsp` | Adendo a Despacho | 8 |
| `aprt` | Adendo a Portaria | 4 |
| `rea` | Retificação de Ato | 3 |
| `areh` | Ato de Retificação de REN/Nota | 3 |
| `reh` | Retificação de REN | 1 |
| `prt` | Portaria | 1 |
| `nreh` | Nota Técnica REN | 1 |
| `ndsp` | Nota a Despacho | 1 |
| `edsp` | Errata de Despacho | 1 |
| `dsp` | Despacho (adendo) | 1 |
| `aarea` | Adendo a Errata | 1 |

**Observação:** a maioria dos 404s são documentos secundários (adendos, erratas,
retificações) — não os atos normativos principais. Os documentos principais (REN, DSP
sem prefixo, RES) foram coletados com sucesso.

---

## Impacto no Corpus

- **Total de URLs nos metadados:** ~27.025
- **Arquivos baixados com sucesso:** ~26.990
- **Falhas definitivas:** 35
- **Taxa de cobertura efetiva:** **99,87%**

Os 35 arquivos ausentes representam documentos acessórios (erratas e adendos).
O corpus principal está íntegro para fins de análise NLP.

---

## URLs com Falha Definitiva

Todas as URLs abaixo retornaram HTTP 404:

### 2016 (14 arquivos)

```
http://www2.aneel.gov.br/cedoc/areh20162130_1.pdf
http://www2.aneel.gov.br/cedoc/adsp20162229_1.pdf
http://www2.aneel.gov.br/cedoc/adsp20162063_1.pdf
http://www2.aneel.gov.br/cedoc/adsp20161895_1.pdf
http://www2.aneel.gov.br/cedoc/aprt20164000_1.pdf
http://www2.aneel.gov.br/cedoc/aprt20163999_1.pdf
http://www2.aneel.gov.br/cedoc/adsp20161316_1.pdf
http://www2.aneel.gov.br/cedoc/rea20165831_1.pdf
http://www2.aneel.gov.br/cedoc/reh20162073_1.pdf
http://www2.aneel.gov.br/cedoc/aprt20163960_1.pdf
http://www2.aneel.gov.br/cedoc/area20165736_.pdf
http://www2.aneel.gov.br/cedoc/rea20165669_1.pdf
http://www2.aneel.gov.br/cedoc/adsp2016304_1.pdf
http://aneel.gov.br/cedoc/prt20163819.pdf
```

### 2021 (3 arquivos)

```
https://www2.aneel.gov.br/cedoc/areh20212995_1.pdf
http://www2.aneel.gov.br/cedoc/nreh20212957.pdf
http://www2.aneel.gov.br/cedoc/adsp2021181.pdf
```

### 2022 (18 arquivos)

```
https://www2.aneel.gov.br/cedoc/adsp20223720_1.pdf
http://www2.aneel.gov.br/cedoc/ndsp20223576.pdf
https://www2.aneel.gov.br/cedoc/areh20223164xlsm.pdf
http://www2.aneel.gov.br/cedoc/edsp20223348.pdf
https://www2.aneel.gov.br/cedoc/area2022112011_1.pdf
https://www2.aneel.gov.br/cedoc/aarea202212035_1.pdf
https://www2.aneel.gov.br/cedoc/area202211917_1.pdf
http://www2.aneel.gov.br/cedoc/adsp2022960_1.pdf
https://www2.aneel.gov.br/cedoc/rea202211647_1.pdf
https://www2.aneel.gov.br/cedoc/area202211728_1.pdf
https://www2.aneel.gov.br/cedoc/area202211729_1.pdf
https://www2.aneel.gov.br/cedoc/area202211730_1.pdf
https://www2.aneel.gov.br/cedoc/area202211731_1.pdf
https://www2.aneel.gov.br/cedoc/area202211297_1.pdf
https://www2.aneel.gov.br/cedoc/area202211314_1ti.pdf
https://www2.aneel.gov.br/cedoc/area202211225_1.pdf
http://www2.aneel.gov.br/cedoc/dsp2022366_1.pdf
https://www2.aneel.gov.br/cedoc/aprt2022028_1.pdf
```

---

## Recomendação

Não é necessária nova tentativa de download. Os 35 arquivos com 404 são documentos
secundários que provavelmente foram removidos do portal ANEEL (possivelmente
incorporados ao documento principal ou descontinuados). O corpus está pronto para
a etapa de parsing em lote com **99,87% de cobertura**.

Se for necessário recuperar algum documento específico, recomenda-se busca manual
no portal da ANEEL (`biblioteca.aneel.gov.br`) pelo número do processo associado.
