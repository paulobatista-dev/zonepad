# Prompt 00 — Toolchain Python 3.15.0 com asdf e virtualenv

- **Status:** pré-requisito do prompt 01.
- **Branch de execução:** `chore/toolchain-python-315`, criada a partir de `main`.
- **Fluxo principal:** `$flow-implement-feature`.
- **Revisão final:** `$flow-review-calibration`.
- **Agentes:** `python-engineer` (toolchain, `pyproject.toml`, CI e comandos) e `prompt-engineer` (instruções em `ai/`, revisão de consistência). `controller-hardware` não participa deste incremento.

## Missão

Fixar Python 3.15.0 como versão padrão do ZonaPad, controlada por asdf, com ambiente de desenvolvimento criado por virtualenv, e alinhar `pyproject.toml`, CI e documentação a essa escolha.

O resultado deve permitir que uma pessoa nova clone o repositório, execute os comandos documentados e obtenha exatamente Python 3.15.0, um `.venv` funcional e os mesmos gates da CI.

Este prompt é um pré-requisito do prompt 01 (`01-runtime-cli-end-to-end.md`). Ele preserva o escopo do runtime CLI e não implementa calibração.

## Por que este prompt existe

O projeto declara Python 3.12+, usa `uv` e `[dependency-groups]`, e a CI roda 3.12. A decisão atual é fixar 3.15.0 via asdf e usar virtualenv no desenvolvimento. Sem esse alinhamento, o prompt 01 seria implementado sobre uma toolchain que não é a oficial.

## Contexto verificado

Os dados abaixo foram verificados em 2026-10-24 no checkout local. Revalide na branch limpa; eles orientam a decisão, mas os gates da seção **Validação** são a fonte de verdade.

| Verificação | Resultado |
| --- | --- |
| `asdf --version` | `0.20.0` |
| `asdf plugin list` / `asdf list python` | plugin `python` presente; versão `3.15.0` instalada |
| `.tool-versions` no repositório | ausente |
| `virtualenv` no interpretador atual | não instalado; a versão `21.14.13` do PyPI requer Python `>=3.9` e deve ser instalada via `pipx` ou `pip --user` |
| `ruff 0.17.2` | aceita `target-version = "py315"` e resolve 3.15 |
| `mypy 2.4.0` | aceita `--python-version 3.15` |
| `pytest 9.1.1` | suíte de `main` passa em Python 3.15.0 |
| `actions/python-versions` | `3.15.0` estável no manifest usado pelo `setup-python` |
| `PySide6 6.12.0` | `requires_python = "<3.16,>=3.10"` |
| `ruff format --check` em `main` com `py315` | falha em `scripts/sync_ai_assets.py` por reescrita PEP 758 |

O checkout onde este prompt foi redigido está em `feat/runtime-cli-end-to-end`, com alterações não commitadas do prompt 01. Este prompt deve ser executado em outro checkout ou worktree limpo, criado a partir de `main`.

## Decisões de política

1. **Versão exata no asdf, faixa nos metadados.** `.tool-versions` fixa `python 3.15.0` para reprodutibilidade local. `requires-python` usa `>=3.15,<3.16`: aceita correções 3.15.x sem reabrir a decisão, bloqueia 3.16 até validação explícita e é a forma de faixa que pip, build backends e ferramentas de packaging esperam. `==3.15.*` tem o mesmo efeito prático; se for escolhido, registre a escolha no README.
2. **Uma fonte para dependências de desenvolvimento.** O extra `[project.optional-dependencies].dev` substitui `[dependency-groups]`. O caminho documentado e usado na CI é `python -m pip install -e '.[dev]'`. Remova `[tool.uv]` e as referências a uv.
3. **CI na versão exata.** O workflow usa `python-version: "3.15.0"` e instala `.[dev]`, mantendo paridade com o ambiente local sem usar asdf na CI.
4. **virtualenv no desenvolvimento, `venv` como fallback.** O virtualenv não está instalado no interpretador atual. A versão `21.14.13` do PyPI requer Python `>=3.9` e deve ser instalada via `pipx` ou `python -m pip install --user virtualenv`. Crie `.venv` com `virtualenv`; se ele não puder ser instalado, use `python -m venv .venv` e registre o fallback.
5. **Alvos de ferramentas alinhados.** `mypy.python_version = "3.15"` e `ruff.target-version = "py315"`. O ruff 0.17.2 aceita `py315`; não é necessário usar `py314`.
6. **Sem ADR neste incremento.** Este incremento não cria ADR: a política fica registrada no README e em `ai/instructions/AGENTS.md`. Se um ADR for criado depois, confira a numeração disponível no momento; não assuma um número.
7. **Hardware fora do escopo.** O diff não altera protocolo, medição, calibração, ranges, normalização nem schema de perfil. Na revisão final, a etapa de hardware do `$flow-review-calibration` fica registrada como **N/A**, com essa justificativa, e não bloqueia o pronto.

