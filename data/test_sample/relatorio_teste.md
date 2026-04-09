# Relatório de Teste de Parsing — Corpus ANEEL

Amostra de 15 documentos testados com PyMuPDF (extração de texto).
Detecção de tabelas por posicionamento espacial de palavras: gap > 15pt = separador de coluna,
blocos com ≥ 4 linhas e ≥ 3 colunas (≥ 3 chars cada) são convertidos para Markdown.

## Tabela Resumo

| # | Arquivo | Ano | Tipo | KB | Pág | Chars | Tabelas | Escaneado | Score | Erros |
|---|---------|-----|------|----|-----|-------|---------|-----------|-------|-------|
| 1 | `dsp2016001.pdf` | 2016 | PDF | 181 | 1 | 690 | 0 | Não | 1.00 | Não |
| 2 | `aap2022014ti.pdf` | 2022 | PDF | 73 | 1 | 1,015 | 0 | Não | 1.00 | Não |
| 3 | `ren2016699.pdf` | 2016 | PDF | 280 | 20 | 42,700 | 0 | Não | 1.00 | Não |
| 4 | `ren20221040.pdf` | 2022 | PDF | 152 | 4 | 8,302 | 0 | Não | 1.00 | Não |
| 5 | `nreh20223128.pdf` | 2022 | PDF | 41634 | 52 | 0 | 0 | Sim | 0.00 | Sim |
| 6 | `dsp2016sn207mme.pdf` | 2016 | PDF | 4 | 1 | 765 | 0 | Não | 1.00 | Não |
| 7 | `aap2016001ti.pdf` | 2016 | PDF | 108 | 1 | 1,300 | 0 | Não | 1.00 | Não |
| 8 | `dsp2022016spde.pdf` | 2022 | PDF | 68 | 1 | 812 | 0 | Não | 1.00 | Não |
| 9 | `ren2020900.pdf` | 2021 | PDF | 156 | 1 | 1,652 | 0 | Não | 1.00 | Não |
| 10 | `ren2016699.html` | 2016 | HTML | 209 | 1 | 52,864 | 0 | Não | 1.00 | Não |
| 11 | `aren2016719_2.zip` | 2016 | ZIP | 61647 | 0 | 0 | 0 | Não | 0.00 | Não |
| 12 | `nreh20212869.pdf` | 2021 | PDF | 14426 | 169 | 593,591 | 23 | Não | 1.00 | Não |
| 13 | `area20165887_2.pdf` | 2016 | PDF | 29359 | 705 | 2,889,395 | 726 | Não | 1.00 | Não |
| 14 | `dsp20211907ti.pdf` | 2021 | PDF | 76 | 1 | 1,306 | 0 | Não | 1.00 | Não |
| 15 | `dsp20212581.pdf` | 2021 | PDF | 73 | 1 | 1,164 | 0 | Não | 1.00 | Não |

## Scores de Qualidade e Métricas por Documento

| Arquivo | Score | Densidade (chars/pág) | % Tabela | Pág. Suspeitas | Lixo Removido |
|---------|-------|----------------------|----------|----------------|---------------|
| `dsp2016001.pdf` | 1.00 | 690 | 0.0% | 0 | 0 chars |
| `aap2022014ti.pdf` | 1.00 | 1015 | 0.0% | 0 | 0 chars |
| `ren2016699.pdf` | 1.00 | 2135 | 0.0% | 0 | 0 chars |
| `ren20221040.pdf` | 1.00 | 2076 | 0.0% | 0 | 0 chars |
| `nreh20223128.pdf` | 0.00 | 0 | 0.0% | 0 | 0 chars |
| `dsp2016sn207mme.pdf` | 1.00 | 765 | 0.0% | 0 | 0 chars |
| `aap2016001ti.pdf` | 1.00 | 1300 | 0.0% | 0 | 24 chars |
| `dsp2022016spde.pdf` | 1.00 | 812 | 0.0% | 0 | 0 chars |
| `ren2020900.pdf` | 1.00 | 1652 | 0.0% | 0 | 0 chars |
| `ren2016699.html` | 1.00 | 52864 | 0.0% | 0 | 0 chars |
| `aren2016719_2.zip` | 0.00 | 0 | 0.0% | 0 | 0 chars |
| `nreh20212869.pdf` | 1.00 | 3512 | 4.0% | 0 | 258 chars |
| `area20165887_2.pdf` | 1.00 | 4098 | 97.2% | 0 | 0 chars |
| `dsp20211907ti.pdf` | 1.00 | 1306 | 0.0% | 0 | 0 chars |
| `dsp20212581.pdf` | 1.00 | 1164 | 0.0% | 0 | 0 chars |

