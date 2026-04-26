# Notebooks — Pipeline RAG ANEEL

## Pré-requisitos

- Python 3.10+
- Token Hugging Face com permissão READ em `.env` como `HF_TOKEN`
- Chave API Groq gratuita em console.groq.com
- Chave API Maritaca gratuita em plataforma.maritaca.ai (opcional)

## Configuração

Crie um arquivo `.env` na raiz do projeto:

```
HF_TOKEN=seu_token_aqui
GROQ_API_KEY=sua_chave_aqui
MARITACA_API_KEY=sua_chave_aqui
```

## Fluxo de execução

### Primeira vez
1. `01_chunking_hierarquico.ipynb` — gera chunks (~35 min, sem GPU)
2. `02_embeddings_indexacao.ipynb` — embeddings + Qdrant (~25 min com GPU)
3. `03_rag_pipeline.ipynb` — pipeline de perguntas e respostas
4. `04_avaliacao.ipynb` — avaliação com RAGAS

### Artefatos já gerados no HF
O Notebook 1 detecta e baixa automaticamente.
O Notebook 3 detecta e baixa automaticamente.
Basta rodar o Notebook 3 diretamente.

## Dataset
huggingface.co/datasets/JvPetas/aneel-legislacao