## Pré-condições e branch

1. O arquivo deste prompt deve estar versionado em `main` antes da execução. Assim o worktree nasce limpo e o próprio prompt não aparece como arquivo não rastreado.
2. Execute em um checkout limpo criado a partir de `main`. A branch sugerida é `chore/toolchain-python-315`.
3. Confirme o estado antes de editar:

```bash
git status --porcelain
git branch --show-current
git log --oneline main..HEAD
git diff --name-only main -- src/ tests/
```

Gates de entrada:

- `git status --porcelain` vazio.
- branch atual `chore/toolchain-python-315`.
- `git log --oneline main..HEAD` vazio no início.
- `git diff --name-only main -- src/ tests/` vazio.

Se qualquer gate falhar, pare e peça um checkout limpo ao usuário. Se o working tree contiver alterações do prompt 01, pare imediatamente.

Regras de segurança:

- Preserve a branch `feat/runtime-cli-end-to-end` e suas alterações não commitadas.
- Use worktree ou clone; não use `git stash`, `git reset`, `git checkout --` nem `git restore` para “limpar” o estado.
- Não faça merge, rebase, push ou pull request sem pedido explícito.
- Não use `sudo` e não instale nada no sistema.
- Não edite arquivos gerados: `AGENTS.md`, `CLAUDE.md`, `.opencode/`, `.claude/`, `.agents/`, `.codex/`.

## Etapas e responsáveis

| # | Etapa | Executor | Revisor/apoio | Fluxo/skill | Saída | Gate |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Preflight e branch | `python-engineer` | `prompt-engineer` | `$flow-implement-feature` (passos 1–2) | branch `chore/toolchain-python-315` a partir de `main` | working tree limpo; branch correta; sem commits do prompt 01 |
| 2 | Fixar Python 3.15.0 | `python-engineer` | — | `python-quality` | `.tool-versions` | `asdf current python` mostra 3.15.0; `python --version` mostra 3.15.0 |
| 3 | Criar `.venv` e instalar `.[dev]` | `python-engineer` | — | `python-quality` | `.venv` com virtualenv | `sys.prefix` aponta para `.venv`; pytest, ruff, mypy e virtualenv respondem |
| 4 | Ajustar `pyproject.toml` | `python-engineer` | `prompt-engineer` | `python-quality`, `clean-code` | metadados, extra `dev`, alvos de ruff/mypy | instalação limpa; pytest, ruff e mypy verdes |
| 5 | Ajustar CI | `python-engineer` | `prompt-engineer` | `python-quality`, `github-interaction` | workflow com 3.15.0 e `.[dev]` | pytest e sync verdes; ruff/mypy incluídos apenas se verdes |
| 6 | Atualizar `README.md` | `python-engineer` | `prompt-engineer` | `python-quality`, `prompt-design` | requisitos, ambiente, validação e prompts | comandos copiáveis; sem uv; versão coerente |
| 7 | Atualizar fontes em `ai/` | `prompt-engineer` | `python-engineer` | `prompt-design`, `positive-ontology` | AGENTS, skill, agente e README de prompts | texto coerente com o README; sem duplicação |
| 8 | Sincronizar espelhos | `prompt-engineer` | `python-engineer` | `prompt-design` | arquivos gerados e manifestos | `sync --check` limpo; nenhum gerado editado à mão |
| 9 | Validar e revisar | `python-engineer` + `prompt-engineer` | — | `$flow-review-calibration` | relatório final | sem blocker; `src/` e `tests/` inalterados; hardware N/A registrado |