## Problemas Encontrados

- **nreh20223128.pdf**: PDF sem camada de texto — provável documento digitalizado. OCR será aplicado condicionalmente via scan_report.json.

## PDFs Digitalizados — Candidatos a OCR

Os arquivos abaixo não retornaram texto via PyMuPDF. No pipeline final, serão registrados em `scan_report.json` para OCR condicional.

- `nreh20223128.pdf`

## Páginas Suspeitas (razão alfanumérica < 60%)

Nenhuma página suspeita encontrada na amostra.

## Recomendações para o Parser Final

- Arquivos ZIP presentes: definir política — extrair PDFs internos ou registrar apenas metadados do conteúdo.
- HTMLs em dois formatos (D*.htm e ren*.html): validar cobertura do parser HTML para ambas as variações de template.
- PDFs > 10 MB presentes: processar por chunks de páginas no pipeline em lote para controlar consumo de memória.
- PDFs digitalizados detectados. OCR condicional com pytesseract/ocrmypdf; candidatos registrados em `scan_report.json`.
- Tabelas detectadas por padrão de espaçamento. Validar amostras manualmente — falsos positivos são possíveis em fórmulas e parágrafos com recuo.

## Limitações Conhecidas

- **Tabelas sem padrão regular de espaçamento**: tabelas com colunas de largura variável ou texto justificado podem não ser detectadas pelo critério de gap > 15pt.
- **Falsos positivos**: listas numeradas, fórmulas matemáticas e parágrafos com recuo largo podem ser interpretados erroneamente como tabelas.
- **PDF digitalizado confirmado**: `nreh20223128.pdf` — 0 chars extraídos. OCR necessário via `scan_report.json` no pipeline final.
- **ZIPs com nomes corrompidos**: filenames com encoding CP437 tratados com `try/except` e fallback para Latin-1; o pipeline não trava.
- **Detecção de cabeçalhos/rodapés em documentos curtos**: requer ≥ 2 ocorrências e ≥ 30% das páginas — pode não funcionar em documentos com menos de 7 páginas.

## Pré-visualização de Texto (primeiros 300 chars)

**dsp2016001.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL DESPACHO N. 1, DE 4 DE JANEIRO DE 2016. O SUPERINTENDENTE DE GESTÃO TARIFÁRIA SUBSTITUTO DA AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA — ANEEL, no uso de suas atribuições que lhe foram delegadas por meio do inciso I do artigo 1º da Portaria nº 2.087, de 7 de fe

**aap2022014ti.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL Processo: 48500.005495/2022-72 AVISO DE AUDIÊNCIA PÚBLICA Nº 014/2022 Texto Original Voto O SUPERINTENDENTE DE MEDIAÇÃO ADMINISTRATIVA, OUVIDORIA SETORIAL E PARTICIPAÇÃO PÚBLICA DA AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA - ANEEL, no uso da competência que lh

**ren2016699.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL RESOLUÇÃO NORMATIVA No 699, DE 26 DE JANEIRO DE 2016 Regulamenta o inciso XIII do art. 3º da Lei nº 9.427, de 26 de dezembro de 1996, que trata dos controles prévio e a posteriori sobre atos e negócios jurídicos entre as concessionárias, permissionárias e

**ren20221040.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA - ANEEL RESOLUÇÃO NORMATIVA ANEEL Nº 1.040, DE 30 DE AGOSTO DE 2022 Altera a Resolução Normativa nº 1.030, de 26 de julho de 2022 que estabelece, dentre outros, os critérios e as condições do programa da Resposta da Demanda. Voto O DIRETOR-GERAL DA AGÊNCIA NACION

**nreh20223128.pdf** (`desconhecido`):
> *(sem texto)*

**dsp2016sn207mme.pdf** (`desconhecido`):
> GABINETE DO MINISTRO DESPACHO DO MINISTRO Em 26 de outubro de 2016 Processo no 48500.003041/2016-19. Interessado: Cemig Geração e Transmissão S.A. Assunto: Requerimento de Prorrogação do Prazo de Concessão da Usina Hidrelétrica denominada UHE Miranda, integrante do Contrato de Concessão no 07/1997- 

**aap2016001ti.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL AVISO DE AUDIÊNCIA PÚBLICA Nº. 001/2016 Texto Original O SUPERINTENDENTE DE MEDIAÇÃO ADMINISTRATIVA, OUVIDORIA SETORIAL E PARTICIPAÇÃO PÚBLICA DA AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA - ANEEL, no uso da competência que lhe foi atribuída por meio da Portari

