# 3cket 2 Brella

Este programa serve para importar participantes do 3cket para a Brella.

- lê a info do ficheiro CSV da lista de participantes da 3cket;
- cria participantes novos na Brella;
- atualiza participantes existentes;
- pode apagar participantes da Brella que já não existam no CSV;
- substitui o QR code da Brella pelo da 3cket.

## O que precisas de fazer

1. ter Python 3.10+;
2. preencher o `.env` com a info da Brella (API key, event ID, org ID);
3. um ficheiro CSV com os dados dos participantes com o nome `participants.csv` (3cket default);
4. colocar o CSV na pasta do projeto;
5. correr `build_exe.bat` uma vez;
6. correr o `3cket2brella.exe` na pasta do projeto /dist.

## Comandos úteis

- `python api.py --dry-run` mostra os participantes que seriam criados, atualizados e removidos;
- `python api.py` cria, atualiza e apaga participantes em falta na Brella por defeito;
- `python api.py --no-prune-missing` cria e atualiza sem apagar participantes em falta na Brella;
- `python api.py --dry-run --no-prune-missing` mostra apenas os participantes que seriam criados ou atualizados.

Por defeito, o programa compara os `external_id` do CSV com os convites existentes na Brella e tenta apagar convites que tenham `external_id` e que já não estejam no CSV.
