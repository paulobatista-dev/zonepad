# ADR 0009 — ambiente de desenvolvimento, build e distribuição

- **Status:** aceito pelo usuário em 2026-10-25.
- **Data:** 2026-10-25.
- **Spec:** [`docs/specs/dev-environment-v1.md`](../specs/dev-environment-v1.md).

## Contexto

O runtime tem `dependencies = []` e os imports de PySide6 ficam em `interface/gui/`. O extra `dev` atual contém pytest, Ruff, mypy e virtualenv, porém não contém `build` nem `pytest-cov`. O extra `gui` contém `PySide6>=6.7`. A CI instala somente `.[dev]`, portanto não garante que os testes GUI rodem. Não existe constraints/lockfile. O `.venv` baseline tem Python 3.15.0, PySide6 6.12.0, pytest 9.1.1, Ruff 0.17.2, mypy 2.4.0 e virtualenv 21.14.13; `build`, `pytest-cov`, setuptools e wheel estão ausentes. `pip check` informa “No broken requirements found”.

A baseline anterior à implementação foi 704 testes aprovados e 5 subtests em 28.73 s; `tests/test_gui.py` executou 11 testes em offscreen. Após a implementação, a suíte passou com 709 testes e 5 subtests, e a suíte GUI passou com 11 testes sem skips. A cobertura medida foi 83% de linhas (7.152 statements, 1.200 misses); `coverage.xml` foi gerado. A branch de trabalho deriva do commit `9312b5c`, que introduz o Prompt 06, com `main` como ancestral. O prompt não está mergeado; a exceção prevista foi registrada e `main..HEAD` contém somente esse commit antes das alterações de design.

O packaging Debian atual declara-se scaffold em `packaging/debian/README.source`; `debian/control` não tem versão, `debian/changelog` não existe e `rules` usa `python -m build`/`pip`. O PKGBUILD declara `0.1.0`, `python-build` e `python-installer`.

## Decisão

1. **Fonte de dependências (D1).** `pyproject.toml` permanece fonte única para runtime e extras. Runtime fica vazio; não será criado requirements.txt nem segundo manifesto.
2. **Reprodutibilidade (D2).** Adotar `constraints/dev.txt` com pins exatos do ambiente validado. Incluir dependências diretas e transitivas e ferramentas usadas em build isolado, como setuptools; para dependências de build não presentes no `pip freeze` principal, declarar o pin explicitamente e validar o build com `PIP_CONSTRAINT`. Excluir a instalação editável de `zonepad` e pacotes fora do ambiente. A atualização instala `.[dev,gui]` sem constraints, executa suíte e `pip check`, gera `pip freeze`, revisa o diff e recebe aprovação antes de atualizar os pins. As constraints se aplicam apenas ao desenvolvimento/CI; metadata publicado mantém as faixas `>=`.
3. **Extras (D3).** `dev` inclui pytest, pytest-cov, Ruff, mypy, virtualenv e build. Mantém pisos de pytest 9.1, Ruff 0.17.2, mypy 2.4 e virtualenv 21.14; os pisos adicionados são pytest-cov 7.1.0 e build 1.6.1, versões validadas nesta implementação. `gui` continua isolado com PySide6. Não adicionar ferramentas além destas.
4. **Bootstrap (D4).** Manter virtualenv como caminho principal. O README usa `pipx` quando disponível para instalar o comando de bootstrap e orienta `python -m venv` quando `pipx` não está instalado; o runtime não depende de virtualenv.
5. **Ferramentas (D5).** A qualidade usa pytest, pytest-cov, Ruff, mypy, build e `pip check`. Sem pre-commit, tox, nox, pip-tools, twine ou serviço de cobertura.
6. **Cobertura (D6).** Medir cobertura de linhas com `pytest-cov`, registrar percentagem no ADR e publicar `coverage.xml`. Não definir `fail_under` neste incremento: uma medição de baseline, sem alvo de cobertura acordado, não justifica um limite de bloqueio. Um alvo poderá ser proposto em incremento posterior com evidência e aprovação.
7. **GUI na CI (D7).** Jobs `test` e `package` instalam o runtime de sistema `libegl1`, requerido pelo Qt em Ubuntu 24.04, e executam GUI com `QT_QPA_PLATFORM=offscreen`. O job de teste instala `.[dev,gui]` com constraints, verifica import PySide6 e executa a suíte e `tests/test_gui.py` dedicado com JUnit XML. A CI analisa o XML com `xml.etree.ElementTree` e falha se houver caso skipped; isso detecta regressão futura no `pytest.importorskip`. O job roda `pip check`.
8. **Build (D8).** `python -m build` usa isolamento padrão e gera sdist/wheel universais. Validar catalog data, entry points, Requires-Python, extras, descrição longa e licença por caminhos de archive e METADATA. Para wheel, README aparece como descrição longa em METADATA; arquivos de licença indicados por `License-File` ficam no diretório `.dist-info/licenses/`, conforme a especificação de wheel e metadata da PyPA. O sdist contém constraints/dev.txt; `MANIFEST.in` pode ser usado para incluí-lo explicitamente, sem duplicar dependências.
9. **Instalação limpa (D9).** Job package cria venv descartável, instala wheel sem GUI, valida CLI e mensagem de GUI ausente, instala o extra GUI, roda smoke offscreen e `pip check`. Artefatos ficam em `dist/` e são publicados como artefatos de CI, não em repositório de pacotes.
10. **Packaging de distribuição (D10).** AUR mantém versão `0.1.0`, dependências de build/instalação e declara `pyside6` como optdepend para GUI (nome observado no catálogo oficial Arch em 2026-10-25). Debian permanece scaffold; `control` passa a indicar sugestão opcional `python3-pyside6.qtwidgets`, e README.source será atualizado para registrar ausência de changelog/versão e build Debian validado. Não criar `debian/changelog` nem anunciar pacote Debian executável neste incremento. A conversão para pybuild requer decidir suporte Python 3.15 por distribuição e validar dependências Debian em ambiente alvo.
11. **Versão/changelog (D11).** Manter `0.1.0` como versão única do projeto e PKGBUILD. Criar CHANGELOG.md com `[Não publicado]` e `[0.1.0]` cobrindo os incrementos 00–05. Debian sem changelog permanece explicitamente scaffold.
12. **Limites (D12).** Sem publicação, hardware, display, mudança de protocolo/domínio/métricas/schema/GUI ou ferramentas externas. Manter o workflow `ai-assets` para não alterar checks obrigatórios.

