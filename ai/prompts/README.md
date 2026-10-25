# Prompts de implementação

Esta pasta guarda prompts de trabalho para implementar o ZonaPad com Claude Code ou Codex. Eles **não** são skills nem agentes: são entradas versionadas para uma sessão de implementação.

Os prompts não são espelhados pelo gerador `scripts/sync_ai_assets.py`. Eles vivem apenas em `ai/prompts/` e podem ser referenciados por caminho.

## Contrato de início de trabalho

Todo prompt deve ser executado no checkout principal do repositório, **nunca em worktree**.

1. `git status --porcelain` deve estar vazio.
2. Leia o prompt e confirme se ele já está mergeado em `main`.
3. No fluxo normal, atualize `main` com `git switch main` e `git pull --ff-only`, então crie `git switch -c <tipo>/<slug>`.
4. Se o Prompt 06 ainda não estiver mergeado, use como base a branch que contém o prompt e registre a exceção. Confirme `git merge-base --is-ancestor main HEAD`; `git log --oneline main..HEAD` deve listar somente o commit que adiciona o Prompt 06.
5. Confirme `git status --porcelain` vazio e a branch de trabalho esperada antes de editar.

Não use `git worktree`. Uma branch por incremento. Não commite direto na `main`.

## Como usar

### Claude Code

```text
Use o prompt em @ai/prompts/06-quality-release.md.
Leia o arquivo inteiro, execute as etapas na ordem e valide com os comandos pedidos.
```

Ou use o fluxo:

```text
/flow-implement-feature
```

Para o prompt 06, a spec e o ADR já foram aprovados; continue com `/flow-implement-feature` e finalize com `/flow-review-calibration`.

### Codex

```text
Siga o prompt em ai/prompts/06-quality-release.md.
Leia o arquivo inteiro, execute as etapas na ordem e valide com os comandos pedidos.
```

Ou use a skill de fluxo:

```text
$flow-implement-feature
```

Para o prompt 06, a spec e o ADR já foram aprovados; continue com `$flow-implement-feature` e finalize com `$flow-review-calibration`.

## Convenções

- Um prompt por incremento verificável.
- O prompt define objetivo, escopo, fora de escopo, critérios de aceite e validação.
- O agente deve ler `AGENTS.md`, o ADR relevante e os arquivos citados antes de editar.
- O prompt não substitui as skills: `evidence-based`, `clean-code`, `clean-architecture` e `python-quality` continuam valendo.
- Se o incremento mudar contrato público, o agente deve propor um ADR.
- Se o incremento mexer em `ai/`, rodar `python scripts/sync_ai_assets.py` e `--check`.

## Sequência planejada

Os prompts 00 a 05 estão concluídos e mergeados em `main`. O prompt 06 é o último incremento planejado do roadmap atual. Execute cada incremento em branch própria no checkout principal e com toolchain 3.15.0. Quando o prompt ainda não estiver mergeado, aplique a exceção descrita no próprio prompt: a branch de trabalho deriva da branch que contém o prompt, `main` permanece ancestral e somente o commit do prompt aparece em `main..HEAD`.

| Prompt | Incremento | Status |
| --- | --- | --- |
| `00-toolchain-python-315-asdf-virtualenv.md` | Python 3.15.0, asdf, virtualenv, pyproject e CI | Concluído — mergeado em `main` |
| `01-runtime-cli-end-to-end.md` | Comando `zonepad run` com evdev → perfil → uinput | Concluído — mergeado em `main` |
| `02-calibration-metrics.md` | Métricas, relatório e profile builder | Concluído — mergeado no PR #5 (spec `docs/specs/metrics-v1.md`, ADR `docs/adr/0004-metricas-relatorio-separado-e-perfil-v1.md`) |
| `03-calibration-wizard.md` | Wizard CLI de calibração | Concluído — mergeado no PR #7 |
| `04-device-discovery-mapping.md` | Descoberta de gamepads, identidade estável e mapeamento por família | Concluído — mergeado no PR #12 (spec `docs/specs/device-discovery-v1.md`, ADR `docs/adr/0006-descoberta-e-identidade-de-dispositivos.md`) |
| `05-gui-pyside6.md` | GUI PySide6 sobre o núcleo de calibração | Concluído — mergeado no PR #14 (spec `docs/specs/gui-v1.md`, ADR `docs/adr/0008-gui-pyside6-como-adaptador.md`) |
| `06-quality-release.md` | Qualidade, dependências, ambiente, build e release | Em implementação — spec e ADR 0009 aprovados |

O prompt 02 é pré-requisito do 03: ele entrega o motor de medição e a geração de perfil; o wizard apenas orquestra esse motor e a política de retry. O prompt 04 substitui a seleção manual de dispositivo e o mapping manual usados no 03. O prompt 05 é adaptador: não altera domínio, métricas, schema de perfil nem o wizard CLI.

O prompt 06 fecha o roadmap: consolida dependências e extras, documenta o ambiente de desenvolvimento, faz a CI executar os testes de GUI que hoje são pulados, valida o conteúdo do wheel/sdist e prova a instalação limpa. Ele não adiciona features nem altera domínio, métricas, schema de perfil ou GUI. A spec `docs/specs/dev-environment-v1.md` e o ADR `docs/adr/0009-*` foram aprovados antes da implementação. A GUI continua exigindo o extra opcional `gui` (`python -m pip install -e '.[dev,gui]'`); a CLI e o domínio funcionam sem PySide6.

## Regra de ouro

Se o agente não conseguir validar sem hardware, ele deve:

1. criar um teste com fake/replay;
2. documentar o smoke manual necessário;
3. declarar explicitamente o que não foi validado.