`controller-hardware` não participa deste incremento. Na revisão final, registre a ausência com a justificativa da decisão 7.

Se `$flow-implement-feature` ou `$flow-review-calibration` não estiverem disponíveis no Codex, siga os arquivos `ai/flows/flow-implement-feature/FLOW.md` e `ai/flows/flow-review-calibration/FLOW.md`, respectivamente, e registre o fallback no relatório.

## Detalhamento das etapas

### 1. asdf e `.tool-versions`

Verifique o plugin e a versão antes de instalar:

```bash
asdf plugin list
asdf list python
```

Se o plugin `python` não estiver presente:

```bash
asdf plugin add python
```

Se `3.15.0` não estiver instalado:

```bash
asdf install python 3.15.0
```

Fixe a versão no repositório:

```bash
asdf set python 3.15.0
cat .tool-versions
asdf current python
python --version
```

Resultado esperado:

- `.tool-versions` contém a linha `python 3.15.0` e nenhuma outra versão de Python.
- `asdf current python` mostra `3.15.0` com fonte no `.tool-versions` do repositório.
- `python --version` imprime `Python 3.15.0`.

Se a versão instalada do asdf não tiver o subcomando `set`, grave o arquivo de forma determinística:

```bash
printf 'python 3.15.0\n' > .tool-versions
```

Se `3.15.0` não estiver disponível no plugin, pare e pergunte ao usuário. Não troque a versão nem use `latest` silenciosamente.

### 2. `.venv` com virtualenv

O virtualenv não está instalado no interpretador atual. Instale-o sem root; prefira `pipx` quando ele existir e use o site de usuário como alternativa:

```bash
python -m pip install --user virtualenv
python -m virtualenv --version
```

A versão `21.14.13` do PyPI requer Python `>=3.9`. Se o ambiente bloquear a instalação em user site, use `pipx install virtualenv` ou siga para o fallback com `venv`.

Crie o ambiente com o interpretador resolvido pelo asdf:

```bash
python -m virtualenv --python "$(asdf which python)" .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Verifique:

```bash
python --version
python -c 'import sys; print(sys.prefix)'
python -m pytest --version
python -m ruff --version
python -m mypy --version
python -m virtualenv --version
```

Gates:

- `sys.prefix` aponta para `<raiz-do-checkout>/.venv`.
- `python --version` mostra `3.15.0`.
- Os quatro comandos de ferramenta respondem sem erro.

Fallback aceito quando `virtualenv` não puder ser instalado:

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

Se `.venv` existir e estiver inconsistente, recrie com `python -m virtualenv --clear --python "$(asdf which python)" .venv`. `.venv` é descartável e já está no `.gitignore`.

### 3. `pyproject.toml`

Preserve o restante do arquivo. Os blocos relevantes devem ficar assim:

```toml
[project]
name = "zonepad"
version = "0.1.0"
description = "Calibração de controles no Linux"
readme = "README.md"
license = "MIT"
license-files = ["LICENSE"]
requires-python = ">=3.15,<3.16"
dependencies = []

[project.optional-dependencies]
gui = ["PySide6>=6.7"]
dev = [
  "pytest>=9.1",
  "ruff>=0.17.2",
  "mypy>=2.4",
  "virtualenv>=21.14",
]

[tool.mypy]
python_version = "3.15"
strict = false
ignore_missing_imports = true
files = ["src/zonepad"]

