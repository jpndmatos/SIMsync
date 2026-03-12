# Importador 3cket -> Brella

Este script importa registos do 3cket para a Brella através da Integration API da Brella.

Neste momento, o fluxo faz o seguinte:

- lê um ficheiro CSV exportado do 3cket;
- cria invites na Brella para o evento configurado;
- atualiza invites existentes quando encontra o mesmo `external_id`;
- envia o QR code externo para a Brella através do campo `external_qr_string`;
- usa o grupo por defeito da Brella, sem forçar `attendee_group_id`.

## Requisitos

- Python 3.13 ou compatível
- acesso à API da Brella
- token de API da Brella com permissões válidas para a organização e evento

## Estrutura esperada

Os ficheiros principais deste projeto são:

- `api.py`
- `.env`
- o CSV exportado do 3cket

Por omissão, o script tenta ler o ficheiro:

```text
participants_API.csv
```

Se o teu ficheiro tiver outro nome, podes passá-lo por argumento.

## Configuração

Cria ou ajusta o ficheiro `.env` com estes valores:

```env
BRELLA_API_KEY=*****
BRELLA_ORG_ID=*****
BRELLA_EVENT_ID=*****
BRELLA_REQUEST_DELAY=0.2
BRELLA_EXTERNAL_QR_COLUMN=0
BRELLA_AUTH_HEADER_NAME=Brella-API-Access-Token
BRELLA_AUTH_HEADER_PREFIX=
BRELLA_PREFLIGHT_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}
BRELLA_INVITES_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites
BRELLA_FIND_INVITE_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites/find/
BRELLA_UPDATE_INVITE_URL=https://api.brella.io/api/integration/organizations/{org_id}/events/{event_id}/invites/{invite_id}
BRELLA_HTTP_USER_AGENT=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36
```

## Significado das variáveis

- `BRELLA_API_KEY`: token da API da Brella.
- `BRELLA_ORG_ID`: ID da organização na Brella.
- `BRELLA_EVENT_ID`: ID do evento na Brella.
- `BRELLA_REQUEST_DELAY`: pausa entre pedidos, em segundos.
- `BRELLA_EXTERNAL_QR_COLUMN`: índice da coluna do CSV que contém o valor do QR code externo.
- `BRELLA_AUTH_HEADER_NAME`: nome do header de autenticação.
- `BRELLA_AUTH_HEADER_PREFIX`: prefixo opcional do token. Neste caso fica vazio.
- `BRELLA_PREFLIGHT_URL`: endpoint usado para validar acesso ao evento antes da importação.
- `BRELLA_INVITES_URL`: endpoint de criação de invites.
- `BRELLA_FIND_INVITE_URL`: endpoint de pesquisa por `external_id`.
- `BRELLA_UPDATE_INVITE_URL`: endpoint de atualização de invites existentes.
- `BRELLA_HTTP_USER_AGENT`: user-agent enviado nos pedidos HTTP.

## Mapeamento atual do CSV

O script usa atualmente este mapeamento:

- coluna `0`: identificador do 3cket, usado como `external_id`
- coluna `1`: nome completo
- coluna `3` ou `12`: email
- coluna `13`: empresa
- coluna definida em `BRELLA_EXTERNAL_QR_COLUMN`: QR code externo

Nota: neste momento `BRELLA_EXTERNAL_QR_COLUMN=0`, por isso o QR externo enviado para a Brella é o mesmo valor do `external_id`.

Se o QR code real estiver noutra coluna do CSV, basta mudar o valor de `BRELLA_EXTERNAL_QR_COLUMN`.

## Como executar

### 1. Teste sem enviar dados

Isto valida o parsing do CSV e mostra o `external_id` e o QR que vão ser enviados:

```powershell
c:/python313/python.exe .\api.py --dry-run --limit 5
```

### 2. Importação real

Isto cria ou atualiza os registos na Brella:

```powershell
c:/python313/python.exe .\api.py
```

### 3. Usar outro CSV

```powershell
c:/python313/python.exe .\api.py --csv .\nome_do_ficheiro.csv
```

### 4. Limitar o número de linhas processadas

```powershell
c:/python313/python.exe .\api.py --limit 10
```

## Executável Windows

Se quiseres simplificar a execução, podes usar o executável Windows gerado com PyInstaller.

Depois do build, o ficheiro fica em:

```text
dist\3cket2brella.exe
```

Importante: o executável procura estes ficheiros primeiro na mesma pasta do `.exe` e, se não os encontrar, tenta também a pasta acima. Isto cobre o caso normal em que o build fica em `dist\` e os ficheiros continuam na raiz do projeto.

Os ficheiros relevantes são:

- `.env`
- `participants_API.csv`

Se preferires, também podes manter tudo junto na mesma pasta do executável.

### Gerar o executável

Instala o PyInstaller no ambiente virtual e corre:

```powershell
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\build_exe.bat
```

### Executar o `.exe`

Teste sem enviar dados:

```powershell
.\dist\3cket2brella.exe --dry-run --limit 5
```

Importação real:

```powershell
.\dist\3cket2brella.exe
```

Usar outro CSV:

```powershell
.\dist\3cket2brella.exe --csv .\nome_do_ficheiro.csv
```

## Como funciona a atualização

O script não cria duplicados à toa.

Fluxo atual:

1. procura um invite existente na Brella através do `external_id`;
2. se encontrar, faz `PATCH` ao invite existente;
3. se não encontrar, faz `POST` para criar um novo invite.

Isto permite correr o script várias vezes para sincronizar alterações vindas do 3cket.

## Como testar se a atualização está a funcionar

Uma forma simples de testar:

1. altera no CSV um campo visível, por exemplo nome, apelido ou empresa;
2. corre novamente o script;
3. verifica na Brella se o registo foi atualizado;
4. confirma no terminal se apareceu `UPDATED` em vez de `CREATED`.

## Notas sobre o QR code

Para a Brella mostrar o QR code do 3cket em vez do QR por defeito, o campo `external_qr_string` tem de ser enviado no payload do invite.

O script já faz isso.

Se a Brella continuar a mostrar o QR interno, confirma:

1. se o valor correto do QR está mesmo na coluna definida por `BRELLA_EXTERNAL_QR_COLUMN`;
2. se o registo foi atualizado com sucesso;
3. se a interface da Brella já fez refresh dos dados.

## Mensagens esperadas no terminal

Exemplos:

```text
[DRY RUN] line 2: pessoa@empresa.com -> external_id abc123 qr abc123
[OK 1] CREATED: pessoa@empresa.com
[OK 2] UPDATED: outra@empresa.com
```

## Problemas comuns

### `401 Authentication required`

O token da Brella não está correto ou não tem acesso válido à API.

### `403 Forbidden`

O token pode não pertencer a um utilizador com permissões suficientes na organização.

### `404 Not Found`

Normalmente significa que o URL, o `organizationId` ou o `eventId` estão errados.

### QR code errado na Brella

Confirma a coluna configurada em `BRELLA_EXTERNAL_QR_COLUMN`.

## Segurança

Não guardes o token da Brella em repositórios públicos.

Se o token tiver sido partilhado durante testes ou debugging, roda o token no painel da Brella.