## Consequências

- Um único manifesto reduz divergência de dependências; constraints reproduzem o conjunto aprovado sem limitar consumidores do pacote.
- A GUI passa a ser exercitada na CI e a instalação limpa prova metadata e entry points do wheel.
- Coverage se torna evidência contínua sem criar um gate de qualidade arbitrário.
- Build do pacote e validação de conteúdo ficam reproduzíveis sem publicar release.
- AUR representa dependência opcional da GUI. Debian mantém status explícito de scaffold até que suporte Python 3.15 no alvo e o processo de build sejam validados; README.source registra essa limitação e a ausência de versão Debian.
- A execução validada em 2026-10-25 registrou 83% de cobertura de linhas (7.152 statements, 1.200 misses). `constraints/dev.txt` contém a resolução completa; o build isolado foi executado com setuptools 84.2.1. As dependências acrescentadas incluem pytest-cov 7.1.0, build 1.6.1, coverage 7.17.0 e PySide6 6.12.0.

## Alternativas consideradas

- **Segundo requirements/lockfile:** rejeitado porque duplicaria metadados de `pyproject.toml`; constraints fixam resoluções sem listar extras.
- **Ranges flutuantes sem snapshot:** rejeitado para CI e onboarding, pois o estado verde poderia mudar sem diff de projeto.
- **Cobertura com limite imediato:** rejeitado até existir alvo medido/aprovado; o primeiro valor será relatado sem bloquear.
- **Dependência GUI no runtime:** rejeitada porque a CLI e o domínio devem funcionar sem PySide6.
- **Converter Debian em pacote pronto neste incremento:** rejeitado na proposta porque o repositório identifica o diretório Debian como scaffold, não declara uma versão Debian e não há ambiente alvo validado com Python 3.15. A sugestão de PySide6 fica explícita; a conversão pybuild requer decisão e validação próprias.
- **Publicar no PyPI/AUR/Debian:** fora do escopo; somente artefato temporário de CI será produzido.

## Referências

- [`docs/specs/dev-environment-v1.md`](../specs/dev-environment-v1.md)
- [`ai/prompts/06-quality-release.md`](../../ai/prompts/06-quality-release.md)
- [Python Packaging User Guide — Core Metadata](https://packaging.python.org/en/latest/specifications/core-metadata/)
- [Python Packaging User Guide — Binary Distribution Format](https://packaging.python.org/en/latest/specifications/binary-distribution-format/)
- [Debian Policy — `debian/changelog`](https://www.debian.org/doc/debian-policy/ch-source.html#debian-changelog-debian-changelog)
- [Debian `pybuild(1)` — PEP 517 plugin](https://manpages.debian.org/bookworm/dh-python/pybuild.1.en.html)
- [Arch Linux package database — `pyside6`](https://archlinux.org/packages/extra/x86_64/pyside6/)

