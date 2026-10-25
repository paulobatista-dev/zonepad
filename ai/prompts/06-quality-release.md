# Prompt 06 — Qualidade, dependências, ambiente de desenvolvimento, build e release

- **Status:** implementação em andamento após aprovação da spec e do ADR 0009.
- **Incremento:** fechar a base técnica do MVP — dependências e extras corretos, ambiente de desenvolvimento reproduzível, README executável do zero, CI que roda a GUI de verdade e empacota, build de wheel/sdist validado e instalação limpa com smoke.
- **Branch de implementação:** `chore/dev-environment-release`, criada a partir da `main` com este prompt mergeado.
- **Fluxos:** `/flow-design-feature` → `/flow-implement-feature` → `/flow-review-calibration`.
- **Agentes:** `python-engineer` executa dependências, extras, constraints, CI, build, empacotamento, testes, README técnico e release. `prompt-engineer` atua só em `ai/` e na estrutura/clareza do README, revisando consistência prompt ↔ README ↔ spec ↔ agentes. `controller-hardware` é **N/A** neste incremento (justificativa na seção **Agentes**). Claude/Codex principal orquestra, valida decisões com o usuário e sintetiza.
- **Fora deste incremento:** features novas, mudanças de domínio/métricas/calibração/schema de perfil, redesenho da GUI, Windows/macOS, publicação em PyPI/AUR, push/PR/merge.

## Missão

Tornar o repositório instalável, reproduzível e verificável por outra pessoa: um ambiente criado do zero com `python -m pip install -e '.[dev,gui]'` permite desenvolver, testar, rodar CLI e GUI e gerar wheel/sdist; a CI executa os testes de GUI que hoje são pulados e valida o pacote; o README leva do zero ao smoke em instalação limpa, sem conhecimento tácito.

Hoje existem três lacunas verificadas:

1. `build` não está no extra `dev`, então `python -m build` falha em ambiente recém-criado (`ModuleNotFoundError: No module named 'build'`).
2. A CI instala apenas `.[dev]` (`.github/workflows/ai-assets.yml:35`); sem PySide6, `tests/test_gui.py:11` faz `importorskip` e o arquivo inteiro é pulado — os 11 testes de GUI deixam de rodar.
3. Não há lockfile/constraints: as versões são pisos `>=` flutuantes, e não há registro de qual combinação foi validada.

Regra estrutural: **`pyproject.toml` continua sendo a única fonte de dependências**. Constraints podem fixar versões, mas não duplicam a lista de pacotes nem criam um segundo manifesto.

## Resultado esperado