**dsp2022016spde.pdf** (`desconhecido`):
> SECRETARIA DE PLANEJAMENTO E DESENVOLVIMENTO ENERGÉTICO DESPACHO DECISÓRIO Nº 16/2022/SPE Processo nº 48360.000210/2021-78. Interessado: CEB GERAÇÃO S.A. Assunto: Recurso Administrativo no qual a CEB GERAÇÃO S.A. solicita reconsideração da definição da garantia física de energia da Pequena Central H

**ren2020900.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL RESOLUÇÃO NORMATIVA ANEEL Nº 900, DE 8 DE DEZEMBRO DE 2020 Altera a Resolução Normativa nº 812/2018, que aprova o Submódulo 10.6 dos Procedimentos de Regulação Tarifária – PRORET, que dispõe sobre as Informações Periódicas da Distribuição. Voto O DIRETOR-

**ren2016699.html** (`utf-8`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL  			  			  				  			  			  				  			  			  				 RESOLUÇÃO NORMATIVA N o 699, DE 26 DE JANEIRO DE 2016  			  			  				  			  			  				  			  			  				 Regulamenta o inciso XIII do art. 3º da Lei nº 9.427, de 26 de dezembro de 1996, que trata dos controles 

**aren2016719_2.zip** (`n/a`):
> Conteúdo (29 arquivo(s)): Anexos_REN_719_2016_SRM/10-19 - MCSD_sem_realce_2015.1.4_(jan-15).pdf, Anexos_REN_719_2016_SRM/1-08 - Ressarcimento_sem_realce_2014.1.10_(jan-14).pdf, Anexos_REN_719_2016_SRM/11-02 - MediÆo Cont bil_sem_realce_2015.1.4_(jan-15).pdf, Anexos_REN_719_2016_SRM/12-02 - MediÆo Cont bil_sem_realce_2015.2.0_(out-15).pdf, Anexos_REN_719_2016_SRM/13-14 - Penalidade de Potncia_sem_realce_2015.2.0_(out-15).pdf, Anexos_REN_719_2016_SRM/14-02 - MediÆo Cont bil_sem_realce_2016.2.0_(jan-16).pdf, Anexos_REN_719_2016_SRM/15-03 - Garantia F¡sica_sem_realce_2016.2.0_(jan-16).pdf, Anexos_REN_719_2016_SRM/16-08 - Comprometimento de Usinas_sem_realce_2016.2.0_(mai-16).pdf, Anexos_REN_719_2016_SRM/17-10 - ConsolidaÆo de Resultados_sem_realce_2016.2.0_(mai-16).pdf, Anexos_REN_719_2016_SRM/18-13 - Penalidades de Energia_sem_realce_2016.2.0_(mai-16).pdf

**nreh20212869.pdf** (`desconhecido`):
> Nota Técnica nº 91/2021- SGT/ANEEL Em 17 de maio de 2021. Processo: 48500.000029/2021-10. Assunto: Cálculo das Tarifas de Uso do Sistema de Transmissão – TUST – para as novas centrais geradoras com acesso ao sistema de transmissão e das Tarifas de Uso do Sistema de Distribuição – TUSDg – para as nov

**area20165887_2.pdf** (`desconhecido`):
> ANEXO DECLARAÇÃO DE UTILIDADE PÚBLICA – D.U.P. UHE SANTO ANTÔNIO DESTINAÇÃO: Reservatório, Área de Preservação Permanente (A.P.P) e Remanescente POLÍGONO 1: Porto Velho-RO LOCALIZAÇÃO DA ÁREA: DESCRIÇÃO: ÁREA: 96,3195 ha PERÍMETRO: 13.987,632 m Inicia-se a descrição do perímetro no vértice P-B714 de

**dsp20211907ti.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL DESPACHO Nº 1.907, DE 24 DE JUNHO DE 2021 Texto Original O SUPERINTENDENTE DE CONCESSÕES E AUTORIZAÇÕES DE GERAÇÃO DA AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA - ANEEL, considerando o disposto na Portaria nº 4.742, de 26 de setembro de 2017, na Resolução Norma

**dsp20212581.pdf** (`desconhecido`):
> AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL DESPACHO Nº 2.581, DE 24 DE AGOSTO DE 2021 O SUPERINTENDENTE DE MEDIAÇÃO ADMINISTRATIVA, OUVIDORIA SETORIAL E PARTICIPAÇÃO PÚBLICA DA AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA – ANEEL, no uso das suas competências, em conformidade com o disposto no inciso IV d
