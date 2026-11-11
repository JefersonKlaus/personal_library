# PDF → Calibre

App desktop (Python + Flet) que recebe um lote de PDFs e os organiza para o Calibre:

1. Lê título e autor de dentro do PDF (e, se faltar ou estiver lixo, do nome do arquivo).
2. Detecta arquivos idênticos e mantém a cópia com melhores metadados.
3. Você revisa e corrige título/autor numa lista.
4. Cria `Autor/Título/Título - Autor.pdf` com `metadata.opf` (e capa, se quiser).
5. Opcionalmente importa direto na biblioteca com `calibredb`.
6. Tudo pode ser **simulado** antes e **desfeito** depois.

## Instalar e abrir

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows   (Linux/macOS: source .venv/bin/activate)
pip install -r requirements.txt
python main.py
```

Para extrair capas: `pip install pypdfium2 Pillow`.

## Como usar

1. **Origem:** adicione PDFs, uma pasta, ou cole o caminho.
2. **Destino:** escolha onde criar a biblioteca organizada (pasta nova de preferência).
3. Clique em **Analisar**, revise título/autor e desmarque o que não quer.
4. **Simular** mostra o que seria feito sem tocar no disco. **Organizar** executa.
5. No Calibre: *Adicionar livros → de pastas (um livro por pasta)* e aponte para o destino.
   Ou marque a opção de importar com `calibredb` (feche o Calibre antes).
6. Errou? **Desfazer última** apaga as cópias (ou devolve os arquivos movidos).

## Segurança dos arquivos

- A cópia é gravada como `.part`, verificada (tamanho e SHA-256) e só então renomeada.
- No modo *mover*, o original só é apagado depois dessa verificação.
- O desfazer nunca sobrescreve um arquivo que já exista na origem.
- Se o disco não tiver espaço para o lote, nada é copiado.
- Nenhum PDF é aberto fora do seu computador; não há rede nem telemetria.

## Estrutura

```
main.py                  ponto de entrada
pdf2calibre/
  models.py              BookEntry, Options, Report...
  naming.py              nomes de arquivo -> título/autor; nomes seguros
  metadata.py            leitura de PDF (pypdf) e montagem do BookEntry
  planner.py             achar PDFs, duplicados, destinos
  organizer.py           copiar/mover, OPF, capa, desfazer
  opf.py / cover.py      metadata.opf e capa
  calibre.py             integração com calibredb
  settings.py            preferências em ~/.pdf2calibre/settings.json
  ui.py                  interface Flet
tests/                   pytest (lógica + ligação da interface)
```

## Testes

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Os testes de interface usam um Flet de mentira: validam a lógica de ligação, **não** a
aparência nem a compatibilidade com a versão instalada do Flet. Abra o app e teste à mão.

## Limites conhecidos

- A leitura de autor pelo nome do arquivo é uma heurística: confira a lista antes de organizar.
- Listas de autores separadas só por vírgula (`Silva, Souza, Lima`) não são divididas; use `&`.
- O `calibredb` recusa trabalhar com a biblioteca aberta no Calibre.