1. `pyproject.toml` com extras coerentes: `dev` suficiente para desenvolver, testar, medir cobertura e construir; `gui` isolado com PySide6.
2. Estratégia de reprodutibilidade decidida, implementada e justificada (constraints com pins exatos e política de atualização, ou flutuação documentada — decisão D2).
3. README com seção **Desenvolvimento** completa: pré-requisitos, asdf, `.venv`, extras, testes/lint/tipos/`pip check`, build, instalação limpa, smoke CLI/GUI e troubleshooting.
4. CI com job de testes que executa a GUI em `offscreen` (sem skip), `pip check` e job de empacotamento com build e smoke do wheel em ambiente limpo.
5. Wheel/sdist validados quanto a conteúdo (`catalog_data/*.json`, entry points, README, LICENSE).
6. `docs/specs/dev-environment-v1.md` e `docs/adr/0009-*.md` (D1–D12) aprovados antes da implementação.
7. `CHANGELOG.md` e versão coerentes entre `pyproject.toml` e `packaging/aur/PKGBUILD`; para Debian, usar `packaging/debian/changelog` se o pacote for mantido como executável, ou registrar explicitamente que o scaffold não declara versão.
8. `ai/prompts/README.md` com 05 concluído (PR #14), 06 em implementação e 06 como último prompt do roadmap.
9. Relatório final com evidência de cada comando e o que não foi executado.

## Contexto verificado (2026-10-25, `main` em `f5fc494`)

Revalide no checkout principal com working tree limpo. Os gates da seção **Validação** são a fonte de verdade.

| Verificação | Resultado observado |
| --- | --- |
| Runtime | `pyproject.toml:13` — `dependencies = []`; domínio e CLI sem dependência externa |
| Extras | `pyproject.toml:16` — `gui = ["PySide6>=6.7"]`; `:17-22` — `dev = [pytest>=9.1, ruff>=0.17.2, mypy>=2.4, virtualenv>=21.14]` |
| Lacuna do `dev` | `build` ausente; `python -c "import build"` falha com `ModuleNotFoundError`; `pytest-cov` ausente |
| Build backend | `pyproject.toml:1-3` — `setuptools>=68`, `setuptools.build_meta` |
| Package data | `pyproject.toml:31-32` — `"zonepad.infrastructure" = ["catalog_data/*.json"]`; arquivo real `src/zonepad/infrastructure/catalog_data/families.json` |
| Versão | `pyproject.toml:7` — `0.1.0`; `packaging/aur/PKGBUILD:2` — `pkgver=0.1.0`; `packaging/debian/control` sem campo de versão |
| Lockfile/constraints | Inexistentes: sem `requirements.txt`, `uv.lock`, `poetry.lock`, `Pipfile`, `constraints/`, `setup.py`, `setup.cfg`, `MANIFEST.in` |
| Origem das dependências | `pip config list` vazio; sem `PIP_INDEX_URL`/`UV_*`; índice padrão PyPI; versões por piso `>=` |
| Ambiente local | `.venv` com Python 3.15.0, PySide6 6.12.0, pytest 9.1.1, mypy 2.4.0, virtualenv 21.14.13; criado com `python -m venv` (não com o pacote `virtualenv`) |
| Suíte | `704 passed, 5 subtests passed in 28.45s` com PySide6 instalado; `tests/test_gui.py` → `11 passed` |
| `pip check` | `No broken requirements found.` |
| CI | `.github/workflows/ai-assets.yml:24-43` — um job `check`: instala `.[dev]` (`:35`), ruff (`:37`), mypy (`:39`), pytest (`:41`), sync `--check` (`:43`). Sem `pip check`, sem build, sem jobs de pacote |
| Testes de GUI | `tests/test_gui.py:7` define `QT_QPA_PLATFORM=offscreen`; `:11` usa `pytest.importorskip("PySide6")` — na CI, sem PySide6, são pulados |
| Subtests | `pytest 9.1.1` reporta `subtests passed` sem `pytest-subtests` instalado; confirme o comportamento antes de adicionar plugin |
| README | `README.md:13-33` — seção inicial de ambiente; `:410-419` — validação e descrição da CI; falta build, wheel, instalação limpa, smoke de GUI e troubleshooting |
| Packaging distro | `packaging/aur/PKGBUILD:12-15` usa `python -m build --wheel`; `packaging/debian/control:5` sem `pybuild`; nenhum declara dependência de GUI |
| Changelog | `CHANGELOG.md` inexistente |
| ADR | `0008` é o último aceito; `0009` é o próximo número livre |
| `.gitignore` | `:5` `.venv/`, `:6` `dist/`, `:7` `build/`, `:13` `.coverage`, `:14` `htmlcov/` — artefatos de build e smoke em `dist/` já são ignorados |

Leia antes de editar: `AGENTS.md`, `pyproject.toml`, `README.md`, `.github/workflows/ai-assets.yml`, `.tool-versions`, `packaging/aur/PKGBUILD`, `packaging/debian/control`, `docs/specs/gui-v1.md`, `docs/specs/device-discovery-v1.md`, `docs/specs/wizard-v1.md`, `docs/specs/metrics-v1.md`, `docs/adr/0001`–`0008`, `ai/prompts/05-gui-pyside6.md`, `ai/prompts/README.md`, `scripts/sync_ai_assets.py`, `tests/test_gui.py`, `tests/test_architecture.py` e `src/zonepad/`.

Skills aplicáveis: `python-quality`, `python-app-architecture`, `clean-code`, `evidence-based`, `positive-ontology`, `prompt-design` (para `ai/` e revisão do README).

## Pré-condições

1. Este prompt deve estar mergeado em `main`. Enquanto não estiver, execute a partir da branch que contém o prompt e registre a exceção. Nessa exceção, `main` deve ser ancestral da branch; `git log --oneline main..HEAD` pode conter somente o commit que adiciona o Prompt 06.
2. Trabalhe **somente no checkout principal** (`/home/costa/Workspace/zonepad`). Proibido `git worktree`, cópia do repositório para outro diretório e edição de arquivos gerados (`AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`).
3. Crie a branch de implementação a partir da `main` quando o prompt já estiver mergeado. Se o Prompt 06 ainda estiver em uma branch de documentação, crie a branch de trabalho a partir da branch que o contém, mantendo `main` como ancestral e registrando a exceção:

```bash
cd /home/costa/Workspace/zonepad
git status --porcelain        # deve estar vazio
git switch main
git pull --ff-only
git switch -c chore/dev-environment-release
```

Na exceção de prompt ainda não mergeado, parta da branch que contém o prompt:

```bash
git switch <branch-que-contem-o-prompt-06>
git switch -c chore/dev-environment-release
git merge-base --is-ancestor main HEAD
git log --oneline main..HEAD # somente o commit do Prompt 06
```

4. Toolchain e baseline:

```bash
asdf current python        # 3.15.0; se não, pare e reporte
python --version           # Python 3.15.0
test -d .venv || (python -m venv .venv)
source .venv/bin/activate
python -m pip install -e '.[dev,gui]'
python -m pytest -q -o addopts=""    # baseline: 704 passed, 5 subtests
python -m pip check                  # baseline: sem quebras
```

5. Gates de entrada:

```bash
git status --porcelain        # vazio
git branch --show-current     # chore/dev-environment-release
git merge-base --is-ancestor main HEAD
git log --oneline main..HEAD  # vazio se o prompt foi mergeado; só o commit do Prompt 06 na exceção
```

Se qualquer gate falhar, pare e peça um checkout principal limpo.

6. Regras de git e segurança:

- Commit local permitido; push, PR, merge e rebase só com pedido explícito do usuário.
- Proibido `git stash`, `git reset`, `git checkout --`, `git restore`, `git rebase`, `git push --force` e `sudo`.
- Nenhum comando abre `/dev/input`, `/dev/uinput` ou display real; GUI sempre em `QT_QPA_PLATFORM=offscreen`.
- Adicionar dependência além das listadas em D3 exige aprovação explícita do usuário e registro na spec.
- Build e instalação limpa usam rede apenas do PyPI padrão; se o índice estiver indisponível, registre como bloqueio e não troque de mirror silenciosamente.

## Agentes

| Agente | Executa | Não executa |
| --- | --- | --- |
| `python-engineer` | Audita e ajusta `pyproject.toml` (extras, `build`, cobertura), constraints, imports de runtime, CI, build, conteúdo de wheel/sdist, testes, README técnico (comandos e troubleshooting), `CHANGELOG.md`, coerência de packaging, cobertura e versão. | Não edita `ai/` nem reescreve agentes, skills ou fluxos; não decide semântica de hardware; não altera domínio, métricas, schema de perfil nem GUI. |
| `prompt-engineer` | Atua **apenas** em `ai/` (prompts, skills, fluxos, instruções) e na estrutura/clareza do `README.md`; revisa consistência entre prompt 06, README, `docs/specs/dev-environment-v1.md`, ADR 0009 e as descrições dos agentes; reporta contradições com arquivo:linha. | Não implementa código, extras, constraints, CI, build ou script algum de `scripts/`; não assina critério de empacotamento nem de cobertura. |
| `controller-hardware` | **N/A neste incremento.** Comparece apenas para declarar a ausência e confirmar que o incremento não altera protocolo, medição, calibração, unidades, thresholds, schema de perfil nem suporte a dispositivo. | Não revisa dependências, CI, build, README ou release; não é acionado para parecer de hardware porque não há hardware novo. |
| Claude/Codex principal | Orquestra design → implementação → revisão, faz handoffs com contexto, valida spec/ADR com o usuário, cobra gates, arbitra conflito entre pareceres e sintetiza o relatório final. | Não substitui o parecer de `python-engineer` em empacotamento; não autoriza publicação em PyPI/AUR; não autoriza push/PR/merge. |

Aprovação humana (usuário): aprova `docs/specs/dev-environment-v1.md` e o ADR 0009 **antes** de qualquer código de produção; autoriza dependência nova, atualização de constraints e push/PR/merge.

`controller-hardware` é N/A porque o incremento não toca `domain/`, `application/measure*`, `application/calibrate*`, thresholds, findings, mapping v1, descoberta, protocolo de leitura nem catálogo de famílias; nenhum teste novo abre dispositivo e nenhum número exibido muda. O relatório final deve conter essa declaração, não o silêncio.

Handoff mínimo: objetivo, contexto verificado, restrições, arquivos relevantes, saída esperada e critério de aceite. Em Claude Code, use a ferramenta **Agent** com o nome do subagente. Em Codex, use subagente ou siga o `FLOW.md` correspondente.

## Etapas e responsáveis

| # | Etapa | Executor | Revisor/apoio | Fluxo/skill | Saída | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Preflight, branch e baseline | `python-engineer` | principal | `/flow-implement-feature` (1–2) | branch `chore/dev-environment-release`, baseline registrado | tree limpo; 3.15.0; 704 testes; `pip check` limpo |
| 2 | Auditoria de dependências e imports | `python-engineer` | `prompt-engineer` (consistência) | `/flow-design-feature` + `python-quality` | inventário `src/` × extras × tooling | cada comando documentado tem dependência no extra correto; nenhum import de dev/GUI em runtime |
| 3 | Política de reprodutibilidade, cobertura e CI (D1–D8) | `python-engineer` | principal | `/flow-design-feature` + `python-quality` | seção de dependências/CI da spec | decisões D1–D8 fechadas e justificadas |
| 4 | Build, instalação limpa, packaging e versão (D9–D12) | `python-engineer` | principal | `/flow-design-feature` + `python-quality` | seção de build/release da spec + ADR 0009 | D9–D12 fechadas; conteúdo do pacote definido |
| 5 | Estrutura e clareza do README; consistência prompt ↔ README ↔ spec ↔ agentes | `prompt-engineer` | `python-engineer` (exatidão técnica) | `prompt-design`, `evidence-based` | esqueleto revisado da seção **Desenvolvimento** e do `ai/prompts/README.md` | nenhuma contradição aberta com arquivo:linha |
| 6 | **Aprovação da spec e do ADR 0009 pelo usuário** | principal | usuário | — | spec e ADR aprovados | sem aprovação, não há implementação |
| 7 | Ajustar extras, `build`, cobertura e constraints | `python-engineer` | principal | `/flow-implement-feature` (3) | `pyproject.toml` + `constraints/dev.txt` | `.[dev]` instala `build`/`pytest-cov`; `.[dev,gui]` cobre GUI; PySide6 só em `gui` |
| 8 | README **Desenvolvimento**: passo a passo e troubleshooting | `python-engineer` (técnico) + `prompt-engineer` (estrutura/clareza) | principal | `/flow-implement-feature` + `prompt-design` | `README.md` atualizado | passos executáveis do zero, na ordem, com saída esperada |
| 9 | CI: jobs `check`, `test` (GUI real + cobertura + `pip check`) e `package` | `python-engineer` | principal | `/flow-implement-feature` (8) | `.github/workflows/ai-assets.yml` | GUI executada sem skip; `pip check`; build e smoke publicados como artefato |
| 10 | Build e validação de conteúdo de wheel/sdist | `python-engineer` | principal | `python-quality` | `dist/*.whl`, `dist/*.tar.gz` + listagem | `catalog_data/*.json`, entry points, README e LICENSE presentes |
| 11 | Instalação limpa e smoke CLI/GUI | `python-engineer` | principal | `python-quality` | log de smoke em `dist/smoke-venv` | `zonepad --help`, `zonepad devices --help`, `zonepad-gui --smoke` com exit 0 |
| 12 | Cobertura: medir baseline e decidir `fail_under` | `python-engineer` | principal | `python-quality` | `coverage.xml` + valor registrado no ADR | decisão registrada; sem threshold inventado |
| 13 | Packaging distro por consistência (AUR/Debian scaffold) | `python-engineer` | principal | `python-quality` | `PKGBUILD`, `debian/control` ajustados | `pkgver` e dependências AUR coerentes; `Suggests` Debian atualizado e scaffold sem versão/build validado documentado; nenhuma publicação |
| 14 | `CHANGELOG.md`, versão e `ai/prompts/README.md` | `python-engineer` (changelog) + `prompt-engineer` (`ai/`) | principal | `python-quality`, `prompt-design` | `CHANGELOG.md`, status 05/06 | versão única; `sync --check` limpo |
| 15 | Revisão final | `python-engineer` + `prompt-engineer`; `controller-hardware` declara N/A | principal sintetiza | `/flow-review-calibration` | relatório com severidade e arquivo:linha | nenhum blocker; N/A de hardware registrado |
| 16 | Encerramento | principal | usuário | — | entrega no **Formato de saída** | critérios marcados; riscos e handoff registrados |

Nenhuma etapa de hardware é obrigatória aqui. Se durante a implementação aparecer mudança que afete protocolo, medição, calibração ou schema de perfil, **pare**: o incremento saiu do escopo e precisa de decisão do usuário.

### Ordem de implementação

1. Auditoria de dependências e imports; escrever `docs/specs/dev-environment-v1.md` e o ADR 0009 com D1–D12.
2. Aprovação do usuário; sem ela, nenhuma edição em `pyproject.toml`, CI, README ou `packaging/`.
3. `pyproject.toml` (extras) e `constraints/dev.txt`; validar `.[dev]` e `.[dev,gui]` em venv limpo.
4. README **Desenvolvimento** e troubleshooting, executando cada comando na ordem em que aparece.
5. CI: job `test` com GUI e cobertura, `pip check`, depois job `package` com build, instalação limpa e smokes.
6. Build e validação de conteúdo (`catalog_data`, entry points, README, LICENSE), seguidos do smoke em `dist/smoke-venv`.
7. `CHANGELOG.md`, versão, packaging distro por consistência e `ai/prompts/README.md`; fechar com `sync --check`.

Sinais de que o incremento saiu do escopo — pare e reporte: necessidade de mudar `domain/` ou `application/measure*`; mudança de mensagem de usuário da CLI/GUI; dependência nova fora de D3; publicação de pacote; qualquer passo que exija `sudo` ou hardware real.

## Decisões que a spec deve fechar

Cada decisão tem dono. `python-engineer` decide estrutura, ferramentas e artefatos; o usuário aprova. Mudar a recomendação exige justificativa registrada na spec.

| ID | Decisão | Recomendação inicial | Dono |
| --- | --- | --- | --- |
| D1 | Fonte das dependências | `pyproject.toml` como fonte única (`dependencies` + `optional-dependencies`); nenhum `requirements.txt`, `setup.py`, `setup.cfg`, `Pipfile` ou `poetry`; o wheel publica `Requires-Dist` derivado; README aponta para o `pyproject.toml` | `python-engineer` |
| D2 | Reprodutibilidade | `constraints/dev.txt` com pins exatos (`==`) de dependências diretas e transitivas da resolução verde, aplicado na CI por `PIP_CONSTRAINT`; declarar também pins de build isolation, como `setuptools`, quando `pip freeze` do ambiente principal não os capturar; extras continuam com pisos `>=`; justificar e registrar como atualizar (por incremento, com suíte verde + `pip check`); rejeitar `uv.lock`/`pip-tools` por ora, salvo pedido explícito | `python-engineer` + usuário |
| D3 | Extras | `dev = [pytest, pytest-cov, ruff, mypy, virtualenv, build]`; `gui = [PySide6>=6.7]` inalterado; sem `twine` (publicação fora do escopo); `.[dev,gui]` é o ambiente completo de desenvolvimento; nenhum extra novo além destes | `python-engineer` |
| D4 | `virtualenv` vs `venv` | Disponibilizar o comando independente com `pipx install virtualenv` e criar o ambiente principal com `virtualenv --python "$(asdf which python)" .venv`; `python -m venv .venv` é fallback documentado; o `.venv` atual (criado com `venv`) continua válido; CI usa o interpretador do `setup-python`; runtime nunca depende de `virtualenv` | `python-engineer` |
| D5 | Ferramentas de desenvolvimento | `ruff`, `mypy`, `pytest`, `pytest-cov`, `build`, `pip check`; sem `pre-commit`, `tox`, `nox`, `pip-tools`, `twine` neste incremento | `python-engineer` |
| D6 | Cobertura | `pytest-cov` com `--cov=zonepad --cov-report=term-missing --cov-report=xml`; medir baseline antes de definir `fail_under` (valor registrado no ADR); publicar `coverage.xml` como artefato da CI; sem badge externo nem serviço de terceiros | `python-engineer` |
| D7 | CI de GUI | Instalar `.[dev,gui]`; executar `tests/test_gui.py` com JUnit XML dedicado e verificar com `xml.etree.ElementTree` que nenhum caso foi pulado; falhar explicitamente se `import PySide6` falhar; `QT_QPA_PLATFORM=offscreen` já definido no teste (`tests/test_gui.py:7`) e replicado no job | `python-engineer` |
| D8 | Build | `python -m build` gera sdist e wheel em `dist/`; validar conteúdo por listagem (`python -m zipfile -l`, `tar -tf`) e metadados; cada `License-File` do wheel deve existir em `.dist-info/licenses/`, e o sdist inclui `constraints/dev.txt` (usar `MANIFEST.in` se necessário); sem assinatura, sem `setuptools_scm`, sem wheel por plataforma (`py3-none-any`) | `python-engineer` |
| D9 | Instalação limpa | `python -m venv dist/smoke-venv` (já ignorado em `.gitignore:6`); instalar o wheel e depois o wheel com extra `gui`; smoke `zonepad --help`, `zonepad devices --help`, `QT_QPA_PLATFORM=offscreen zonepad-gui --smoke`; `pip check` no venv limpo | `python-engineer` |
| D10 | Packaging distro | AUR: manter `PKGBUILD` com `pkgver` igual ao `pyproject.toml` e `optdepends=('pyside6')`. Debian: preservar o scaffold, atualizar `Suggests: python3-pyside6.qtwidgets` em `debian/control` e registrar em `README.source` que não há versão Debian nem build validado; adiar conversão para `pybuild` porque ainda não há distro-alvo validada com Python 3.15. Publicação em AUR/Debian fica fora | `python-engineer` |
| D11 | Versão e changelog | Manter `0.1.0` (não publicado) como versão única em `pyproject.toml:7`; criar `CHANGELOG.md` em PT-BR com `[Não publicado]` e `[0.1.0]` cobrindo os incrementos 00–05; PKGBUILD usa o mesmo número; o scaffold Debian não declara versão enquanto `debian/changelog` não existir | `python-engineer` |
| D12 | Limites | Sem publicação em PyPI/AUR, sem Windows/macOS, sem mudar domínio/métricas/schema/mapping/GUI, sem Docker, sem assinatura de pacote, sem renomear entry points ou pacote | principal |

## Escopo

### 1. Dependências e extras

Inventário esperado após a auditoria (confirme com `grep`/AST antes de concluir; ajuste se o código real divergir):

| Camada | Uso | Onde declara | Observação |
| --- | --- | --- | --- |
| Runtime (`src/zonepad/domain`, `application`, `infrastructure`, `interface/cli.py`) | stdlib apenas | `dependencies = []` | `import zonepad`, `zonepad --help` e `zonepad devices --help` funcionam em instalação mínima |
| GUI (`src/zonepad/interface/gui/**`) | PySide6 | extra `gui` | import lazy; ausência gera exit `2` com instrução |
| Desenvolvimento | pytest, pytest-cov, ruff, mypy, virtualenv, build | extra `dev` | suficiente para testar, medir, formatar, tipar e construir |
| Build isolado | setuptools, wheel (via `build`) | `[build-system]` | `python -m build` usa ambiente isolado; `virtualenv` não é dependência de build |

- Auditar todo `import` de `src/zonepad/` e classificar: stdlib, runtime (hoje nenhum), opcional `gui`, ferramenta de dev.
- `dev` passa a conter `build` e `pytest-cov`, além do que já existe; manter `virtualenv` porque o README o recomenda.
- `gui` mantém `PySide6>=6.7`; nenhuma dependência de GUI pode migrar para `dependencies`.
- Verificar que nenhum módulo de `domain/`, `application/` ou `interface/cli.py` importa `PySide6`, `pytest`, `build`, `ruff` ou `mypy`.
- `python -m pip check` limpo após instalar `.[dev,gui]`.
- Se `pytest 9.1.1` já cobre `subtests` sem plugin (verificado localmente), **não** adicionar `pytest-subtests`; documente a constatação.

### 2. Reprodutibilidade

- Implementar D2: `constraints/dev.txt` com pins exatos da resolução verde, incluindo dependências diretas, transitivas, PySide6 e ferramentas de build isolation como `setuptools`.
- Documentar como o arquivo é gerado e atualizado (comando, critério de aceite, quem aprova) — pode ser um parágrafo na spec, sem script novo obrigatório.
- CI aplica `PIP_CONSTRAINT=constraints/dev.txt` no job de testes; se o pin impedir a instalação, a CI falha de forma legível.
- Não criar segundo manifesto de dependências: o constraints fixa versões, não lista extras nem substitui o `pyproject.toml`.
- Registrar explicitamente que `>=` continua valendo para consumidores do wheel.
- Procedimento de atualização esperado (registre o comando real na spec):

```bash
python -m pip install -e '.[dev,gui]'      # em .venv, sem PIP_CONSTRAINT
python -m pytest -q -o addopts=""          # 704 testes verdes
python -m pip check
python -m pip freeze > constraints/dev.txt # revisar dependências diretas/transitivas; declarar pins de build isolation ausentes do freeze; remover entrada editável do projeto e pacotes alheios ao ambiente
git diff constraints/dev.txt               # registrar o que mudou e por quê
```

### 3. Ambiente local e README

Reescrever a seção **Desenvolvimento** do `README.md:13-33` com os passos abaixo, cada um com comando e saída esperada:

1. Pré-requisitos: Linux, `asdf`, `git`, compilador apenas se o Python exigir build local.
2. `asdf`/`.tool-versions`: `asdf plugin add python`, `asdf install python 3.15.0`, `asdf set python 3.15.0`, `python --version`.
3. Instalar o comando `virtualenv` com `pipx install virtualenv` e criar `.venv` com `virtualenv --python "$(asdf which python)" .venv`; manter `python -m venv .venv` como fallback quando `pipx`/`virtualenv` não estiver disponível, explicando quando usar cada um (D4).
4. Ativar e instalar: `source .venv/bin/activate`, `python -m pip install -e '.[dev]'` (CLI + testes) e `python -m pip install -e '.[dev,gui]'` (GUI); explicar o que cada extra traz.
5. Verificar: `python -m pytest -q`, `python -m ruff check .`, `python -m mypy src/zonepad`, `python -m pip check`.
6. Build: `python -m build` → `dist/zonepad-0.1.0-py3-none-any.whl` e `dist/zonepad-0.1.0.tar.gz`.
7. Instalação limpa: criar `dist/smoke-venv`, instalar o wheel, rodar `zonepad --help`, `zonepad devices --help`, instalar o extra `gui` e rodar `QT_QPA_PLATFORM=offscreen zonepad-gui --smoke`.
8. Rodar CLI e GUI: fluxo `devices` → `mapping draft` → `calibrate` → `run` e `zonepad-gui`.
9. Troubleshooting: PySide6 ausente (mensagem e comando), display indisponível/`offscreen`, permissões de `/dev/input` e `/dev/uinput` (grupo e regra udev reversível, nunca `sudo` silencioso), PyPI indisponível/mirror/offline (`--find-links`, cache local, aviso sobre índice alternativo).
10. Origem das dependências: PyPI padrão, ausência de `requirements.txt`, `pyproject.toml` como fonte, o que cada extra resolve.

- Substituir `README.md:419` (descrição da CI) pela nova matriz de jobs.
- Não duplicar fórmulas, protocolo de captura, schema de perfil ou detalhes de GUI: referenciar `docs/specs/metrics-v1.md`, `wizard-v1.md`, `device-discovery-v1.md`, `gui-v1.md` e ADRs 0001–0008.

### 4. CI

- Manter o arquivo `.github/workflows/ai-assets.yml` e o job `check` (ruff, mypy, sync `--check`), sem renomear o workflow — renomear altera checks obrigatórios e exige ação do usuário.
- Novo job `test`: instalar `.[dev,gui]` com `PIP_CONSTRAINT`, definir `QT_QPA_PLATFORM=offscreen`, rodar `pytest` com cobertura, rodar `pip check`, publicar `coverage.xml`.
- Falhar se a GUI for pulada: além de instalar PySide6, adicione verificação explícita (`python -c "import PySide6"`), execute `tests/test_gui.py` com JUnit XML dedicado e use `xml.etree.ElementTree` para falhar se qualquer caso estiver marcado como skipped.
- Novo job `package`: `python -m build`, instalação do wheel em venv limpo, smokes de CLI e GUI, `pip check`, upload de `dist/*` como artefato.
- Manter Python 3.15.0 e incluir `constraints/**`, `README.md` e `packaging/**` no gatilho `paths` do workflow.
- Não adicionar serviços externos, badges ou codecov; cobertura fica como artefato.

### 5. Build e empacotamento

- `python -m build` sem `--no-isolation` no fluxo local; no `PKGBUILD`, manter `--no-isolation` (build do sistema).
- Validar o wheel por listagem e metadados: `zonepad/**` completo, `zonepad/infrastructure/catalog_data/families.json`, `METADATA` com `Requires-Python`, `Requires-Dist` do extra `gui` e a descrição longa originada de `README.md`; `entry_points.txt` com `zonepad` e `zonepad-gui`; cada caminho `License-File` deve existir em `.dist-info/licenses/`.
- Validar que o sdist contém `pyproject.toml`, `src/`, `README.md`, `LICENSE` e `constraints/dev.txt`; incluir `tests/` quando aplicável ao pacote. Se o backend não incluir constraints, adicionar `MANIFEST.in` para declarar esse conteúdo.
- Smoke do wheel **sem** o extra `gui`: CLI funciona e `zonepad-gui` retorna `2` com mensagem acionável quando PySide6 está ausente.
- Não commitar `dist/`; `.gitignore` já cobre `dist/` (`:6`) e `build/` (`:7`). Se a execução local gerar `coverage.xml` na raiz, adicione a entrada ao `.gitignore` (`.coverage` em `:13` e `htmlcov/` em `:14` já existem; `coverage.xml` não).

### 6. Release e versão

- `CHANGELOG.md` no formato Keep a Changelog em PT-BR, com `[Não publicado]` e `[0.1.0]` resumindo 00–05 por área (runtime, métricas, wizard, descoberta, GUI).
- Versão única em `pyproject.toml:7`; `packaging/aur/PKGBUILD:2` e `packaging/debian/changelog` (criar se o pacote Debian for mantido como executável) coerentes. Se o Debian continuar apenas como scaffold sem changelog, registrar que ele ainda não declara versão; `debian/control` descreve dependências e metadados do pacote, não sua versão.
- Revisar `PKGBUILD` (`depends`, `makedepends`, `optdepends`, `build`/`package`) para consistência. No scaffold Debian, atualizar apenas `Suggests` em `debian/control` e manter em `README.source` o registro de que não há versão Debian nem build validado; adiar conversão para `pybuild` até haver distro-alvo validada com Python 3.15. Nenhuma publicação.
- Registrar no README o comando de build e onde ficam os artefatos.

### 7. Documentação

- `docs/specs/dev-environment-v1.md`: problema, usuário, escopo, inventário de dependências, D1–D12 com dono e justificativa, matriz de testes, riscos, limites.
- `docs/adr/0009-ambiente-de-desenvolvimento-build-e-release.md` (confirme que 0009 é livre): fonte única de dependências, constraints, extras, política `virtualenv`/`venv`, cobertura, CI de GUI e de pacote, build, instalação limpa, packaging distro e versão.
- `README.md`: seção **Desenvolvimento** completa e matriz de CI atual.
- `ai/prompts/README.md` (via `prompt-engineer`): 05 concluído (PR #14), 06 como último prompt do roadmap, exemplos de invocação apontando para o 06.

## Artefatos e caminhos

| Artefato | Caminho esperado | Versionado |
| --- | --- | --- |
| Constraints de desenvolvimento | `constraints/dev.txt` | sim |
| Wheel | `dist/zonepad-0.1.0-py3-none-any.whl` | não (`dist/` ignorado) |
| Sdist | `dist/zonepad-0.1.0.tar.gz` | não |
| Ambiente de desenvolvimento | `.venv/` | não |
| Ambiente de smoke | `dist/smoke-venv/` | não |
| Cobertura | `coverage.xml`, `htmlcov/` | não; ajustar `.gitignore` se gerados localmente |
| Changelog | `CHANGELOG.md` | sim |
| Spec e ADR | `docs/specs/dev-environment-v1.md`, `docs/adr/0009-*.md` | sim |
| Workflow | `.github/workflows/ai-assets.yml` | sim |

## Fora de escopo

- Qualquer feature nova, mudança de comportamento da CLI/GUI ou de mensagens de usuário.
- Domínio, normalização, métricas, thresholds, findings, calibração, wizard, schema de perfil v1/v2, mapping v1, descoberta e catálogo de famílias.
- Publicação real em PyPI, AUR, Debian ou qualquer repositório; assinatura de pacotes; deploy.
- Windows, macOS, containerização, Nix, Flatpak, Snap.
- Renomear pacote, entry points, workflow ou mover `src/zonepad/`.
- Adicionar `pre-commit`, `tox`, `nox`, `pip-tools`, `uv`, `poetry`, `hatch`, `pdm` ou `twine`.
- Push, PR, merge ou rebase.

## Critérios de aceite

- [ ] `python -m pip install -e '.[dev]'` em venv novo instala `pytest`, `pytest-cov`, `ruff`, `mypy`, `virtualenv` e `build`, e `python -c "import build, pytest_cov"` funciona.
- [ ] `python -m pip install -e '.[dev,gui]'` instala PySide6 e a suíte de GUI roda completa.
- [ ] `python -m pip install -e '.[dev]'` (sem `gui`) mantém `import zonepad`, `zonepad --help` e `zonepad devices --help` funcionando; `zonepad-gui` retorna `2` com mensagem acionável.
- [ ] O repositório continua sem `requirements.txt`, `setup.py`, `setup.cfg` e `Pipfile`; `dependencies` runtime permanece vazio.
- [ ] `constraints/dev.txt` fixa versões exatas da resolução aprovada, incluindo dependências diretas/transitivas e pins de build isolation; a CI instala com `PIP_CONSTRAINT`.
- [ ] `python -m pip check` retorna `No broken requirements found` no ambiente de dev e no venv limpo.
- [ ] Nenhum módulo de `src/zonepad/` importa `pytest`, `build`, `ruff`, `mypy` ou `PySide6` fora de `interface/gui/`.
- [ ] `README.md` tem seção **Desenvolvimento** com os 10 blocos do escopo 3, executáveis na ordem, com saída esperada.
- [ ] README documenta: origem PyPI, ausência de `requirements.txt`, função de cada extra e política `virtualenv`/`venv`.
- [ ] README traz troubleshooting para PySide6 ausente, display/offscreen, `/dev/input`, `/dev/uinput` e PyPI/offline.
- [ ] A CI executa `tests/test_gui.py` em offscreen e verifica zero skips no JUnit XML dedicado; falha se PySide6 não importar.
- [ ] A CI roda `pip check`, ruff, mypy, pytest e `sync_ai_assets.py --check`.
- [ ] A CI constrói sdist e wheel, instala o wheel em venv limpo e executa os três smokes.
- [ ] `python -m build` gera `dist/*.whl` e `dist/*.tar.gz` sem erro.
- [ ] O wheel contém `zonepad/infrastructure/catalog_data/families.json` e `entry_points.txt` com `zonepad` e `zonepad-gui`; `METADATA` inclui descrição longa originada do README e cada `License-File` declarado aponta para arquivo presente em `.dist-info/licenses/`.
- [ ] O sdist contém `constraints/dev.txt`; se necessário, `MANIFEST.in` declara sua inclusão.
- [ ] Em venv limpo: `zonepad --help` = 0, `zonepad devices --help` = 0, `QT_QPA_PLATFORM=offscreen zonepad-gui --smoke` = 0.
- [ ] `docs/specs/dev-environment-v1.md` e ADR 0009 aceitos, com D1–D12 fechadas e justificadas.
- [ ] `CHANGELOG.md` existe com `[Não publicado]` e `[0.1.0]`; versão coerente com `PKGBUILD` e, se o pacote Debian for mantido como executável, com `packaging/debian/changelog`. Se Debian permanecer como scaffold sem changelog, essa ausência fica registrada.
- [ ] `packaging/aur/PKGBUILD` coerente com versão e dependências; `packaging/debian/control` mantém `Suggests` atualizado e o scaffold sem versão/build validado fica documentado em `README.source`; nenhuma publicação executada.
- [ ] `ai/prompts/README.md` marca 05 concluído (PR #14) e 06 em implementação/último do roadmap; `sync_ai_assets.py --check` limpo.
- [ ] O relatório final declara `controller-hardware` como N/A com justificativa e lista o que não foi executado.

## Matriz de testes

| Caso | Entrada | Esperado |
| --- | --- | --- |
| Extras de dev completos | venv novo + `pip install -e '.[dev]'` | `build`, `pytest_cov`, `ruff`, `mypy`, `virtualenv` importáveis; `python -m build` inicia |
| Isolamento da GUI | venv novo + `pip install -e '.[dev]'` | `import PySide6` falha; `zonepad --help` = 0; `zonepad-gui` = 2 com instrução de instalação |
| GUI na CI | `.[dev,gui]` + `QT_QPA_PLATFORM=offscreen` + relatório JUnit XML dedicado | `tests/test_gui.py` executado, 11 passed, 0 skipped; o XML dedicado é analisado com `xml.etree.ElementTree` |
| Detecção de skip | step de verificação do relatório JUnit XML do workflow | step falha citando qualquer teste skipped |
| `pip check` | ambiente de dev e venv limpo | código 0, `No broken requirements found` |
| Constraints | `PIP_CONSTRAINT=constraints/dev.txt pip install -e '.[dev,gui]'` | versões fixadas instaladas; suíte verde; `pip freeze` compatível com o arquivo |
| Deriva de constraints | pin inexistente/incompatível | instalação falha com mensagem legível; nenhum fallback silencioso |
| Conteúdo do wheel | `python -m zipfile -l dist/*.whl` + leitura de `METADATA` | `catalog_data/families.json`, `entry_points.txt`; descrição longa de README em `METADATA`; cada caminho `License-File` existe em `.dist-info/licenses/` |
| Conteúdo do sdist | `tar -tf dist/*.tar.gz` | `pyproject.toml`, `src/zonepad/`, `catalog_data/families.json`, `README.md`, `LICENSE`, `constraints/dev.txt` |
| Wheel sem GUI | venv limpo + wheel | CLI ok; `zonepad-gui` = 2; sem traceback |
| Wheel com GUI | venv limpo + `pip install "dist/zonepad-0.1.0-py3-none-any.whl[gui]"` | `zonepad-gui --smoke` offscreen = 0 |
| Sdist instalável | venv limpo + `pip install dist/*.tar.gz` | instala e smokes passam |
| Metadados de extras | parse de `pyproject.toml` em teste | `dev` contém `build` e `pytest-cov`; `PySide6` aparece só em `gui`; `dependencies == []` |
| Package data declarado | `pyproject.toml` + árvore real | todo `*.json` de `catalog_data/` está coberto pelo padrão declarado |
| Imports de runtime | AST de `src/zonepad/` exceto `interface/gui/` | nenhum import de `PySide6`, `pytest`, `build`, `ruff`, `mypy` |
| README executável | comandos da seção **Desenvolvimento** | cada comando existe, na ordem, com saída esperada declarada |
| Changelog e versão | `CHANGELOG.md`, `pyproject.toml`, `PKGBUILD`, `packaging/debian/changelog` quando aplicável | mesma versão `0.1.0`; `[Não publicado]` presente; Debian sem changelog é reportado como scaffold sem versão |
| Regressão | suíte completa | 704 testes anteriores continuam verdes + novos |

Adicione `tests/test_packaging.py` cobrindo metadados, package data e imports de runtime — determinístico, sem rede e **sem** rodar build. Um teste que execute `python -m build` é opcional: marque-o com `skip` por padrão (ou marker `slow`) e rode-o no job `package` da CI.

## Validação

Execute e reporte a saída:

```bash
python --version
python -m pip install -e '.[dev,gui]'
python -m pip check
python -m pytest -q -o addopts=""
QT_QPA_PLATFORM=offscreen python -m pytest -q tests/test_gui.py -o addopts=""
python -m pytest -q --cov=zonepad --cov-report=term-missing --cov-report=xml
python -m ruff check .
python -m ruff format --check .
python -m mypy src/zonepad
python scripts/sync_ai_assets.py --check
python -m build
python -m zipfile -l dist/zonepad-0.1.0-py3-none-any.whl
tar -tf dist/zonepad-0.1.0.tar.gz
python -m venv dist/smoke-venv
dist/smoke-venv/bin/python -m pip install dist/zonepad-0.1.0-py3-none-any.whl
dist/smoke-venv/bin/zonepad --help
dist/smoke-venv/bin/zonepad devices --help
dist/smoke-venv/bin/zonepad-gui; echo "exit=$?"          # esperado 2, sem traceback
dist/smoke-venv/bin/python -m pip install "dist/zonepad-0.1.0-py3-none-any.whl[gui]"
QT_QPA_PLATFORM=offscreen dist/smoke-venv/bin/zonepad-gui --smoke; echo "exit=$?"
dist/smoke-venv/bin/python -m pip check
```

Repita a instalação com `PIP_CONSTRAINT=constraints/dev.txt` e registre o diff de versões.

Se `ruff format --check` já falhar em `main` em arquivo fora do escopo, registre o débito e não o amplie. Se uma ferramenta não estiver disponível ou um comando depender de rede indisponível, declare exatamente o que não foi executado. Não execute `sudo`, não altere permissões e não publique nada.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| Drift sem lockfile | CI e máquina local divergem sem aviso | D2 com constraints; CI aplica `PIP_CONSTRAINT`; atualização com suíte verde e `pip check` |
| Constraints desatualizadas | instalação quebra ou bloqueia patch de segurança | processo de atualização documentado; falha legível na CI; revisão por incremento |
| PySide6 com wheel indisponível | job de GUI quebra ou volta a pular testes | D7 falha explícita quando PySide6 não importa; versão fixada em constraints; registrar versão validada |
| CI mais pesada e lenta | feedback demorado, custo de minutos | dividir em `check`, `test`, `package`; cache de pip; artefatos só quando necessário |
| Wheel sem package data | catálogo ausente em runtime instalado | teste de conteúdo do wheel + teste que cruza `package-data` com a árvore real |
| GUI headless instável | flakiness na CI | `offscreen` fixado; sem display real; smoke isolado em processo próprio |
| Permissões de `/dev/input` e `/dev/uinput` | usuário acha que a instalação falhou | troubleshooting no README com grupo e udev reversível; nunca `sudo` embutido |
| Instalação limpa depende de rede | job falha por indisponibilidade do PyPI | separar falha de rede de falha de pacote; documentar `--find-links`/cache local |
| `fail_under` inventado | suíte vermelha sem ganho real | medir baseline e registrar o valor no ADR antes de ativar |
| README divergir dos comandos reais | onboarding quebrado | revisão por `prompt-engineer` + execução literal dos comandos nas etapas 8 e 11 |
| Packaging distro divergir da versão | pacote de distribuição inconsistente | D10 limitado à consistência do AUR e à manutenção do scaffold Debian; `pkgver`, `Suggests` e nota sobre ausência de distro-alvo Python 3.15 conferidos na etapa 13 |
| Escopo crescer para release real | incremento não fecha | D12 e **Fora de escopo** explícitos; publicação exige novo incremento |

## Formato de saída

Responda em PT-BR com:

1. **Plano executado** — 3–6 bullets com a ordem real e onde houve handoff.
2. **Spec e decisões** — caminho de `dev-environment-v1.md`, ADR 0009 e D1–D12 fechadas, com o que mudou em relação às recomendações.
3. **Mudanças por arquivo** — `pyproject.toml`, `constraints/`, CI, README, `CHANGELOG.md`, `packaging/`, testes e docs.
4. **Ambiente provado** — comandos de instalação, versões efetivamente instaladas, resultado de `pip check` e do `pip freeze`.
5. **Build e conteúdo** — listagem do wheel e do sdist, com evidência de `catalog_data` e entry points.
6. **Instalação limpa** — caminho do venv, comandos e exit codes dos três smokes; declare o que não rodou.
7. **CI** — jobs, comandos, cobertura publicada e como a GUI deixou de ser pulada.
8. **Parecer de `controller-hardware`** — declarar N/A com a justificativa da seção **Agentes**.
9. **Riscos e limitações** — drift, PySide6, cobertura, headless, permissões, distribuição.
10. **Próximo passo** — o que fica aberto para publicação real, validação com hardware e revisão visual da GUI.

## Invocação

### Claude Code (prioritária)

```text
Use o prompt em @ai/prompts/06-quality-release.md.
Leia o arquivo inteiro antes de agir e siga a tabela "Etapas e responsáveis" na ordem.
Trabalhe no checkout principal, sem git worktree, na branch chore/dev-environment-release
criada a partir da main; confirme os gates de "Pré-condições" antes de qualquer edição.
Comece com /flow-design-feature e NÃO escreva código de produção antes de a spec
docs/specs/dev-environment-v1.md e o ADR 0009 serem aprovados pelo usuário.
Delegue a python-engineer: auditoria de dependências, pyproject e extras, constraints,
CI, build, wheel/sdist, instalação limpa, testes, README técnico, CHANGELOG e packaging.
Delegue a prompt-engineer apenas ai/ e a estrutura/clareza do README, revisando
consistência entre prompt, README, spec, ADR e agentes; ele não implementa build.
Não acione controller-hardware para parecer: registre explicitamente que é N/A
(este incremento não altera protocolo, medição, calibração nem hardware).
Implemente com /flow-implement-feature e faça a revisão final com /flow-review-calibration.
Valide com os comandos da seção "Validação" e entregue o relatório no "Formato de saída".
```

### Codex (alternativa)

```text
Siga o prompt em ai/prompts/06-quality-release.md.
Leia o arquivo inteiro e execute as etapas na ordem, no checkout principal, sem worktree,
na branch chore/dev-environment-release criada a partir da main.
Use $flow-design-feature para a spec e o ADR 0009, $flow-implement-feature para a
implementação e $flow-review-calibration para a revisão. Não escreva código antes da
aprovação da spec.
Delegue pyproject, extras, constraints, CI, build, empacotamento, instalação limpa,
testes, README técnico e CHANGELOG a python-engineer.
Use prompt-engineer apenas para ai/ e para a estrutura/clareza do README.
Não acione controller-hardware: declare N/A com justificativa.
Valide com pytest, ruff, mypy, pip check, sync --check, python -m build, instalação
do wheel em venv limpo e os smokes zonepad --help, zonepad devices --help e
zonepad-gui --smoke em QT_QPA_PLATFORM=offscreen.
```

Se os fluxos não existirem no harness, siga `ai/flows/flow-design-feature/FLOW.md`, `ai/flows/flow-implement-feature/FLOW.md` e `ai/flows/flow-review-calibration/FLOW.md`, e registre o fallback.

## Sequência

- **Prompts 00–05 (concluídos):** toolchain, runtime, métricas, wizard CLI, descoberta/mapping e GUI PySide6.
- **Prompt 06 (este):** qualidade, dependências, ambiente, build e release — último incremento planejado do roadmap atual.

Este prompt fecha o roadmap. Trabalho posterior (publicação em PyPI/AUR, validação com múltiplos controles reais, revisão visual da GUI em desktop) exige novo incremento com spec própria.

## Handoff final

Ao concluir, entregue:

1. Versões exatas do ambiente validado (Python, PySide6, pytest, pytest-cov, ruff, mypy, build) e o conteúdo de `constraints/dev.txt`.
2. Comando único que reproduz o ambiente completo e o que ele instala.
3. Evidência de build: nomes dos artefatos, tamanho, listagem de conteúdo.
4. Evidência de instalação limpa: caminho do venv, comandos, exit codes, saída de `pip check`.
5. Estado da CI: jobs, comandos e artefatos publicados.
6. Valor de cobertura inicial e a decisão sobre `fail_under`.
7. Pendências declaradas e próximo incremento proposto.
