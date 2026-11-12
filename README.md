# Personal Library

App desktop (Python + Flet) para cuidar da sua biblioteca de PDFs no Calibre:

1. **Importar**: escolha PDFs; título e autor são lidos e ajustados automaticamente
   (metadados de dentro do PDF, nome do arquivo, lixo como "Microsoft Word - doc1" ou
   "admin" é descartado, arquivos idênticos são detectados). Você confere e importa para a
   sua biblioteca do Calibre.
2. **Galeria**: a biblioteca do Calibre em grade de capas, com busca e detalhes.
3. **Exportar**: copia livros da biblioteca para outra pasta, no formato do Calibre.

## Instalar e abrir

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python main.py
```

Precisa do [Calibre](https://calibre-ebook.com) instalado (o app usa o `calibredb` dele para
importar). Preferências, registro e miniaturas da galeria ficam em `~/.personal_library`.

## Como usar

### 1. Importar

1. **Adicionar PDFs…**, **Adicionar pasta…** ou cole um caminho. A análise começa sozinha.
2. Se os arquivos seguem um formato, descreva-o em **Como importar** (ou escolha em
   **Modelos**) e clique em **Aplicar**: parâmetros (`@name`, `@vol`, `@auth`...), os
   delimitadores entre eles e valores fixos para todos os PDFs (`@auth=ONE`). A linha de
   exemplo mostra como o primeiro arquivo será lido. Vazio = automático.
3. Confira título, autor, série e volume na lista (edite o que precisar; desmarque o que não
   quer). Vários autores: separe com `&`.
4. Opcional: etiquetas para todos os livros (ex.: `importado`).
5. **Importar para a biblioteca**: os livros vão para a biblioteca escolhida na aba Galeria,
   com título, autores, ano, idioma, etiquetas e capa (1ª página). Livros que a biblioteca
   já tem (mesmo título e autor) são avisados e não são duplicados.
6. **Desfazer última importação** remove esses livros (eles vão para a lixeira do Calibre).

> **Feche o Calibre antes de importar**: com ele aberto o `calibredb` recusa o acesso.

#### Qual biblioteca recebe os livros

Se nenhuma biblioteca foi escolhida ainda (ou a escolhida foi apagada/movida), o item 3 mostra
um aviso com as opções:

- **Usar esta**: bibliotecas que o seu Calibre já conhece aparecem listadas (o app lê a
  configuração do Calibre: biblioteca atual e usadas recentemente, e a pasta padrão
  `Calibre Library` na sua pasta de usuário);
- **Escolher biblioteca existente…**: a pasta que tem o `metadata.db` (escolher a pasta de
  cima, como `Documentos`, também funciona se houver uma só biblioteca dentro dela);
- **Criar biblioteca nova…**: escolha onde; se a pasta não estiver vazia, a biblioteca é
  criada numa subpasta `Calibre Library`. Quem cria é o próprio Calibre (`calibredb`), então
  o Calibre precisa estar instalado e fechado. Para abri-la depois no Calibre: botão
  **Biblioteca > Alternar/criar biblioteca** e escolha a pasta.

Com uma biblioteca escolhida, **Trocar biblioteca…** mostra as mesmas opções. A biblioteca
é a mesma nas três abas (Importar, Galeria e Exportar); a Galeria também tem **Criar nova…**.

#### Como importar: parâmetros, delimitadores e valores fixos

Escreva os parâmetros na ordem em que aparecem no nome do arquivo, com os delimitadores
usados entre eles (`-`, `_`, espaço, parênteses...):

| Parâmetro    | Significa                                     | Também aceito                |
|--------------|-----------------------------------------------|------------------------------|
| `@name`      | título da obra                                | `@nome`, `@title`, `@titulo` |
| `@vol`       | volume: `Vol 18`, `Volume 41`, `v03`, `03`    | `@volume`                    |
| `@auth`      | autor(es)                                     | `@autor`, `@author`          |
| `@year`      | ano: `1999` ou `(1999)`                       | `@ano`                       |
| `@series`    | série, quando diferente do `@name`            | `@serie`                     |
| `@publisher` | editora                                       | `@editora`                   |
| `@lang`      | idioma (`pt`, `por`, `en`...)                 | `@idioma`                    |
| `@tags`      | etiquetas, separadas por vírgula              | `@etiquetas`                 |
| `@skip`      | parte a ignorar                               | `@ignorar`                   |

**Valor fixo** (vale para todos os PDFs e vence o nome do arquivo e os metadados do PDF):
`@parâmetro=valor`, no fim do padrão ou separado por `;`.

| Como importar                                        | `One Punch Man - Vol 18` vira                                   |
|------------------------------------------------------|-----------------------------------------------------------------|
| `@name - @vol - @auth`                               | título `One Punch Man`, vol. 18, série `One Punch Man`           |
| `@name - @vol; @auth=ONE`                            | idem, autor **ONE** em todos                                     |
| `@name - @vol - @auth=ONE`                           | idem; se o arquivo tiver uma 3ª parte, ela é trocada por ONE     |
| `@name - @vol; @series=Coleção OPM`                  | título `One Punch Man`, vol. 18, série `Coleção OPM`             |
| `@name - @vol; @auth=ONE; @tags=mangá; @publisher=Panini; @lang=pt` | idem, com etiqueta, editora e idioma            |
| `@auth=ONE` (sem padrão)                             | modo automático, só o autor fixo                                 |
| `@vol; @name=One Punch Man` (arquivos `01.pdf`, `02.pdf`...) | título fixo e volume do nome do arquivo                 |

Outros exemplos: `@auth - @name (@year)` lê `Machado de Assis - Dom Casmurro (1899)`;
`@series - @vol - @name` lê `Harry Potter - 1 - A Pedra Filosofal`;
`@skip - @name - @auth` ignora o `[Grupo]` de `[Grupo] - Iracema - José de Alencar`.
Partes que faltam no fim do nome ficam vazias. Arquivos fora do padrão ficam com **atenção**
e são lidos no modo automático (os valores fixos continuam valendo). Quando há padrão, o
nome do arquivo vale mais que os metadados de dentro do PDF, que só completam o que faltar.
O formato antigo (`NOME - VOL - AUTOR`) continua aceito.

**Cada parâmetro preenche só o seu campo**: `@name` é o título (exatamente), `@vol` é o
volume, `@auth` o autor, `@series` a série. Se o padrão põe algo como `Vol 01` no autor ou no
título (ex.: `@name - @auth` em `One Punch Man - Vol 01`), o livro fica com **atenção** e a
linha de exemplo avisa "parece um volume: use @vol".

**Volumes e série**: o Calibre só guarda o número do volume dentro de uma série (sem série
ele descarta o número). Por isso, quando há `@vol` e não há `@series`, a série é o próprio
`@name`, e a linha de exemplo mostra isso ("Série: One Punch Man (de @name)"). Para outra
série, use `@series` no padrão ou `@series=...`.

**Duplicados**: o Calibre considera duplicados livros com o mesmo título e autor, e
recusaria o volume 2 de "One Punch Man". Para volumes, o app compara título + autor + série +
volume com a biblioteca antes de importar (o mesmo volume de novo aparece como "já existe") e
manda o resto para o Calibre aceitar. Na Galeria cada capa mostra o volume, e ordenar por
**Título** ou **Série e volume** põe os volumes em ordem. Ao exportar, volumes com o mesmo
título e autor ganham o volume no nome do arquivo (`One Punch Man - Vol. 18 - ONE.pdf`).

O modo automático (campo vazio) também reconhece volumes (`Vol 18`, `Volume 41`, `v03`,
`- 03`) e segue as mesmas regras.

### 2. Galeria

Escolha a pasta da biblioteca do Calibre (a que tem `metadata.db`). Os livros aparecem em
grade de capas como no Calibre: busca por título, autor, etiqueta, série ou editora (sem
diferenciar acentos), ordem (mais recentes, título, série e volume, autor, publicação) e, ao
clicar, os
detalhes do livro com botões para abrir o PDF ou a pasta. A galeria **só lê** a biblioteca
(banco aberto em modo somente leitura) e funciona com o Calibre aberto. Ela se atualiza
sozinha depois de uma importação.

### 3. Exportar

Marque os livros da biblioteca (todos vêm marcados; o filtro e "Marcar/Desmarcar todos"
ajudam a escolher), escolha a pasta de destino e clique em **Exportar**. Cada livro vira:

```
Autor/Título/Título - Autor.pdf     (e os outros formatos que o livro tiver)
Autor/Título/Título - Autor.opf     todos os metadados: série, editora, ISBN, descrição...
Autor/Título/cover.jpg
```

**Simular** mostra o que seria feito sem tocar no disco; **Desfazer última** apaga a
exportação. A pasta exportada entra em qualquer Calibre com *Adicionar livros → Adicionar
de pastas e subpastas*, arrastando os PDFs ou pela pasta de adição automática (nesse caso
desmarque "Uma pasta por livro", porque o Calibre não olha subpastas).

> O destino não pode ser uma biblioteca do Calibre: ele só mostra livros registrados no
> `metadata.db`, e arquivos copiados direto para lá ficariam invisíveis. Para colocar livros
> numa biblioteca, use a aba Importar.

A barra de baixo mostra o progresso, o botão **Cancelar** e a última mensagem; **Registro**
abre o histórico (ele abre sozinho quando há erro).

## Como a biblioteca lê os metadados

Regras conferidas no código do Calibre (`calibre/ebooks/metadata/meta.py` e `opf2.py`); os
nomes exigidos por ele ficam todos em `personal_library/library/manager.py`:

- Só é usado um `.opf` que tenha o identificador `opf:scheme="calibre"`. Sem ele, o arquivo
  é ignorado e valem os dados de dentro do PDF ("Microsoft Word - doc1", "admin"...).
- Para um PDF adicionado sozinho, só é lido o `.opf` **com o mesmo nome** do PDF.
  Por isso o app grava `Título - Autor.opf`.
- O ano vai como `AAAA-01-01T12:00:00+00:00`: com meia-noite UTC apareceria dezembro do ano
  anterior em fusos como o do Brasil.
- O `opf:file-as` de todos os autores leva a ordenação do livro inteiro
  (`Lima, Ana & Dias, Rui`), que é como a biblioteca grava e lê.
- A ferramenta de linha de comando (`calibredb`) é chamada com a saída em inglês, para o app
  entender a resposta mesmo com o programa em português.
- Importar passa por uma pasta temporária (PDF + `.opf` + capa) e a ferramenta; a pasta
  temporária é apagada no fim, mesmo se der erro.

## Segurança dos arquivos

- Os PDFs de origem nunca são alterados nem apagados.
- Cópias são gravadas como `.part`, verificadas (tamanho e SHA-256) e só então renomeadas;
  o `.opf` e a capa são gravados antes, para o livro nunca aparecer sem eles.
- A biblioteca só é alterada pela ferramenta do próprio Calibre (`calibredb`); o app apenas
  lê o banco de dados dela (em modo somente leitura).
- Desfazer nunca sobrescreve arquivos; importações desfeitas vão para a lixeira do Calibre.
- Se o disco não tiver espaço para o lote, nada é copiado.
- Nenhum PDF sai do seu computador; não há rede nem telemetria.

## Estrutura

Cada módulo tem uma responsabilidade; as dependências vão de cima para baixo (a interface
usa a lógica, a lógica não conhece a interface, e só `library/` conhece o programa externo).

```
main.py                    ponto de entrada
personal_library/
  paths.py                 pastas do app (~/.personal_library)
  settings.py              preferências (settings.json)
  logging_setup.py         registro em arquivo
  models.py                BookEntry, ImportOptions, Status

  text.py                  limpeza de texto, nomes seguros de arquivo, busca sem acentos
  people.py                nomes de pessoas: reconhecer, separar, ordenar
  volumes.py               volumes no nome ("Vol 18", "v03")
  filename_parser.py       modo automático: título/autor/volume do nome do arquivo
  import_spec.py           "Como importar": @name - @vol; @auth=ONE

  pdf_reader.py            metadados de dentro do PDF (e o que é lixo)
  pdf_cover.py             capa = 1ª página
  analysis.py              achar PDFs, montar cada livro, duplicados
  files.py                 cópia verificada, espaço em disco, desfazer (manifesto)
  importer.py              PDFs revisados -> biblioteca (e desfazer)
  exporter.py              biblioteca -> pasta com .opf e capa

  library/                 a biblioteca de e-books
    manager.py             ÚNICO lugar com os nomes do programa externo
    database.py            leitura somente leitura do banco da biblioteca
    search.py              busca e ordem
    thumbnails.py          miniaturas das capas
    opf.py                 formato .opf
    location.py            validar, achar e onde criar bibliotecas
    cli.py                 ferramenta de linha de comando: adicionar, remover, criar

  ui/                      interface Flet
    app.py                 janela, barra de status, tarefas e a biblioteca aberta
    widgets.py             peças reutilizadas (seções, paginação, cores)
    library_picker.py      escolher/criar/trocar a biblioteca
    import_tab.py          aba Importar
    gallery_tab.py         aba Galeria
    book_views.py          capa, cartão e detalhes de um livro
    export_tab.py          aba Exportar
tests/                     pytest: um arquivo por módulo (test_ui_*: ligação da interface)
```

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Os testes de interface usam um Flet de mentira: validam a lógica de ligação, **não** a
aparência nem a compatibilidade com a versão instalada do Flet. Abra o app e teste à mão.

## Limites conhecidos

- A leitura de autor pelo nome do arquivo é uma heurística: confira a lista antes de importar.
- Listas de autores separadas só por vírgula (`Silva, Souza, Lima`) não são divididas; use `&`.
- O `calibredb` recusa trabalhar com a biblioteca aberta no Calibre (feche-o para importar).
- A galeria mostra 60 livros por página e não edita a biblioteca (isso fica com o Calibre).
