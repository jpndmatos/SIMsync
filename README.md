# 3cket 2 Brella

Importa participantes do 3cket para a Brella atraves de um dashboard web no GitHub Pages + GitHub Actions.

## Como funciona

1. O dashboard (GitHub Pages) envia um pedido `workflow_dispatch` para o GitHub Actions.
2. O GitHub Actions corre `python api.py` com as opcoes escolhidas.
3. As credenciais (API key, cookie) ficam nos **GitHub Secrets** — nunca no browser.
4. O dashboard mostra o estado e os logs do workflow.

## Setup

### 1. Adicionar secrets no repositorio

Em **Settings > Secrets and variables > Actions**, adicionar:

| Secret | Descricao |
|--------|-----------|
| `BRELLA_API_KEY` | Chave da API de integracao da Brella |
| `BRELLA_ORG_ID` | ID da organizacao na Brella |
| `BRELLA_EVENT_ID` | ID do evento na Brella |
| `THREECKET_COOKIE` | Cookie de sessao da 3cket para download do CSV |
| `BRELLA_REQUEST_DELAY` | (opcional) Delay entre chamadas API, default `0.2` |

### 2. Criar um GitHub Personal Access Token

Em **Settings > Developer settings > Personal access tokens > Fine-grained tokens**:

- **Repository access**: so este repositorio
- **Permissions**: Actions (read & write)

### 3. Ativar GitHub Pages

Em **Settings > Pages**:

- Source: Deploy from a branch
- Branch: `main`
- Folder: `/docs`

### 4. Usar o dashboard

1. Abrir o URL do GitHub Pages.
2. Introduzir o PAT.
3. Clicar **Preview** para ver o que muda.
4. Clicar **Import** para executar o sync.

## CLI (alternativa)

```bash
python api.py                          # sync completo
python api.py --dry-run                # preview
python api.py --no-prune-missing       # sem apagar
python api.py --no-download-csv        # usar CSV local
python api.py --limit N                # limitar a N participantes
```

## Download automatico da 3cket

O programa tenta descarregar o CSV da 3cket antes de importar. Se falhar mas existir um `participants.csv` local, usa esse ficheiro.

Para o download funcionar, o secret `THREECKET_COOKIE` tem de ter a cookie da sessao do browser (encontra-se nas devtools, seccao Network).
