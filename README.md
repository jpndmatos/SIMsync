# 3cket 2 Brella

Este programa serve para importar participantes do 3cket para a Brella.

- lê a info do ficheiro CSV da lista de participantes da 3cket;
- cria participantes novos na Brella;
- atualiza participantes existentes;
- substitui o QR code da Brella pelo da 3cket.

## O que precisas de fazer

1. ter Python 3.10+;
2. preencher o `.env` com a info da Brella (API key, event ID, org ID);
3. um ficheiro CSV com os dados dos participantes com o nome `participants_API.csv`;
4. colocar o CSV na pasta do projeto;
5. correr `build_exe.bat` uma vez;
6. correr o `3cket2brella.exe` na pasta do projeto /dist.