[tool.ruff]
line-length = 100
target-version = "py315"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]
```

Remova:

- o bloco `[tool.uv]` e a chave `package = true`;
- o bloco `[dependency-groups]` com o `dev` antigo.

Justificativa dos pisos: `ruff 0.17.2`, `mypy 2.4.0` e `pytest 9.1.1` foram verificados em Python 3.15.0. O `virtualenv 21.14.13` é a versão do PyPI, declara `requires-python >=3.9` e foi testado com Python 3.15.0. Pisos anteriores podem não reconhecer `py315` ou `3.15`. Mantenha `gui` como extra separado; o incremento não instala nem valida a GUI.

Verifique os alvos efetivos:

```bash
python -m ruff check --show-settings src/zonepad/__init__.py | grep -i 'target_version'
python -m mypy --python-version 3.15 src/zonepad
```

O ruff deve resolver `3.15`. Se a versão instalada rejeitar `py315`, eleve o piso do ruff para uma versão que aceite. Use `py314` apenas se nenhuma versão suportada aceitar `py315`, e registre a limitação no relatório.

### 4. CI

Atualize `.github/workflows/ai-assets.yml`:

```yaml
name: ai-assets

on:
  push:
    paths:
      - "ai/**"
      - "scripts/sync_ai_assets.py"
      - "tests/**"
      - "src/**"
      - "pyproject.toml"
      - ".tool-versions"
      - ".github/workflows/ai-assets.yml"
  pull_request:
    paths:
      - "ai/**"
      - "scripts/sync_ai_assets.py"
      - "tests/**"
      - "src/**"
      - "pyproject.toml"
      - ".tool-versions"
      - ".github/workflows/ai-assets.yml"
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.15.0"
      - name: Instalar projeto e dependências de desenvolvimento
        run: |
          python -m pip install --upgrade pip
          python -m pip install -e '.[dev]'
      - name: Lint
        run: python -m ruff check .
      - name: Tipos
        run: python -m mypy src/zonepad
      - name: Executar testes
        run: python -m pytest -q
      - name: Verificar espelhamento
        run: python scripts/sync_ai_assets.py --check
```

Regras:

- Inclua `.tool-versions` nos filtros de caminho para que uma mudança de versão dispare a CI.
- Adicione os passos de `ruff` e `mypy` somente se ambos estiverem verdes na branch. Se um deles falhar por código pré-existente de `main`, remova o passo vermelho do workflow e registre comando, saída e follow-up.
- Não adicione `ruff format --check` neste incremento. Em `main`, com `target-version = "py315"`, ele falha em `scripts/sync_ai_assets.py` por sugerir a sintaxe PEP 758 (`except A, B:`). Não rode `ruff format`, não reformate esse arquivo e não relaxe a regra; deixe o format check para o prompt 06.
- A CI não usa asdf nem virtualenv: `setup-python` fornece o interpretador e `.[dev]` fornece as ferramentas.
- Mantenha pytest e o sync check como gates obrigatórios.

### 5. `README.md`

Atualize apenas as seções de requisitos, ambiente, instalação, validação, estrutura e prompts. Preserve as seções de runtime, mapping, permissões, arquitetura e próximos passos como estão na branch.

Inclua um bloco de requisitos e ambiente semelhante a:

````markdown
## Requisitos

- Linux (MVP atual).
- Python 3.15.x. O projeto fixa `3.15.0` em `.tool-versions` e declara
  `requires-python = ">=3.15,<3.16"`.

## Ambiente de desenvolvimento

O projeto usa asdf para a versão do Python e virtualenv para o ambiente.

```bash
asdf plugin add python          # apenas se o plugin ainda não existir
asdf install python 3.15.0      # apenas se a versão ainda não estiver instalada
asdf set python 3.15.0          # grava .tool-versions
python --version                # Python 3.15.0

