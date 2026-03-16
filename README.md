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
5. abrir a pasta `release/3cket2brella` e correr o `3cket2brella-gui.exe`.

## Pacote para enviar a outras pessoas

Para criar um pacote pronto a enviar, sem segredos do teu `.env`:

- correr `build_send.bat` (ou `build_exe.bat send`);
- usar o ficheiro `release/3cket2brella-send.zip`.

Esse zip inclui apenas:

- `3cket2brella-gui.exe`;
- `participants.csv` (ou `participants_tester.csv` renomeado para `participants.csv`, se existir);
- `.env.template` sem API key nem cookie.

Assim, nao envias o teu `.env` real nem dados sensiveis.

## Estrutura limpa apos build

Depois de correr `build_exe.bat`, o layout fica organizado assim:

- `release/3cket2brella/build_exe.bat`;
- `release/3cket2brella/3cket2brella-gui.exe` (principal, para o utilizador final);
- `release/3cket2brella/_internal/` (pasta escondida com ficheiros de suporte, incluindo `.env`, `participants.csv` e versao consola).

## Versao visual (GUI)

O `3cket2brella-gui.exe` abre uma janela com:

- escolha do ficheiro CSV;
- secao `Settings` para editar `BRELLA_API_KEY`, `BRELLA_ORG_ID`, `BRELLA_EVENT_ID` e `THREECKET_COOKIE`;
- botao `Save Settings` para guardar no `.env` sem editar ficheiros manualmente;
- botao `Test Connection` para validar rapidamente a ligacao a Brella;
- botoes para `Preview Changes` e `Run Import`;
- lista de participantes sem email;
- listas de participantes a adicionar, atualizar e remover;
- botao `Export CSV` para exportar a lista de participantes sem email (nome + ID 3cket quando disponivel);
- log completo da execucao (inclui erros e avisos que a versao consola tambem mostra).

Fluxo recomendado na GUI:

1. clicar em `Preview Changes` para ver quem vai mudar;
2. confirmar as listas de adicionar/atualizar/remover e os sem email;
3. opcional: clicar em `Export CSV` para guardar a lista de sem email;
4. clicar em `Run Import` para aplicar as alteracoes.

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
