# 3cket 2 Brella

Este programa serve para importar participantes do 3cket para a Brella.

- lê a info do ficheiro CSV da lista de participantes da 3cket;
- cria participantes novos na Brella;
- atualiza participantes existentes;
- pode apagar participantes da Brella que já não existam no CSV;
- substitui o QR code da Brella pelo da 3cket.

## O que precisas de fazer

1. ter Python 3.10+;
2. preencher o `.env` com a info da Brella (API key, event ID, org ID) e ainda com o autenticacao para o download do CSV da 3cket (vê o proximo ponto);
3. configurar o acesso ao CSV da 3cket no `.env` (THREECKET_COOKIE=...) ou, em alternativa, ter um ficheiro local `participants.csv` e colocar o CSV na pasta do projeto (vê a secção do download automatico da 3cket);
4. correr `build_exe.bat` uma vez;
5. correr o `3cket2brella.exe` na pasta do projeto /dist.

## Download automatico da 3cket

O programa tenta descarregar o CSV da 3cket antes de importar. O URL configurado é:

- `https://app.3cket.com/webservices/backoffice/event-manager/participants/participants-info-csv.php?eventExternalId=d16f4292debc4eb6aaaafbf36f2af562`

Esse endpoint devolve `401` sem autenticacao. Para o download funcionar no `.exe`, adiciona no `.env` a autenticacao da tua sessao do browser:

- no `.env` altera `THREECKET_COOKIE=...` para a cookie da tua sessao do browser, que podes encontrar nas devtools do browser, na secção de network, ao carregar o URL do CSV e copiar a cookie da request.

Se o download falhar mas existir um `participants.csv` local, o programa usa esse ficheiro local como fallback.

## Comandos úteis

- `python api.py` cria, atualiza e apaga participantes em falta na Brella por defeito;
- `python api.py --dry-run` mostra os participantes que seriam criados, atualizados e removidos;
- `python api.py --no-prune-missing` cria e atualiza sem apagar participantes em falta na Brella;
- `python api.py --dry-run --no-prune-missing` mostra apenas os participantes que seriam criados ou atualizados;
- `python api.py --no-download-csv` usa apenas o ficheiro local `participants.csv` e nao tenta descarregar da 3cket.