python -m pip install --user virtualenv   # ou: pipx install virtualenv
python -m virtualenv --python "$(asdf which python)" .venv
. .venv/bin/activate
python -m pip install -e '.[dev]'
```

Alternativa sem virtualenv instalado: `python -m venv .venv`, ative e rode
`python -m pip install -e '.[dev]'`.

O extra `dev` instala pytest, ruff, mypy e virtualenv. A CI usa Python 3.15.0
e o mesmo extra.
````

Ajustes obrigatórios:

- Troque a instrução de instalação de runtime para `python -m pip install .` dentro de um ambiente 3.15; mantenha `zonepad`, `zonepad list`, `zonepad profiles` e `zonepad replay` como exemplos de uso.
- Mantenha a GUI como extra opcional: `python -m pip install -e '.[gui]'` ou `'.[dev,gui]'`.
- Na seção de validação, substitua `python -m unittest discover -s tests -v` por `python -m pytest -q` e inclua `python -m ruff check .`, `python -m mypy src/zonepad` e `python scripts/sync_ai_assets.py --check`.
- Na árvore de estrutura, inclua `.tool-versions` com a descrição “versão do Python para asdf”.
- Na seção de prompts, registre `00-toolchain-python-315-asdf-virtualenv.md` como pré-requisito do `01-runtime-cli-end-to-end.md`.
- Remova qualquer menção a uv, `[dependency-groups]` ou lockfile.

### 6. Fontes em `ai/`

Edite apenas as fontes; os espelhos são gerados.

`ai/instructions/AGENTS.md`:

- Troque `Python 3.12+.` por `Python 3.15.x, fixado em `.tool-versions` (`python 3.15.0`); a CI usa `3.15.0`.`
- Troque a linha de uv por `asdf` para a versão do Python; `virtualenv` para o ambiente; dependências de desenvolvimento no extra `dev` (`python -m pip install -e '.[dev]'`).`
- Na definição de pronto, acrescente: `.tool-versions`, `requires-python` e a CI declaram a mesma versão de Python.`

`ai/skills/python-quality/SKILL.md`:

- Substitua a linha `Ambiente/deps` por `asdf + virtualenv + pip`, com a observação “Versão fixada em `.tool-versions`; extras em `pyproject.toml` (`.[dev]`).”
- Na seção de CI, registre que a CI usa Python 3.15.0, instala `.[dev]` e roda ruff, mypy, pytest e o sync check.
- Atualize o checklist para “A CI roda testes + lint + tipos + sync check.”

`ai/agents/python-engineer/prompt.md`:

- Troque `Python 3.12+` por `Python 3.15.x (fixado em `.tool-versions`)`.
- Acrescente uma linha curta: `Ambiente: asdf + virtualenv; instale com `python -m pip install -e '.[dev]'`.`

`ai/prompts/README.md`:

- Adicione a linha do prompt 00 na tabela de sequência, com status “Pré-requisito”.
- Acrescente uma nota: execute o 00 antes do 01, em branch própria a partir de `main`; ele fixa a toolchain e não altera o runtime CLI.

Não crie ADR. Não altere `ai/flows/` nem `ai/prompts/01-runtime-cli-end-to-end.md`.

### 7. Sincronização

```bash
python scripts/sync_ai_assets.py
python scripts/sync_ai_assets.py --check
git status --porcelain
```

Arquivos gerados esperados:

- `AGENTS.md`
- `CLAUDE.md`
- `.opencode/agents/python-engineer.md`
- `.claude/agents/python-engineer.md`
- `.codex/agents/python-engineer.toml`
- `.opencode/skills/python-quality/SKILL.md`
- `.claude/skills/python-quality/SKILL.md`
- `.agents/skills/python-quality/SKILL.md`
- manifestos `.generated.json` dos destinos

Se um arquivo gerado aparecer com mudança que o gerador não produz, pare e investigue; não edite o espelho à mão.

## Arquivos esperados

Edição manual:

- `.tool-versions` (novo)
- `pyproject.toml`
- `.github/workflows/ai-assets.yml`
- `README.md`
- `ai/instructions/AGENTS.md`
- `ai/skills/python-quality/SKILL.md`
- `ai/agents/python-engineer/prompt.md`
- `ai/prompts/README.md`

Gerados pelo sync:

- `AGENTS.md`, `CLAUDE.md`
- `.opencode/`, `.claude/`, `.agents/`, `.codex/` conforme a lista acima

Permanecem inalterados:

- `src/**`
- `tests/**`
- `docs/adr/**`
- `LICENSE`
- `packaging/**`
- `ai/flows/**`
- `ai/prompts/01-runtime-cli-end-to-end.md`

## Critérios de aceite

**Versão e ambiente**

- [ ] `.tool-versions` contém `python 3.15.0` e nenhuma outra versão de Python.
- [ ] `asdf current python` mostra `3.15.0` com fonte no `.tool-versions` do repositório.
- [ ] `python --version` imprime `Python 3.15.0` dentro do checkout.
- [ ] `.venv` foi criado com virtualenv; `python -c 'import sys; print(sys.prefix)'` aponta para `<checkout>/.venv`.
- [ ] `python -m pip install -e '.[dev]'` conclui sem erro em `.venv` limpo.
- [ ] pytest, ruff, mypy e virtualenv respondem no `.venv`.

**pyproject e CI**

- [ ] `requires-python = ">=3.15,<3.16"` (ou `==3.15.*` com justificativa registrada).
- [ ] `[tool.mypy].python_version = "3.15"` e `[tool.ruff].target-version = "py315"`.
- [ ] `[tool.uv]` e `[dependency-groups]` removidos.
- [ ] O extra `dev` contém pytest, ruff, mypy e virtualenv.
- [ ] O workflow usa `python-version: "3.15.0"` e instala `.[dev]`.
- [ ] O workflow roda pytest e `sync --check`; ruff e mypy estão presentes apenas se verdes.
- [ ] O workflow dispara em mudanças de `.tool-versions`.

**Documentação e instruções**

- [ ] README documenta asdf + virtualenv + `.[dev]`, sem uv, com comandos copiáveis.
- [ ] README usa `pytest` na validação e registra o prompt 00 como pré-requisito.
- [ ] `ai/instructions/AGENTS.md`, `ai/skills/python-quality/SKILL.md` e `ai/agents/python-engineer/prompt.md` refletem Python 3.15, asdf e virtualenv.
- [ ] `ai/prompts/README.md` lista o prompt 00 como pré-requisito.
- [ ] `sync` foi executado e `sync --check` está limpo.
- [ ] Nenhum arquivo gerado foi editado à mão.
- [ ] `git grep` não encontra `uv`, `py312` ou `3.12` em código, configuração e documentação ativos, exceto em `ai/prompts/` e no histórico.

**Escopo e qualidade**

- [ ] `git diff --name-only main...HEAD -- src/ tests/` está vazio.
- [ ] `python -m pytest -q` passa.
- [ ] `python -m ruff check .` passa.
- [ ] `python -m mypy src/zonepad` passa.
- [ ] `$flow-review-calibration` não encontrou `blocker`.
- [ ] A revisão de hardware está registrada como N/A, com justificativa.
- [ ] Não houve push, merge ou pull request.

## Validação

Execute e reporte, na ordem:

```bash
# Preflight
git status --porcelain
git branch --show-current
git log --oneline main..HEAD

# Versão e ambiente
grep -n '^python ' .tool-versions
asdf current python
python --version
python -c 'import sys; print(sys.prefix)'

# Dependências de desenvolvimento
python -m pytest --version
python -m ruff --version
python -m mypy --version
python -m virtualenv --version

# Qualidade
python -m pytest -q
python -m ruff check .
python -m mypy src/zonepad

# Assets
python scripts/sync_ai_assets.py
python scripts/sync_ai_assets.py --check

# Escopo e resíduos
git diff --name-only main...HEAD -- src/ tests/
git grep -n -E '\buv\b|py312|3\.12' -- . ':!ai/prompts' || true
git diff --stat main
```

Diagnóstico opcional, que não é gate neste incremento:

```bash
python -m ruff format --check .
```

Ele falha em `scripts/sync_ai_assets.py` sob `py315` por sugerir PEP 758. Registre a saída e deixe a correção para o prompt 06.

Se algum comando não puder ser executado, declare o motivo e o impacto. Não simule resultados.

## Riscos

| Risco | Impacto | Mitigação |
| --- | --- | --- |
| `3.15.0` ausente no plugin do asdf ou no `setup-python` | bloqueia o incremento | verificado localmente e no manifest; se faltar, pare e pergunte; não troque a versão silenciosamente |
| Ferramenta antiga não reconhece `py315` ou `3.15` | lint ou tipos quebram | pisos `ruff>=0.17.2`, `mypy>=2.4`; versões verificadas |
| `ruff format --check` vermelho em `main` | impede adicionar format check à CI | fora do gate; follow-up no prompt 06; não reformate neste incremento |
| virtualenv não instalado no interpretador atual | atrasa a criação do `.venv` ou falha se o user site estiver bloqueado | instalar `21.14.13` via `pipx` ou `pip --user`; fallback `python -m venv` |
| PySide6 ou outra dependência futura sem suporte a 3.15 | GUI pode não instalar | metadados atuais permitem; smoke de GUI fica fora do escopo |
| Remoção de uv e `[dependency-groups]` | contribuidores que usam uv perdem o grupo `dev` | mudança intencional; README passa a documentar apenas pip + extra `dev` |
| `.tool-versions` afeta qualquer shell no repositório | `python` muda de versão ao entrar no diretório | documente a ativação e use `.venv/bin/python` para o ambiente |
| Python 3.15 é recente | usuários em 3.14 ficam bloqueados por `requires-python` | intencional; registre o requisito no README |
| Ausência de lockfile | ferramentas podem variar dentro dos pisos | fora do escopo; prompt 06 avalia lockfile |
| Prompt 01 em andamento no mesmo checkout | mistura de mudanças | worktree limpo + preflight; nada de stash/reset |
| Espelhos dessincronizados | instruções divergentes entre ferramentas | rodar o gerador e validar com `--check` |

## Fora de escopo

- Implementar ou alterar o runtime CLI, evdev, uinput, mapping ou permissões de dispositivo.
- Métricas de calibração, wizard, schema de perfil ou GUI.
- Suporte a Python 3.16+, Windows ou macOS.
- Lockfile, uv, pip-tools, Renovate ou Dependabot.
- ADR numerado; este incremento não cria ADR. Se um ADR for necessário depois, confira a numeração disponível antes de criá-lo.
- `ruff format --check` na CI ou reformatação de `scripts/sync_ai_assets.py`.
- Smoke de instalação ou execução da GUI PySide6.
- Alterar versão do pacote, licença, README de runtime ou arquivos do prompt 01.
- Push, merge ou pull request.

## Formato de saída

Responda em PT-BR com:

1. **Plano executado** — 2–5 bullets.
2. **Ambiente** — versões de asdf, Python, pip, virtualenv, ruff, mypy e pytest; comandos de ativação.
3. **Mudanças por arquivo** — separando fontes editadas e arquivos gerados.
4. **Validações** — comandos e resultados, incluindo falhas e como foram tratadas.
5. **Revisão final** — achados do `$flow-review-calibration`, com severidade, arquivo:linha e recomendação.
6. **Riscos e limitações** — incluindo o que não foi validado.
7. **Próximo passo** — handoff ou pendências para o prompt 01 e o prompt 06.

Se um gate falhar, pare e reporte. Não relaxe configuração, não adicione `# type: ignore` e não reformate código alheio para fazer o gate passar.

## Invocação no Codex

### Preparação

O arquivo deste prompt deve estar versionado em `main`. Crie um worktree limpo e abra o Codex nele:

```bash
cd /home/costa/Workspace/zonepad
git worktree add -b chore/toolchain-python-315 ../zonepad-toolchain main
cd ../zonepad-toolchain
codex
```

Se a branch já existir, use `git worktree add ../zonepad-toolchain chore/toolchain-python-315`.

### Texto para colar no Codex

```text
$flow-implement-feature

Siga o prompt em ai/prompts/00-toolchain-python-315-asdf-virtualenv.md.
Leia o arquivo inteiro antes de editar.

Execute em um checkout limpo criado a partir de main, na branch chore/toolchain-python-315.
Não acesse, altere, faça stash, reset ou commit na branch feat/runtime-cli-end-to-end
nem nas alterações não commitadas do prompt 01.

Use python-engineer para implementar e validar a toolchain, o pyproject.toml, a CI e os
comandos do README. Use prompt-engineer para editar e revisar ai/instructions/AGENTS.md,
ai/skills/python-quality/SKILL.md, ai/agents/python-engineer/prompt.md e ai/prompts/README.md,
e para revisar a consistência das instruções. controller-hardware não é necessário neste incremento.

Pare e pergunte se o working tree estiver sujo, se 3.15.0 não estiver disponível ou se algum
gate falhar. Ao final, rode $flow-review-calibration neste diff e reporte no formato do prompt.
```
